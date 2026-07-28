"""Canonical exception types raised by every layer of penguin-licensing.

These live in a single module so that a caller catching the package-exported
class catches exactly what the clients and decorators raise; same-named classes
defined per-module previously made ``except`` clauses silently miss.
"""


class LicenseValidationError(Exception):
    """Raised when a license cannot be validated against the license server.

    Covers definitive rejection (revoked/unknown key) as well as transport
    failures with no cached validation to fall back on.
    """


class LicenseRequiredError(Exception):
    """Raised when the active license tier is below the tier a feature requires.

    Carries both tiers so callers can render an accurate upgrade prompt.
    """

    def __init__(self, required_tier: str, current_tier: str) -> None:
        self.required_tier = required_tier
        self.current_tier = current_tier
        super().__init__(
            f"This feature requires a {required_tier} license (current: {current_tier})"
        )


class FeatureNotAvailableError(Exception):
    """Raised when a named feature is not entitled under the active license.

    Carries the feature name so callers can report which entitlement is missing.
    """

    def __init__(self, feature: str) -> None:
        self.feature = feature
        super().__init__(f"Feature '{feature}' requires license upgrade")


__all__ = [
    "FeatureNotAvailableError",
    "LicenseRequiredError",
    "LicenseValidationError",
]
