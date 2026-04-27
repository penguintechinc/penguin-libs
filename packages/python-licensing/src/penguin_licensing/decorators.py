"""License validation decorators for Elder enterprise features."""

import inspect
from functools import wraps
from typing import Any, Callable, TypeVar

import structlog

logger = structlog.get_logger()

F = TypeVar("F", bound=Callable[..., Any])

# Managed deployment domains — license enforcement bypassed (billed separately)
_BYPASS_DOMAINS = (
    ".penguincloud.io",
    ".penguintech.cloud",
    ".localhost.local",
)


def _is_bypass_domain(host: str) -> bool:
    """Return True if host is a managed PenguinTech domain that skips license checks."""
    h = host.split(":")[0].lower()
    return any(h == d.lstrip(".") or h.endswith(d) for d in _BYPASS_DOMAINS)


def _get_license_client() -> Any:
    """Retrieve LicenseClient from Flask app config, or create one from environment."""
    from flask import current_app  # noqa: PLC0415

    client = current_app.config.get("LICENSE_CLIENT")
    if client is not None:
        return client
    from penguin_licensing.client import LicenseClient  # noqa: PLC0415

    return LicenseClient()


def _in_flask_context() -> bool:
    """Return True when called inside an active Flask application context."""
    try:
        from flask import current_app  # noqa: PLC0415

        current_app._get_current_object()
        return True
    except RuntimeError:
        return False


def license_required(required_tier: str = "enterprise") -> Callable[[F], F]:
    """
    Enforce license tier requirements for enterprise features.

    Tier hierarchy: community < professional < enterprise

    Args:
        required_tier: Minimum tier required (default: enterprise)

    Returns 403 JSON when tier is insufficient:
        {"error": "License Required", "required_tier": "enterprise",
         "current_tier": "community", "upgrade_url": "https://penguintech.io/pricing"}
    """

    def decorator(func: F) -> F:
        @wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            if _in_flask_context():
                from flask import jsonify, request  # noqa: PLC0415

                host = request.host
                if not _is_bypass_domain(host):
                    client = _get_license_client()
                    if not client.check_tier(required_tier):
                        validation = client.validate()
                        logger.warning(
                            "license_check_failed",
                            required_tier=required_tier,
                            current_tier=validation.tier,
                            endpoint=func.__name__,
                        )
                        return (
                            jsonify(
                                {
                                    "error": "License Required",
                                    "message": f"This feature requires a {required_tier} license",
                                    "required_tier": required_tier,
                                    "current_tier": validation.tier,
                                    "upgrade_url": "https://penguintech.io/pricing",
                                }
                            ),
                            403,
                        )
                    logger.debug(
                        "license_check_passed",
                        required_tier=required_tier,
                        endpoint=func.__name__,
                    )
                else:
                    logger.debug(
                        "license_check_domain_bypass",
                        host=host,
                        endpoint=func.__name__,
                    )

            if inspect.iscoroutinefunction(func):
                return await func(*args, **kwargs)
            return func(*args, **kwargs)

        return wrapper  # type: ignore[return-value]

    return decorator  # type: ignore[return-value]


def feature_required(feature_name: str) -> Callable[[F], F]:
    """
    Enforce specific feature entitlement.

    Args:
        feature_name: Feature identifier to check

    Returns 403 JSON when feature is not entitled:
        {"error": "Feature Not Available", "feature": "sso",
         "upgrade_url": "https://penguintech.io/pricing"}
    """

    def decorator(func: F) -> F:
        @wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            if _in_flask_context():
                from flask import jsonify, request  # noqa: PLC0415

                host = request.host
                if not _is_bypass_domain(host):
                    client = _get_license_client()
                    if not client.check_feature(feature_name):
                        logger.warning(
                            "feature_check_failed",
                            feature=feature_name,
                            endpoint=func.__name__,
                        )
                        return (
                            jsonify(
                                {
                                    "error": "Feature Not Available",
                                    "message": "This feature is not included in your license",
                                    "feature": feature_name,
                                    "upgrade_url": "https://penguintech.io/pricing",
                                }
                            ),
                            403,
                        )
                    logger.debug(
                        "feature_check_passed",
                        feature=feature_name,
                        endpoint=func.__name__,
                    )
                else:
                    logger.debug(
                        "feature_check_domain_bypass",
                        host=host,
                        endpoint=func.__name__,
                    )

            if inspect.iscoroutinefunction(func):
                return await func(*args, **kwargs)
            return func(*args, **kwargs)

        return wrapper  # type: ignore[return-value]

    return decorator  # type: ignore[return-value]
