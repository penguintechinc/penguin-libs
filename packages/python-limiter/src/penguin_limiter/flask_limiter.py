"""Flask rate limiter extension."""

from __future__ import annotations

from dataclasses import dataclass
from functools import wraps
from typing import Callable, Optional

from flask import Flask, request, jsonify

from .config import RateLimitConfig
from .storage.base import RateLimitStorage


@dataclass(slots=True)
class RateLimitStatus:
    """Rate limit status for a request."""

    limited: bool
    limit: int
    remaining: int
    reset: int


class FlaskRateLimiter:
    """Flask extension for rate limiting.

    Example:
        from flask import Flask
        from penguin_limiter import FlaskRateLimiter, MemoryStorage, RateLimitConfig

        app = Flask(__name__)
        limiter = FlaskRateLimiter(
            config=RateLimitConfig.from_string("100/hour"),
            storage=MemoryStorage(),
        )
        limiter.init_app(app)

        @app.route("/api/endpoint")
        @limiter.limit()
        def my_endpoint():
            return {"message": "success"}
    """

    def __init__(
        self,
        config: RateLimitConfig,
        storage: RateLimitStorage,
        key_func: Optional[Callable[[], str]] = None,
    ) -> None:
        """Initialize rate limiter.

        Args:
            config: Rate limit configuration (e.g., "100/hour")
            storage: Storage backend (MemoryStorage or RedisStorage)
            key_func: Optional function to extract rate limit key from request.
                     Defaults to request.remote_addr
        """
        self.config = config
        self.storage = storage
        self.key_func = key_func or (lambda: request.remote_addr or "unknown")
        self.app: Optional[Flask] = None

    def init_app(self, app: Flask) -> None:
        """Initialize Flask application.

        Args:
            app: Flask application instance
        """
        self.app = app
        app.limiter = self

    def limit(self, config: Optional[RateLimitConfig] = None) -> Callable:
        """Decorator to apply rate limiting to a route.

        Args:
            config: Optional RateLimitConfig to override default.
                   Uses self.config if not provided.

        Returns:
            Decorator function
        """
        cfg = config or self.config

        def decorator(f: Callable) -> Callable:
            @wraps(f)
            def decorated_function(*args, **kwargs) -> tuple:  # type: ignore
                key = self.key_func()
                window_seconds = cfg.to_seconds()
                ttl_seconds = window_seconds

                # Get current count
                current = self.storage.increment(key, 1, ttl_seconds)

                # Check if rate limit exceeded
                if current > cfg.rate:
                    # Set response headers
                    response = jsonify(
                        {
                            "error": "rate_limit_exceeded",
                            "message": f"Rate limit exceeded: {cfg.rate}/{cfg.unit}",
                            "limit": cfg.rate,
                            "remaining": 0,
                            "retry_after": ttl_seconds,
                        }
                    )
                    response.status_code = 429
                    response.headers["Retry-After"] = str(ttl_seconds)
                    response.headers["X-RateLimit-Limit"] = str(cfg.rate)
                    response.headers["X-RateLimit-Remaining"] = "0"
                    response.headers["X-RateLimit-Reset"] = str(int(ttl_seconds))
                    return response

                # Set response headers for successful request
                remaining = max(0, cfg.rate - current)

                # Call original function
                result = f(*args, **kwargs)

                # Add rate limit headers to response
                if isinstance(result, tuple):
                    response_obj, status_code = result[:2]
                else:
                    response_obj = result
                    status_code = 200

                # Convert to Flask Response if needed
                if not hasattr(response_obj, "headers"):
                    from flask import make_response

                    flask_response = make_response(response_obj, status_code)
                else:
                    flask_response = response_obj

                flask_response.headers["X-RateLimit-Limit"] = str(cfg.rate)
                flask_response.headers["X-RateLimit-Remaining"] = str(remaining)
                flask_response.headers["X-RateLimit-Reset"] = str(int(ttl_seconds))

                # Return appropriately based on original result type
                if isinstance(result, tuple):
                    return flask_response, status_code
                return flask_response

            return decorated_function

        return decorator

    def get_status(self) -> RateLimitStatus:
        """Get rate limit status for current request."""
        key = self.key_func()
        counter, ttl = self.storage.get_with_ttl(key)
        limited = counter > self.config.rate
        remaining = max(0, self.config.rate - counter)

        return RateLimitStatus(
            limited=limited,
            limit=self.config.rate,
            remaining=remaining,
            reset=int(ttl) if ttl > 0 else 0,
        )
