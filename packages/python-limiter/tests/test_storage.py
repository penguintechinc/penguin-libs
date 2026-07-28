"""Tests for MemoryStorage and RedisStorage backends."""

from __future__ import annotations

import time

import pytest

from penguin_limiter.storage.memory import MemoryStorage


class TestMemoryStorage:
    def test_increment_returns_1_first_call(self) -> None:
        s = MemoryStorage()
        assert s.increment("k", 60) == 1

    def test_increment_accumulates(self) -> None:
        s = MemoryStorage()
        s.increment("k", 60)
        s.increment("k", 60)
        assert s.increment("k", 60) == 3

    def test_increment_resets_after_window(self) -> None:
        s = MemoryStorage()
        # Set the expiry in the past to simulate window expiry
        s.increment("k", 60)
        s._counters["k"].expires_at = time.time() - 1  # expired
        assert s.increment("k", 60) == 1  # fresh window

    def test_get_returns_0_for_unknown_key(self) -> None:
        s = MemoryStorage()
        assert s.get("missing") == 0

    def test_get_reflects_current_count(self) -> None:
        s = MemoryStorage()
        s.increment("k", 60)
        s.increment("k", 60)
        assert s.get("k") == 2

    def test_get_returns_0_after_expiry(self) -> None:
        s = MemoryStorage()
        s.increment("k", 60)
        s._counters["k"].expires_at = time.time() - 1
        assert s.get("k") == 0

    def test_add_timestamp_accumulates(self) -> None:
        s = MemoryStorage()
        now = time.time()
        assert s.add_timestamp("k", now, 60) == 1
        assert s.add_timestamp("k", now + 1, 60) == 2
        assert s.add_timestamp("k", now + 2, 60) == 3

    def test_add_timestamp_prunes_old_entries(self) -> None:
        s = MemoryStorage()
        old = time.time() - 120  # 2 minutes ago, outside 60s window
        s.add_timestamp("k", old, 60)
        now = time.time()
        count = s.add_timestamp("k", now, 60)
        assert count == 1  # old entry pruned

    def test_get_timestamps_returns_copy(self) -> None:
        s = MemoryStorage()
        now = time.time()
        s.add_timestamp("k", now, 60)
        ts = s.get_timestamps("k")
        assert len(ts) == 1
        ts.clear()  # modifying copy should not affect stored list
        assert len(s.get_timestamps("k")) == 1

    def test_token_state_absent_returns_sentinel(self) -> None:
        s = MemoryStorage()
        tokens, ts = s.get_token_state("k")
        assert tokens == -1.0
        assert ts == 0.0

    def test_token_state_round_trip(self) -> None:
        s = MemoryStorage()
        now = time.time()
        s.set_token_state("k", 7.5, now, 60)
        tokens, ts = s.get_token_state("k")
        assert tokens == pytest.approx(7.5)
        assert ts == pytest.approx(now)

    def test_token_state_expired_returns_sentinel(self) -> None:
        s = MemoryStorage()
        now = time.time()
        s.set_token_state("k", 5.0, now, 1)
        s._token_states["k"].expires_at = now - 1  # force expiry
        tokens, _ = s.get_token_state("k")
        assert tokens == -1.0

    def test_ping_always_true(self) -> None:
        assert MemoryStorage().ping() is True


class TestRedisStorage:
    """Uses fakeredis to simulate Redis without a running server."""

    @pytest.fixture()
    def storage(self):  # type: ignore[return]
        try:
            import fakeredis
            from penguin_limiter.storage.redis_store import RedisStorage
        except ImportError:
            pytest.skip("fakeredis not available")
        client = fakeredis.FakeRedis()
        return RedisStorage(client, key_prefix="test_rl")

    def test_increment_returns_1_first_call(self, storage) -> None:  # type: ignore[return]
        assert storage.increment("key1", 60) == 1

    def test_increment_accumulates(self, storage) -> None:  # type: ignore[return]
        storage.increment("key2", 60)
        storage.increment("key2", 60)
        assert storage.increment("key2", 60) == 3

    def test_get_returns_0_for_unknown_key(self, storage) -> None:  # type: ignore[return]
        assert storage.get("unknown") == 0

    def test_get_reflects_current_count(self, storage) -> None:  # type: ignore[return]
        storage.increment("key3", 60)
        storage.increment("key3", 60)
        assert storage.get("key3") == 2

    def test_add_timestamp_accumulates(self, storage) -> None:  # type: ignore[return]
        now = time.time()
        assert storage.add_timestamp("slkey", now, 60) == 1
        assert storage.add_timestamp("slkey", now + 1, 60) == 2

    def test_token_state_round_trip(self, storage) -> None:  # type: ignore[return]
        now = time.time()
        storage.set_token_state("tokkey", 8.0, now, 120)
        tokens, ts = storage.get_token_state("tokkey")
        assert tokens == pytest.approx(8.0)
        assert ts == pytest.approx(now)

    def test_token_state_absent_returns_sentinel(self, storage) -> None:  # type: ignore[return]
        tokens, ts = storage.get_token_state("nokey")
        assert tokens == -1.0

    def test_ping_returns_true(self, storage) -> None:  # type: ignore[return]
        assert storage.ping() is True
