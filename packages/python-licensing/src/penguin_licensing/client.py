"""PenguinTech License Server client for Elder."""

# flake8: noqa: E501


import os
import threading
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Sequence, cast

import requests
import structlog

from .domains import is_bypass_domain
from .urls import require_https_url

logger = structlog.get_logger()


@dataclass(slots=True)
class Feature:
    """License feature with entitlement details."""

    name: str
    entitled: bool
    units: int  # 0 = unlimited, -1 = not applicable
    description: str
    metadata: Dict[str, Any]


@dataclass(slots=True)
class LicenseInfo:
    """License information from server."""

    valid: bool
    customer: str
    product: str
    license_version: str
    license_key: str
    expires_at: datetime
    issued_at: datetime
    tier: str  # community, professional, enterprise
    features: List[Feature]
    limits: Dict[str, Any]
    metadata: Dict[str, Any]
    server_id: Optional[str] = None
    message: Optional[str] = None


class LicenseClient:
    """
    Client for PenguinTech License Server integration.

    Provides license validation, feature checking, and keepalive reporting.
    Caches validation results in memory for performance.
    """

    def __init__(
        self,
        license_key: Optional[str] = None,
        product: str = "elder",
        base_url: Optional[str] = None,
        deployment_host: Optional[str] = None,
        extra_bypass_domains: Optional[Sequence[str]] = None,
    ):
        """
        Initialize license client.

        Args:
            license_key: PenguinTech license key (PENG-XXXX-...)
            product: Product identifier
            base_url: License server base URL (default: LICENSE_SERVER_URL env var,
                falling back to https://license.penguintech.io if unset)
            deployment_host: This deployment's public hostname (e.g. the ingress
                host the app is served on), used to decide domain-based license
                bypass. See ``set_deployment_host`` for services that only learn
                the host after construction. Never sourced from a client-supplied
                header -- callers must pass the app's own configured hostname.
            extra_bypass_domains: Product-specific domains (e.g. a product's own
                ``.app`` domain) to treat as managed alongside the built-in
                PenguinCloud/beta-cluster domains.
        """
        # os.getenv's overload resolves to `str` on its own (default is a str
        # literal), but mypy loses that when the call is inlined directly into
        # an `or` expression -- binding it to an explicitly-typed local first
        # keeps self.license_key correctly typed as `str`, not `str | None`.
        env_license_key: str = os.getenv("LICENSE_KEY", "")
        self.license_key: str = license_key or env_license_key
        self.product = product
        self.deployment_host = deployment_host
        self._extra_bypass_domains: tuple[str, ...] = tuple(extra_bypass_domains or ())
        # Explicit arg wins; otherwise honor LICENSE_SERVER_URL; otherwise the
        # hardcoded default. A truthy parameter default here would make the env
        # var dead code (base_url would never be falsy), so the default lives
        # in this fallback chain instead of the parameter signature.
        self.base_url = (
            base_url or os.getenv("LICENSE_SERVER_URL") or "https://license.penguintech.io"
        )

        # Enforce TLS for license server (https required, except loopback)
        self.base_url = require_https_url(self.base_url)

        self.server_id: Optional[str] = None

        # Cache validation results (5 minute TTL)
        self._cached_validation: Optional[LicenseInfo] = None
        self._cache_expiry: Optional[datetime] = None

        # Session for connection pooling
        self.session = requests.Session()
        self.session.headers.update(
            {
                "Content-Type": "application/json",
                "User-Agent": f"Elder/{os.getenv('APP_VERSION', '0.1.0')}",
            }
        )

        if self.license_key:
            self.session.headers["Authorization"] = f"Bearer {self.license_key}"

    def set_deployment_host(self, host: Optional[str]) -> None:
        """
        Update the deployment's public hostname used for domain-based bypass.

        Call this once the app's own hostname becomes known, for services that
        must construct the client before that value is available (e.g. before
        config/ingress settings load).
        """
        self.deployment_host = host

    def _bypass_active(self) -> bool:
        """Return True when this deployment's host is a managed bypass domain."""
        if not self.deployment_host:
            return False
        active = is_bypass_domain(self.deployment_host, self._extra_bypass_domains)
        if active:
            logger.debug("license_check_domain_bypass", host=self.deployment_host)
        return active

    def _bypass_license_info(self) -> LicenseInfo:
        """Fully-entitled enterprise LicenseInfo used while domain bypass is active."""
        now = datetime.now(timezone.utc)
        return LicenseInfo(
            valid=True,
            customer="PenguinTech Managed Deployment",
            product=self.product,
            license_version="2.0",
            license_key=self.license_key,
            expires_at=datetime.max.replace(tzinfo=timezone.utc),
            issued_at=now,
            tier="enterprise",
            features=[],
            limits={},
            metadata={"bypass": "domain"},
            message=f"License checks bypassed for managed domain {self.deployment_host}",
        )

    def validate(self, force_refresh: bool = False) -> LicenseInfo:
        """
        Validate license and get server ID for keepalives.

        Fail-closed policy:
        - 401/403/404: definitive rejection, drop cache, return community tier
        - 5xx/transport errors: return last cached value if available
        - Expiry: enforce with 72h offline grace period if payload includes expires_at

        Domain bypass short-circuits all of the above: a deployment on a
        managed PenguinTech domain never hits the license server at all.

        Args:
            force_refresh: Force refresh from server (ignore cache)

        Returns:
            LicenseInfo with validation results
        """
        if self._bypass_active():
            return self._bypass_license_info()

        # Check cache first
        if not force_refresh and self._cached_validation and self._cache_expiry:
            if datetime.now(timezone.utc) < self._cache_expiry:
                logger.debug("license_validation_cache_hit")
                return self._cached_validation

        # No license key = community tier with basic features
        if not self.license_key:
            logger.warning("no_license_key_configured", tier="community")
            return self._get_community_tier_info()

        try:
            response = self.session.post(
                f"{self.base_url}/api/v2/validate",
                json={"product": self.product},
                timeout=10,
            )

            # Definitive rejection: drop cache and return community tier
            if response.status_code in (401, 403, 404):
                logger.warning(
                    "license_server_rejected",
                    status_code=response.status_code,
                )
                self._cached_validation = None
                self._cache_expiry = None
                return LicenseInfo(
                    valid=False,
                    customer="",
                    product=self.product,
                    license_version="2.0",
                    license_key=self.license_key,
                    expires_at=datetime.now(timezone.utc),
                    issued_at=datetime.now(timezone.utc),
                    tier="community",
                    features=[],
                    limits={},
                    metadata={},
                    message=f"License revoked or invalid (HTTP {response.status_code})",
                )

            if response.status_code == 200:
                data = response.json()

                # Parse features
                features = [
                    Feature(
                        name=f["name"],
                        entitled=f["entitled"],
                        units=f.get("units", -1),
                        description=f.get("description", ""),
                        metadata=f.get("metadata", {}),
                    )
                    for f in data.get("features", [])
                ]

                # Parse timestamps
                expires_at = datetime.fromisoformat(data["expires_at"].replace("Z", "+00:00"))
                issued_at = datetime.fromisoformat(data["issued_at"].replace("Z", "+00:00"))

                license_info = LicenseInfo(
                    valid=True,
                    customer=data["customer"],
                    product=data["product"],
                    license_version=data["license_version"],
                    license_key=data["license_key"],
                    expires_at=expires_at,
                    issued_at=issued_at,
                    tier=data["tier"],
                    features=features,
                    limits=data.get("limits", {}),
                    metadata=data.get("metadata", {}),
                    server_id=data.get("metadata", {}).get("server_id"),
                )

                # Enforce expiry with 72h grace period
                now = datetime.now(timezone.utc)
                grace_period = timedelta(hours=72)
                if license_info.expires_at < now:
                    if license_info.expires_at + grace_period < now:
                        logger.error(
                            "license_expired_beyond_grace",
                            expires_at=license_info.expires_at.isoformat(),
                        )
                        return LicenseInfo(
                            valid=False,
                            customer="",
                            product=self.product,
                            license_version="2.0",
                            license_key=self.license_key,
                            expires_at=datetime.now(timezone.utc),
                            issued_at=datetime.now(timezone.utc),
                            tier="community",
                            features=[],
                            limits={},
                            metadata={},
                            message="License expired beyond grace period",
                        )
                    else:
                        logger.warning(
                            "license_expired_within_grace",
                            expires_at=license_info.expires_at.isoformat(),
                        )

                # Store server ID for keepalives
                if license_info.server_id:
                    self.server_id = license_info.server_id

                # Cache validation result
                self._cached_validation = license_info
                self._cache_expiry = datetime.now(timezone.utc) + timedelta(minutes=5)

                logger.info(
                    "license_validation_success",
                    customer=license_info.customer,
                    tier=license_info.tier,
                    expires_at=license_info.expires_at.isoformat(),
                )

                return license_info

            else:
                # 5xx or other error: return cached value if available
                logger.error(
                    "license_validation_server_error",
                    status_code=response.status_code,
                )
                if self._cached_validation:
                    logger.warning("license_validation_using_cached_value")
                    return self._cached_validation
                # No cache available: return community tier
                return self._get_community_tier_info(
                    message=f"License server error (HTTP {response.status_code}), using community tier"
                )

        except Exception as e:
            logger.error("license_validation_exception", error=str(e), exc_info=True)
            # Transient errors: return cached value if available
            if self._cached_validation:
                logger.warning("license_validation_using_cached_value_on_error")
                return self._cached_validation
            # No cache: fall back to community tier
            return self._get_community_tier_info(message=f"Validation error: {str(e)}")

    def check_feature(self, feature_name: str) -> bool:
        """
        Check if specific feature is enabled.

        Args:
            feature_name: Feature identifier to check

        Returns:
            True if feature is entitled, False otherwise
        """
        if self._bypass_active():
            return True

        validation = self.validate()

        if not validation.valid:
            return False

        for feature in validation.features:
            if feature.name == feature_name and feature.entitled:
                return True

        return False

    def check_tier(self, required_tier: str) -> bool:
        """
        Check if license meets minimum tier requirement.

        Tier hierarchy: community < professional < enterprise

        Args:
            required_tier: Minimum tier required (community, professional, enterprise)

        Returns:
            True if license tier meets or exceeds requirement
        """
        if self._bypass_active():
            return True

        tier_levels = {"community": 1, "professional": 2, "enterprise": 3}

        validation = self.validate()
        current_level = tier_levels.get(validation.tier, 0)
        required_level = tier_levels.get(required_tier, 99)

        return current_level >= required_level

    def keepalive(self, usage_data: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """
        Send keepalive with optional usage statistics.

        Args:
            usage_data: Optional usage statistics to report

        Returns:
            Keepalive response data
        """
        if not self.license_key:
            logger.debug("keepalive_skipped_no_license")
            return {"success": False, "message": "No license key configured"}

        # Ensure we have server_id
        if not self.server_id:
            validation = self.validate(force_refresh=True)
            if not validation.valid or not validation.server_id:
                return {"success": False, "message": "No server ID available"}

        payload: Dict[str, Any] = {
            "product": self.product,
            "server_id": self.server_id,
        }

        if usage_data:
            payload.update(usage_data)

        try:
            response = self.session.post(
                f"{self.base_url}/api/v2/keepalive",
                json=payload,
                timeout=10,
            )

            if response.status_code == 200:
                logger.info("keepalive_success", server_id=self.server_id)
                return cast(Dict[str, Any], response.json())
            else:
                logger.error(
                    "keepalive_failed",
                    status_code=response.status_code,
                    response=response.text,
                )
                return {
                    "success": False,
                    "message": f"Keepalive failed: {response.status_code}",
                }

        except Exception as e:
            logger.error("keepalive_exception", error=str(e))
            return {"success": False, "message": f"Keepalive error: {str(e)}"}

    def _get_community_tier_info(self, message: Optional[str] = None) -> LicenseInfo:
        """Get default community tier license info."""
        return LicenseInfo(
            valid=True,  # Community tier is always valid
            customer="Community User",
            product=self.product,
            license_version="2.0",
            license_key="",
            expires_at=datetime.max.replace(tzinfo=timezone.utc),
            issued_at=datetime.now(timezone.utc),
            tier="community",
            features=[
                Feature(
                    name="basic_features",
                    entitled=True,
                    units=-1,
                    description="Basic Elder features",
                    metadata={},
                ),
            ],
            limits={"max_entities": 100},
            metadata={},
            message=message or "Community tier (no license key)",
        )


# Global license client instance, guarded for threaded WSGI/ASGI servers where
# concurrent first requests would otherwise each construct their own client.
_license_client: Optional[LicenseClient] = None
_license_client_lock = threading.Lock()


def get_license_client() -> LicenseClient:
    """
    Get global license client instance.

    Initialization is double-checked under a lock: the warm-cache-survives-outage
    guarantee only holds if every caller shares one client, and an unguarded
    check-then-act would let concurrent first requests build rival instances,
    each with its own empty validation cache and connection pool.

    Returns:
        Shared LicenseClient instance
    """
    global _license_client

    # Fast path: already initialized, no lock needed.
    client = _license_client
    if client is not None:
        return client

    with _license_client_lock:
        # Re-check: another thread may have initialized while we waited.
        if _license_client is None:
            _license_client = LicenseClient()
        return _license_client


def init_license_client(app: Any) -> LicenseClient:
    """
    Initialize license client from Flask app config.

    Args:
        app: Flask application instance

    Returns:
        Configured LicenseClient
    """
    global _license_client

    license_key = app.config.get("LICENSE_KEY") or os.getenv("LICENSE_KEY")
    base_url = app.config.get("LICENSE_SERVER_URL") or os.getenv(
        "LICENSE_SERVER_URL", "https://license.penguintech.io"
    )

    _license_client = LicenseClient(
        license_key=license_key,
        product="elder",
        base_url=base_url,
    )

    # Validate on startup
    validation = _license_client.validate()

    logger.info(
        "license_client_initialized",
        tier=validation.tier,
        valid=validation.valid,
        customer=validation.customer,
    )

    return _license_client
