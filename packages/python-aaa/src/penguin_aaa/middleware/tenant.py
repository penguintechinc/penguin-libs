"""Tenant isolation middleware for multi-tenant ASGI applications."""

from __future__ import annotations

import json
from typing import Any, Awaitable, Callable

Scope = dict[str, Any]
Receive = Callable[[], Awaitable[dict[str, Any]]]
Send = Callable[[dict[str, Any]], Awaitable[None]]
ASGIApp = Callable[[Scope, Receive, Send], Awaitable[None]]


class TenantMiddleware:
    """Enforce tenant claim presence on authenticated requests.

    Reads ``scope["state"]["claims"]["tenant"]`` (populated by OIDCAuthMiddleware)
    and returns 403 if the claim is absent when ``required=True``.

    The resolved tenant identifier is stored in ``scope["state"]["tenant"]``
    for downstream handlers.

    Args:
        app: The wrapped ASGI application.
        required: When True, requests lacking a tenant claim receive a 403
            response. When False, the middleware is a no-op for claims-less
            requests (useful in mixed-auth environments).
    """

    def __init__(self, app: ASGIApp, required: bool = True) -> None:
        self._app = app
        self._required = required

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] not in ("http", "websocket"):
            await self._app(scope, receive, send)
            return

        state = scope.get("state", {})
        claims: dict[str, Any] = state.get("claims") or {}
        tenant = claims.get("tenant")

        if not tenant and self._required:
            body = json.dumps({"error": "Tenant claim missing from token"}).encode()
            await send({
                "type": "http.response.start",
                "status": 403,
                "headers": [
                    (b"content-type", b"application/json"),
                    (b"content-length", str(len(body)).encode()),
                ],
            })
            await send({"type": "http.response.body", "body": body})
            return

        if tenant:
            scope.setdefault("state", {})["tenant"] = tenant

        await self._app(scope, receive, send)
