"""penguin-limiter — pluggable rate limiting for REST, gRPC, and H3.

Quick start::

    from penguin_limiter import RateLimitConfig, FlaskRateLimiter, MemoryStorage

    limiter = FlaskRateLimiter(
        config=RateLimitConfig.from_string("100/minute"),
        storage=MemoryStorage(),
    )
    limiter.init_app(app)

Private-IP bypass
-----------------
By default (``skip_private_ips=True`` on :class:`RateLimitConfig`), requests
from RFC-1918 addresses, loopback, link-local, and carrier-grade NAT ranges
are **never counted or blocked**.  Internal cluster traffic is exempt.

To disable the bypass for a specific rule::

    config = RateLimitConfig.from_string("100/minute", skip_private_ips=False)
"""

from .algorithms import RateLimitResult
from .algorithms.fixed_window import FixedWindow
from .algorithms.sliding_window import SlidingWindow
from .algorithms.token_bucket import TokenBucket
from .config import Algorithm, RateLimitConfig, parse_limit, parse_multi_tier
from .ip import extract_client_ip, is_private_ip, should_rate_limit
from .middleware.flask import FlaskRateLimiter
from .middleware.grpc import GrpcRateLimitInterceptor
from .middleware.h3 import H3RateLimitMiddleware
from .storage.memory import MemoryStorage

__all__ = [
    # Config
    "Algorithm",
    "RateLimitConfig",
    "parse_limit",
    "parse_multi_tier",
    # IP utilities
    "is_private_ip",
    "extract_client_ip",
    "should_rate_limit",
    # Algorithms
    "RateLimitResult",
    "FixedWindow",
    "SlidingWindow",
    "TokenBucket",
    # Storage
    "MemoryStorage",
    # Middleware
    "FlaskRateLimiter",
    "GrpcRateLimitInterceptor",
    "H3RateLimitMiddleware",
]

__version__ = "0.1.0"
