"""Small, bounded sliding-window rate limits for a single API process.

Keys are expected to be one-way hashes. The limiter never retains bearer tokens,
request bodies, or IP addresses in their original form.
"""

from collections import OrderedDict, deque
from dataclasses import dataclass
from threading import Lock
import time


@dataclass(frozen=True)
class Limit:
    name: str
    requests: int
    window_seconds: int


class SlidingWindowLimiter:
    def __init__(self, clock=time.monotonic, max_keys: int = 10_000):
        self._clock = clock
        self._max_keys = max_keys
        self._entries: OrderedDict[tuple[str, str], deque[float]] = OrderedDict()
        self._lock = Lock()

    def check(self, key: str, limit: Limit) -> tuple[bool, int, int]:
        """Return (allowed, remaining, retry_after_seconds)."""
        now = self._clock()
        cutoff = now - limit.window_seconds
        entry_key = (limit.name, key)
        with self._lock:
            timestamps = self._entries.get(entry_key)
            if timestamps is None:
                if len(self._entries) >= self._max_keys:
                    self._entries.popitem(last=False)
                timestamps = deque()
                self._entries[entry_key] = timestamps
            else:
                self._entries.move_to_end(entry_key)
            while timestamps and timestamps[0] <= cutoff:
                timestamps.popleft()
            if len(timestamps) >= limit.requests:
                retry_after = max(1, int(timestamps[0] + limit.window_seconds - now) + 1)
                return False, 0, retry_after
            timestamps.append(now)
            return True, limit.requests - len(timestamps), 0


class DatabaseWindowLimiter:
    """Atomic fixed windows shared across API processes, with bounded expired-row cleanup."""

    def __init__(self, engine, clock=time.time):
        self.engine = engine
        self.clock = clock

    def check(self, key: str, limit: Limit) -> tuple[bool, int, int]:
        from sqlalchemy import delete, select, case
        from sqlalchemy.dialects.postgresql import insert as pg_insert
        from sqlalchemy.dialects.sqlite import insert as sqlite_insert
        from .db import RateLimitBucket

        now = int(self.clock())
        window = now // limit.window_seconds
        expires = (window + 1) * limit.window_seconds
        bucket_key = f"{limit.name}:{limit.window_seconds}:{window}:{key}"
        table = RateLimitBucket.__table__
        insert = pg_insert if self.engine.dialect.name == "postgresql" else sqlite_insert
        statement = insert(table).values(key=bucket_key, count=1, expires_at=expires)
        statement = statement.on_conflict_do_update(
            index_elements=[table.c.key],
            set_={"count": case((table.c.count <= limit.requests, table.c.count + 1), else_=table.c.count)},
        ).returning(table.c.count)
        with self.engine.begin() as connection:
            expired = select(table.c.key).where(table.c.expires_at <= now).limit(100)
            connection.execute(delete(table).where(table.c.key.in_(expired)))
            count = connection.scalar(statement)
        allowed = count <= limit.requests
        return allowed, max(0, limit.requests - count), 0 if allowed else max(1, expires - now)
