"""Token-bucket algorithm.

Tokens accumulate at a rate of ``limit / window`` per second up to a maximum
of ``limit`` tokens.  Each request consumes one token.  If the bucket is empty,
the request is denied.

This algorithm (used in MarchProxy's ``proxy-nlb``) smooths out bursts: a
client that has been quiet for a while can burst up to *limit* requests
immediately, then is throttled to the steady-state rate.
"""

from __future__ import annotations

import time

from ..algorithms import RateLimitResult
from ..storage import RateLimitStorage


class TokenBucket:
    """Token-bucket rate limiter.

    Parameters
    ----------
    storage:
        Storage backend instance.
    limit:
        Bucket capacity (maximum burst size).
    window:
        Refill period in seconds.  One full bucket refills in *window* seconds,
        i.e. ``limit / window`` tokens per second.
    """

    __slots__ = ("_storage", "_limit", "_window", "_rate")

    def __init__(self, storage: RateLimitStorage, limit: int, window: int) -> None:
        self._storage = storage
        self._limit = limit
        self._window = window
        self._rate: float = limit / window  # tokens per second

    def is_allowed(self, key: str) -> RateLimitResult:
        """Consume one token and return whether the bucket had capacity."""
        now = time.time()
        try:
            tokens, last_refill = self._storage.get_token_state(key)
        except Exception:
            return RateLimitResult(
                allowed=True,
                limit=self._limit,
                remaining=self._limit,
                reset_after=0.0,
                current_count=0,
            )

        if tokens < 0:
            # First request — start with a full bucket
            tokens = float(self._limit)
            last_refill = now

        # Refill tokens based on elapsed time
        elapsed = now - last_refill
        tokens = min(float(self._limit), tokens + elapsed * self._rate)

        if tokens >= 1.0:
            tokens -= 1.0
            allowed = True
        else:
            allowed = False

        remaining = int(tokens)
        # Time until 1 token refills
        if not allowed:
            reset_after = (1.0 - tokens) / self._rate
        else:
            reset_after = 0.0

        try:
            self._storage.set_token_state(key, tokens, now, self._window * 2)
        except Exception:
            pass  # fail-open: don't deny if we can't persist state

        return RateLimitResult(
            allowed=allowed,
            limit=self._limit,
            remaining=remaining,
            reset_after=reset_after,
            current_count=self._limit - remaining,
        )
