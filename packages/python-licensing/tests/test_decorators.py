"""Tests for license validation decorators — real license gating."""

from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock, patch

import pytest
from flask import Flask
from quart import Quart

import penguin_licensing.client as client_module
import penguin_licensing.decorators as decorators_module
from penguin_licensing.client import LicenseClient
from penguin_licensing.decorators import (
    FeatureNotAvailableError,
    LicenseRequiredError,
    _is_bypass_domain,
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


@pytest.fixture(autouse=True)
def reset_no_web_framework_warning_flag():
    """Clear the one-time "no web framework" warning latch between tests."""
    decorators_module._logged_no_web_framework = False
    yield
    decorators_module._logged_no_web_framework = False


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
        shared._cache_expiry = datetime.now(UTC) - timedelta(seconds=1)

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
        shared._cache_expiry = datetime.now(UTC) - timedelta(seconds=1)

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
        shared._cache_expiry = datetime.now(UTC) - timedelta(seconds=1)

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


class TestDomainBypass:
    """Managed PenguinTech domains skip license enforcement entirely.

    Bypass is host-driven only — there is no env var or config flag — so these
    tests pin both the matching rules and the zero-client-call guarantee.
    """

    @pytest.mark.parametrize(
        "host",
        [
            "elder.penguincloud.io",
            "penguincloud.io",
            "waddlebot.penguintech.cloud",
            "penguintech.cloud",
            "squawk.localhost.local",
            "ELDER.PENGUINCLOUD.IO",
            "elder.penguincloud.io:8443",
        ],
    )
    def test_bypass_domains_match(self, host):
        """Managed hosts match on a dot boundary, case- and port-insensitively."""
        assert _is_bypass_domain(host) is True

    @pytest.mark.parametrize(
        "host",
        [
            "evilpenguincloud.io",
            "penguincloud.io.attacker.test",
            "notpenguintech.cloud",
            "example.com",
            "localhost",
        ],
    )
    def test_non_bypass_domains_do_not_match(self, host):
        """Look-alike hosts must not slip past the dot-boundary check."""
        assert _is_bypass_domain(host) is False

    def test_bypass_host_allows_without_client_calls(self):
        """A bypass-domain request runs the view with zero license client calls."""
        app = Flask(__name__)

        @license_required("enterprise")
        def sync_func():
            return "ran"

        with patch("penguin_licensing.client.get_license_client") as mock_get:
            with app.test_request_context("/", base_url="https://elder.penguincloud.io"):
                assert sync_func() == "ran"
            mock_get.assert_not_called()

    def test_bypass_host_allows_feature_without_client_calls(self):
        """feature_required is bypassed on managed domains, with no client calls."""
        app = Flask(__name__)

        @feature_required("sso")
        def sync_func():
            return "ran"

        with patch("penguin_licensing.client.get_license_client") as mock_get:
            with app.test_request_context("/", base_url="https://waddlebot.penguintech.cloud"):
                assert sync_func() == "ran"
            mock_get.assert_not_called()

    @pytest.mark.asyncio
    async def test_bypass_host_allows_async_without_client_calls(self):
        """The async wrapper short-circuits on managed domains too."""
        app = Flask(__name__)

        @license_required("enterprise")
        async def async_func():
            return "ran"

        with patch("penguin_licensing.client.get_license_client") as mock_get:
            with app.test_request_context("/", base_url="https://elder.penguincloud.io"):
                assert await async_func() == "ran"
            mock_get.assert_not_called()

    @patch("penguin_licensing.client.LicenseClient")
    def test_non_bypass_host_still_enforced(self, mock_client_class):
        """A non-managed host gets the normal fail-closed tier check."""
        app = Flask(__name__)
        mock_client = MagicMock()
        mock_client_class.return_value = mock_client
        mock_validation = MagicMock()
        mock_validation.valid = True
        mock_validation.tier = "community"
        mock_client.validate.return_value = mock_validation

        @license_required("enterprise")
        def sync_func():
            return "ran"

        with app.test_request_context("/", base_url="https://customer.example.com"):
            with pytest.raises(LicenseRequiredError):
                sync_func()

    @patch("penguin_licensing.client.LicenseClient")
    def test_no_flask_context_fails_closed(self, mock_client_class):
        """Outside a Flask request there is no trusted host, so gating still runs."""
        mock_client = MagicMock()
        mock_client_class.return_value = mock_client
        mock_validation = MagicMock()
        mock_validation.valid = True
        mock_validation.tier = "community"
        mock_client.validate.return_value = mock_validation

        @license_required("enterprise")
        def sync_func():
            return "ran"

        with pytest.raises(LicenseRequiredError):
            sync_func()


class TestQuartDomainBypass:
    """Quart is the mandated PenguinTech framework — bypass must work under it.

    ``request.host`` is only populated by Quart when a Host header is present
    on the synthetic request, so these use ``headers={"host": ...}`` rather
    than the ``base_url`` kwarg Flask's ``test_request_context`` accepts.
    """

    @pytest.mark.asyncio
    async def test_bypass_host_allows_without_client_calls(self):
        """A bypass-domain request under Quart runs the view with zero client calls."""
        app = Quart(__name__)

        @license_required("enterprise")
        def sync_func():
            return "ran"

        with patch("penguin_licensing.client.get_license_client") as mock_get:
            async with app.test_request_context(
                "/", headers={"host": "elder.penguincloud.io"}, scheme="https"
            ):
                assert sync_func() == "ran"
            mock_get.assert_not_called()

    @pytest.mark.asyncio
    async def test_bypass_host_allows_async_without_client_calls(self):
        """The async wrapper short-circuits on managed domains under Quart too."""
        app = Quart(__name__)

        @license_required("enterprise")
        async def async_func():
            return "ran"

        with patch("penguin_licensing.client.get_license_client") as mock_get:
            async with app.test_request_context(
                "/", headers={"host": "waddlebot.penguintech.cloud"}, scheme="https"
            ):
                assert await async_func() == "ran"
            mock_get.assert_not_called()

    @pytest.mark.asyncio
    async def test_non_bypass_host_still_enforced(self):
        """A non-managed host under Quart still gets the normal fail-closed check."""
        app = Quart(__name__)

        with patch("penguin_licensing.client.LicenseClient") as mock_client_class:
            mock_client = MagicMock()
            mock_client_class.return_value = mock_client
            mock_validation = MagicMock()
            mock_validation.valid = True
            mock_validation.tier = "community"
            mock_client.validate.return_value = mock_validation

            @license_required("enterprise")
            def sync_func():
                return "ran"

            async with app.test_request_context(
                "/", headers={"host": "customer.example.com"}, scheme="https"
            ):
                with pytest.raises(LicenseRequiredError):
                    sync_func()

    @patch("penguin_licensing.client.LicenseClient")
    def test_flask_context_still_bypasses_when_quart_also_installed(self, mock_client_class):
        """Quart being importable must not shadow an active Flask request context.

        Quart is preferred, but when Quart has no active context the code
        must still fall back and read Flask's — this is the regression case
        for the original bug (hard dependency on Flask's globals).
        """
        app = Flask(__name__)

        @license_required("enterprise")
        def sync_func():
            return "ran"

        with patch("penguin_licensing.client.get_license_client") as mock_get:
            with app.test_request_context("/", base_url="https://elder.penguincloud.io"):
                assert sync_func() == "ran"
            mock_get.assert_not_called()


class TestNoWebFrameworkInstalled:
    """Neither Quart nor Flask importable is a config gap, not a bypass signal."""

    @patch("penguin_licensing.client.LicenseClient")
    def test_fails_closed_and_warns_once(self, mock_client_class):
        """Missing both frameworks still fails closed, and logs a warning exactly once.

        structlog's default (unconfigured) logger writes via its own printer,
        not stdlib ``logging`` handlers, so ``caplog`` can't observe it here —
        assert on the logger call directly instead.
        """
        mock_client = MagicMock()
        mock_client_class.return_value = mock_client
        mock_validation = MagicMock()
        mock_validation.valid = True
        mock_validation.tier = "community"
        mock_client.validate.return_value = mock_validation

        @license_required("enterprise")
        def sync_func():
            return "ran"

        with (
            patch.object(decorators_module, "_quart_request_host", return_value=(None, False)),
            patch.object(decorators_module, "_flask_request_host", return_value=(None, False)),
            patch.object(decorators_module, "logger") as mock_logger,
        ):
            with pytest.raises(LicenseRequiredError):
                sync_func()
            with pytest.raises(LicenseRequiredError):
                sync_func()

        warn_calls = [
            c
            for c in mock_logger.warning.call_args_list
            if c.args[:1] == ("license_bypass_no_web_framework",)
        ]
        assert len(warn_calls) == 1
