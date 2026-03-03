"""ASGI middleware for OIDC authentication, SPIFFE mTLS, and audit logging."""

from __future__ import annotations

import json
import time
from collections.abc import Awaitable, Callable
from typing import Any

from penguin_aaa.audit.emitter import Emitter
from penguin_aaa.audit.event import AuditEvent, EventType, Outcome

# ASGI type aliases — consistent with ASGI spec and existing h3 middleware
Scope = dict[str, Any]
Receive = Callable[[], Awaitable[dict[str, Any]]]
Send = Callable[[dict[str, Any]], Awaitable[None]]
ASGIApp = Callable[[Scope, Receive, Send], Awaitable[None]]


async def _send_json_error(send: Send, status: int, message: str) -> None:
    """Send a minimal JSON error response without invoking the wrapped app."""
    body = json.dumps({"error": message}).encode()
    await send(
        {
            "type": "http.response.start",
            "status": status,
            "headers": [
                (b"content-type", b"application/json"),
                (b"content-length", str(len(body)).encode()),
            ],
        }
    )
    await send({"type": "http.response.body", "body": body})


class OIDCAuthMiddleware:
    """Validate Bearer tokens via an OIDC Relying Party and populate claims.

    On success, ``scope["state"]["claims"]`` is set to the decoded token
    payload. On failure, a 401 JSON response is returned immediately without
    invoking the wrapped application.

    Args:
        app: The wrapped ASGI application.
        rp: An OIDCRelyingParty instance used to verify tokens.
        public_paths: Paths that bypass authentication entirely.
    """

    def __init__(
        self,
        app: ASGIApp,
        rp: Any,
        public_paths: set[str] | None = None,
    ) -> None:
        self._app = app
        self._rp = rp
        self._public_paths = public_paths or set()

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] not in ("http", "websocket"):
            await self._app(scope, receive, send)
            return

        path = scope.get("path", "")
        if path in self._public_paths:
            await self._app(scope, receive, send)
            return

        headers = dict(scope.get("headers", []))
        auth = headers.get(b"authorization", b"").decode()

        if not auth.startswith("Bearer "):
            await _send_json_error(send, 401, "Missing or invalid Bearer token")
            return

        token = auth[7:]
        try:
            claims = await self._rp.verify_token(token)
        except Exception:
            await _send_json_error(send, 401, "Token verification failed")
            return

        scope.setdefault("state", {})["claims"] = claims
        await self._app(scope, receive, send)


class SPIFFEAuthMiddleware:
    """Validate SPIFFE workload identity from the TLS peer certificate.

    Expects the ASGI server (or a TLS-terminating proxy) to populate
    ``scope["extensions"]["tls"]["peer_cert"]["spiffe_id"]`` with the
    verified SPIFFE ID string. If the authenticator rejects the ID, a 401
    JSON response is returned.

    Args:
        app: The wrapped ASGI application.
        authenticator: An object with an ``authenticate(spiffe_id: str)``
            method that raises on failure.
    """

    def __init__(self, app: ASGIApp, authenticator: Any) -> None:
        self._app = app
        self._authenticator = authenticator

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] not in ("http", "websocket"):
            await self._app(scope, receive, send)
            return

        extensions = scope.get("extensions", {})
        tls_info = extensions.get("tls", {})
        peer_cert = tls_info.get("peer_cert", {})
        spiffe_id = peer_cert.get("spiffe_id")

        if not spiffe_id:
            await _send_json_error(send, 401, "Missing SPIFFE peer identity")
            return

        try:
            self._authenticator.authenticate(spiffe_id)
        except Exception:
            await _send_json_error(send, 401, "SPIFFE identity rejected")
            return

        scope.setdefault("state", {})["spiffe_id"] = spiffe_id
        await self._app(scope, receive, send)


class AuditMiddleware:
    """Emit an AuditEvent for every HTTP request handled by the application.

    Captures the response status code and elapsed time, then emits an
    AuditEvent with type ``auth.success`` or ``auth.failure`` based on
    whether the status is below 400. Timing and correlation IDs are included
    in the ``details`` field.

    Args:
        app: The wrapped ASGI application.
        emitter: An Emitter instance to deliver events to registered sinks.
    """

    def __init__(self, app: ASGIApp, emitter: Emitter) -> None:
        self._app = app
        self._emitter = emitter

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self._app(scope, receive, send)
            return

        start = time.monotonic()
        status_code = 0

        async def capture_send(message: dict[str, Any]) -> None:
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = message.get("status", 0)
            await send(message)

        await self._app(scope, receive, capture_send)

        duration_ms = (time.monotonic() - start) * 1000
        state = scope.get("state", {})
        claims: dict[str, Any] = state.get("claims") or {}
        correlation_id = state.get("correlation_id")
        headers = dict(scope.get("headers", []))

        outcome = Outcome.SUCCESS if status_code < 400 else Outcome.FAILURE
        event_type = EventType.AUTH_SUCCESS if status_code < 400 else EventType.AUTH_FAILURE
        subject = claims.get("sub", "anonymous") if claims else "anonymous"

        event = AuditEvent(
            type=event_type,
            subject=subject,
            action=scope.get("method", "UNKNOWN"),
            resource=scope.get("path", "/"),
            outcome=outcome,
            ip=headers.get(b"x-forwarded-for", b"").decode() or None,
            user_agent=headers.get(b"user-agent", b"").decode() or None,
            correlation_id=correlation_id,
            details={
                "status_code": status_code,
                "duration_ms": round(duration_ms, 2),
            },
        )
        self._emitter.emit(event.to_dict())
