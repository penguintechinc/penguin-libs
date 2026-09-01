"""Integration regression tests for the OIDCAuthMiddleware -> TenantMiddleware
claims hand-off (gh security review: aaa-jwt-verification).

OIDCAuthMiddleware populates ``scope["state"]["claims"]`` from
``OIDCRelyingParty.verify_token()``, which returns a pydantic ``Claims``
instance (see ``authn/oidc_rp.py``), not a dict. Downstream consumers —
``TenantMiddleware`` and ``AuditMiddleware`` — call ``.get()`` on that value,
which raises ``AttributeError`` on a real ``Claims`` instance since pydantic
BaseModel has no ``.get()`` method. Every prior test only exercised these
middlewares with hand-built mock dicts, which is why this shipped: it masked
the incompatibility between what the RP actually returns and what downstream
middleware actually consumes.

These tests build a real ``Claims`` instance (as ``OIDCRelyingParty.verify_token``
does) and run it through the full middleware chain to prove no AttributeError
is raised and the tenant/claims data survives the hand-off correctly.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from penguin_aaa.authn.types import Claims
from penguin_aaa.middleware.asgi import AuditMiddleware, OIDCAuthMiddleware
from penguin_aaa.middleware.tenant import TenantMiddleware


def _make_real_claims(tenant: str = "acme-corp") -> Claims:
    """Build a real pydantic Claims instance, exactly as OIDCRelyingParty
    .validate_token() constructs one via Claims.model_validate(payload)."""
    now = datetime.now(UTC)
    return Claims.model_validate(
        {
            "sub": "user-42",
            "iss": "https://auth.example.com",
            "aud": ["client-123"],
            "iat": now,
            "exp": now + timedelta(hours=1),
            "scope": ["openid", "profile"],
            "roles": ["admin"],
            "tenant": tenant,
            "teams": ["eng"],
        }
    )


def _http_scope(path: str = "/api") -> dict[str, Any]:
    return {"type": "http", "method": "GET", "path": path, "headers": [], "state": {}}


def _make_send() -> tuple[list[dict], Any]:
    messages: list[dict] = []

    async def send(msg: dict) -> None:
        messages.append(msg)

    return messages, send


class TestOIDCAuthMiddlewareToTenantMiddlewareIntegration:
    @pytest.mark.asyncio
    async def test_real_claims_instance_does_not_raise_in_tenant_middleware(self):
        """Regression: previously raised AttributeError('Claims' object has
        no attribute 'get') inside TenantMiddleware when a real RP-verified
        token flowed through — this only ever passed in tests because tests
        used plain dicts, not the real Claims model the RP returns."""
        recorded_tenant: dict[str, Any] = {}

        async def _downstream_app(scope, receive, send):
            recorded_tenant["tenant"] = scope["state"].get("tenant")
            await send({"type": "http.response.start", "status": 200, "headers": []})
            await send({"type": "http.response.body", "body": b"ok"})

        rp = MagicMock()
        rp.verify_token = AsyncMock(return_value=_make_real_claims(tenant="acme-corp"))

        chain = OIDCAuthMiddleware(TenantMiddleware(_downstream_app, required=True), rp=rp)
        scope = _http_scope()
        scope["headers"] = [(b"authorization", b"Bearer valid-token")]
        messages, send = _make_send()

        await chain(scope, AsyncMock(), send)

        assert messages[0]["status"] == 200
        assert recorded_tenant["tenant"] == "acme-corp"

    @pytest.mark.asyncio
    async def test_real_claims_instance_missing_tenant_still_type_errors_cleanly(self):
        """Claims always requires a non-empty tenant (see authn/types.py), so
        this exercises TenantMiddleware's required=True 403 path with a
        model-derived (not dict-derived) claims value."""

        async def _downstream_app(scope, receive, send):
            await send({"type": "http.response.start", "status": 200, "headers": []})
            await send({"type": "http.response.body", "body": b"ok"})

        rp = MagicMock()
        rp.verify_token = AsyncMock(return_value=_make_real_claims(tenant="other-tenant"))

        chain = OIDCAuthMiddleware(TenantMiddleware(_downstream_app, required=True), rp=rp)
        scope = _http_scope()
        scope["headers"] = [(b"authorization", b"Bearer valid-token")]
        messages, send = _make_send()

        await chain(scope, AsyncMock(), send)

        # Tenant present on the real Claims model -> passes through, not 403.
        assert messages[0]["status"] == 200

    @pytest.mark.asyncio
    async def test_scope_state_claims_is_dict_like_after_normalization(self):
        """The normalized claims stored in scope state must support .get()
        the same way a plain dict does, for TenantMiddleware/AuditMiddleware/
        authz decorators."""

        async def _downstream_app(scope, receive, send):
            await send({"type": "http.response.start", "status": 200, "headers": []})
            await send({"type": "http.response.body", "body": b"ok"})

        rp = MagicMock()
        rp.verify_token = AsyncMock(return_value=_make_real_claims(tenant="acme-corp"))

        middleware = OIDCAuthMiddleware(_downstream_app, rp=rp)
        scope = _http_scope()
        scope["headers"] = [(b"authorization", b"Bearer valid-token")]
        messages, send = _make_send()

        await middleware(scope, AsyncMock(), send)

        claims = scope["state"]["claims"]
        assert hasattr(claims, "get")
        assert claims.get("tenant") == "acme-corp"
        assert claims.get("sub") == "user-42"


class TestOIDCAuthMiddlewareToAuditMiddlewareIntegration:
    @pytest.mark.asyncio
    async def test_real_claims_instance_does_not_raise_in_audit_middleware(self):
        """Regression: AuditMiddleware also calls claims.get("sub", ...),
        same AttributeError risk as TenantMiddleware."""
        from penguin_aaa.audit.emitter import Emitter

        async def _downstream_app(scope, receive, send):
            await send({"type": "http.response.start", "status": 200, "headers": []})
            await send({"type": "http.response.body", "body": b"ok"})

        rp = MagicMock()
        rp.verify_token = AsyncMock(return_value=_make_real_claims(tenant="acme-corp"))

        emitted: list[dict] = []
        emitter = Emitter(MagicMock(emit=emitted.append))

        chain = OIDCAuthMiddleware(AuditMiddleware(_downstream_app, emitter=emitter), rp=rp)
        scope = _http_scope()
        scope["headers"] = [(b"authorization", b"Bearer valid-token")]
        messages, send = _make_send()

        await chain(scope, AsyncMock(), send)

        assert messages[0]["status"] == 200
        assert len(emitted) == 1
        assert emitted[0]["subject"] == "user-42"
