"""Authorization subpackage — RBAC enforcement and permission decorators."""

from penguin_aaa.authz.decorators import require_any_scope, require_role, require_scope
from penguin_aaa.authz.rbac import RBACEnforcer, Role, validate_scopes

__all__ = [
    "Role",
    "RBACEnforcer",
    "validate_scopes",
    "require_scope",
    "require_role",
    "require_any_scope",
]
