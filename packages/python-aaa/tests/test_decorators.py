"""Tests for penguin_aaa.authz.decorators — async permission decorators."""

from types import SimpleNamespace

import pytest

from penguin_aaa.authz.decorators import require_any_scope, require_role, require_scope


def _make_request(claims: dict) -> SimpleNamespace:
    """Build a minimal request-like object with state.claims populated."""
    state = SimpleNamespace(claims=claims)
    return SimpleNamespace(state=state)


# ---------------------------------------------------------------------------
# require_scope
# ---------------------------------------------------------------------------


class TestRequireScope:
    @pytest.mark.asyncio
    async def test_allows_when_scope_present_in_list(self):
        req = _make_request({"scopes": ["reports:read", "users:read"]})

        @require_scope("reports:read")
        async def handler(request):
            return "ok"

        result = await handler(req)
        assert result == "ok"

    @pytest.mark.asyncio
    async def test_allows_when_scope_present_as_space_string(self):
        req = _make_request({"scope": "openid reports:read users:write"})

        @require_scope("reports:read")
        async def handler(request):
            return "ok"

        result = await handler(req)
        assert result == "ok"

    @pytest.mark.asyncio
    async def test_raises_when_scope_absent(self):
        req = _make_request({"scopes": ["users:read"]})

        @require_scope("reports:write")
        async def handler(request):
            return "ok"

        with pytest.raises(PermissionError, match="reports:write"):
            await handler(req)

    @pytest.mark.asyncio
    async def test_raises_when_claims_empty(self):
        req = _make_request({})

        @require_scope("reports:read")
        async def handler(request):
            return "ok"

        with pytest.raises(PermissionError):
            await handler(req)

    @pytest.mark.asyncio
    async def test_preserves_function_metadata(self):
        @require_scope("reports:read")
        async def my_handler(request):
            """Docstring."""
            return "ok"

        assert my_handler.__name__ == "my_handler"
        assert my_handler.__doc__ == "Docstring."


# ---------------------------------------------------------------------------
# require_role
# ---------------------------------------------------------------------------


class TestRequireRole:
    @pytest.mark.asyncio
    async def test_allows_when_role_present_as_list(self):
        req = _make_request({"roles": ["admin", "viewer"]})

        @require_role("admin")
        async def handler(request):
            return "ok"

        result = await handler(req)
        assert result == "ok"

    @pytest.mark.asyncio
    async def test_allows_when_role_present_as_scalar_string(self):
        req = _make_request({"role": "admin"})

        @require_role("admin")
        async def handler(request):
            return "ok"

        result = await handler(req)
        assert result == "ok"

    @pytest.mark.asyncio
    async def test_raises_when_role_absent(self):
        req = _make_request({"roles": ["viewer"]})

        @require_role("admin")
        async def handler(request):
            return "ok"

        with pytest.raises(PermissionError, match="admin"):
            await handler(req)

    @pytest.mark.asyncio
    async def test_raises_when_claims_empty(self):
        req = _make_request({})

        @require_role("admin")
        async def handler(request):
            return "ok"

        with pytest.raises(PermissionError):
            await handler(req)


# ---------------------------------------------------------------------------
# require_any_scope
# ---------------------------------------------------------------------------


class TestRequireAnyScope:
    @pytest.mark.asyncio
    async def test_allows_when_first_scope_matches(self):
        req = _make_request({"scopes": ["reports:read"]})

        @require_any_scope("reports:read", "reports:write")
        async def handler(request):
            return "ok"

        result = await handler(req)
        assert result == "ok"

    @pytest.mark.asyncio
    async def test_allows_when_second_scope_matches(self):
        req = _make_request({"scopes": ["reports:write"]})

        @require_any_scope("reports:read", "reports:write")
        async def handler(request):
            return "ok"

        result = await handler(req)
        assert result == "ok"

    @pytest.mark.asyncio
    async def test_raises_when_no_scope_matches(self):
        req = _make_request({"scopes": ["users:read"]})

        @require_any_scope("reports:read", "reports:write")
        async def handler(request):
            return "ok"

        with pytest.raises(PermissionError):
            await handler(req)

    @pytest.mark.asyncio
    async def test_raises_when_claims_empty(self):
        req = _make_request({})

        @require_any_scope("reports:read")
        async def handler(request):
            return "ok"

        with pytest.raises(PermissionError):
            await handler(req)

    @pytest.mark.asyncio
    async def test_kwargs_passed_through(self):
        req = _make_request({"scopes": ["admin:*"]})

        @require_any_scope("admin:*", "reports:read")
        async def handler(request, extra=None):
            return extra

        result = await handler(req, extra="passed")
        assert result == "passed"
