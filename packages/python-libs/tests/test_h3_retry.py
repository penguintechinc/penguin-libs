"""Tests for penguin_libs.h3.retry module."""

import asyncio
from unittest.mock import AsyncMock, patch

import pytest

from penguin_libs.h3.config import RetryConfig
from penguin_libs.h3.retry import _calc_backoff, async_retry


def test_calc_backoff_exponential():
    """Test exponential backoff calculation without jitter."""
    config = RetryConfig(
        initial_backoff=0.1,
        max_backoff=5.0,
        multiplier=2.0,
        jitter=False
    )

    assert _calc_backoff(config, 0) == 0.1
    assert _calc_backoff(config, 1) == 0.2
    assert _calc_backoff(config, 2) == 0.4


def test_calc_backoff_max_capped():
    """Test that backoff is capped at max_backoff."""
    config = RetryConfig(
        initial_backoff=0.1,
        max_backoff=1.0,
        multiplier=2.0,
        jitter=False
    )

    # After enough attempts, should cap at 1.0
    assert _calc_backoff(config, 10) == 1.0


def test_calc_backoff_jitter_range():
    """Test that jitter produces values in expected range."""
    config = RetryConfig(
        initial_backoff=1.0,
        max_backoff=10.0,
        multiplier=2.0,
        jitter=True
    )

    # Run multiple times to test jitter randomness
    for _ in range(10):
        backoff = _calc_backoff(config, 0)
        # Jitter should produce values in range [0.5 * base, 1.5 * base]
        assert 0.5 <= backoff <= 1.5


@pytest.mark.asyncio
async def test_async_retry_success_first_try():
    """Test async_retry succeeds on first attempt."""
    mock_fn = AsyncMock(return_value="success")
    config = RetryConfig(max_retries=3)

    result = await async_retry(mock_fn, config)

    assert result == "success"
    assert mock_fn.call_count == 1


@pytest.mark.asyncio
async def test_async_retry_success_after_failures():
    """Test async_retry succeeds after some failures."""
    mock_fn = AsyncMock(side_effect=[
        ValueError("fail 1"),
        ValueError("fail 2"),
        "success"
    ])
    config = RetryConfig(max_retries=3, initial_backoff=0.01)

    with patch('asyncio.sleep', new_callable=AsyncMock) as mock_sleep:
        result = await async_retry(mock_fn, config)

    assert result == "success"
    assert mock_fn.call_count == 3
    assert mock_sleep.call_count == 2  # Sleep between attempts


@pytest.mark.asyncio
async def test_async_retry_exhausted():
    """Test async_retry raises after max_retries exhausted."""
    mock_fn = AsyncMock(side_effect=ValueError("always fails"))
    config = RetryConfig(max_retries=2, initial_backoff=0.01)

    with patch('asyncio.sleep', new_callable=AsyncMock):
        with pytest.raises(ValueError, match="always fails"):
            await async_retry(mock_fn, config)

    assert mock_fn.call_count == 3  # Initial + 2 retries
