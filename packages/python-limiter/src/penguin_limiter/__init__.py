"""Penguin Rate Limiter - Flask rate limiting middleware.

A production-ready rate limiter for Flask applications with support for
in-process and Redis-backed storage.
"""

from __future__ import annotations

__version__ = "0.1.0"

from .config import RateLimitConfig
from .flask_limiter import FlaskRateLimiter, RateLimitStatus
from .storage import MemoryStorage, RateLimitStorage

# RedisStorage is optional (requires redis package)
try:
    from .storage import RedisStorage
    _has_redis = True
except (ImportError, AttributeError):
    _has_redis = False

__all__ = [
    "__version__",
    # Config
    "RateLimitConfig",
    # Flask extension
    "FlaskRateLimiter",
    "RateLimitStatus",
    # Storage
    "RateLimitStorage",
    "MemoryStorage",
]

if _has_redis:
    __all__.append("RedisStorage")
