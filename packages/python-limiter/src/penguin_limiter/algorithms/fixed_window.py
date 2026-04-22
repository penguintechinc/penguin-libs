"""Fixed-window counter algorithm.

The simplest possible rate limiter: divide time into fixed buckets of
*window* seconds, reset the counter at the bucket boundary.

Trade-off: allows up to 2× the limit at window boundaries (a burst at the
end of one window followed by a burst at the start of the next).  Use
:class:`~penguin_limiter.algorithms.sliding_window.SlidingWindow` if boundary
bursts are unacceptable.
"""

from __future__ import annotations

import time

from ..algorithms import RateLimitResult
from ..storage import RateLimitStorage


class FixedWindow:
    """Fixed-window rate limiter.

    Parameters
    ----------
    storage:
        Storage backend instance.
    limit:
        Maximum requests per *window* seconds.
    window:
        Window duration in seconds.
    """

    __slots__ = ("_storage", "_limit", "_window")

    def __init__(self, storage: RateLimitStorage, limit: int, window: int) -> None:
        self._storage = storage
        self._limit = limit
        self._window = window

    def is_allowed(self, key: str) -> RateLimitResult:
        """Check and count the request identified by *key*.

        The counter is incremented *before* the limit check so that concurrent
        requests at the boundary are handled correctly.
        """
        try:
            count = self._storage.increment(key, self._window)
        except Exception:
            # Storage unavailable — caller decides whether to fail open/closed
            return RateLimitResult(
                allowed=True,
                limit=self._limit,
                remaining=self._limit,
                reset_after=self._window,
                current_count=0,
            )

        allowed = count <= self._limit
        remaining = max(0, self._limit - count)
        # Fixed window resets at the next window boundary; approximate here
        reset_after = float(self._window)

        return RateLimitResult(
            allowed=allowed,
            limit=self._limit,
            remaining=remaining,
            reset_after=reset_after,
            current_count=count,
        )
