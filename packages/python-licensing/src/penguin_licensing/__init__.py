"""License server integration for Elder enterprise features."""

# flake8: noqa: E501

from .client import LicenseClient, get_license_client
from .decorators import configure_deployment_domain, feature_required, license_required
from .exceptions import (
    FeatureNotAvailableError,
    LicenseRequiredError,
    LicenseValidationError,
)

__all__ = [
    "FeatureNotAvailableError",
    "LicenseClient",
    "LicenseRequiredError",
    "LicenseValidationError",
    "configure_deployment_domain",
    "feature_required",
    "get_license_client",
    "license_required",
]
