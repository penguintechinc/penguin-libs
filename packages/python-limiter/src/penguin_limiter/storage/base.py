"""Base storage interface for rate limiting."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Tuple


class RateLimitStorage(ABC):
    """Abstract base class for rate limit storage backends."""

    @abstractmethod
    def get(self, key: str) -> int:
        """Get the current counter value for a key.

        Args:
            key: The rate limit key (e.g., IP address or user ID)

        Returns:
            Current counter value
        """

    @abstractmethod
    def increment(self, key: str, amount: int = 1, ttl_seconds: int = 3600) -> int:
        """Increment counter and set/update TTL.

        Args:
            key: The rate limit key
            amount: Amount to increment by
            ttl_seconds: Time-to-live in seconds for the key

        Returns:
            New counter value after increment
        """

    @abstractmethod
    def reset(self, key: str) -> None:
        """Reset counter for a key.

        Args:
            key: The rate limit key
        """

    @abstractmethod
    def get_with_ttl(self, key: str) -> Tuple[int, int]:
        """Get counter and remaining TTL.

        Args:
            key: The rate limit key

        Returns:
            Tuple of (counter_value, ttl_seconds) where ttl_seconds is -2 if key doesn't exist
        """
