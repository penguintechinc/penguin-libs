"""Flask / Quart rate-limit middleware and decorator helpers.

Usage — global middleware (applied to every request)::

    from flask import Flask
    from penguin_limiter.middleware.flask import FlaskRateLimiter
    from penguin_limiter.config import RateLimitConfig
    from penguin_limiter.storage.memory import MemoryStorage

    app = Flask(__name__)
    limiter = FlaskRateLimiter(
        config=RateLimitConfig.from_string("100/minute"),
        storage=MemoryStorage(),
    )
    limiter.init_app(app)

Usage — per-route decorator::

    @app.route("/api/v1/search")
    @limiter.limit("10/second")
    def search():
        ...

The ``skip_private_ips`` flag on :class:`~penguin_limiter.config.RateLimitConfig`
is honoured by default — internal cluster traffic is **never** counted.
Set ``skip_private_ips=False`` in the config to disable the bypass.
"""

from __future__ import annotations

import functools
import time
from typing import Any, Callable, TypeVar

from ..algorithms import RateLimitResult
from ..algorithms.fixed_window import FixedWindow
from ..algorithms.sliding_window import SlidingWindow
from ..algorithms.token_bucket import TokenBucket
from ..config import Algorithm, RateLimitConfig
from ..ip import should_rate_limit
from ..storage import RateLimitStorage

F = TypeVar("F", bound=Callable[..., Any])


def _build_algorithm(
    config: RateLimitConfig, storage: RateLimitStorage
) -> FixedWindow | SlidingWindow | TokenBucket:
    if config.algorithm == Algorithm.FIXED_WINDOW:
        return FixedWindow(storage, config.limit, config.window)
    if config.algorithm == Algorithm.TOKEN_BUCKET:
        return TokenBucket(storage, config.limit, config.window)
    return SlidingWindow(storage, config.limit, config.window)


def _rate_limit_headers(result: RateLimitResult) -> dict[str, str]:
    return {
        "X-RateLimit-Limit": str(result.limit),
        "X-RateLimit-Remaining": str(result.remaining),
        "X-RateLimit-Reset": str(int(time.time() + result.reset_after)),
        "Retry-After": str(int(result.reset_after)) if not result.allowed else "0",
    }


class FlaskRateLimiter:
    """Flask/Quart rate limiter.

    Parameters
    ----------
    config:
        Default :class:`~penguin_limiter.config.RateLimitConfig` applied to
        every request unless overridden by a per-route decorator.
    storage:
        Storage backend.  Defaults to a new :class:`~penguin_limiter.storage.memory.MemoryStorage`.
    key_func:
        Callable that receives the Flask ``request`` object and returns a
        string key.  Defaults to client IP.
    """

    def __init__(
        self,
        config: RateLimitConfig,
        storage: RateLimitStorage | None = None,
        key_func: Callable[..., str] | None = None,
    ) -> None:
        if storage is None:
            from ..storage.memory import MemoryStorage
            storage = MemoryStorage()
        self._config = config
        self._storage = storage
        self._algo = _build_algorithm(config, storage)
        self._key_func = key_func or self._default_key_func
        self._app: Any = None

    @staticmethod
    def _default_key_func(request: Any) -> str:  # noqa: ANN401
        """Extract client IP from the Flask request object."""
        xff = request.headers.get("X-Forwarded-For")
        xri = request.headers.get("X-Real-IP")
        ra = request.remote_addr or ""
        _, ip = should_rate_limit(xff, xri, ra)
        return ip or ra

    def init_app(self, app: Any) -> None:
        """Register the before/after request hooks on *app*."""
        self._app = app
        app.before_request(self._before_request)

    def _before_request(self) -> Any:
        """Check rate limit; abort with 429 if exceeded."""
        try:
            from flask import abort, request
        except ImportError:
            try:
                from quart import abort, request  # type: ignore[no-reattr]
            except ImportError:
                return None

        # ----------------------------------------------------------
        # Private-IP bypass (configurable via skip_private_ips)
        # ----------------------------------------------------------
        if self._config.skip_private_ips:
            xff = request.headers.get("X-Forwarded-For")
            xri = request.headers.get("X-Real-IP")
            ra = request.remote_addr or ""
            do_limit, client_ip = should_rate_limit(xff, xri, ra)
            if not do_limit:
                return None  # internal traffic — skip entirely
        else:
            client_ip = self._key_func(request)

        key = f"{self._config.key_prefix}:{client_ip}"
        try:
            result = self._algo.is_allowed(key)
        except Exception:
            if self._config.fail_open:
                return None
            abort(503)

        if not result.allowed:
            response = abort(429)
            return response

        return None

    def limit(
        self,
        spec: str,
        key_func: Callable[..., str] | None = None,
        skip_private_ips: bool | None = None,
    ) -> Callable[[F], F]:
        """Per-route rate-limit decorator.

        Parameters
        ----------
        spec:
            Limit string, e.g. ``"10/second"`` or ``"100/minute"``.
        key_func:
            Override the default IP-based key function for this route.
        skip_private_ips:
            Override the global ``skip_private_ips`` setting for this route.
            Pass ``False`` to rate-limit even private/internal callers.
        """
        route_config = RateLimitConfig.from_string(
            spec,
            algorithm=self._config.algorithm,
            key_prefix=self._config.key_prefix,
            fail_open=self._config.fail_open,
            add_headers=self._config.add_headers,
            skip_private_ips=(
                skip_private_ips
                if skip_private_ips is not None
                else self._config.skip_private_ips
            ),
        )
        route_algo = _build_algorithm(route_config, self._storage)
        effective_key_func = key_func or self._key_func

        def decorator(fn: F) -> F:
            @functools.wraps(fn)
            def wrapper(*args: Any, **kwargs: Any) -> Any:
                try:
                    from flask import abort, request
                except ImportError:
                    from quart import abort, request  # type: ignore[no-reattr]

                # Private-IP bypass for this route
                if route_config.skip_private_ips:
                    xff = request.headers.get("X-Forwarded-For")
                    xri = request.headers.get("X-Real-IP")
                    ra = request.remote_addr or ""
                    do_limit, client_ip = should_rate_limit(xff, xri, ra)
                    if not do_limit:
                        return fn(*args, **kwargs)
                    key = f"{route_config.key_prefix}:{client_ip}"
                else:
                    key = f"{route_config.key_prefix}:{effective_key_func(request)}"

                try:
                    result = route_algo.is_allowed(key)
                except Exception:
                    if route_config.fail_open:
                        return fn(*args, **kwargs)
                    abort(503)

                if not result.allowed:
                    abort(429)

                return fn(*args, **kwargs)

            return wrapper  # type: ignore[return-value]

        return decorator

    def exempt(self, fn: F) -> F:
        """Mark a route as exempt from all rate limits."""
        fn._rate_limit_exempt = True  # type: ignore[attr-defined]
        return fn
