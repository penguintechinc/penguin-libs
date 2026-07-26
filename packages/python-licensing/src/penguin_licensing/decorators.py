"""License validation decorators for Elder enterprise features."""

# flake8: noqa: E501


import inspect
from functools import wraps
from typing import Any, Callable, TypeVar

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


def license_required(required_tier: str = "enterprise") -> Callable[[F], F]:
    """
    Decorator to enforce license tier requirements for enterprise features.

    Checks if the current license meets the minimum tier requirement.
    Tier hierarchy: community < professional < enterprise

    Uses the shared license client, so a validation cached before a license
    server outage keeps gating decisions stable while the server is down.

    Args:
        required_tier: Minimum license tier required (default: enterprise)

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
    Decorator to enforce specific feature entitlement.

    Checks if the license includes entitlement for a specific feature.

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
