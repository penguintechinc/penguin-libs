"""Sliding-window log algorithm.

Maintains a per-key list of request timestamps.  On each request, timestamps
older than *window* seconds are discarded, then the new timestamp is appended
and the list length is compared against *limit*.

This is the algorithm used in License Server and Waddlebot and is the
**default** for ``penguin-limiter`` because it never allows boundary bursts.

Memory usage: O(limit × active_keys).  For very high limits on high-traffic
keys, :class:`~penguin_limiter.algorithms.fixed_window.FixedWindow` is cheaper.
"""

from __future__ import annotations

import time

from ..algorithms import RateLimitResult
from ..storage import RateLimitStorage


class SlidingWindow:
    """Sliding-window log rate limiter.

    Parameters
    ----------
    storage:
        Storage backend instance.
    limit:
        Maximum requests in any *window*-second span.
    window:
        Observation window in seconds.
    """

    __slots__ = ("_storage", "_limit", "_window")

    def __init__(self, storage: RateLimitStorage, limit: int, window: int) -> None:
        self._storage = storage
        self._limit = limit
        self._window = window

    def is_allowed(self, key: str) -> RateLimitResult:
        """Record the request and return whether it falls within quota."""
        now = time.time()
        try:
            count = self._storage.add_timestamp(key, now, self._window)
        except Exception:
            return RateLimitResult(
                allowed=True,
                limit=self._limit,
                remaining=self._limit,
                reset_after=self._window,
                current_count=0,
            )

        allowed = count <= self._limit
        remaining = max(0, self._limit - count)

        # Estimate reset time: how long until the oldest timestamp falls out
        try:
            timestamps = self._storage.get_timestamps(key)
            if timestamps:
                oldest = min(timestamps)
                reset_after = max(0.0, (oldest + self._window) - now)
            else:
                reset_after = float(self._window)
        except Exception:
            reset_after = float(self._window)

        return RateLimitResult(
            allowed=allowed,
            limit=self._limit,
            remaining=remaining,
            reset_after=reset_after,
            current_count=count,
        )
