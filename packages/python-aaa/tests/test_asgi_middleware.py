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

    # ---------------------------------------------------------------
    # API-key verifier tests (backward compatibility + new feature)
    # ---------------------------------------------------------------

    async def _good_api_key_verifier(self, key: str) -> dict[str, Any]:
        """Async verifier that accepts 'good-key' and returns a sentinel."""
        if key != "good-key":
            raise ValueError("Invalid API key")
        return {"sub": "api-key-user", "via": "api_key"}

    async def _bad_api_key_verifier(self, key: str) -> dict[str, Any]:
        """Async verifier that rejects everything."""
        raise ValueError("Invalid API key")

    @pytest.mark.asyncio
    async def test_no_verifier_preserves_backward_compatible_behavior(self):
        """When api_key_verifier is None, behavior is byte-identical to before."""
        rp = self._rp()
        middleware = OIDCAuthMiddleware(_ok_app, rp)
        # Test 1: missing auth → 401 with original message
        scope = _http_scope()
        messages, send = _make_send()
        await middleware(scope, AsyncMock(), send)
        body = messages[1]["body"]
        parsed = json.loads(body)
        assert parsed["error"] == "Missing or invalid Bearer token"
        assert messages[0]["status"] == 401

        # Test 2: non-Bearer auth → 401 with original message
        messages, send = _make_send()
        scope = _http_scope(headers=[(b"authorization", b"Basic dXNlcjpwYXNz")])
        await middleware(scope, AsyncMock(), send)
        body = messages[1]["body"]
        parsed = json.loads(body)
        assert parsed["error"] == "Missing or invalid Bearer token"
        assert messages[0]["status"] == 401

        # Test 3: Bearer token verified → passes
        messages, send = _make_send()
        scope = _http_scope(headers=[(b"authorization", b"Bearer valid-token")])
        await middleware(scope, AsyncMock(), send)
        assert messages[0]["status"] == 200

    @pytest.mark.asyncio
    async def test_api_key_from_header_passes_through(self):
        """API key from x-api-key header bypasses Bearer requirement."""
        rp = self._rp()
        middleware = OIDCAuthMiddleware(_ok_app, rp, api_key_verifier=self._good_api_key_verifier)
        scope = _http_scope(headers=[(b"x-api-key", b"good-key")])
        messages, send = _make_send()
        await middleware(scope, AsyncMock(), send)
        assert messages[0]["status"] == 200
        assert scope["state"]["claims"] == {"sub": "api-key-user", "via": "api_key"}

    @pytest.mark.asyncio
    async def test_raw_auth_header_without_bearer_prefix(self):
        """Raw (non-Bearer) Authorization header is treated as API key."""
        rp = self._rp()
        middleware = OIDCAuthMiddleware(_ok_app, rp, api_key_verifier=self._good_api_key_verifier)
        scope = _http_scope(headers=[(b"authorization", b"good-key")])
        messages, send = _make_send()
        await middleware(scope, AsyncMock(), send)
        assert messages[0]["status"] == 200
        assert scope["state"]["claims"] == {"sub": "api-key-user", "via": "api_key"}

    @pytest.mark.asyncio
    async def test_bearer_jwt_fails_verifier_succeeds(self):
        """When Bearer JWT fails, fallback to verifier if set."""
        rp = self._rp(raises=True)
        middleware = OIDCAuthMiddleware(_ok_app, rp, api_key_verifier=self._good_api_key_verifier)
        # Authorization: Bearer good-key (not a JWT, so rp.verify_token raises)
        scope = _http_scope(headers=[(b"authorization", b"Bearer good-key")])
        messages, send = _make_send()
        await middleware(scope, AsyncMock(), send)
        assert messages[0]["status"] == 200
        assert scope["state"]["claims"] == {"sub": "api-key-user", "via": "api_key"}

    @pytest.mark.asyncio
    async def test_bad_api_key_returns_401(self):
        """Bad API key returns 401 with API-key-specific error message."""
        rp = self._rp()
        middleware = OIDCAuthMiddleware(_ok_app, rp, api_key_verifier=self._good_api_key_verifier)
        scope = _http_scope(headers=[(b"x-api-key", b"bad-key")])
        messages, send = _make_send()
        await middleware(scope, AsyncMock(), send)
        assert messages[0]["status"] == 401
        body = messages[1]["body"]
        parsed = json.loads(body)
        assert parsed["error"] == "API key verification failed"

    @pytest.mark.asyncio
    async def test_valid_bearer_jwt_skips_verifier(self):
        """Valid Bearer JWT is accepted without consulting verifier."""
        expected_claims = {"sub": "jwt-user", "scopes": ["read"]}
        rp = self._rp(claims=expected_claims)
        # verifier rejects everything, but should not be called
        middleware = OIDCAuthMiddleware(_ok_app, rp, api_key_verifier=self._bad_api_key_verifier)
        scope = _http_scope(headers=[(b"authorization", b"Bearer valid-jwt")])
        messages, send = _make_send()
        await middleware(scope, AsyncMock(), send)
        assert messages[0]["status"] == 200
        # Claims from JWT, not from verifier
        assert scope["state"]["claims"] == expected_claims

    @pytest.mark.asyncio
    async def test_custom_api_key_header(self):
        """api_key_header parameter customizes the header name."""
        rp = self._rp()
        middleware = OIDCAuthMiddleware(
            _ok_app,
            rp,
            api_key_verifier=self._good_api_key_verifier,
            api_key_header="authorization-key",
        )
        scope = _http_scope(headers=[(b"authorization-key", b"good-key")])
        messages, send = _make_send()
        await middleware(scope, AsyncMock(), send)
        assert messages[0]["status"] == 200
        assert scope["state"]["claims"] == {"sub": "api-key-user", "via": "api_key"}

    @pytest.mark.asyncio
    async def test_api_key_header_takes_precedence_over_raw_auth(self):
        """When both api_key_header and raw auth are present, header is tried first."""
        call_count = 0
        original_verifier = self._good_api_key_verifier

        async def tracking_verifier(key: str) -> dict[str, Any]:
            nonlocal call_count
            call_count += 1
            return await original_verifier(key)

        rp = self._rp()
        middleware = OIDCAuthMiddleware(_ok_app, rp, api_key_verifier=tracking_verifier)
        # Both api_key_header and raw auth present; api_key_header should be used
        scope = _http_scope(
            headers=[
                (b"x-api-key", b"good-key"),
                (b"authorization", b"bad-key"),
            ]
        )
        messages, send = _make_send()
        await middleware(scope, AsyncMock(), send)
        assert messages[0]["status"] == 200
        assert call_count == 1
        # Should have passed with good-key (from header)
        assert scope["state"]["claims"]["via"] == "api_key"


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
