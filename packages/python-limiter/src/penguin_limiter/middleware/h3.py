"""H3 (penguin_libs H3 protocol) rate-limit middleware.

Integrates with the ``penguin_libs.h3.middleware`` ASGI middleware stack used
across penguin services.  The middleware follows the same pattern as
``LoggingMiddleware`` and ``AuthMiddleware`` — it wraps the ASGI ``scope`` /
``receive`` / ``send`` triple.

Usage::

    from penguin_limiter.middleware.h3 import H3RateLimitMiddleware
    from penguin_limiter.config import RateLimitConfig
    from penguin_limiter.storage.redis_store import RedisStorage
    import redis

    r = redis.Redis.from_url("redis://localhost:6379/0")

    app = H3RateLimitMiddleware(
        app=your_asgi_app,
        config=RateLimitConfig.from_string("200/minute"),
        storage=RedisStorage(r),
    )

IP extraction for H3
--------------------
H3 connections carry HTTP/3 headers.  The middleware reads (in order):

1. ``x-forwarded-for`` header from the H3 request headers
2. ``x-real-ip`` header
3. ``scope["client"][0]`` — the QUIC source address

Private-IP bypass is controlled by ``skip_private_ips`` on the config
(default ``True``).  Pass ``skip_private_ips=False`` to disable it.
"""

from __future__ import annotations

import time
from typing import Any, Callable

from ..algorithms.fixed_window import FixedWindow
from ..algorithms.sliding_window import SlidingWindow
from ..algorithms.token_bucket import TokenBucket
from ..config import Algorithm, RateLimitConfig
from ..ip import should_rate_limit
from ..storage import RateLimitStorage


def _build_algorithm(
    config: RateLimitConfig, storage: RateLimitStorage
) -> FixedWindow | SlidingWindow | TokenBucket:
    if config.algorithm == Algorithm.FIXED_WINDOW:
        return FixedWindow(storage, config.limit, config.window)
    if config.algorithm == Algorithm.TOKEN_BUCKET:
        return TokenBucket(storage, config.limit, config.window)
    return SlidingWindow(storage, config.limit, config.window)


class H3RateLimitMiddleware:
    """ASGI middleware for H3 / HTTP3 rate limiting.

    Parameters
    ----------
    app:
        The downstream ASGI application.
    config:
        Rate-limit configuration.  ``skip_private_ips=True`` (default) means
        private-network sources bypass rate limiting entirely.
        Set ``skip_private_ips=False`` to enforce limits for all sources.
    storage:
        Storage backend.
    """

    def __init__(
        self,
        app: Any,
        config: RateLimitConfig,
        storage: RateLimitStorage | None = None,
    ) -> None:
        if storage is None:
            from ..storage.memory import MemoryStorage
            storage = MemoryStorage()
        self._app = app
        self._config = config
        self._algo = _build_algorithm(config, storage)

    async def __call__(
        self,
        scope: dict[str, Any],
        receive: Callable[..., Any],
        send: Callable[..., Any],
    ) -> None:
        if scope.get("type") not in ("http", "websocket", "h3"):
            await self._app(scope, receive, send)
            return

        # ------------------------------------------------------------------
        # Extract client IP from H3 headers or QUIC source address
        # ------------------------------------------------------------------
        headers: dict[str, str] = {}
        for name, value in scope.get("headers", []):
            headers[name.decode().lower() if isinstance(name, bytes) else name.lower()] = (
                value.decode() if isinstance(value, bytes) else value
            )

        xff = headers.get("x-forwarded-for")
        xri = headers.get("x-real-ip")
        client = scope.get("client")
        remote_addr = client[0] if isinstance(client, (list, tuple)) and client else None

        if self._config.skip_private_ips:
            do_limit, client_ip = should_rate_limit(xff, xri, remote_addr)
            if not do_limit:
                await self._app(scope, receive, send)
                return
        else:
            _, client_ip = should_rate_limit(xff, xri, remote_addr)
            client_ip = client_ip or remote_addr or "unknown"
            do_limit = True

        key = f"{self._config.key_prefix}:{client_ip}"

        try:
            result = self._algo.is_allowed(key)
        except Exception:
            if self._config.fail_open:
                await self._app(scope, receive, send)
                return
            await self._send_429(send, reset_after=self._config.window)
            return

        if not result.allowed:
            await self._send_429(send, reset_after=result.reset_after, result=result)
            return

        # Inject X-RateLimit-* headers into the response via a send wrapper
        if self._config.add_headers:
            send = self._wrap_send(send, result)

        await self._app(scope, receive, send)

    @staticmethod
    def _wrap_send(
        send: Callable[..., Any],
        result: Any,
    ) -> Callable[..., Any]:
        """Inject rate-limit headers into the first ``http.response.start`` event."""
        injected = False

        async def wrapped_send(event: dict[str, Any]) -> None:
            nonlocal injected
            if event.get("type") == "http.response.start" and not injected:
                injected = True
                extra_headers = [
                    (b"x-ratelimit-limit", str(result.limit).encode()),
                    (b"x-ratelimit-remaining", str(result.remaining).encode()),
                    (b"x-ratelimit-reset", str(int(time.time() + result.reset_after)).encode()),
                ]
                event = {
                    **event,
                    "headers": list(event.get("headers", [])) + extra_headers,
                }
            await send(event)

        return wrapped_send

    @staticmethod
    async def _send_429(
        send: Callable[..., Any],
        reset_after: float,
        result: Any = None,
    ) -> None:
        """Send an HTTP 429 Too Many Requests response."""
        headers = [
            (b"content-type", b"application/json"),
            (b"retry-after", str(int(reset_after)).encode()),
        ]
        if result is not None:
            headers += [
                (b"x-ratelimit-limit", str(result.limit).encode()),
                (b"x-ratelimit-remaining", b"0"),
                (b"x-ratelimit-reset", str(int(time.time() + reset_after)).encode()),
            ]
        await send({"type": "http.response.start", "status": 429, "headers": headers})
        body = b'{"error":"rate_limit_exceeded","message":"Too many requests"}'
        await send({"type": "http.response.body", "body": body, "more_body": False})
