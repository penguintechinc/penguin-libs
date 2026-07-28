"""Rate-limit configuration and limit-string parsing.

Limit strings follow the pattern used across existing penguin repos:
``"100/minute"``, ``"10/second"``, ``"5000/hour"``, ``"1/day"``

Multi-tier specs (semicolon-separated) are supported:
``"10/second;100/minute;1000/hour"``
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
from typing import ClassVar


class Algorithm(str, Enum):
    """Rate-limiting algorithm selection."""

    FIXED_WINDOW = "fixed_window"
    """Divide time into fixed buckets of *window* seconds. Simple and fast."""

    SLIDING_WINDOW = "sliding_window"
    """Per-key timestamp log. Precise but uses more storage for high-traffic keys."""

    TOKEN_BUCKET = "token_bucket"
    """Smooth burst handling. Tokens accumulate at *limit/window* per second."""


_UNIT_SECONDS: dict[str, int] = {
    "second": 1,
    "sec": 1,
    "s": 1,
    "minute": 60,
    "min": 60,
    "m": 60,
    "hour": 3600,
    "hr": 3600,
    "h": 3600,
    "day": 86400,
    "d": 86400,
}

_LIMIT_RE = re.compile(
    r"^\s*(\d+)\s*/\s*(second|sec|s|minute|min|m|hour|hr|h|day|d)\s*$",
    re.IGNORECASE,
)


def parse_limit(spec: str) -> tuple[int, int]:
    """Parse ``'100/minute'`` → ``(limit=100, window_seconds=60)``.

    Raises ``ValueError`` on unrecognised format.
    """
    m = _LIMIT_RE.match(spec.strip())
    if not m:
        raise ValueError(
            f"Invalid rate-limit spec {spec!r}. "
            "Expected format: '<count>/<unit>' where unit is second/minute/hour/day."
        )
    count = int(m.group(1))
    window = _UNIT_SECONDS[m.group(2).lower()]
    return count, window


def parse_multi_tier(spec: str) -> list[tuple[int, int]]:
    """Parse a multi-tier spec ``'10/second;100/minute'`` into a list of ``(limit, window)``."""
    return [parse_limit(s) for s in spec.split(";") if s.strip()]


@dataclass(slots=True)
class RateLimitConfig:
    """Complete configuration for a single rate-limit rule.

    Parameters
    ----------
    limit:
        Maximum number of requests allowed in *window* seconds.
    window:
        Size of the rate-limit window in seconds.
    algorithm:
        Which counting algorithm to use (default: sliding window).
    key_prefix:
        Redis / memory key namespace (default: ``"rl"``).
    fail_open:
        If ``True`` (default), allow requests when the storage backend is
        unavailable.  Set to ``False`` for strict enforcement.
    add_headers:
        Attach ``X-RateLimit-*`` and ``Retry-After`` headers to responses.
    skip_private_ips:
        Skip rate limiting entirely for requests from private / internal IPs.
        Defaults to ``True`` — internal cluster traffic is always exempt.
    """

    limit: int
    window: int
    algorithm: Algorithm = Algorithm.SLIDING_WINDOW
    key_prefix: str = "rl"
    fail_open: bool = True
    add_headers: bool = True
    skip_private_ips: bool = True

    # Multi-tier support: if set, these override limit/window with a list of tiers
    tiers: list[tuple[int, int]] = field(default_factory=list)

    _SPEC_PATTERN: ClassVar[re.Pattern[str]] = _LIMIT_RE

    @classmethod
    def from_string(
        cls,
        spec: str,
        algorithm: Algorithm = Algorithm.SLIDING_WINDOW,
        **kwargs: object,
    ) -> "RateLimitConfig":
        """Build from a limit string, e.g. ``RateLimitConfig.from_string('100/minute')``."""
        tiers = parse_multi_tier(spec)
        # Use the tightest tier as primary limit/window
        limit, window = tiers[0]
        return cls(
            limit=limit,
            window=window,
            algorithm=algorithm,
            tiers=tiers if len(tiers) > 1 else [],
            **kwargs,  # type: ignore[arg-type]
        )

    @property
    def rate_per_second(self) -> float:
        """Convenience: requests allowed per second (used by token bucket)."""
        return self.limit / self.window
