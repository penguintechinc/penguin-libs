"""Tests for FixedWindow, SlidingWindow, and TokenBucket algorithms."""

from __future__ import annotations

import time
from unittest.mock import MagicMock

import pytest

from penguin_limiter.algorithms.fixed_window import FixedWindow
from penguin_limiter.algorithms.sliding_window import SlidingWindow
from penguin_limiter.algorithms.token_bucket import TokenBucket
from penguin_limiter.storage.memory import MemoryStorage


# ---------------------------------------------------------------------------
# FixedWindow
# ---------------------------------------------------------------------------

class TestFixedWindow:
    def test_first_request_allowed(self) -> None:
        algo = FixedWindow(MemoryStorage(), limit=5, window=60)
        result = algo.is_allowed("ip:1.2.3.4")
        assert result.allowed is True
        assert result.limit == 5
        assert result.remaining == 4

    def test_within_limit_allowed(self) -> None:
        storage = MemoryStorage()
        algo = FixedWindow(storage, limit=3, window=60)
        for _ in range(3):
            r = algo.is_allowed("ip:1.2.3.4")
            assert r.allowed is True

    def test_exceeds_limit_denied(self) -> None:
        storage = MemoryStorage()
        algo = FixedWindow(storage, limit=2, window=60)
        algo.is_allowed("ip:1.2.3.4")
        algo.is_allowed("ip:1.2.3.4")
        result = algo.is_allowed("ip:1.2.3.4")
        assert result.allowed is False
        assert result.remaining == 0

    def test_different_keys_independent(self) -> None:
        storage = MemoryStorage()
        algo = FixedWindow(storage, limit=1, window=60)
        assert algo.is_allowed("ip:1.1.1.1").allowed is True
        assert algo.is_allowed("ip:1.1.1.1").allowed is False
        # Different key should still have full budget
        assert algo.is_allowed("ip:2.2.2.2").allowed is True

    def test_storage_error_fails_open(self) -> None:
        bad_storage = MagicMock()
        bad_storage.increment.side_effect = ConnectionError("redis down")
        algo = FixedWindow(bad_storage, limit=5, window=60)
        result = algo.is_allowed("key")
        assert result.allowed is True  # fail-open


# ---------------------------------------------------------------------------
# SlidingWindow
# ---------------------------------------------------------------------------

class TestSlidingWindow:
    def test_within_limit_allowed(self) -> None:
        storage = MemoryStorage()
        algo = SlidingWindow(storage, limit=5, window=60)
        for _ in range(5):
            assert algo.is_allowed("ip:1.2.3.4").allowed is True

    def test_exceeds_limit_denied(self) -> None:
        storage = MemoryStorage()
        algo = SlidingWindow(storage, limit=3, window=60)
        for _ in range(3):
            algo.is_allowed("ip:1.2.3.4")
        result = algo.is_allowed("ip:1.2.3.4")
        assert result.allowed is False

    def test_old_timestamps_do_not_count(self) -> None:
        storage = MemoryStorage()
        algo = SlidingWindow(storage, limit=2, window=60)
        # Inject an old timestamp directly
        old = time.time() - 120
        storage.add_timestamp("ip:1.2.3.4", old, 60)
        # Now 2 new requests should be allowed (old one falls outside window)
        assert algo.is_allowed("ip:1.2.3.4").allowed is True
        assert algo.is_allowed("ip:1.2.3.4").allowed is True

    def test_storage_error_fails_open(self) -> None:
        bad_storage = MagicMock()
        bad_storage.add_timestamp.side_effect = ConnectionError("redis down")
        algo = SlidingWindow(bad_storage, limit=5, window=60)
        result = algo.is_allowed("key")
        assert result.allowed is True

    def test_reset_after_is_positive_when_denied(self) -> None:
        storage = MemoryStorage()
        algo = SlidingWindow(storage, limit=1, window=60)
        algo.is_allowed("k")
        result = algo.is_allowed("k")
        assert result.allowed is False
        assert result.reset_after > 0


# ---------------------------------------------------------------------------
# TokenBucket
# ---------------------------------------------------------------------------

class TestTokenBucket:
    def test_first_request_consumes_one_token(self) -> None:
        algo = TokenBucket(MemoryStorage(), limit=10, window=60)
        result = algo.is_allowed("ip:1.2.3.4")
        assert result.allowed is True
        assert result.remaining == 9

    def test_burst_up_to_limit_then_denied(self) -> None:
        storage = MemoryStorage()
        algo = TokenBucket(storage, limit=3, window=60)
        for _ in range(3):
            assert algo.is_allowed("ip:1.2.3.4").allowed is True
        result = algo.is_allowed("ip:1.2.3.4")
        assert result.allowed is False

    def test_tokens_refill_over_time(self) -> None:
        storage = MemoryStorage()
        algo = TokenBucket(storage, limit=2, window=2)  # 1 token/second
        algo.is_allowed("k")
        algo.is_allowed("k")
        assert algo.is_allowed("k").allowed is False

        # Simulate 2 seconds elapsed by manipulating last_refill
        state = storage._token_states.get("k")
        if state:
            state.last_refill -= 2.0  # rewind time

        # Should have ~2 tokens now
        assert algo.is_allowed("k").allowed is True

    def test_storage_error_fails_open(self) -> None:
        bad_storage = MagicMock()
        bad_storage.get_token_state.side_effect = ConnectionError("redis down")
        algo = TokenBucket(bad_storage, limit=5, window=60)
        result = algo.is_allowed("key")
        assert result.allowed is True

    def test_reset_after_positive_when_denied(self) -> None:
        storage = MemoryStorage()
        algo = TokenBucket(storage, limit=1, window=60)
        algo.is_allowed("k")
        result = algo.is_allowed("k")
        assert result.allowed is False
        assert result.reset_after > 0
