"""Tests for penguin_aaa.authz.rbac — Role and RBACEnforcer."""

import pytest

from penguin_aaa.authz.rbac import RBACEnforcer, Role, validate_scopes


class TestValidateScopes:
    def test_valid_simple_scope(self):
        validate_scopes(["reports:read"])

    def test_valid_wildcard_action(self):
        validate_scopes(["reports:*"])

    def test_valid_multiple_scopes(self):
        validate_scopes(["reports:read", "users:write", "admin:delete"])

    def test_empty_list_is_valid(self):
        validate_scopes([])

    def test_invalid_scope_missing_colon_raises(self):
        with pytest.raises(ValueError, match="Invalid scope format"):
            validate_scopes(["reports"])

    def test_invalid_scope_spaces_raises(self):
        with pytest.raises(ValueError, match="Invalid scope format"):
            validate_scopes(["reports: read"])

    def test_invalid_scope_empty_string_raises(self):
        with pytest.raises(ValueError, match="Invalid scope format"):
            validate_scopes([""])

    def test_invalid_scope_only_colon_raises(self):
        with pytest.raises(ValueError, match="Invalid scope format"):
            validate_scopes([":"])


class TestRole:
    def test_role_created_with_valid_scopes(self):
        role = Role(name="viewer", scopes=["reports:read", "users:read"])
        assert role.name == "viewer"
        assert role.scopes == ["reports:read", "users:read"]

    def test_role_with_empty_scopes(self):
        role = Role(name="guest", scopes=[])
        assert role.scopes == []

    def test_role_rejects_invalid_scope(self):
        with pytest.raises(ValueError):
            Role(name="bad", scopes=["invalid-scope-no-colon"])

    def test_role_uses_slots(self):
        role = Role(name="admin", scopes=["admin:*"])
        assert not hasattr(role, "__dict__")


class TestRBACEnforcer:
    def _enforcer_with_roles(self) -> RBACEnforcer:
        enforcer = RBACEnforcer()
        enforcer.register(Role(name="viewer", scopes=["reports:read", "users:read"]))
        enforcer.register(Role(name="editor", scopes=["reports:read", "reports:write"]))
        enforcer.register(Role(name="admin", scopes=["reports:read", "reports:write", "users:*"]))
        return enforcer

    def test_register_and_scopes_for_role(self):
        enforcer = self._enforcer_with_roles()
        scopes = enforcer.scopes_for_role("viewer")
        assert "reports:read" in scopes
        assert "users:read" in scopes

    def test_duplicate_registration_raises(self):
        enforcer = RBACEnforcer()
        enforcer.register(Role(name="viewer", scopes=["reports:read"]))
        with pytest.raises(ValueError, match="already registered"):
            enforcer.register(Role(name="viewer", scopes=["users:read"]))

    def test_scopes_for_unknown_role_raises(self):
        enforcer = self._enforcer_with_roles()
        with pytest.raises(KeyError):
            enforcer.scopes_for_role("unknown")

    def test_has_scope_true(self):
        enforcer = self._enforcer_with_roles()
        assert enforcer.has_scope("viewer", "reports:read") is True

    def test_has_scope_false(self):
        enforcer = self._enforcer_with_roles()
        assert enforcer.has_scope("viewer", "reports:write") is False

    def test_has_scope_unknown_role_returns_false(self):
        enforcer = self._enforcer_with_roles()
        assert enforcer.has_scope("ghost", "reports:read") is False

    def test_has_any_scope_match(self):
        enforcer = self._enforcer_with_roles()
        assert enforcer.has_any_scope("viewer", ["reports:write", "reports:read"]) is True

    def test_has_any_scope_no_match(self):
        enforcer = self._enforcer_with_roles()
        assert enforcer.has_any_scope("viewer", ["reports:write", "users:write"]) is False

    def test_has_any_scope_unknown_role_returns_false(self):
        enforcer = self._enforcer_with_roles()
        assert enforcer.has_any_scope("ghost", ["reports:read"]) is False

    def test_has_all_scopes_all_present(self):
        enforcer = self._enforcer_with_roles()
        assert enforcer.has_all_scopes("editor", ["reports:read", "reports:write"]) is True

    def test_has_all_scopes_partial_match_returns_false(self):
        enforcer = self._enforcer_with_roles()
        assert enforcer.has_all_scopes("viewer", ["reports:read", "reports:write"]) is False

    def test_has_all_scopes_empty_list_returns_true(self):
        enforcer = self._enforcer_with_roles()
        assert enforcer.has_all_scopes("viewer", []) is True

    def test_has_all_scopes_unknown_role_returns_false(self):
        enforcer = self._enforcer_with_roles()
        assert enforcer.has_all_scopes("ghost", []) is False

    def test_scopes_for_role_returns_copy(self):
        enforcer = self._enforcer_with_roles()
        scopes = enforcer.scopes_for_role("viewer")
        scopes.append("injected:scope")
        assert "injected:scope" not in enforcer.scopes_for_role("viewer")
