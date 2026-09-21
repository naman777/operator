"""Migration 020: shared admission counters; contains only hashed client identifiers."""

from operator_api.db import RateLimitBucket


def upgrade(connection):
    RateLimitBucket.__table__.create(connection, checkfirst=True)
