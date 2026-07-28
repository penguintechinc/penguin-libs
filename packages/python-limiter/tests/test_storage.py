"""Tests for rate limit storage backends."""

import time

import pytest

from penguin_limiter import MemoryStorage, RateLimitStorage


class TestMemoryStorage:
    """Test MemoryStorage implementation."""

    def test_get_empty_key(self) -> None:
        """Test getting non-existent key."""
        storage = MemoryStorage()
        assert storage.get("missing") == 0

    def test_increment(self) -> None:
        """Test incrementing counter."""
        storage = MemoryStorage()
        assert storage.increment("key1") == 1
        assert storage.increment("key1") == 2
        assert storage.increment("key1", 5) == 7

    def test_get_after_increment(self) -> None:
        """Test getting counter after increment."""
        storage = MemoryStorage()
        storage.increment("key1", 3)
        assert storage.get("key1") == 3

    def test_reset(self) -> None:
        """Test resetting counter."""
        storage = MemoryStorage()
        storage.increment("key1", 5)
        storage.reset("key1")
        assert storage.get("key1") == 0

    def test_expiration(self) -> None:
        """Test key expiration."""
        storage = MemoryStorage()
        storage.increment("key1", 1, ttl_seconds=1)
        assert storage.get("key1") == 1
        time.sleep(1.1)
        assert storage.get("key1") == 0

    def test_ttl_update(self) -> None:
        """Test that TTL is updated on increment."""
        storage = MemoryStorage()
        storage.increment("key1", 1, ttl_seconds=2)
        time.sleep(1)
        storage.increment("key1", 1, ttl_seconds=2)
        time.sleep(1)
        # Should still be present due to TTL extension
        assert storage.get("key1") == 2

    def test_isolation_between_keys(self) -> None:
        """Test that keys are isolated."""
        storage = MemoryStorage()
        storage.increment("key1", 5)
        storage.increment("key2", 3)
        assert storage.get("key1") == 5
        assert storage.get("key2") == 3

    def test_get_with_ttl(self) -> None:
        """Test get_with_ttl method."""
        storage = MemoryStorage()
        storage.increment("key1", 5, ttl_seconds=60)
        counter, ttl = storage.get_with_ttl("key1")
        assert counter == 5
        assert 59 <= ttl <= 60

    def test_get_with_ttl_missing_key(self) -> None:
        """Test get_with_ttl with missing key."""
        storage = MemoryStorage()
        counter, ttl = storage.get_with_ttl("missing")
        assert counter == 0
        assert ttl == -2

    def test_lru_eviction(self) -> None:
        """Test LRU eviction when max_entries reached."""
        storage = MemoryStorage(max_entries=3)

        # Fill up storage
        storage.increment("key1")
        storage.increment("key2")
        storage.increment("key3")

        assert storage.get("key1") == 1
        assert storage.get("key2") == 1
        assert storage.get("key3") == 1

        # Add one more, should evict least recently used (key1)
        storage.increment("key4")

        assert storage.get("key1") == 0  # Evicted
        assert storage.get("key2") == 1
        assert storage.get("key3") == 1
        assert storage.get("key4") == 1

    def test_thread_safety_basic(self) -> None:
        """Test that storage is thread-safe (basic)."""
        import threading

        storage = MemoryStorage()
        results: list[int] = []

        def increment_many() -> None:
            for _ in range(100):
                storage.increment("shared_key")

        threads = [threading.Thread(target=increment_many) for _ in range(3)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # Should have 300 total increments
        assert storage.get("shared_key") == 300

    def test_different_max_entries(self) -> None:
        """Test MemoryStorage with different max_entries."""
        storage = MemoryStorage(max_entries=5)
        for i in range(10):
            storage.increment(f"key{i}")

        # Should only have last 5 keys due to LRU eviction
        assert storage.get("key5") == 1
        assert storage.get("key9") == 1
        assert storage.get("key0") == 0  # First key should be evicted
