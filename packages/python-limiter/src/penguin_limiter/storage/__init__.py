"""Rate limit storage backends."""

from .base import RateLimitStorage
from .memory import MemoryStorage

# RedisStorage is optional (requires redis package)
try:
    from .redis_store import RedisStorage
    __all__ = [
        "RateLimitStorage",
        "MemoryStorage",
        "RedisStorage",
    ]
except ImportError:
    __all__ = [
        "RateLimitStorage",
        "MemoryStorage",
    ]
