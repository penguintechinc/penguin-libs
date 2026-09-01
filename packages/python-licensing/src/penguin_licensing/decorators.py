"""License validation decorators for Elder enterprise features."""

import inspect
import os
from collections.abc import Callable
from functools import wraps
from typing import Any, TypeVar

import structlog

from .exceptions import FeatureNotAvailableError, LicenseRequiredError

logger = structlog.get_logger()

F = TypeVar("F", bound=Callable[..., Any])

# Re-exported for backwards compatibility; canonical definitions live in
# penguin_licensing.exceptions so every layer raises the same classes.
__all__ = [
    "FeatureNotAvailableError",
    "LicenseRequiredError",
    "configure_deployment_domain",
    "feature_required",
    "license_required",
]

# Managed deployment domains — license enforcement is bypassed because these
# deployments are billed separately. Bypass is domain-driven only; there is
# deliberately no environment variable or config flag that disables gating
# wholesale. `.localhost.local` is a 4th, alpha-only addition beyond the
# canonical 3 (see `penguintech.md` Domains & TLDs) — kept for local/alpha
# deployments, never a production bypass surface.
_BYPASS_DOMAINS = (
    ".penguincloud.io",
    ".penguintech.cloud",
    ".localhost.local",  # alpha-only
)

# Deployer-set env var fallback for the deployment domain below. Read at
# call time (not import time) so tests and process managers can set it
# before the first request without needing a module reload.
_DEPLOYMENT_DOMAIN_ENV_VAR = "PENGUIN_LICENSE_DEPLOYMENT_DOMAIN"

# The domain this process serves, set exactly once by the deployer via
# `configure_deployment_domain()` — NEVER derived from an in-flight
# request. This (or the env var above) is the sole authoritative signal
# `_bypass_active` trusts; see its docstring for the full precedence and
# why `request.host` was removed as a decision input on its own.
_deployment_domain_override: str | None = None


def configure_deployment_domain(domain: str | None) -> None:
    """
    Set the domain this deployment serves, for license bypass matching.

    Call this once at process startup with the service's own canonical
    serving domain (e.g. ``"widgets.penguintech.cloud"``). It is compared
    against the hardcoded suffix list in ``_BYPASS_DOMAINS`` — setting it
    does not itself enable or disable license enforcement, it only tells
    this library which domain identity the current deployment holds; the
    bypass still only fires when that domain matches a managed suffix.

    Set this from a value your service controls (build-time config,
    deployment manifest, secrets), **never** from a request header, query
    param, or any other client-supplied input — mirroring an
    attacker-controlled ``Host`` header back into this function is exactly
    the vulnerability this API exists to close. If never called, the
    ``PENGUIN_LICENSE_DEPLOYMENT_DOMAIN`` environment variable (also
    deployer-set, never request-derived) is used as a fallback.
    """
    global _deployment_domain_override
    _deployment_domain_override = domain


def _configured_deployment_domain() -> str | None:
    """
    Resolve the server-configured deployment domain.

    An explicit ``configure_deployment_domain()`` call wins; otherwise the
    ``PENGUIN_LICENSE_DEPLOYMENT_DOMAIN`` env var is used. Returns ``None``
    when neither is set, in which case the domain bypass can never
    activate — this is the fail-closed default.
    """
    if _deployment_domain_override is not None:
        return _deployment_domain_override
    return os.environ.get(_DEPLOYMENT_DOMAIN_ENV_VAR) or None


def _is_bypass_domain(host: str) -> bool:
    """
    Return True when host is a managed PenguinTech domain that skips license checks.

    Matches on a dot boundary only, so ``evilpenguincloud.io`` never matches
    ``.penguincloud.io``; the bare apex (``penguincloud.io``) does match.
    """
    h = host.split(":")[0].lower()
    return any(h == d.lstrip(".") or h.endswith(d) for d in _BYPASS_DOMAINS)


def _quart_request_host() -> str | None:
    """Best-effort read of ``request.host`` from Quart's active request context."""
    try:
        from quart import request  # noqa: PLC0415
    except ImportError:
        return None
    try:
        return request.host
    except RuntimeError:
        return None


def _flask_request_host() -> str | None:
    """
    Best-effort read of ``request.host`` from Flask's active request context.

    Kept for legacy Flask callers per ``backend-python.md`` (Flask is
    deprecated but still supported for existing services).
    """
    try:
        from flask import request  # noqa: PLC0415
    except ImportError:
        return None
    try:
        return request.host
    except RuntimeError:
        return None


def _request_host() -> str | None:
    """
    Best-effort read of the in-flight request's Host header, if any.

    Tries Quart first (the mandated PenguinTech framework), then Flask.
    Used ONLY as a defense-in-depth narrowing check inside
    ``_bypass_active`` — never as a bypass decision on its own. A missing
    framework, an inactive request context, or no header at all all
    resolve to ``None``, which the caller treats as "nothing to narrow
    against" rather than an error.
    """
    return _quart_request_host() or _flask_request_host()


def _bypass_active() -> bool:
    """
    Return True when this deployment is configured to skip license checks.

    Precedence, most to least authoritative:

    1. **Configured deployment domain** — the server-side identity set via
       ``configure_deployment_domain()`` or the
       ``PENGUIN_LICENSE_DEPLOYMENT_DOMAIN`` env var (see
       ``_configured_deployment_domain``). This is the sole authoritative
       gate: a deployer, not a client, sets it, so it cannot be spoofed the
       way ``request.host`` can. If it is unset, or set to a domain outside
       ``_BYPASS_DOMAINS``, the bypass never activates — full stop,
       regardless of any request in flight or its ``Host`` header.
    2. **In-flight request Host, defense-in-depth only** — when a request
       context IS active, its ``Host`` header must independently fall
       inside ``_BYPASS_DOMAINS`` too, or the bypass is refused even though
       the configured domain matched. This can only *narrow* the bypass,
       never grant one: it exists solely to catch a bypass-domain
       deployment that is (mis)routed unrelated tenant traffic.
       ``request.host`` is NEVER sufficient by itself — see the regression
       this replaces below.

    A prior version derived the bypass entirely from ``request.host``,
    which Flask/Quart do not verify by default: any request carrying a
    spoofed ``Host: x.penguintech.cloud`` header unlocked every licensed
    feature on a self-hosted customer deployment, unauthenticated. That
    path is gone; only server-side config can grant the bypass now.
    """
    domain = _configured_deployment_domain()
    if not domain or not _is_bypass_domain(domain):
        return False

    host = _request_host()
    if host is not None and not _is_bypass_domain(host):
        logger.warning(
            "license_bypass_host_mismatch",
            deployment_domain=domain,
            request_host=host,
        )
        return False

    logger.debug(
        "license_check_domain_bypass",
        deployment_domain=domain,
        request_host=host,
    )
    return True


def license_required(required_tier: str = "enterprise") -> Callable[[F], F]:
    """
    Enforce license tier requirements for enterprise features.

    Tier hierarchy: community < professional < enterprise

    Uses the shared license client, so a validation cached before a license
    server outage keeps gating decisions stable while the server is down.

    Args:
        required_tier: Minimum tier required (default: enterprise)

    Returns:
        Decorated function that checks license before execution

    Usage:
        @app.route('/api/v1/issues', methods=['POST'])
        @login_required
        @license_required('enterprise')
        def create_issue():
            # Only accessible with enterprise license
            pass

    Raises:
        LicenseRequiredError: When license tier does not meet requirement
    """

    def decorator(func: F) -> F:
        @wraps(func)
        async def async_wrapper(*args: Any, **kwargs: Any) -> Any:
            if _bypass_active():
                return await func(*args, **kwargs)

            from penguin_licensing.client import get_license_client

            client = get_license_client()
            validation = client.validate()

            tier_levels = {"community": 0, "professional": 1, "enterprise": 2}
            current_level = tier_levels.get(validation.tier, 0)
            required_level = tier_levels.get(required_tier, 99)

            if not validation.valid or current_level < required_level:
                logger.warning(
                    "license_tier_insufficient",
                    required_tier=required_tier,
                    current_tier=validation.tier,
                    endpoint=func.__name__,
                )
                raise LicenseRequiredError(required_tier, validation.tier)

            return await func(*args, **kwargs)

        @wraps(func)
        def sync_wrapper(*args: Any, **kwargs: Any) -> Any:
            if _bypass_active():
                return func(*args, **kwargs)

            from penguin_licensing.client import get_license_client

            client = get_license_client()
            validation = client.validate()

            tier_levels = {"community": 0, "professional": 1, "enterprise": 2}
            current_level = tier_levels.get(validation.tier, 0)
            required_level = tier_levels.get(required_tier, 99)

            if not validation.valid or current_level < required_level:
                logger.warning(
                    "license_tier_insufficient",
                    required_tier=required_tier,
                    current_tier=validation.tier,
                    endpoint=func.__name__,
                )
                raise LicenseRequiredError(required_tier, validation.tier)

            return func(*args, **kwargs)

        if inspect.iscoroutinefunction(func):
            return async_wrapper  # type: ignore[return-value]
        else:
            return sync_wrapper  # type: ignore[return-value]

    return decorator


def feature_required(feature_name: str) -> Callable[[F], F]:
    """
    Enforce specific feature entitlement.

    Args:
        feature_name: Feature identifier to check

    Returns:
        Decorated function that checks feature entitlement before execution

    Usage:
        @app.route('/api/v1/advanced-analytics', methods=['GET'])
        @login_required
        @feature_required('advanced_analytics')
        def get_advanced_analytics():
            # Only accessible if 'advanced_analytics' feature is entitled
            pass

    Raises:
        FeatureNotAvailableError: When feature is not entitled
    """

    def decorator(func: F) -> F:
        @wraps(func)
        async def async_wrapper(*args: Any, **kwargs: Any) -> Any:
            if _bypass_active():
                return await func(*args, **kwargs)

            from penguin_licensing.client import get_license_client

            client = get_license_client()
            if not client.check_feature(feature_name):
                logger.warning(
                    "feature_not_entitled",
                    feature=feature_name,
                    endpoint=func.__name__,
                )
                raise FeatureNotAvailableError(feature_name)

            return await func(*args, **kwargs)

        @wraps(func)
        def sync_wrapper(*args: Any, **kwargs: Any) -> Any:
            if _bypass_active():
                return func(*args, **kwargs)

            from penguin_licensing.client import get_license_client

            client = get_license_client()
            if not client.check_feature(feature_name):
                logger.warning(
                    "feature_not_entitled",
                    feature=feature_name,
                    endpoint=func.__name__,
                )
                raise FeatureNotAvailableError(feature_name)

            return func(*args, **kwargs)

        if inspect.iscoroutinefunction(func):
            return async_wrapper  # type: ignore[return-value]
        else:
            return sync_wrapper  # type: ignore[return-value]

    return decorator
