"""Role-Based Access Control enforcement for PenguinTech services."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

_SCOPE_PATTERN = re.compile(r"^[a-zA-Z0-9_-]+:[a-zA-Z0-9_\-*]+$")


def validate_scopes(scopes: list[str]) -> None:
    """Validate that all scopes follow the 'resource:action' format.

    Args:
        scopes: List of scope strings to validate.

    Raises:
        ValueError: If any scope does not match the expected format.
    """
    for scope in scopes:
        if not _SCOPE_PATTERN.match(scope):
            raise ValueError(
                f"Invalid scope format '{scope}': must be 'resource:action' "
                "(alphanumeric, hyphens, underscores; action may include '*')"
            )


@dataclass(slots=True)
class Role:
    """A named role with an associated set of permission scopes.

    Args:
        name: Unique role identifier.
        scopes: List of permission scopes in 'resource:action' format.
    """

    name: str
    scopes: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        validate_scopes(self.scopes)


class RBACEnforcer:
    """Registry and enforcer for role-based access control.

    Roles are registered by name. Enforcement methods check whether a given
    role (or its resolved scopes) satisfies a permission requirement.
    """

    def __init__(self) -> None:
        self._roles: dict[str, Role] = {}

    def register(self, role: Role) -> None:
        """Register a role in the enforcer.

        Args:
            role: The role to register.

        Raises:
            ValueError: If a role with the same name is already registered.
        """
        if role.name in self._roles:
            raise ValueError(f"Role '{role.name}' is already registered")
        self._roles[role.name] = role

    def scopes_for_role(self, role_name: str) -> list[str]:
        """Return the scopes assigned to a role.

        Args:
            role_name: The role name to look up.

        Raises:
            KeyError: If the role is not registered.
        """
        if role_name not in self._roles:
            raise KeyError(f"Role '{role_name}' is not registered")
        return list(self._roles[role_name].scopes)

    def has_scope(self, role_name: str, scope: str) -> bool:
        """Check whether a role has a specific scope.

        Args:
            role_name: The role to check.
            scope: The scope to look for.

        Returns:
            True if the role has the scope, False otherwise (including unknown roles).
        """
        if role_name not in self._roles:
            return False
        return scope in self._roles[role_name].scopes

    def has_any_scope(self, role_name: str, scopes: list[str]) -> bool:
        """Check whether a role has at least one of the given scopes.

        Args:
            role_name: The role to check.
            scopes: The candidate scopes, any of which satisfies the check.

        Returns:
            True if the role has at least one matching scope.
        """
        if role_name not in self._roles:
            return False
        role_scopes = set(self._roles[role_name].scopes)
        return any(s in role_scopes for s in scopes)

    def has_all_scopes(self, role_name: str, scopes: list[str]) -> bool:
        """Check whether a role has all of the given scopes.

        Args:
            role_name: The role to check.
            scopes: All scopes that must be present.

        Returns:
            True if the role has every listed scope.
        """
        if role_name not in self._roles:
            return False
        role_scopes = set(self._roles[role_name].scopes)
        return all(s in role_scopes for s in scopes)
