"""Authorization decorators for async route handlers.

Decorators extract OIDC claims from `request.state.claims` and enforce
scope or role requirements, raising PermissionError on failure.
"""

from __future__ import annotations

import functools
from typing import Any, Callable, Coroutine


def _extract_request(args: tuple[Any, ...]) -> Any:
    """Extract the request object from positional arguments.

    Looks for the first argument that has a ``state`` attribute containing
    ``claims``. Falls back to the first positional argument.

    Args:
        args: Positional arguments passed to the decorated function.

    Returns:
        The request-like object.

    Raises:
        ValueError: If no suitable request object is found.
    """
    for arg in args:
        state = getattr(arg, "state", None)
        if state is not None and hasattr(state, "claims"):
            return arg
    if args:
        return args[0]
    raise ValueError("No request argument found; cannot extract claims")


def require_scope(
    scope: str,
) -> Callable[[Callable[..., Coroutine[Any, Any, Any]]], Callable[..., Coroutine[Any, Any, Any]]]:
    """Require that the authenticated principal has a specific scope.

    Extracts ``request.state.claims`` and checks for the named scope in the
    ``scopes`` claim (space-separated string or list).

    Args:
        scope: The scope that must be present, e.g. ``"reports:read"``.

    Returns:
        An async decorator that raises PermissionError when the scope is absent.
    """

    def decorator(
        fn: Callable[..., Coroutine[Any, Any, Any]],
    ) -> Callable[..., Coroutine[Any, Any, Any]]:
        @functools.wraps(fn)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            request = _extract_request(args)
            claims: dict[str, Any] = getattr(getattr(request, "state", None), "claims", {}) or {}
            raw_scopes = claims.get("scopes", claims.get("scope", ""))
            if isinstance(raw_scopes, str):
                granted = set(raw_scopes.split())
            else:
                granted = set(raw_scopes)
            if scope not in granted:
                raise PermissionError(f"Missing required scope: '{scope}'")
            return await fn(*args, **kwargs)

        return wrapper

    return decorator


def require_role(
    role: str,
) -> Callable[[Callable[..., Coroutine[Any, Any, Any]]], Callable[..., Coroutine[Any, Any, Any]]]:
    """Require that the authenticated principal has a specific role.

    Checks the ``role`` or ``roles`` claim. Informational — enforces role
    presence but does not resolve role-to-scope mappings.

    Args:
        role: The role name that must be present, e.g. ``"admin"``.

    Returns:
        An async decorator that raises PermissionError when the role is absent.
    """

    def decorator(
        fn: Callable[..., Coroutine[Any, Any, Any]],
    ) -> Callable[..., Coroutine[Any, Any, Any]]:
        @functools.wraps(fn)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            request = _extract_request(args)
            claims: dict[str, Any] = getattr(getattr(request, "state", None), "claims", {}) or {}
            raw_roles = claims.get("roles", claims.get("role", ""))
            if isinstance(raw_roles, str):
                granted = {raw_roles} if raw_roles else set()
            else:
                granted = set(raw_roles)
            if role not in granted:
                raise PermissionError(f"Missing required role: '{role}'")
            return await fn(*args, **kwargs)

        return wrapper

    return decorator


def require_any_scope(
    *scopes: str,
) -> Callable[[Callable[..., Coroutine[Any, Any, Any]]], Callable[..., Coroutine[Any, Any, Any]]]:
    """Require that the authenticated principal has at least one of the given scopes.

    Args:
        *scopes: One or more scope strings, any of which satisfies the check.

    Returns:
        An async decorator that raises PermissionError when none of the scopes
        are present.
    """

    def decorator(
        fn: Callable[..., Coroutine[Any, Any, Any]],
    ) -> Callable[..., Coroutine[Any, Any, Any]]:
        @functools.wraps(fn)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            request = _extract_request(args)
            claims: dict[str, Any] = getattr(getattr(request, "state", None), "claims", {}) or {}
            raw_scopes = claims.get("scopes", claims.get("scope", ""))
            if isinstance(raw_scopes, str):
                granted = set(raw_scopes.split())
            else:
                granted = set(raw_scopes)
            if not any(s in granted for s in scopes):
                needed = ", ".join(f"'{s}'" for s in scopes)
                raise PermissionError(f"Missing at least one required scope: {needed}")
            return await fn(*args, **kwargs)

        return wrapper

    return decorator
