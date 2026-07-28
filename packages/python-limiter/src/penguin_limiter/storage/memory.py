"""In-process memory storage for rate limiting."""

from __future__ import annotations

import threading
import time
from collections import OrderedDict
from typing import Tuple

from .base import RateLimitStorage


class MemoryStorage(RateLimitStorage):
    """In-process rate limit storage with LRU eviction.

    Thread-safe implementation using locks. Automatically evicts oldest entries
    when max_entries is reached to prevent unbounded memory growth.
    """

    def __init__(self, max_entries: int = 10000) -> None:
        """Initialize memory storage.

        Args:
            max_entries: Maximum number of keys to store (default 10000)
        """
        self.max_entries = max_entries
        # Dictionary to store (counter, expiry_time) tuples
        self._data: OrderedDict[str, Tuple[int, float]] = OrderedDict()
        self._lock = threading.RLock()

    def get(self, key: str) -> int:
        """Get the current counter value for a key."""
        with self._lock:
            if key not in self._data:
                return 0
            counter, expiry = self._data[key]
            if time.time() > expiry:
                del self._data[key]
                return 0
            return counter

    def increment(self, key: str, amount: int = 1, ttl_seconds: int = 3600) -> int:
        """Increment counter and set/update TTL."""
        with self._lock:
            # Clean up expired entry if present
            if key in self._data:
                counter, expiry = self._data[key]
                if time.time() > expiry:
                    del self._data[key]
                    counter = 0
                else:
                    # Move to end (most recently used)
                    self._data.move_to_end(key)
            else:
                counter = 0

            # Increment
            new_counter = counter + amount
            expiry = time.time() + ttl_seconds

            # Check if we need to evict
            if key not in self._data and len(self._data) >= self.max_entries:
                # Remove oldest (least recently used) entry
                self._data.popitem(last=False)

            self._data[key] = (new_counter, expiry)
            # Move to end (most recently used)
            self._data.move_to_end(key)

            return new_counter

    def reset(self, key: str) -> None:
        """Reset counter for a key."""
        with self._lock:
            if key in self._data:
                del self._data[key]

    def get_with_ttl(self, key: str) -> Tuple[int, int]:
        """Get counter and remaining TTL.

        Returns:
            Tuple of (counter_value, ttl_seconds) where ttl_seconds is -2 if key doesn't exist
        """
        with self._lock:
            if key not in self._data:
                return 0, -2
            counter, expiry = self._data[key]
            now = time.time()
            if now > expiry:
                del self._data[key]
                return 0, -2
            ttl = int(expiry - now)
            return counter, max(ttl, 0)
