"""Redis-backed storage backend.

Requires ``pip install 'penguin-limiter[redis]'`` (or ``redis>=5.0``).

All counter operations use atomic Lua scripts to avoid TOCTOU races in
multi-instance deployments — the same safety guarantee as ``INCR`` + ``EXPIRE``
but with proper ``SETNX``-style initialisation.
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    pass  # redis types resolved lazily

# Lua script: increment key, set TTL only on first call within a window
_INCR_SCRIPT = """
local current = redis.call('INCR', KEYS[1])
if current == 1 then
    redis.call('EXPIRE', KEYS[1], ARGV[1])
end
return current
"""

# Lua script: append timestamp, prune old entries, return new count
_SLIDE_SCRIPT = """
local key   = KEYS[1]
local now   = tonumber(ARGV[1])
local cutoff = tonumber(ARGV[2])
local ttl   = tonumber(ARGV[3])
redis.call('ZADD', key, now, now .. ':' .. redis.call('INCR', key .. ':seq'))
redis.call('ZREMRANGEBYSCORE', key, '-inf', cutoff)
redis.call('EXPIRE', key, ttl)
return redis.call('ZCARD', key)
"""


class RedisStorage:
    """Redis-backed rate-limit storage.

    Parameters
    ----------
    client:
        A ``redis.Redis`` (sync) client instance.  Pass a ``fakeredis.FakeRedis``
        instance in tests.
    key_prefix:
        Optional namespace prefix applied to all keys (default: ``"penguin_rl"``).
    """

    def __init__(self, client: Any, key_prefix: str = "penguin_rl") -> None:
        self._r = client
        self._prefix = key_prefix
        self._incr_script = self._r.register_script(_INCR_SCRIPT)
        self._slide_script = self._r.register_script(_SLIDE_SCRIPT)

    def _key(self, key: str) -> str:
        return f"{self._prefix}:{key}"

    # ------------------------------------------------------------------
    # Fixed-window
    # ------------------------------------------------------------------

    def increment(self, key: str, window: int) -> int:
        """Atomically increment and return new count; sets expiry on first call."""
        result = self._incr_script(keys=[self._key(key)], args=[window])
        return int(result)

    def get(self, key: str) -> int:
        """Return current count (0 if absent/expired)."""
        val = self._r.get(self._key(key))
        return int(val) if val else 0

    # ------------------------------------------------------------------
    # Sliding-window
    # ------------------------------------------------------------------

    def get_timestamps(self, key: str) -> list[float]:
        """Return all scores (timestamps) from the sorted set."""
        members = self._r.zrange(self._key(key), 0, -1, withscores=True)
        return [score for _, score in members]

    def add_timestamp(self, key: str, ts: float, window: int) -> int:
        """Append *ts*, prune stale entries, return current count."""
        cutoff = ts - window
        result = self._slide_script(
            keys=[self._key(key)],
            args=[ts, cutoff, int(window) + 1],
        )
        return int(result)

    # ------------------------------------------------------------------
    # Token bucket
    # ------------------------------------------------------------------

    def get_token_state(self, key: str) -> tuple[float, float]:
        """Return ``(tokens, last_refill)`` from a Redis hash; ``(-1, 0)`` if absent."""
        k = self._key(f"{key}:tok")
        data = self._r.hmget(k, "tokens", "ts")
        if data[0] is None:
            return -1.0, 0.0
        return float(data[0]), float(data[1])

    def set_token_state(self, key: str, tokens: float, ts: float, ttl: int) -> None:
        """Persist token-bucket state."""
        k = self._key(f"{key}:tok")
        self._r.hset(k, mapping={"tokens": tokens, "ts": ts})
        self._r.expire(k, ttl)

    # ------------------------------------------------------------------
    # Health
    # ------------------------------------------------------------------

    def ping(self) -> bool:
        """Return ``True`` if Redis responds to PING."""
        try:
            return bool(self._r.ping())
        except Exception:
            return False
