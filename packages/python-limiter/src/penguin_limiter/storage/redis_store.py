"""Redis-backed rate limit storage."""

from __future__ import annotations

from typing import Tuple

try:
    import redis
except ImportError as e:
    raise ImportError(
        "redis package required for RedisStorage. Install with: pip install 'penguin-limiter[redis]'"
    ) from e

from .base import RateLimitStorage


class RedisStorage(RateLimitStorage):
    """Redis-backed rate limit storage.

    Uses Redis INCR and EXPIRE commands for atomic operations and automatic
    key expiration.
    """

    def __init__(self, url: str) -> None:
        """Initialize Redis storage.

        Args:
            url: Redis connection URL (e.g., 'redis://localhost:6379/0')
        """
        self.client = redis.from_url(url, decode_responses=True)
        # Test connection
        self.client.ping()

    def get(self, key: str) -> int:
        """Get the current counter value for a key."""
        value = self.client.get(key)
        return int(value) if value else 0

    def increment(self, key: str, amount: int = 1, ttl_seconds: int = 3600) -> int:
        """Increment counter and set/update TTL."""
        pipeline = self.client.pipeline()
        pipeline.incrby(key, amount)
        pipeline.expire(key, ttl_seconds)
        result = pipeline.execute()
        return int(result[0])

    def reset(self, key: str) -> None:
        """Reset counter for a key."""
        self.client.delete(key)

    def get_with_ttl(self, key: str) -> Tuple[int, int]:
        """Get counter and remaining TTL.

        Returns:
            Tuple of (counter_value, ttl_seconds) where ttl_seconds is -2 if key doesn't exist
        """
        pipeline = self.client.pipeline()
        pipeline.get(key)
        pipeline.ttl(key)
        result = pipeline.execute()
        counter_value = int(result[0]) if result[0] else 0
        ttl = int(result[1])
        return counter_value, ttl
