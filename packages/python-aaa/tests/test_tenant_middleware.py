"""Tests for penguin_aaa.middleware.tenant — tenant isolation middleware."""

import json

import pytest

from penguin_aaa.middleware.tenant import TenantMiddleware


async def _dummy_app(scope, receive, send):
    """Minimal ASGI app that records it was called."""
    scope.setdefault("_test", {})["called"] = True
    await send({"type": "http.response.start", "status": 200, "headers": []})
    await send({"type": "http.response.body", "body": b"ok"})


class TestTenantMiddleware:
    @pytest.mark.asyncio
    async def test_non_http_scope_passes_through(self):
        """Non-http/websocket scopes bypass tenant enforcement."""
        called = False

        async def lifespan_app(scope, receive, send):
            nonlocal called
            called = True

        app = TenantMiddleware(lifespan_app, required=True)
        scope = {"type": "lifespan", "state": {}}

        async def noop_send(msg):
            pass

        await app(scope, lambda: None, noop_send)
        assert called is True

    @pytest.mark.asyncio
    async def test_required_tenant_missing_returns_403(self):
        """When required=True and tenant claim is absent, returns 403."""
        app = TenantMiddleware(_dummy_app, required=True)
        scope = {"type": "http", "state": {"claims": {}}}
        sent = []

        async def send(msg):
            sent.append(msg)

        await app(scope, lambda: None, send)

        assert sent[0]["status"] == 403
        body = json.loads(sent[1]["body"])
        assert "Tenant claim missing" in body["error"]

    @pytest.mark.asyncio
    async def test_required_tenant_present_passes_through(self):
        """When required=True and tenant is present, passes to app."""
        app = TenantMiddleware(_dummy_app, required=True)
        scope = {
            "type": "http",
            "state": {"claims": {"tenant": "acme-corp"}},
        }
        sent = []

        async def send(msg):
            sent.append(msg)

        await app(scope, lambda: None, send)

        assert scope["state"]["tenant"] == "acme-corp"
        assert sent[0]["status"] == 200

    @pytest.mark.asyncio
    async def test_not_required_no_tenant_passes_through(self):
        """When required=False and tenant is absent, passes to app anyway."""
        app = TenantMiddleware(_dummy_app, required=False)
        scope = {"type": "http", "state": {"claims": {}}}
        sent = []

        async def send(msg):
            sent.append(msg)

        await app(scope, lambda: None, send)

        assert sent[0]["status"] == 200

    @pytest.mark.asyncio
    async def test_tenant_stored_in_scope_state(self):
        """Tenant is stored in scope['state']['tenant']."""
        app = TenantMiddleware(_dummy_app, required=False)
        scope = {
            "type": "http",
            "state": {"claims": {"tenant": "test-tenant"}},
        }
        sent = []

        async def send(msg):
            sent.append(msg)

        await app(scope, lambda: None, send)

        assert scope["state"]["tenant"] == "test-tenant"

    @pytest.mark.asyncio
    async def test_no_state_key_in_scope(self):
        """When scope has no 'state' key at all, required=True returns 403."""
        app = TenantMiddleware(_dummy_app, required=True)
        scope = {"type": "http"}
        sent = []

        async def send(msg):
            sent.append(msg)

        await app(scope, lambda: None, send)

        assert sent[0]["status"] == 403

    @pytest.mark.asyncio
    async def test_claims_is_none(self):
        """When claims is None, required=True returns 403."""
        app = TenantMiddleware(_dummy_app, required=True)
        scope = {"type": "http", "state": {"claims": None}}
        sent = []

        async def send(msg):
            sent.append(msg)

        await app(scope, lambda: None, send)

        assert sent[0]["status"] == 403

    @pytest.mark.asyncio
    async def test_websocket_scope_enforced(self):
        """Tenant enforcement applies to websocket scope type too."""
        app = TenantMiddleware(_dummy_app, required=True)
        scope = {
            "type": "websocket",
            "state": {"claims": {"tenant": "ws-tenant"}},
        }
        sent = []

        async def send(msg):
            sent.append(msg)

        await app(scope, lambda: None, send)

        assert scope["state"]["tenant"] == "ws-tenant"
