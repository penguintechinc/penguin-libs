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
    configure_deployment_domain,
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
def reset_deployment_domain(monkeypatch):
    """Clear the configured deployment domain (both config and env) between tests.

    Bypass now derives solely from server-side config, so a domain configured
    by one test must never leak into the next.
    """
    decorators_module._deployment_domain_override = None
    monkeypatch.delenv(decorators_module._DEPLOYMENT_DOMAIN_ENV_VAR, raising=False)
    yield
    decorators_module._deployment_domain_override = None


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


class TestDeploymentDomainConfig:
    """Resolution and precedence of the server-side deployment domain signal.

    This is the sole authoritative bypass gate — a deployer-set value, never
    request-derived (see `decorators.configure_deployment_domain`).
    """

    def test_unset_resolves_to_none(self):
        """No config call and no env var means no deployment domain at all."""
        assert decorators_module._configured_deployment_domain() is None

    def test_configure_function_sets_value(self):
        """configure_deployment_domain() is read back by the resolver."""
        configure_deployment_domain("widgets.penguintech.cloud")
        assert decorators_module._configured_deployment_domain() == "widgets.penguintech.cloud"

    def test_env_var_used_as_fallback(self, monkeypatch):
        """The env var is honored when configure_deployment_domain() was never called."""
        monkeypatch.setenv(
            decorators_module._DEPLOYMENT_DOMAIN_ENV_VAR, "widgets.penguintech.cloud"
        )
        assert decorators_module._configured_deployment_domain() == "widgets.penguintech.cloud"

    def test_explicit_config_wins_over_env_var(self, monkeypatch):
        """A configure_deployment_domain() call takes precedence over the env var."""
        monkeypatch.setenv(decorators_module._DEPLOYMENT_DOMAIN_ENV_VAR, "env.penguintech.cloud")
        configure_deployment_domain("code.penguintech.cloud")
        assert decorators_module._configured_deployment_domain() == "code.penguintech.cloud"

    def test_configure_none_clears_override_back_to_env(self, monkeypatch):
        """Passing None falls back to the env var instead of leaving a stuck value."""
        monkeypatch.setenv(decorators_module._DEPLOYMENT_DOMAIN_ENV_VAR, "env.penguintech.cloud")
        configure_deployment_domain("code.penguintech.cloud")
        configure_deployment_domain(None)
        assert decorators_module._configured_deployment_domain() == "env.penguintech.cloud"

    def test_blank_env_var_resolves_to_none(self, monkeypatch):
        """An empty-string env var is treated as unset, not a matching empty domain."""
        monkeypatch.setenv(decorators_module._DEPLOYMENT_DOMAIN_ENV_VAR, "")
        assert decorators_module._configured_deployment_domain() is None


class TestDomainBypass:
    """Managed PenguinTech domains skip license enforcement entirely.

    Bypass is gated on the server-side configured deployment domain — see
    `TestHostSpoofingRegression` for the vulnerability this replaces. These
    tests pin the dot-boundary matching rules and the zero-client-call
    guarantee once a legitimate deployment domain is configured.
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

    def test_bypass_allows_without_client_calls(self):
        """A configured bypass domain runs the view with zero license client calls."""
        configure_deployment_domain("elder.penguincloud.io")

        @license_required("enterprise")
        def sync_func():
            return "ran"

        with patch("penguin_licensing.client.get_license_client") as mock_get:
            assert sync_func() == "ran"
            mock_get.assert_not_called()

    def test_bypass_allows_feature_without_client_calls(self):
        """feature_required is bypassed on a configured managed domain, with no client calls."""
        configure_deployment_domain("waddlebot.penguintech.cloud")

        @feature_required("sso")
        def sync_func():
            return "ran"

        with patch("penguin_licensing.client.get_license_client") as mock_get:
            assert sync_func() == "ran"
            mock_get.assert_not_called()

    @pytest.mark.asyncio
    async def test_bypass_allows_async_without_client_calls(self):
        """The async wrapper short-circuits on a configured managed domain too."""
        configure_deployment_domain("elder.penguincloud.io")

        @license_required("enterprise")
        async def async_func():
            return "ran"

        with patch("penguin_licensing.client.get_license_client") as mock_get:
            assert await async_func() == "ran"
            mock_get.assert_not_called()

    def test_bypass_works_with_no_request_context_at_all(self):
        """The configured domain is authoritative on its own — no framework or request needed."""
        configure_deployment_domain("elder.penguincloud.io")

        @license_required("enterprise")
        def sync_func():
            return "ran"

        with patch("penguin_licensing.client.get_license_client") as mock_get:
            assert sync_func() == "ran"
            mock_get.assert_not_called()

    @patch("penguin_licensing.client.LicenseClient")
    def test_non_bypass_configured_domain_still_enforced(self, mock_client_class):
        """A configured domain outside the managed suffix list gets the normal fail-closed check."""
        configure_deployment_domain("customer.example.com")
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

    @patch("penguin_licensing.client.LicenseClient")
    def test_no_config_and_no_request_context_fails_closed(self, mock_client_class):
        """With nothing configured and no request in flight, gating still runs."""
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


class TestHostMismatchDefenseInDepth:
    """Defense-in-depth: an inconsistent in-flight request Host narrows the bypass.

    The configured deployment domain is still the sole *grant*; a mismatched
    request Host can only refuse a bypass that config already allowed, never
    grant one on its own.
    """

    @pytest.mark.asyncio
    async def test_mismatched_quart_host_refuses_bypass_despite_matching_config(self):
        """A configured bypass domain does not fire if the live request Host disagrees."""
        configure_deployment_domain("elder.penguincloud.io")
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

    @pytest.mark.asyncio
    async def test_matching_quart_host_allows_bypass(self):
        """A live request Host consistent with the configured domain does not block the bypass."""
        configure_deployment_domain("elder.penguincloud.io")
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

    def test_mismatched_flask_host_refuses_bypass_despite_matching_config(self):
        """Same narrowing behaviour under the legacy Flask fallback path."""
        configure_deployment_domain("elder.penguincloud.io")
        app = Flask(__name__)

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

            with app.test_request_context("/", base_url="https://customer.example.com"):
                with pytest.raises(LicenseRequiredError):
                    sync_func()


class TestHostSpoofingRegression:
    """
    Regression tests for the published 0.1.0 vulnerability.

    `_bypass_active()` used to derive the bypass entirely from
    `request.host` — a client-supplied, unverified header — so any request
    carrying `Host: x.penguintech.cloud` unlocked every licensed feature on
    a self-hosted deployment, unauthenticated. These must FAIL against the
    pre-fix code and PASS against the fix.
    """

    def test_spoofed_host_without_configured_domain_does_not_bypass(self):
        """(a) A spoofed Host with no server-side config configured grants nothing."""
        app = Flask(__name__)

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

            with app.test_request_context("/", base_url="https://evil.penguintech.cloud"):
                with pytest.raises(LicenseRequiredError):
                    sync_func()

    def test_configured_bypass_domain_grants_access(self):
        """(b) A configured deployment domain matching a managed suffix bypasses gating."""
        configure_deployment_domain("foo.penguintech.cloud")

        @license_required("enterprise")
        def sync_func():
            return "ran"

        with patch("penguin_licensing.client.get_license_client") as mock_get:
            assert sync_func() == "ran"
            mock_get.assert_not_called()

    def test_configured_customer_domain_does_not_bypass(self):
        """(c) A configured domain that is a genuine customer domain never bypasses."""
        configure_deployment_domain("customer.example.com")

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

            with pytest.raises(LicenseRequiredError):
                sync_func()

    def test_no_request_context_fails_closed(self):
        """(d) No configured domain and no request in flight still fails closed."""
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

            with pytest.raises(LicenseRequiredError):
                sync_func()

    def test_no_env_var_can_toggle_licensing_off(self, monkeypatch):
        """(e) No env var, of any plausible name, disables enforcement outright."""
        for toggle_name, toggle_value in [
            ("LICENSE_REQUIRED", "false"),
            ("LICENSE_ENFORCEMENT", "0"),
            ("PENGUIN_LICENSE_DISABLE", "1"),
            ("PENGUIN_LICENSE_BYPASS", "true"),
        ]:
            monkeypatch.setenv(toggle_name, toggle_value)

        # The one env var this module DOES read is a domain identity, not a
        # toggle — pointing it at a non-managed domain must still enforce.
        monkeypatch.setenv(decorators_module._DEPLOYMENT_DOMAIN_ENV_VAR, "customer.example.com")

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

            with pytest.raises(LicenseRequiredError):
                sync_func()
