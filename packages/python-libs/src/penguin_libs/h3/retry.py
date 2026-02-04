"""Retry logic with exponential backoff for async operations."""

from __future__ import annotations

import asyncio
import logging
import random
from typing import Any, Callable, TypeVar

from .config import RetryConfig

logger = logging.getLogger(__name__)

T = TypeVar("T")


def _calc_backoff(cfg: RetryConfig, attempt: int) -> float:
    """Calculate backoff duration for a given attempt."""
    backoff = cfg.initial_backoff * (cfg.multiplier ** attempt)
    backoff = min(backoff, cfg.max_backoff)
    if cfg.jitter:
        backoff *= 0.5 + random.random()
    return backoff


async def async_retry(
    fn: Callable[..., Any],
    cfg: RetryConfig | None = None,
    *args: Any,
    **kwargs: Any,
) -> Any:
    """Execute an async callable with exponential backoff retries.

    Args:
        fn: Async callable to execute.
        cfg: Retry configuration. Uses defaults if None.
        *args: Positional arguments passed to fn.
        **kwargs: Keyword arguments passed to fn.

    Returns:
        The return value of fn.

    Raises:
        The last exception raised by fn after all retries are exhausted.
    """
    if cfg is None:
        cfg = RetryConfig()

    last_exc: Exception | None = None

    for attempt in range(cfg.max_retries + 1):
        try:
            return await fn(*args, **kwargs)
        except Exception as exc:
            last_exc = exc
            if attempt >= cfg.max_retries:
                break
            backoff = _calc_backoff(cfg, attempt)
            logger.warning(
                "Attempt %d/%d failed: %s. Retrying in %.2fs",
                attempt + 1,
                cfg.max_retries,
                exc,
                backoff,
            )
            await asyncio.sleep(backoff)

    if last_exc is not None:
        raise last_exc
    raise RuntimeError("Unexpected error in async_retry")
