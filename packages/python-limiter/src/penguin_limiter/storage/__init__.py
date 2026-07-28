"""Storage backend protocol for rate-limit counters.

Any class that implements :class:`RateLimitStorage` can be used as a backend.
Two built-in implementations are provided:

- :class:`~penguin_limiter.storage.memory.MemoryStorage` — in-process dict,
  suitable for single-instance services and testing.
- :class:`~penguin_limiter.storage.redis_store.RedisStorage` — Redis-backed,
  suitable for multi-instance deployments.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class RateLimitStorage(Protocol):
    """Structural protocol for rate-limit storage backends."""

    def increment(self, key: str, window: int) -> int:
        """Atomically increment *key* and return the new count.

        The counter expires after *window* seconds.
        """
        ...

    def get(self, key: str) -> int:
        """Return the current counter value for *key* (0 if not set)."""
        ...

    def get_timestamps(self, key: str) -> list[float]:
        """Return stored request timestamps for *key* (sliding window)."""
        ...

    def add_timestamp(self, key: str, ts: float, window: int) -> int:
        """Append *ts*, prune old entries, return current count."""
        ...

    def get_token_state(self, key: str) -> tuple[float, float]:
        """Return ``(tokens, last_refill_time)`` for token-bucket state."""
        ...

    def set_token_state(self, key: str, tokens: float, ts: float, ttl: int) -> None:
        """Persist token-bucket state for *key* with *ttl*-second expiry."""
        ...

    def ping(self) -> bool:
        """Return ``True`` if the backend is reachable."""
        ...


__all__ = ["RateLimitStorage"]
