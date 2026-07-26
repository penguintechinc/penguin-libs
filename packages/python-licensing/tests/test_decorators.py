"""Tests for license validation decorators — real license gating."""

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest

import penguin_licensing.client as client_module
from penguin_licensing.client import LicenseClient
from penguin_licensing.decorators import (
    FeatureNotAvailableError,
    LicenseRequiredError,
    feature_required,
    license_required,
)


@pytest.fixture(autouse=True)
def reset_shared_client():
    """Clear the process-wide license client between tests.

    The decorators resolve the shared client so cached validations survive a
    license server outage; without this reset one test's client would leak into
    the next.
    """
    client_module._license_client = None
    yield
    client_module._license_client = None


def _license_payload(tier="enterprise", features=None):
    """Build a well-formed /api/v2/validate 200 payload for the given tier."""
    return {
        "valid": True,
        "customer": "Test Co",
        "product": "elder",
        "license_version": "2.0",
        "license_key": "PENG-TEST-1234",
        "expires_at": "2030-01-01T00:00:00Z",
        "issued_at": "2024-01-01T00:00:00Z",
        "tier": tier,
        "features": (
            features
            if features is not None
            else [{"name": "sso", "entitled": True, "units": -1, "description": "", "metadata": {}}]
        ),
        "limits": {},
        "metadata": {},
    }


def _ok_response(tier="enterprise", features=None):
    """Build a mock 200 response carrying a valid license payload."""
    response = MagicMock()
    response.status_code = 200
    response.json.return_value = _license_payload(tier, features)
    return response


def _status_response(status_code):
    """Build a mock response carrying only a status code."""
    response = MagicMock()
    response.status_code = status_code
    return response


class TestLicenseRequiredDecorator:
    """Tests for license_required decorator — real license gating."""

    @patch("penguin_licensing.client.LicenseClient")
    def test_license_required_entitled_sync(self, mock_client_class):
        """Sync function allowed when license tier meets requirement."""
        mock_client = MagicMock()
        mock_client_class.return_value = mock_client
        mock_validation = MagicMock()
        mock_validation.valid = True
        mock_validation.tier = "enterprise"
        mock_client.validate.return_value = mock_validation

        @license_required("enterprise")
        def sync_func(x):
            return x * 2

        result = sync_func(5)
        assert result == 10

    @patch("penguin_licensing.client.LicenseClient")
    def test_license_required_denied_sync(self, mock_client_class):
        """Sync function denied when license tier insufficient."""
        mock_client = MagicMock()
        mock_client_class.return_value = mock_client
        mock_validation = MagicMock()
        mock_validation.valid = True
        mock_validation.tier = "professional"
        mock_client.validate.return_value = mock_validation

        @license_required("enterprise")
        def sync_func(x):
            return x * 2

        with pytest.raises(LicenseRequiredError):
            sync_func(5)

    @patch("penguin_licensing.client.LicenseClient")
    @pytest.mark.asyncio
    async def test_license_required_entitled_async(self, mock_client_class):
        """Async function allowed when license tier meets requirement."""
        mock_client = MagicMock()
        mock_client_class.return_value = mock_client
        mock_validation = MagicMock()
        mock_validation.valid = True
        mock_validation.tier = "enterprise"
        mock_client.validate.return_value = mock_validation

        @license_required("enterprise")
        async def async_func(x):
            return x * 2

        result = await async_func(5)
        assert result == 10

    @patch("penguin_licensing.client.LicenseClient")
    @pytest.mark.asyncio
    async def test_license_required_denied_async(self, mock_client_class):
        """Async function denied when license tier insufficient."""
        mock_client = MagicMock()
        mock_client_class.return_value = mock_client
        mock_validation = MagicMock()
        mock_validation.valid = True
        mock_validation.tier = "community"
        mock_client.validate.return_value = mock_validation

        @license_required("enterprise")
        async def async_func(x):
            return x * 2

        with pytest.raises(LicenseRequiredError):
            await async_func(5)

    def test_license_required_preserves_name(self):
        """license_required preserves function name."""

        @license_required()
        def my_function():
            pass

        assert my_function.__name__ == "my_function"


class TestFeatureRequiredDecorator:
    """Tests for feature_required decorator — real feature gating."""

    @patch("penguin_licensing.client.LicenseClient")
    def test_feature_required_entitled_sync(self, mock_client_class):
        """Sync function allowed when feature is entitled."""
        mock_client = MagicMock()
        mock_client_class.return_value = mock_client
        mock_client.check_feature.return_value = True

        @feature_required("sso")
        def sync_func(x):
            return x * 3

        result = sync_func(4)
        assert result == 12

    @patch("penguin_licensing.client.LicenseClient")
    def test_feature_required_denied_sync(self, mock_client_class):
        """Sync function denied when feature not entitled."""
        mock_client = MagicMock()
        mock_client_class.return_value = mock_client
        mock_client.check_feature.return_value = False

        @feature_required("sso")
        def sync_func(x):
            return x * 3

        with pytest.raises(FeatureNotAvailableError):
            sync_func(4)

    @patch("penguin_licensing.client.LicenseClient")
    @pytest.mark.asyncio
    async def test_feature_required_entitled_async(self, mock_client_class):
        """Async function allowed when feature is entitled."""
        mock_client = MagicMock()
        mock_client_class.return_value = mock_client
        mock_client.check_feature.return_value = True

        @feature_required("sso")
        async def async_func(x):
            return x * 3

        result = await async_func(4)
        assert result == 12

    @patch("penguin_licensing.client.LicenseClient")
    @pytest.mark.asyncio
    async def test_feature_required_denied_async(self, mock_client_class):
        """Async function denied when feature not entitled."""
        mock_client = MagicMock()
        mock_client_class.return_value = mock_client
        mock_client.check_feature.return_value = False

        @feature_required("sso")
        async def async_func(x):
            return x * 3

        with pytest.raises(FeatureNotAvailableError):
            await async_func(4)

    def test_feature_required_preserves_name(self):
        """feature_required preserves function name."""

        @feature_required("sso")
        def my_feature_function():
            pass

        assert my_feature_function.__name__ == "my_feature_function"


class TestDecoratorRevokedLicense:
    """Decorator behaviour when the license is revoked or reported invalid."""

    @patch("penguin_licensing.client.LicenseClient")
    def test_license_required_denied_when_validation_invalid(self, mock_client_class):
        """valid=False denies even when the reported tier would be sufficient."""
        mock_client = MagicMock()
        mock_client_class.return_value = mock_client
        mock_validation = MagicMock()
        mock_validation.valid = False
        mock_validation.tier = "enterprise"
        mock_client.validate.return_value = mock_validation

        @license_required("enterprise")
        def sync_func():
            return "ran"

        with pytest.raises(LicenseRequiredError):
            sync_func()

    @patch("penguin_licensing.client.requests.Session.post")
    def test_license_required_denied_on_server_revocation(self, mock_post):
        """A 401 from the license server drops the caller to community tier."""
        mock_post.return_value = _status_response(401)
        client_module._license_client = LicenseClient(license_key="PENG-TEST-1234", product="elder")

        @license_required("enterprise")
        def sync_func():
            return "ran"

        with pytest.raises(LicenseRequiredError) as excinfo:
            sync_func()

        assert mock_post.call_count == 1
        assert excinfo.value.current_tier == "community"

    @patch("penguin_licensing.client.requests.Session.post")
    def test_feature_required_denied_on_server_revocation(self, mock_post):
        """A revoked license entitles no features."""
        mock_post.return_value = _status_response(403)
        client_module._license_client = LicenseClient(license_key="PENG-TEST-1234", product="elder")

        @feature_required("sso")
        def sync_func():
            return "ran"

        with pytest.raises(FeatureNotAvailableError) as excinfo:
            sync_func()

        assert mock_post.call_count == 1
        assert excinfo.value.feature == "sso"

    @patch("penguin_licensing.client.requests.Session.post")
    def test_revocation_invalidates_previously_cached_entitlement(self, mock_post):
        """A revocation drops the cache instead of serving the stale tier."""
        mock_post.side_effect = [_ok_response("enterprise"), _status_response(403)]
        shared = LicenseClient(license_key="PENG-TEST-1234", product="elder")
        client_module._license_client = shared

        @license_required("enterprise")
        def sync_func():
            return "ran"

        assert sync_func() == "ran"

        # Expire the cache so the next call re-contacts the (now rejecting) server.
        shared._cache_expiry = datetime.now(timezone.utc) - timedelta(seconds=1)

        with pytest.raises(LicenseRequiredError):
            sync_func()

        assert mock_post.call_count == 2
        assert shared._cached_validation is None


class TestDecoratorHonorsCacheDuringOutage:
    """Decorator behaviour when the license server is down."""

    @patch("penguin_licensing.client.requests.Session.post")
    def test_warm_cache_survives_server_outage(self, mock_post):
        """A 5xx after a successful validation keeps the cached decision."""
        mock_post.side_effect = [_ok_response("enterprise"), _status_response(503)]
        shared = LicenseClient(license_key="PENG-TEST-1234", product="elder")
        client_module._license_client = shared

        @license_required("enterprise")
        def sync_func():
            return "ran"

        # Warm the cache against a healthy server.
        assert sync_func() == "ran"
        assert mock_post.call_count == 1

        # Expire the cache TTL so the outage is genuinely exercised.
        shared._cache_expiry = datetime.now(timezone.utc) - timedelta(seconds=1)

        assert sync_func() == "ran"
        assert mock_post.call_count == 2
        assert shared._cached_validation is not None
        assert shared._cached_validation.tier == "enterprise"

    @patch("penguin_licensing.client.requests.Session.post")
    def test_feature_decorator_honors_cache_during_outage(self, mock_post):
        """Feature entitlement survives an outage once it has been cached."""
        mock_post.side_effect = [_ok_response("enterprise"), _status_response(503)]
        shared = LicenseClient(license_key="PENG-TEST-1234", product="elder")
        client_module._license_client = shared

        @feature_required("sso")
        def sync_func():
            return "ran"

        assert sync_func() == "ran"
        shared._cache_expiry = datetime.now(timezone.utc) - timedelta(seconds=1)

        assert sync_func() == "ran"
        assert mock_post.call_count == 2

    @patch("penguin_licensing.client.requests.Session.post")
    def test_cold_cache_outage_denies(self, mock_post):
        """Control: without a warm cache the same outage denies access."""
        mock_post.return_value = _status_response(503)
        client_module._license_client = LicenseClient(license_key="PENG-TEST-1234", product="elder")

        @license_required("enterprise")
        def sync_func():
            return "ran"

        with pytest.raises(LicenseRequiredError) as excinfo:
            sync_func()

        assert excinfo.value.current_tier == "community"


class TestExceptionIdentity:
    """The package export must be the class the decorators actually raise."""

    def test_exception_classes_are_shared_across_modules(self):
        """decorators, python_client and the package export the same classes."""
        import penguin_licensing
        import penguin_licensing.decorators as decorators_module
        import penguin_licensing.exceptions as exceptions_module
        import penguin_licensing.python_client as python_client_module

        assert (
            penguin_licensing.FeatureNotAvailableError
            is decorators_module.FeatureNotAvailableError
            is python_client_module.FeatureNotAvailableError
            is exceptions_module.FeatureNotAvailableError
        )
        assert (
            penguin_licensing.LicenseRequiredError
            is decorators_module.LicenseRequiredError
            is exceptions_module.LicenseRequiredError
        )
        assert (
            penguin_licensing.LicenseValidationError
            is python_client_module.LicenseValidationError
            is exceptions_module.LicenseValidationError
        )

    @patch("penguin_licensing.client.LicenseClient")
    def test_package_export_catches_decorator_feature_error(self, mock_client_class):
        """Catching the package-exported class catches the decorator's raise."""
        from penguin_licensing import FeatureNotAvailableError as ExportedError

        mock_client = MagicMock()
        mock_client_class.return_value = mock_client
        mock_client.check_feature.return_value = False

        @feature_required("sso")
        def sync_func():
            return "ran"

        with pytest.raises(ExportedError) as excinfo:
            sync_func()

        assert excinfo.value.feature == "sso"

    @patch("penguin_licensing.client.LicenseClient")
    def test_package_export_catches_decorator_tier_error(self, mock_client_class):
        """Catching the package-exported tier class catches the decorator's raise."""
        from penguin_licensing import LicenseRequiredError as ExportedError

        mock_client = MagicMock()
        mock_client_class.return_value = mock_client
        mock_validation = MagicMock()
        mock_validation.valid = True
        mock_validation.tier = "community"
        mock_client.validate.return_value = mock_validation

        @license_required("enterprise")
        def sync_func():
            return "ran"

        with pytest.raises(ExportedError) as excinfo:
            sync_func()

        assert excinfo.value.required_tier == "enterprise"
        assert excinfo.value.current_tier == "community"
