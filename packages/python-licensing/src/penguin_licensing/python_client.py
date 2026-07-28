"""
PenguinTech License Server Python Client

This module provides a Python client for integrating with the PenguinTech License Server
to validate licenses and check feature entitlements.
"""

import logging
import os
import time
from datetime import datetime, timedelta, timezone
from functools import wraps
from typing import Any, Callable, Dict, List, Optional, cast

import requests

from .exceptions import FeatureNotAvailableError, LicenseValidationError
from .urls import require_https_url

logger = logging.getLogger(__name__)

# Re-exported for backwards compatibility; canonical definitions live in
# penguin_licensing.exceptions so every layer raises the same classes.
__all__ = [
    "FeatureNotAvailableError",
    "LicenseValidationError",
    "PenguinTechLicenseClient",
    "check_feature",
    "get_client",
    "initialize_licensing",
    "requires_feature",
    "send_keepalive",
]


class PenguinTechLicenseClient:
    """Client for PenguinTech License Server integration."""

    def __init__(
        self,
        license_key: str,
        product: str,
        base_url: Optional[str] = None,
        timeout: int = 30,
    ) -> None:
        """
        Initialize the license client.

        Args:
            license_key: The license key (format: PENG-XXXX-XXXX-XXXX-XXXX-ABCD)
            product: The product identifier
            base_url: License server URL (default: https://license.penguintech.io)
            timeout: Request timeout in seconds

        Raises:
            ValueError: If base_url is a non-loopback URL that does not use https
        """
        self.license_key = license_key
        self.product = product
        # Enforce TLS for license server (https required, except loopback)
        self.base_url = require_https_url(base_url or "https://license.penguintech.io")
        self.server_id = None
        self.timeout = timeout

        self.session = requests.Session()
        self.session.headers.update(
            {
                "Authorization": f"Bearer {license_key}",
                "Content-Type": "application/json",
            }
        )

        # Feature cache
        self._feature_cache: Dict[str, bool] = {}
        self._cache_timestamp: Optional[float] = None
        self._cache_ttl = 300  # 5 minutes

        # Validation cache (fail-closed)
        self._cached_validation: Optional[Dict[str, Any]] = None
        self._validation_cache_expiry: Optional[float] = None

    @classmethod
    def from_env(cls, timeout: int = 30) -> Optional["PenguinTechLicenseClient"]:
        """
        Create client from environment variables.

        Requires LICENSE_KEY and PRODUCT_NAME environment variables.
        Optional LICENSE_SERVER_URL for custom server.

        Args:
            timeout: Request timeout in seconds

        Returns:
            PenguinTechLicenseClient instance or None if env vars missing
        """
        license_key = os.getenv("LICENSE_KEY")
        product = os.getenv("PRODUCT_NAME")
        base_url = os.getenv("LICENSE_SERVER_URL")

        if not license_key or not product:
            logger.warning("LICENSE_KEY and PRODUCT_NAME environment variables required")
            return None

        return cls(license_key, product, base_url, timeout)

    def validate(self, force_refresh: bool = False) -> Dict[str, Any]:
        """
        Validate license and get server ID for keepalives.

        Fail-closed policy:
        - 401/403/404: definitive rejection, drop cache, raise (never serve the
          previously cached entitlement, so the caller degrades to no features)
        - 5xx/transport errors: return last cached value if available
        - Expiry: enforce with 72h grace period if payload includes expires_at

        Args:
            force_refresh: Skip the validation cache and re-contact the server

        Returns:
            Dict containing the validation response, or the last known-good
            cached response when the server is unreachable

        Raises:
            LicenseValidationError: If the license is definitively rejected, or
                the server is unreachable and there is no cached validation
        """
        now = time.time()
        # Check cache first
        if not force_refresh and self._cached_validation and self._validation_cache_expiry:
            if now < self._validation_cache_expiry:
                logger.debug("license_validation_cache_hit")
                return self._cached_validation

        try:
            response = self.session.post(
                f"{self.base_url}/api/v2/validate",
                json={"product": self.product},
                timeout=self.timeout,
            )

            # Definitive rejection: drop cache and raise
            if response.status_code in (401, 403, 404):
                logger.warning(f"License server rejected request (HTTP {response.status_code})")
                self._cached_validation = None
                self._validation_cache_expiry = None
                raise LicenseValidationError(
                    f"License revoked or invalid (HTTP {response.status_code})"
                )

            response.raise_for_status()

            data = response.json()

            if not data.get("valid"):
                raise LicenseValidationError(f"License validation failed: {data.get('message')}")

            # Enforce expiry with 72h grace period
            if "expires_at" in data:
                expires_at = datetime.fromisoformat(data["expires_at"].replace("Z", "+00:00"))
                now_dt = datetime.now(expires_at.tzinfo or timezone.utc)
                grace_period = timedelta(hours=72)
                if expires_at < now_dt:
                    if expires_at + grace_period < now_dt:
                        logger.error("License expired beyond grace period")
                        raise LicenseValidationError("License expired beyond grace period")
                    else:
                        logger.warning("License expired but within grace period")

            # Store server ID for keepalives
            if "metadata" in data and "server_id" in data["metadata"]:
                self.server_id = data["metadata"]["server_id"]

            # Update feature cache
            self._update_feature_cache(data.get("features", []))

            # Cache validation result
            self._cached_validation = data
            self._validation_cache_expiry = now + 300  # 5 minute TTL

            return cast(Dict[str, Any], data)

        except requests.RequestException as e:
            logger.error(f"License validation request failed: {e}")
            # Transient errors: return cached value if available
            if self._cached_validation:
                logger.warning("Using cached license validation on error")
                return self._cached_validation
            # No cache available: raise
            raise LicenseValidationError(f"License validation request failed: {e}") from e

    def check_feature(self, feature: str, use_cache: bool = True) -> bool:
        """
        Check if a specific feature is enabled.

        Args:
            feature: Feature name to check
            use_cache: Whether to use cached results

        Returns:
            True if feature is enabled, False otherwise
        """
        # Check cache first if enabled and valid
        if use_cache and self._is_cache_valid():
            cached_result = self._feature_cache.get(feature)
            if cached_result is not None:
                return cached_result

        try:
            response = self.session.post(
                f"{self.base_url}/api/v2/features",
                json={"product": self.product, "feature": feature},
                timeout=self.timeout,
            )
            response.raise_for_status()

            data = response.json()
            features = cast(List[Dict[str, Any]], data.get("features", []))

            if features:
                entitled = cast(bool, features[0].get("entitled", False))
                # Cache the result
                self._feature_cache[feature] = entitled
                self._cache_timestamp = time.time()
                return entitled

            return False

        except requests.RequestException as e:
            logger.error(f"Feature check failed for {feature}: {e}")
            return False

    def keepalive(self, usage_data: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """
        Send keepalive with optional usage statistics.

        Args:
            usage_data: Optional usage statistics to send

        Returns:
            Dict containing keepalive response

        Raises:
            LicenseValidationError: If keepalive fails
        """
        if not self.server_id:
            # Validate first to get server ID
            validation = self.validate()
            if not validation.get("valid"):
                raise LicenseValidationError("Failed to validate license for keepalive")

        payload = {"product": self.product, "server_id": self.server_id}

        if usage_data:
            payload.update(usage_data)

        try:
            response = self.session.post(
                f"{self.base_url}/api/v2/keepalive", json=payload, timeout=self.timeout
            )
            response.raise_for_status()

            return cast(Dict[str, Any], response.json())

        except requests.RequestException as e:
            raise LicenseValidationError(f"Keepalive request failed: {e}")

    def get_all_features(self) -> Dict[str, bool]:
        """
        Get all available features from cache or validation.

        Returns:
            Dict mapping feature names to enabled status
        """
        if not self._is_cache_valid():
            try:
                self.validate()
            except LicenseValidationError:
                logger.error("Failed to refresh feature cache")

        return self._feature_cache.copy()

    def _update_feature_cache(self, features: List[Dict[str, Any]]) -> None:
        """Update the feature cache with new feature data."""
        self._feature_cache = {}
        for feature in features:
            name = feature.get("name")
            entitled = cast(bool, feature.get("entitled", False))
            if name:
                self._feature_cache[name] = entitled

        self._cache_timestamp = time.time()

    def _is_cache_valid(self) -> bool:
        """Check if the feature cache is still valid."""
        if self._cache_timestamp is None:
            return False

        return (time.time() - self._cache_timestamp) < self._cache_ttl

    @staticmethod
    def is_valid_license_key(key: str) -> bool:
        """
        Validate license key format.

        Args:
            key: License key to validate

        Returns:
            True if format is valid
        """
        if not key or len(key) != 29:
            return False

        if not key.startswith("PENG-"):
            return False

        # Count dashes - should be 5 total
        return key.count("-") == 5


# Global client instance for convenience
_global_client: Optional[PenguinTechLicenseClient] = None


def get_client() -> Optional[PenguinTechLicenseClient]:
    """Get the global license client instance."""
    global _global_client
    if _global_client is None:
        _global_client = PenguinTechLicenseClient.from_env()
    return _global_client


def requires_feature(
    feature_name: str, client: Optional[PenguinTechLicenseClient] = None
) -> Callable[[Any], Any]:
    """
    Decorator to gate functionality behind license features.

    Args:
        feature_name: Name of the required feature
        client: License client instance (uses global if None)

    Raises:
        FeatureNotAvailableError: If feature is not available
    """

    def decorator(func: Any) -> Any:
        @wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            license_client = client or get_client()

            if not license_client:
                raise FeatureNotAvailableError(feature_name)

            if not license_client.check_feature(feature_name):
                raise FeatureNotAvailableError(feature_name)

            return func(*args, **kwargs)

        return wrapper

    return decorator


def initialize_licensing(
    license_key: Optional[str] = None, product: Optional[str] = None
) -> Dict[str, Any]:
    """
    Initialize licensing system and validate license.

    Args:
        license_key: License key (uses env var if None)
        product: Product name (uses env var if None)

    Returns:
        Validation response dict

    Raises:
        LicenseValidationError: If initialization fails
    """
    global _global_client

    # Use provided values or environment variables
    final_license_key = license_key or os.getenv("LICENSE_KEY")
    final_product = product or os.getenv("PRODUCT_NAME")

    if not final_license_key or not final_product:
        raise LicenseValidationError("LICENSE_KEY and PRODUCT_NAME are required")

    _global_client = PenguinTechLicenseClient(final_license_key, final_product)
    validation = _global_client.validate()

    logger.info(f"License valid for {validation['customer']} ({validation['tier']} tier)")

    # Log available features
    for feature in validation.get("features", []):
        if feature.get("entitled"):
            logger.info(f"Feature enabled: {feature['name']}")

    return validation


# Convenience functions for common operations
def check_feature(feature: str) -> bool:
    """Check if a feature is available using the global client."""
    client = get_client()
    if not client:
        return False
    return client.check_feature(feature)


def send_keepalive(usage_data: Optional[Dict[str, Any]] = None) -> bool:
    """Send keepalive using the global client."""
    client = get_client()
    if not client:
        return False

    try:
        client.keepalive(usage_data)
        return True
    except LicenseValidationError:
        logger.error("Failed to send keepalive")
        return False
