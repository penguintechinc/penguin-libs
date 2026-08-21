"""License validation decorators for Elder enterprise features."""

import inspect
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
    "feature_required",
    "license_required",
]

# Managed deployment domains — license enforcement is bypassed because these
# deployments are billed separately. Bypass is domain-driven only; there is
# deliberately no environment variable or config flag that can disable gating.
_BYPASS_DOMAINS = (
    ".penguincloud.io",
    ".penguintech.cloud",
    ".localhost.local",
)

# Set once a process has already logged the "no web framework" warning, so a
# hot decorator path doesn't spam the logs on every call — the condition is a
# static deployment fact, not something that changes call to call.
_logged_no_web_framework = False


def _is_bypass_domain(host: str) -> bool:
    """
    Return True when host is a managed PenguinTech domain that skips license checks.

    Matches on a dot boundary only, so ``evilpenguincloud.io`` never matches
    ``.penguincloud.io``; the bare apex (``penguincloud.io``) does match.
    """
    h = host.split(":")[0].lower()
    return any(h == d.lstrip(".") or h.endswith(d) for d in _BYPASS_DOMAINS)


def _quart_request_host() -> tuple[str | None, bool]:
    """
    Read ``request.host`` from Quart's active request context, if any.

    Returns ``(host, installed)``. ``installed`` is False only when Quart
    itself cannot be imported — a ``RuntimeError`` (no active request
    context) still reports ``installed=True`` with ``host=None``, since a
    present-but-inactive framework is not the same failure as it never being
    there at all.
    """
    try:
        from quart import request  # noqa: PLC0415
    except ImportError:
        return None, False
    try:
        return request.host, True
    except RuntimeError:
        return None, True


def _flask_request_host() -> tuple[str | None, bool]:
    """
    Read ``request.host`` from Flask's active request context, if any.

    Same ``(host, installed)`` contract as ``_quart_request_host`` — kept for
    legacy Flask callers per ``backend-python.md`` (Flask is deprecated but
    still supported for existing services).
    """
    try:
        from flask import request  # noqa: PLC0415
    except ImportError:
        return None, False
    try:
        return request.host, True
    except RuntimeError:
        return None, True


def _bypass_active() -> bool:
    """
    Return True when the in-flight request targets a managed bypass domain.

    Reads the host from whichever web framework's request context is
    actually active. Quart — the mandated PenguinTech framework — is tried
    first; Flask is a fallback for legacy callers. Two distinct situations
    both resolve to "no bypass", but only one of them is a request-shaped
    decision:

    - No active request context (Quart's or Flask's): there is genuinely no
      host to trust, so this fails closed by design — the normal license
      check runs.
    - Neither Quart nor Flask is importable: bypass can never activate no
      matter the host, which is a deployment/dependency gap, not a bypass
      decision. That gap is logged once at WARNING so a domain that should
      be license-free doesn't silently stay gated.
    """
    global _logged_no_web_framework

    host, installed = _quart_request_host()
    if not host:
        flask_host, flask_installed = _flask_request_host()
        host = flask_host
        installed = installed or flask_installed

    if not installed:
        if not _logged_no_web_framework:
            logger.warning(
                "license_bypass_no_web_framework",
                detail="neither quart nor flask is importable; domain-based "
                "license bypass can never activate until one is installed",
            )
            _logged_no_web_framework = True
        return False

    if not host or not _is_bypass_domain(host):
        return False
    logger.debug("license_check_domain_bypass", host=host)
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
