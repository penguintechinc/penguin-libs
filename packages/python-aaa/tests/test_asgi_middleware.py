"""Tests for penguin_aaa.middleware.asgi — OIDC, SPIFFE, and Audit middleware."""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from penguin_aaa.audit.emitter import Emitter
from penguin_aaa.middleware.asgi import AuditMiddleware, OIDCAuthMiddleware, SPIFFEAuthMiddleware

# ---------------------------------------------------------------------------
# ASGI test helpers
# ---------------------------------------------------------------------------


async def _ok_app(scope, receive, send):
    """Minimal ASGI app that always returns 200 OK."""
    await send({"type": "http.response.start", "status": 200, "headers": []})
    await send({"type": "http.response.body", "body": b"ok"})


async def _forbidden_app(scope, receive, send):
    """Minimal ASGI app that returns 403."""
    await send({"type": "http.response.start", "status": 403, "headers": []})
    await send({"type": "http.response.body", "body": b"forbidden"})


def _http_scope(path: str = "/api", headers: list | None = None) -> dict[str, Any]:
    return {
        "type": "http",
        "method": "GET",
        "path": path,
        "headers": headers or [],
        "state": {},
    }


def _make_send() -> tuple[list[dict], Any]:
    """Return a (messages list, async send callable) pair."""
    messages: list[dict] = []

    async def send(msg: dict) -> None:
        messages.append(msg)

    return messages, send


# ---------------------------------------------------------------------------
# OIDCAuthMiddleware
# ---------------------------------------------------------------------------


class TestOIDCAuthMiddleware:
    def _rp(self, claims: dict | None = None, raises: bool = False) -> Any:
        rp = MagicMock()
        if raises:
            rp.verify_token = AsyncMock(side_effect=ValueError("bad token"))
        else:
            rp.verify_token = AsyncMock(return_value=claims or {"sub": "user-1"})
        return rp

    @pytest.mark.asyncio
    async def test_missing_authorization_header_returns_401(self):
        rp = self._rp()
        middleware = OIDCAuthMiddleware(_ok_app, rp)
        scope = _http_scope()
        messages, send = _make_send()
        await middleware(scope, AsyncMock(), send)
        assert messages[0]["status"] == 401

    @pytest.mark.asyncio
    async def test_non_bearer_scheme_returns_401(self):
        rp = self._rp()
        middleware = OIDCAuthMiddleware(_ok_app, rp)
        scope = _http_scope(headers=[(b"authorization", b"Basic dXNlcjpwYXNz")])
        messages, send = _make_send()
        await middleware(scope, AsyncMock(), send)
        assert messages[0]["status"] == 401

    @pytest.mark.asyncio
    async def test_invalid_token_returns_401(self):
        rp = self._rp(raises=True)
        middleware = OIDCAuthMiddleware(_ok_app, rp)
        scope = _http_scope(headers=[(b"authorization", b"Bearer bad-token")])
        messages, send = _make_send()
        await middleware(scope, AsyncMock(), send)
        assert messages[0]["status"] == 401

    @pytest.mark.asyncio
    async def test_valid_token_populates_claims_and_passes_through(self):
        expected_claims = {"sub": "user-42", "scopes": ["reports:read"]}
        rp = self._rp(claims=expected_claims)
        middleware = OIDCAuthMiddleware(_ok_app, rp)
        scope = _http_scope(headers=[(b"authorization", b"Bearer valid-token")])
        messages, send = _make_send()
        await middleware(scope, AsyncMock(), send)
        assert messages[0]["status"] == 200
        assert scope["state"]["claims"] == expected_claims

    @pytest.mark.asyncio
    async def test_public_path_bypasses_auth(self):
        rp = self._rp(raises=True)
        middleware = OIDCAuthMiddleware(_ok_app, rp, public_paths={"/health", "/metrics"})
        scope = _http_scope(path="/health")
        messages, send = _make_send()
        await middleware(scope, AsyncMock(), send)
        assert messages[0]["status"] == 200
        rp.verify_token.assert_not_called()

    @pytest.mark.asyncio
    async def test_non_http_scope_bypasses_auth(self):
        rp = self._rp()
        middleware = OIDCAuthMiddleware(_ok_app, rp)
        lifespan_scope: dict[str, Any] = {"type": "lifespan", "state": {}}
        messages, send = _make_send()
        await middleware(lifespan_scope, AsyncMock(), send)
        rp.verify_token.assert_not_called()

    @pytest.mark.asyncio
    async def test_401_response_body_is_json(self):
        rp = self._rp()
        middleware = OIDCAuthMiddleware(_ok_app, rp)
        scope = _http_scope()
        messages, send = _make_send()
        await middleware(scope, AsyncMock(), send)
        body = messages[1]["body"]
        parsed = json.loads(body)
        assert "error" in parsed


# ---------------------------------------------------------------------------
# SPIFFEAuthMiddleware
# ---------------------------------------------------------------------------


class TestSPIFFEAuthMiddleware:
    def _authenticator(self, raises: bool = False) -> Any:
        auth = MagicMock()
        if raises:
            auth.authenticate = MagicMock(side_effect=ValueError("rejected"))
        else:
            auth.authenticate = MagicMock(return_value=None)
        return auth

    def _spiffe_scope(self, spiffe_id: str | None = "spiffe://example.io/svc") -> dict[str, Any]:
        scope = _http_scope()
        if spiffe_id:
            scope["extensions"] = {"tls": {"peer_cert": {"spiffe_id": spiffe_id}}}
        return scope

    @pytest.mark.asyncio
    async def test_missing_spiffe_id_returns_401(self):
        auth = self._authenticator()
        middleware = SPIFFEAuthMiddleware(_ok_app, auth)
        scope = _http_scope()  # no extensions
        messages, send = _make_send()
        await middleware(scope, AsyncMock(), send)
        assert messages[0]["status"] == 401

    @pytest.mark.asyncio
    async def test_rejected_spiffe_id_returns_401(self):
        auth = self._authenticator(raises=True)
        middleware = SPIFFEAuthMiddleware(_ok_app, auth)
        scope = self._spiffe_scope()
        messages, send = _make_send()
        await middleware(scope, AsyncMock(), send)
        assert messages[0]["status"] == 401

    @pytest.mark.asyncio
    async def test_valid_spiffe_id_passes_through(self):
        auth = self._authenticator()
        middleware = SPIFFEAuthMiddleware(_ok_app, auth)
        scope = self._spiffe_scope("spiffe://example.io/trusted-svc")
        messages, send = _make_send()
        await middleware(scope, AsyncMock(), send)
        assert messages[0]["status"] == 200
        assert scope["state"]["spiffe_id"] == "spiffe://example.io/trusted-svc"

    @pytest.mark.asyncio
    async def test_non_http_scope_bypasses_auth(self):
        auth = self._authenticator()
        middleware = SPIFFEAuthMiddleware(_ok_app, auth)
        lifespan_scope: dict[str, Any] = {"type": "lifespan", "state": {}}
        messages, send = _make_send()
        await middleware(lifespan_scope, AsyncMock(), send)
        auth.authenticate.assert_not_called()


# ---------------------------------------------------------------------------
# AuditMiddleware
# ---------------------------------------------------------------------------


class _CaptureSink:
    """Test sink that collects emitted events."""

    def __init__(self) -> None:
        self.events: list[dict] = []

    def emit(self, event: dict) -> None:
        self.events.append(event)

    def flush(self) -> None:
        pass

    def close(self) -> None:
        pass


class TestAuditMiddleware:
    def _setup(self, app=_ok_app) -> tuple[AuditMiddleware, _CaptureSink]:
        sink = _CaptureSink()
        emitter = Emitter(sink)
        return AuditMiddleware(app, emitter), sink

    @pytest.mark.asyncio
    async def test_emits_success_event_on_200(self):
        middleware, sink = self._setup()
        scope = _http_scope()
        messages, send = _make_send()
        await middleware(scope, AsyncMock(), send)
        assert len(sink.events) == 1
        assert sink.events[0]["outcome"] == "success"
        assert sink.events[0]["type"] == "auth.success"

    @pytest.mark.asyncio
    async def test_emits_failure_event_on_4xx(self):
        middleware, sink = self._setup(app=_forbidden_app)
        scope = _http_scope()
        messages, send = _make_send()
        await middleware(scope, AsyncMock(), send)
        assert sink.events[0]["outcome"] == "failure"
        assert sink.events[0]["type"] == "auth.failure"

    @pytest.mark.asyncio
    async def test_includes_status_code_in_details(self):
        middleware, sink = self._setup()
        scope = _http_scope()
        messages, send = _make_send()
        await middleware(scope, AsyncMock(), send)
        assert sink.events[0]["details"]["status_code"] == 200

    @pytest.mark.asyncio
    async def test_extracts_subject_from_claims(self):
        middleware, sink = self._setup()
        scope = _http_scope()
        scope["state"]["claims"] = {"sub": "user-99"}
        messages, send = _make_send()
        await middleware(scope, AsyncMock(), send)
        assert sink.events[0]["subject"] == "user-99"

    @pytest.mark.asyncio
    async def test_uses_anonymous_subject_when_no_claims(self):
        middleware, sink = self._setup()
        scope = _http_scope()
        messages, send = _make_send()
        await middleware(scope, AsyncMock(), send)
        assert sink.events[0]["subject"] == "anonymous"

    @pytest.mark.asyncio
    async def test_includes_duration_ms_in_details(self):
        middleware, sink = self._setup()
        scope = _http_scope()
        messages, send = _make_send()
        await middleware(scope, AsyncMock(), send)
        assert "duration_ms" in sink.events[0]["details"]
        assert isinstance(sink.events[0]["details"]["duration_ms"], float)

    @pytest.mark.asyncio
    async def test_non_http_scope_does_not_emit(self):
        middleware, sink = self._setup()
        lifespan_scope: dict[str, Any] = {"type": "lifespan", "state": {}}
        messages, send = _make_send()
        await middleware(lifespan_scope, AsyncMock(), send)
        assert sink.events == []

    @pytest.mark.asyncio
    async def test_response_is_still_passed_to_client(self):
        middleware, sink = self._setup()
        scope = _http_scope()
        messages, send = _make_send()
        await middleware(scope, AsyncMock(), send)
        status_messages = [m for m in messages if m.get("type") == "http.response.start"]
        assert len(status_messages) == 1
        assert status_messages[0]["status"] == 200
