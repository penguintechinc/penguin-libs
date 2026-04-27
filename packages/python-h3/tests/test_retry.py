"""Tests for retry logic with exponential backoff."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from penguin_h3.config import RetryConfig
from penguin_h3.retry import _calc_backoff, async_retry


class TestCalcBackoff:
    """Test backoff calculation."""

    def test_calc_backoff_first_attempt(self) -> None:
        """Test backoff calculation for first attempt."""
        cfg = RetryConfig(initial_backoff=0.1, multiplier=2.0, jitter=False)
        backoff = _calc_backoff(cfg, 0)
        assert backoff == 0.1

    def test_calc_backoff_second_attempt(self) -> None:
        """Test backoff calculation for second attempt."""
        cfg = RetryConfig(initial_backoff=0.1, multiplier=2.0, jitter=False)
        backoff = _calc_backoff(cfg, 1)
        assert backoff == 0.2

    def test_calc_backoff_exponential_growth(self) -> None:
        """Test exponential growth of backoff."""
        cfg = RetryConfig(initial_backoff=0.1, multiplier=2.0, jitter=False)
        backoff_0 = _calc_backoff(cfg, 0)
        backoff_1 = _calc_backoff(cfg, 1)
        backoff_2 = _calc_backoff(cfg, 2)

        assert backoff_0 == 0.1
        assert backoff_1 == 0.2
        assert backoff_2 == 0.4

    def test_calc_backoff_max_backoff_cap(self) -> None:
        """Test that backoff is capped at max_backoff."""
        cfg = RetryConfig(initial_backoff=1.0, max_backoff=5.0, multiplier=2.0, jitter=False)
        backoff_0 = _calc_backoff(cfg, 0)
        backoff_1 = _calc_backoff(cfg, 1)
        backoff_2 = _calc_backoff(cfg, 2)
        backoff_3 = _calc_backoff(cfg, 3)

        assert backoff_0 == 1.0
        assert backoff_1 == 2.0
        assert backoff_2 == 4.0
        assert backoff_3 == 5.0  # Capped at max_backoff
        assert _calc_backoff(cfg, 10) == 5.0  # Still capped

    def test_calc_backoff_with_jitter(self) -> None:
        """Test backoff calculation with jitter enabled."""
        cfg = RetryConfig(initial_backoff=1.0, multiplier=2.0, jitter=True)
        backoff = _calc_backoff(cfg, 0)

        # Jitter multiplies by 0.5 + random(), so result should be 0.5x to 1.5x base
        assert 0.5 <= backoff <= 1.5

    def test_calc_backoff_jitter_range(self) -> None:
        """Test that jitter produces values in expected range."""
        cfg = RetryConfig(initial_backoff=2.0, multiplier=1.0, jitter=True)
        backoffs = [_calc_backoff(cfg, 0) for _ in range(100)]

        # All values should be between 1.0 (2.0 * 0.5) and 3.0 (2.0 * 1.5)
        assert all(1.0 <= b <= 3.0 for b in backoffs)
        # Ensure we get variation (not all same value)
        assert len(set(backoffs)) > 10


class TestAsyncRetry:
    """Test async_retry function."""

    @pytest.mark.asyncio
    async def test_async_retry_success_first_try(self) -> None:
        """Test successful execution on first try."""
        fn = AsyncMock(return_value="success")
        cfg = RetryConfig(max_retries=3)

        result = await async_retry(fn, cfg)

        assert result == "success"
        assert fn.call_count == 1

    @pytest.mark.asyncio
    async def test_async_retry_success_after_retries(self) -> None:
        """Test successful execution after initial failures."""
        fn = AsyncMock(side_effect=[ValueError("fail 1"), ValueError("fail 2"), "success"])
        cfg = RetryConfig(max_retries=3, initial_backoff=0.01, jitter=False)

        result = await async_retry(fn, cfg)

        assert result == "success"
        assert fn.call_count == 3

    @pytest.mark.asyncio
    async def test_async_retry_exhausts_retries(self) -> None:
        """Test that all retries are exhausted before raising."""
        fn = AsyncMock(side_effect=ValueError("always fails"))
        cfg = RetryConfig(max_retries=2, initial_backoff=0.01, jitter=False)

        with pytest.raises(ValueError, match="always fails"):
            await async_retry(fn, cfg)

        assert fn.call_count == 3  # Initial + 2 retries

    @pytest.mark.asyncio
    async def test_async_retry_respects_max_retries(self) -> None:
        """Test that max_retries limit is respected."""
        fn = AsyncMock(side_effect=RuntimeError("fail"))
        cfg = RetryConfig(max_retries=5, initial_backoff=0.01, jitter=False)

        with pytest.raises(RuntimeError):
            await async_retry(fn, cfg)

        assert fn.call_count == 6  # Initial + 5 retries

    @pytest.mark.asyncio
    async def test_async_retry_default_config(self) -> None:
        """Test async_retry with default config (None)."""
        fn = AsyncMock(return_value="success")

        result = await async_retry(fn, None)

        assert result == "success"
        assert fn.call_count == 1

    @pytest.mark.asyncio
    async def test_async_retry_passes_args(self) -> None:
        """Test that args are passed to the function."""
        fn = AsyncMock(return_value="success")
        cfg = RetryConfig(max_retries=1)

        result = await async_retry(fn, cfg, "arg1", "arg2")

        assert result == "success"
        fn.assert_called_once_with("arg1", "arg2")

    @pytest.mark.asyncio
    async def test_async_retry_passes_kwargs(self) -> None:
        """Test that kwargs are passed to the function."""
        fn = AsyncMock(return_value="success")
        cfg = RetryConfig(max_retries=1)

        result = await async_retry(fn, cfg, key1="value1", key2="value2")

        assert result == "success"
        fn.assert_called_once_with(key1="value1", key2="value2")

    @pytest.mark.asyncio
    async def test_async_retry_passes_mixed_args_kwargs(self) -> None:
        """Test that both args and kwargs are passed."""
        fn = AsyncMock(return_value="success")
        cfg = RetryConfig(max_retries=1)

        result = await async_retry(fn, cfg, "arg1", key="value")

        assert result == "success"
        fn.assert_called_once_with("arg1", key="value")

    @pytest.mark.asyncio
    async def test_async_retry_backoff_timing(self) -> None:
        """Test that backoff delay is applied between retries."""
        fn = AsyncMock(side_effect=ValueError("fail"))
        cfg = RetryConfig(max_retries=2, initial_backoff=0.05, multiplier=1.0, jitter=False)

        with patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
            with pytest.raises(ValueError):
                await async_retry(fn, cfg)

            # Should sleep twice (between attempts)
            assert mock_sleep.call_count == 2
            # First sleep 0.05, second sleep 0.05
            sleep_calls = [call[0][0] for call in mock_sleep.call_args_list]
            assert sleep_calls[0] == 0.05
            assert sleep_calls[1] == 0.05

    @pytest.mark.asyncio
    async def test_async_retry_exponential_backoff_timing(self) -> None:
        """Test exponential backoff timing between retries."""
        fn = AsyncMock(side_effect=ValueError("fail"))
        cfg = RetryConfig(max_retries=3, initial_backoff=0.1, multiplier=2.0, jitter=False)

        with patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
            with pytest.raises(ValueError):
                await async_retry(fn, cfg)

            assert mock_sleep.call_count == 3
            sleep_calls = [call[0][0] for call in mock_sleep.call_args_list]
            assert abs(sleep_calls[0] - 0.1) < 0.01
            assert abs(sleep_calls[1] - 0.2) < 0.01
            assert abs(sleep_calls[2] - 0.4) < 0.01

    @pytest.mark.asyncio
    async def test_async_retry_preserves_exception_type(self) -> None:
        """Test that original exception type is preserved."""
        fn = AsyncMock(side_effect=TimeoutError("timeout"))
        cfg = RetryConfig(max_retries=1, initial_backoff=0.01, jitter=False)

        with pytest.raises(TimeoutError):
            await async_retry(fn, cfg)

    @pytest.mark.asyncio
    async def test_async_retry_preserves_exception_message(self) -> None:
        """Test that original exception message is preserved."""
        error_msg = "specific error message"
        fn = AsyncMock(side_effect=ValueError(error_msg))
        cfg = RetryConfig(max_retries=1, initial_backoff=0.01, jitter=False)

        with pytest.raises(ValueError, match=error_msg):
            await async_retry(fn, cfg)

    @pytest.mark.asyncio
    async def test_async_retry_returns_value_on_success(self) -> None:
        """Test various return values are preserved."""
        # Test with dict
        fn = AsyncMock(return_value={"key": "value"})
        cfg = RetryConfig(max_retries=1)
        result = await async_retry(fn, cfg)
        assert result == {"key": "value"}

        # Test with list
        fn = AsyncMock(return_value=[1, 2, 3])
        result = await async_retry(fn, cfg)
        assert result == [1, 2, 3]

        # Test with None
        fn = AsyncMock(return_value=None)
        result = await async_retry(fn, cfg)
        assert result is None

    @pytest.mark.asyncio
    async def test_async_retry_no_sleep_on_final_failure(self) -> None:
        """Test that no sleep occurs after final failure."""
        fn = AsyncMock(side_effect=ValueError("fail"))
        cfg = RetryConfig(max_retries=2, initial_backoff=0.01, jitter=False)

        with patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
            with pytest.raises(ValueError):
                await async_retry(fn, cfg)

            # Should sleep only 2 times (between 3 attempts), not after the last
            assert mock_sleep.call_count == 2

    @pytest.mark.asyncio
    async def test_async_retry_zero_max_retries(self) -> None:
        """Test with max_retries=0 (only initial attempt, no retries)."""
        fn = AsyncMock(side_effect=ValueError("fail"))
        cfg = RetryConfig(max_retries=0)

        with pytest.raises(ValueError):
            await async_retry(fn, cfg)

        assert fn.call_count == 1  # Only initial attempt

    @pytest.mark.asyncio
    async def test_async_retry_logs_on_failure(self) -> None:
        """Test that failures are logged with attempt info."""
        fn = AsyncMock(side_effect=ValueError("fail"))
        cfg = RetryConfig(max_retries=2, initial_backoff=0.01, jitter=False)

        with patch("penguin_h3.retry.logger") as mock_logger:
            with pytest.raises(ValueError):
                await async_retry(fn, cfg)

            # Should log warning for each failed attempt except the last
            assert mock_logger.warning.call_count == 2
