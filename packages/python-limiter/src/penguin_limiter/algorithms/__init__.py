"""Rate-limiting algorithm implementations.

All algorithms operate on a :class:`~penguin_limiter.storage.RateLimitStorage`
backend and return a :class:`RateLimitResult` describing whether the request
is allowed and the current quota state.

Available algorithms
--------------------
- :class:`~penguin_limiter.algorithms.fixed_window.FixedWindow`
- :class:`~penguin_limiter.algorithms.sliding_window.SlidingWindow`
- :class:`~penguin_limiter.algorithms.token_bucket.TokenBucket`
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(slots=True)
class RateLimitResult:
    """Outcome of a single rate-limit check.

    Attributes
    ----------
    allowed:
        ``True`` if the request is within quota.
    limit:
        The configured maximum (requests per window).
    remaining:
        Requests left in the current window (0 when *allowed* is ``False``).
    reset_after:
        Approximate seconds until the quota resets (for ``Retry-After`` header).
    current_count:
        Raw counter value at the time of the check.
    """

    allowed: bool
    limit: int
    remaining: int
    reset_after: float
    current_count: int = field(default=0)


__all__ = ["RateLimitResult"]
