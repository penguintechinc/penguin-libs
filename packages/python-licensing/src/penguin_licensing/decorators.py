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


def _is_bypass_domain(host: str) -> bool:
    """
    Return True when host is a managed PenguinTech domain that skips license checks.

    Matches on a dot boundary only, so ``evilpenguincloud.io`` never matches
    ``.penguincloud.io``; the bare apex (``penguincloud.io``) does match.
    """
    h = host.split(":")[0].lower()
    return any(h == d.lstrip(".") or h.endswith(d) for d in _BYPASS_DOMAINS)


def _bypass_active() -> bool:
    """
    Return True when the in-flight request targets a managed bypass domain.

    Reads the host from the active Flask request. Outside a Flask request
    context there is no host to trust, so this fails closed (no bypass) and
    the normal license check runs.
    """
    try:
        from flask import request  # noqa: PLC0415

        host = request.host
    except (ImportError, RuntimeError):
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
