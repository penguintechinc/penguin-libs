"""ASGI middleware for HTTP/3 services.

Provides auth, logging, and correlation ID middleware
compatible with any ASGI framework (Quart, FastAPI, Starlette).
"""

from __future__ import annotations

import logging
import time
import uuid
from typing import Any, Awaitable, Callable

logger = logging.getLogger(__name__)

# ASGI type aliases
Scope = dict[str, Any]
Receive = Callable[[], Awaitable[dict[str, Any]]]
Send = Callable[[dict[str, Any]], Awaitable[None]]
ASGIApp = Callable[[Scope, Receive, Send], Awaitable[None]]


class CorrelationIDMiddleware:
    """ASGI middleware that propagates or generates X-Correlation-ID headers."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] not in ("http", "websocket"):
            await self.app(scope, receive, send)
            return

        headers = dict(scope.get("headers", []))
        cid = headers.get(b"x-correlation-id", b"").decode() or str(uuid.uuid4())
        scope.setdefault("state", {})["correlation_id"] = cid

        async def send_with_cid(message: dict[str, Any]) -> None:
            if message["type"] == "http.response.start":
                response_headers = list(message.get("headers", []))
                response_headers.append((b"x-correlation-id", cid.encode()))
                message["headers"] = response_headers
            await send(message)

        await self.app(scope, receive, send_with_cid)


class LoggingMiddleware:
    """ASGI middleware that logs request method, path, status, and duration."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        start = time.monotonic()
        method = scope.get("method", "?")
        path = scope.get("path", "?")
        status_code = 0

        async def capture_send(message: dict[str, Any]) -> None:
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = message.get("status", 0)
            await send(message)

        try:
            await self.app(scope, receive, capture_send)
        finally:
            duration_ms = (time.monotonic() - start) * 1000
            cid = scope.get("state", {}).get("correlation_id", "")
            logger.info(
                "%s %s -> %d (%.1fms)",
                method,
                path,
                status_code,
                duration_ms,
                extra={"correlation_id": cid, "method": method, "path": path},
            )


class AuthMiddleware:
    """ASGI middleware that validates Bearer tokens.

    Args:
        app: The ASGI application to wrap.
        validate_fn: Async callable that receives a token string and raises
            on invalid tokens.
        public_paths: Set of paths that bypass authentication.
    """

    def __init__(
        self,
        app: ASGIApp,
        validate_fn: Callable[[str], Awaitable[None]],
        public_paths: set[str] | None = None,
    ) -> None:
        self.app = app
        self.validate_fn = validate_fn
        self.public_paths = public_paths or set()

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        path = scope.get("path", "")
        if path in self.public_paths:
            await self.app(scope, receive, send)
            return

        headers = dict(scope.get("headers", []))
        auth = headers.get(b"authorization", b"").decode()
        if not auth.startswith("Bearer "):
            await self._send_error(send, 401, "Missing bearer token")
            return

        token = auth[7:]
        try:
            await self.validate_fn(token)
        except Exception:
            await self._send_error(send, 401, "Invalid token")
            return

        await self.app(scope, receive, send)

    @staticmethod
    async def _send_error(send: Send, status: int, body: str) -> None:
        await send({
            "type": "http.response.start",
            "status": status,
            "headers": [(b"content-type", b"text/plain")],
        })
        await send({
            "type": "http.response.body",
            "body": body.encode(),
        })
