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
