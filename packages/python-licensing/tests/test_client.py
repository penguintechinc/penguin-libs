"""Tests for the PenguinTech License Server client."""

from datetime import datetime, timezone
from unittest.mock import MagicMock, patch
import pytest
from penguin_licensing.client import Feature, LicenseInfo, LicenseClient, get_license_client


class TestFeatureDataclass:
    """Tests for Feature dataclass."""

    def test_feature_dataclass(self):
        """Feature stores all fields correctly."""
        feature = Feature(
            name="test_feature",
            entitled=True,
            units=0,
            description="Test description",
            metadata={"key": "value"}
        )
        assert feature.name == "test_feature"
        assert feature.entitled is True
        assert feature.units == 0
        assert feature.description == "Test description"
        assert feature.metadata == {"key": "value"}


class TestLicenseInfoDataclass:
    """Tests for LicenseInfo dataclass."""

    def test_license_info_dataclass(self):
        """LicenseInfo construction with all required fields."""
        issued_at = datetime.now(timezone.utc)
        expires_at = datetime.now(timezone.utc)

        license_info = LicenseInfo(
            valid=True,
            tier="enterprise",
            customer="Test Co",
            product="test-product",
            license_version="2.0",
            license_key="PENG-TEST-1234",
            issued_at=issued_at,
            expires_at=expires_at,
            features=[],
            limits={},
            metadata={}
        )

        assert license_info.valid is True
        assert license_info.tier == "enterprise"
        assert license_info.customer == "Test Co"
        assert license_info.product == "test-product"
        assert license_info.license_key == "PENG-TEST-1234"
        assert license_info.issued_at == issued_at
        assert license_info.expires_at == expires_at
        assert license_info.features == []
        assert license_info.limits == {}
        assert license_info.metadata == {}


class TestLicenseClientNoCommunity:
    """Tests for LicenseClient community tier fallback."""

    def test_license_client_no_key_returns_community(self):
        """LicenseClient with empty key returns community tier."""
        client = LicenseClient(license_key="")
        result = client.validate()

        assert result.valid is True
        assert result.tier == "community"


class TestLicenseClientValidate:
    """Tests for LicenseClient validation."""

    @patch('penguin_licensing.client.requests.Session.post')
    def test_license_client_validate_success(self, mock_post):
        """LicenseClient validate parses successful response."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "customer": "Test Co",
            "product": "elder",
            "license_version": "2.0",
            "license_key": "PENG-TEST-1234",
            "expires_at": "2030-01-01T00:00:00Z",
            "issued_at": "2024-01-01T00:00:00Z",
            "tier": "enterprise",
            "features": [
                {
                    "name": "sso",
                    "entitled": True,
                    "units": -1,
                    "description": "SSO",
                    "metadata": {}
                }
            ],
            "limits": {"max_entities": 1000},
            "metadata": {"server_id": "srv-123"},
        }
        mock_post.return_value = mock_response

        client = LicenseClient(license_key="PENG-TEST-1234")
        result = client.validate()

        assert result.valid is True
        assert result.tier == "enterprise"
        assert result.customer == "Test Co"
        assert result.product == "elder"
        assert result.license_key == "PENG-TEST-1234"
        assert len(result.features) == 1
        assert result.features[0].name == "sso"
        assert result.features[0].entitled is True
        assert result.limits == {"max_entities": 1000}
        assert result.metadata == {"server_id": "srv-123"}

    @patch('penguin_licensing.client.requests.Session.post')
    def test_license_client_validate_failure(self, mock_post):
        """LicenseClient validate returns invalid on 403."""
        mock_response = MagicMock()
        mock_response.status_code = 403
        mock_post.return_value = mock_response

        client = LicenseClient(license_key="PENG-INVALID-KEY")
        result = client.validate()

        assert result.valid is False

    @patch('penguin_licensing.client.requests.Session.post')
    def test_license_client_validate_exception(self, mock_post):
        """LicenseClient validate returns community on connection error."""
        mock_post.side_effect = ConnectionError("Network error")

        client = LicenseClient(license_key="PENG-TEST-1234")
        result = client.validate()

        assert result.valid is True
        assert result.tier == "community"


class TestLicenseClientCheckFeature:
    """Tests for LicenseClient feature checking."""

    @patch('penguin_licensing.client.requests.Session.post')
    def test_check_feature_found(self, mock_post):
        """check_feature returns True for entitled feature."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "customer": "Test Co",
            "product": "elder",
            "license_version": "2.0",
            "license_key": "PENG-TEST-1234",
            "expires_at": "2030-01-01T00:00:00Z",
            "issued_at": "2024-01-01T00:00:00Z",
            "tier": "enterprise",
            "features": [
                {
                    "name": "sso",
                    "entitled": True,
                    "units": -1,
                    "description": "SSO",
                    "metadata": {}
                }
            ],
            "limits": {},
            "metadata": {},
        }
        mock_post.return_value = mock_response

        client = LicenseClient(license_key="PENG-TEST-1234")
        client.validate()

        assert client.check_feature("sso") is True

    @patch('penguin_licensing.client.requests.Session.post')
    def test_check_feature_not_found(self, mock_post):
        """check_feature returns False for nonexistent feature."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "customer": "Test Co",
            "product": "elder",
            "license_version": "2.0",
            "license_key": "PENG-TEST-1234",
            "expires_at": "2030-01-01T00:00:00Z",
            "issued_at": "2024-01-01T00:00:00Z",
            "tier": "enterprise",
            "features": [],
            "limits": {},
            "metadata": {},
        }
        mock_post.return_value = mock_response

        client = LicenseClient(license_key="PENG-TEST-1234")
        client.validate()

        assert client.check_feature("nonexistent") is False


class TestLicenseClientCheckTier:
    """Tests for LicenseClient tier checking."""

    def test_check_tier_hierarchy(self):
        """check_tier respects tier hierarchy."""
        client = LicenseClient(license_key="")
        client.validate()

        assert client.check_tier("community") is True
        assert client.check_tier("professional") is False
        assert client.check_tier("enterprise") is False


class TestLicenseClientKeepalive:
    """Tests for LicenseClient keepalive."""

    def test_keepalive_no_key(self):
        """keepalive returns failure for empty license key."""
        client = LicenseClient(license_key="")
        result = client.keepalive()

        assert result["success"] is False

    @patch('penguin_licensing.client.requests.Session.post')
    def test_keepalive_success(self, mock_post):
        """keepalive succeeds when validate has server_id."""
        validate_response = MagicMock()
        validate_response.status_code = 200
        validate_response.json.return_value = {
            "customer": "Test Co",
            "product": "elder",
            "license_version": "2.0",
            "license_key": "PENG-TEST-1234",
            "expires_at": "2030-01-01T00:00:00Z",
            "issued_at": "2024-01-01T00:00:00Z",
            "tier": "enterprise",
            "features": [],
            "limits": {},
            "metadata": {"server_id": "srv-123"},
        }

        keepalive_response = MagicMock()
        keepalive_response.status_code = 200
        keepalive_response.json.return_value = {"success": True}

        mock_post.side_effect = [validate_response, keepalive_response]

        client = LicenseClient(license_key="PENG-TEST-1234")
        client.validate()
        result = client.keepalive()

        assert result["success"] is True


class TestLicenseClientCheckFeatureInvalid:
    """Tests for check_feature when validation is invalid."""

    @patch('penguin_licensing.client.requests.Session.post')
    def test_check_feature_returns_false_when_invalid(self, mock_post):
        """check_feature returns False when license validation is invalid."""
        mock_response = MagicMock()
        mock_response.status_code = 403
        mock_response.text = "Forbidden"
        mock_post.return_value = mock_response

        client = LicenseClient(license_key="PENG-INVALID-KEY")
        assert client.check_feature("sso") is False


class TestLicenseClientKeepaliveExtended:
    """Extended keepalive tests for missed coverage paths."""

    @patch('penguin_licensing.client.requests.Session.post')
    def test_keepalive_no_server_id_validates_first(self, mock_post):
        """keepalive validates to get server_id when missing, returns failure if still none."""
        # validate returns valid=True but no server_id
        validate_response = MagicMock()
        validate_response.status_code = 200
        validate_response.json.return_value = {
            "customer": "Test Co",
            "product": "elder",
            "license_version": "2.0",
            "license_key": "PENG-TEST-1234",
            "expires_at": "2030-01-01T00:00:00Z",
            "issued_at": "2024-01-01T00:00:00Z",
            "tier": "enterprise",
            "features": [],
            "limits": {},
            "metadata": {},
        }
        mock_post.return_value = validate_response

        client = LicenseClient(license_key="PENG-TEST-1234")
        # server_id is None, validate won't set it either
        result = client.keepalive()
        assert result["success"] is False
        assert "No server ID" in result["message"]

    @patch('penguin_licensing.client.requests.Session.post')
    def test_keepalive_with_usage_data(self, mock_post):
        """keepalive includes usage_data in payload."""
        keepalive_response = MagicMock()
        keepalive_response.status_code = 200
        keepalive_response.json.return_value = {"success": True}
        mock_post.return_value = keepalive_response

        client = LicenseClient(license_key="PENG-TEST-1234")
        client.server_id = "srv-123"
        result = client.keepalive(usage_data={"active_users": 5})

        assert result["success"] is True
        call_args = mock_post.call_args
        payload = call_args[1]["json"]
        assert payload["active_users"] == 5

    @patch('penguin_licensing.client.requests.Session.post')
    def test_keepalive_non_200_response(self, mock_post):
        """keepalive returns failure dict on non-200 status."""
        mock_response = MagicMock()
        mock_response.status_code = 500
        mock_response.text = "Internal Server Error"
        mock_post.return_value = mock_response

        client = LicenseClient(license_key="PENG-TEST-1234")
        client.server_id = "srv-123"
        result = client.keepalive()

        assert result["success"] is False
        assert "500" in result["message"]

    @patch('penguin_licensing.client.requests.Session.post')
    def test_keepalive_exception(self, mock_post):
        """keepalive returns failure dict on request exception."""
        mock_post.side_effect = ConnectionError("network down")

        client = LicenseClient(license_key="PENG-TEST-1234")
        client.server_id = "srv-123"
        result = client.keepalive()

        assert result["success"] is False
        assert "error" in result["message"].lower()

    @patch('penguin_licensing.client.requests.Session.post')
    def test_keepalive_no_server_id_invalid_validation(self, mock_post):
        """keepalive returns failure when validate returns invalid and no server_id."""
        validate_response = MagicMock()
        validate_response.status_code = 403
        validate_response.text = "Forbidden"
        mock_post.return_value = validate_response

        client = LicenseClient(license_key="PENG-TEST-1234")
        result = client.keepalive()

        assert result["success"] is False


class TestInitLicenseClient:
    """Tests for init_license_client function."""

    def setup_method(self):
        import penguin_licensing.client
        penguin_licensing.client._license_client = None

    def teardown_method(self):
        import penguin_licensing.client
        penguin_licensing.client._license_client = None

    @patch('penguin_licensing.client.requests.Session.post')
    def test_init_license_client_from_app_config(self, mock_post):
        """init_license_client reads from Flask app config."""
        from penguin_licensing.client import init_license_client

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "customer": "Test Co",
            "product": "elder",
            "license_version": "2.0",
            "license_key": "PENG-TEST-1234",
            "expires_at": "2030-01-01T00:00:00Z",
            "issued_at": "2024-01-01T00:00:00Z",
            "tier": "enterprise",
            "features": [],
            "limits": {},
            "metadata": {"server_id": "srv-123"},
        }
        mock_post.return_value = mock_response

        mock_app = MagicMock()
        mock_app.config = {
            "LICENSE_KEY": "PENG-TEST-1234",
            "LICENSE_SERVER_URL": "https://custom.license.io",
        }

        client = init_license_client(mock_app)

        assert client is not None
        assert client.license_key == "PENG-TEST-1234"
        assert client.base_url == "https://custom.license.io"

    @patch('penguin_licensing.client.requests.Session.post')
    @patch.dict("os.environ", {"LICENSE_KEY": "PENG-ENV-1234", "LICENSE_SERVER_URL": "https://env.license.io"})
    def test_init_license_client_falls_back_to_env(self, mock_post):
        """init_license_client falls back to env vars when app config empty."""
        from penguin_licensing.client import init_license_client

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "customer": "Env Co",
            "product": "elder",
            "license_version": "2.0",
            "license_key": "PENG-ENV-1234",
            "expires_at": "2030-01-01T00:00:00Z",
            "issued_at": "2024-01-01T00:00:00Z",
            "tier": "professional",
            "features": [],
            "limits": {},
            "metadata": {},
        }
        mock_post.return_value = mock_response

        mock_app = MagicMock()
        mock_app.config = {}

        client = init_license_client(mock_app)
        assert client is not None
        assert client.license_key == "PENG-ENV-1234"

    @patch('penguin_licensing.client.requests.Session.post')
    def test_init_license_client_sets_global(self, mock_post):
        """init_license_client sets the global _license_client."""
        from penguin_licensing.client import init_license_client
        import penguin_licensing.client as mod

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "customer": "Test Co",
            "product": "elder",
            "license_version": "2.0",
            "license_key": "PENG-TEST-1234",
            "expires_at": "2030-01-01T00:00:00Z",
            "issued_at": "2024-01-01T00:00:00Z",
            "tier": "enterprise",
            "features": [],
            "limits": {},
            "metadata": {},
        }
        mock_post.return_value = mock_response

        mock_app = MagicMock()
        mock_app.config = {"LICENSE_KEY": "PENG-TEST-1234"}

        client = init_license_client(mock_app)
        assert mod._license_client is client


class TestGetLicenseClient:
    """Tests for get_license_client singleton."""

    def test_get_license_client_singleton(self):
        """get_license_client returns same instance on repeated calls."""
        # Reset the global singleton
        import penguin_licensing.client
        penguin_licensing.client._license_client = None

        client1 = get_license_client()
        client2 = get_license_client()

        assert client1 is client2

        # Reset after test
        penguin_licensing.client._license_client = None


class TestLicenseClientFailClosed:
    """Tests for fail-closed license validation."""

    @patch('penguin_licensing.client.requests.Session.post')
    def test_definitive_rejection_drops_cache(self, mock_post):
        """401/403/404 drops cache and returns community tier."""
        # First call succeeds and caches enterprise tier
        valid_response = MagicMock()
        valid_response.status_code = 200
        valid_response.json.return_value = {
            "valid": True,
            "customer": "Test Co",
            "product": "elder",
            "license_version": "2.0",
            "license_key": "PENG-TEST-1234",
            "expires_at": "2030-01-01T00:00:00Z",
            "issued_at": "2024-01-01T00:00:00Z",
            "tier": "enterprise",
            "features": [{"name": "saml", "entitled": True, "units": -1, "description": "", "metadata": {}}],
            "limits": {},
            "metadata": {},
        }

        # Second call gets 403 (revocation)
        rejection_response = MagicMock()
        rejection_response.status_code = 403

        mock_post.side_effect = [valid_response, rejection_response]

        client = LicenseClient(license_key="PENG-TEST-1234")

        # First validate succeeds
        result1 = client.validate()
        assert result1.tier == "enterprise"
        assert result1.valid is True

        # Second validate (forced refresh) gets rejected
        result2 = client.validate(force_refresh=True)
        assert result2.tier == "community"
        assert result2.valid is False
        assert "revoked" in result2.message.lower()

    @patch('penguin_licensing.client.requests.Session.post')
    def test_server_error_returns_cached_value(self, mock_post):
        """5xx error returns last cached value."""
        # First call succeeds and caches professional tier
        valid_response = MagicMock()
        valid_response.status_code = 200
        valid_response.json.return_value = {
            "valid": True,
            "customer": "Test Co",
            "product": "elder",
            "license_version": "2.0",
            "license_key": "PENG-TEST-1234",
            "expires_at": "2030-01-01T00:00:00Z",
            "issued_at": "2024-01-01T00:00:00Z",
            "tier": "professional",
            "features": [{"name": "sso_google", "entitled": True, "units": -1, "description": "", "metadata": {}}],
            "limits": {},
            "metadata": {},
        }

        # Second call gets 503 (service unavailable)
        error_response = MagicMock()
        error_response.status_code = 503

        mock_post.side_effect = [valid_response, error_response]

        client = LicenseClient(license_key="PENG-TEST-1234")

        # First validate succeeds
        result1 = client.validate()
        assert result1.tier == "professional"

        # Second validate (forced refresh) gets 503 but uses cache
        result2 = client.validate(force_refresh=True)
        assert result2.tier == "professional"
        assert result2.valid is True

    @patch('penguin_licensing.client.requests.Session.post')
    def test_expiry_grace_period(self, mock_post):
        """License expiry enforced with 72h grace period."""
        from datetime import timedelta

        # License expired but within grace period
        expired_at = datetime.now(timezone.utc) - timedelta(hours=24)
        expiry_response = MagicMock()
        expiry_response.status_code = 200
        expiry_response.json.return_value = {
            "valid": True,
            "customer": "Test Co",
            "product": "elder",
            "license_version": "2.0",
            "license_key": "PENG-TEST-1234",
            "expires_at": expired_at.isoformat().replace('+00:00', 'Z'),
            "issued_at": "2024-01-01T00:00:00Z",
            "tier": "enterprise",
            "features": [],
            "limits": {},
            "metadata": {},
        }

        mock_post.return_value = expiry_response

        client = LicenseClient(license_key="PENG-TEST-1234")
        result = client.validate()

        # Should still be valid because within 72h grace
        assert result.valid is True
        assert result.tier == "enterprise"

    @patch('penguin_licensing.client.requests.Session.post')
    def test_expiry_beyond_grace_period(self, mock_post):
        """License beyond 72h grace period rejected."""
        from datetime import timedelta

        # License expired beyond grace period (75 hours ago)
        expired_at = datetime.now(timezone.utc) - timedelta(hours=75)
        expiry_response = MagicMock()
        expiry_response.status_code = 200
        expiry_response.json.return_value = {
            "valid": True,
            "customer": "Test Co",
            "product": "elder",
            "license_version": "2.0",
            "license_key": "PENG-TEST-1234",
            "expires_at": expired_at.isoformat().replace('+00:00', 'Z'),
            "issued_at": "2024-01-01T00:00:00Z",
            "tier": "enterprise",
            "features": [],
            "limits": {},
            "metadata": {},
        }

        mock_post.return_value = expiry_response

        client = LicenseClient(license_key="PENG-TEST-1234")
        result = client.validate()

        # Should be invalid because beyond grace period
        assert result.valid is False
        assert result.tier == "community"
        assert "grace" in result.message.lower()


class TestTLSEnforcement:
    """Tests for TLS scheme enforcement."""

    def test_https_required_for_license_server(self):
        """HTTPS required for license server (except localhost)."""
        import pytest
        from penguin_licensing.client import LicenseClient

        # HTTP for non-localhost should raise ValueError
        with pytest.raises(ValueError, match="HTTPS"):
            LicenseClient(base_url="http://example.com/api")

    def test_http_allowed_for_localhost(self):
        """HTTP allowed for localhost (development)."""
        from penguin_licensing.client import LicenseClient

        # Should not raise
        client = LicenseClient(base_url="http://localhost:8080/api")
        assert client.base_url == "http://localhost:8080/api"

    def test_http_allowed_for_127_0_0_1(self):
        """HTTP allowed for 127.0.0.1 (development)."""
        from penguin_licensing.client import LicenseClient

        # Should not raise
        client = LicenseClient(base_url="http://127.0.0.1:8080/api")
        assert client.base_url == "http://127.0.0.1:8080/api"

    def test_https_accepted(self):
        """HTTPS always accepted."""
        from penguin_licensing.client import LicenseClient

        # Should not raise
        client = LicenseClient(base_url="https://license.example.com/api")
        assert client.base_url == "https://license.example.com/api"


class TestLicenseServerUrlEnvVar:
    """LICENSE_SERVER_URL must actually take effect when base_url is not passed.

    Regression: LicenseClient's base_url parameter used to default to the
    truthy literal "https://license.penguintech.io", so `base_url or
    os.getenv("LICENSE_SERVER_URL", ...)` never reached the env var lookup —
    the default short-circuited the `or` every time.
    """

    @patch.dict("os.environ", {"LICENSE_SERVER_URL": "https://env.example.io"})
    def test_env_var_honored_when_base_url_omitted(self):
        """Constructing LicenseClient() with no base_url picks up the env var."""
        from penguin_licensing.client import LicenseClient

        client = LicenseClient(license_key="PENG-TEST-1234")
        assert client.base_url == "https://env.example.io"

    def test_hardcoded_default_used_when_no_env_and_no_arg(self):
        """With no env var and no explicit base_url, the hardcoded default wins."""
        from penguin_licensing.client import LicenseClient

        with patch.dict("os.environ", {}, clear=True):
            client = LicenseClient(license_key="PENG-TEST-1234")
        assert client.base_url == "https://license.penguintech.io"

    @patch.dict("os.environ", {"LICENSE_SERVER_URL": "https://explicit-wins.example.io"})
    def test_explicit_base_url_overrides_env_var(self):
        """An explicitly passed base_url still takes precedence over the env var."""
        from penguin_licensing.client import LicenseClient

        client = LicenseClient(
            license_key="PENG-TEST-1234", base_url="https://arg.example.io"
        )
        assert client.base_url == "https://arg.example.io"

    @patch.dict("os.environ", {"LICENSE_SERVER_URL": "http://insecure.example.io"})
    def test_env_var_still_subject_to_https_enforcement(self):
        """HTTPS enforcement applies to whichever value wins, including the env var."""
        from penguin_licensing.client import LicenseClient

        with pytest.raises(ValueError, match="HTTPS"):
            LicenseClient(license_key="PENG-TEST-1234")


class TestLicenseClientTransportFallback:
    """Transport-level failures must serve the last known-good validation."""

    @staticmethod
    def _ok_response(tier="enterprise"):
        """Build a mock 200 /api/v2/validate response for the given tier."""
        response = MagicMock()
        response.status_code = 200
        response.json.return_value = {
            "valid": True,
            "customer": "Test Co",
            "product": "elder",
            "license_version": "2.0",
            "license_key": "PENG-TEST-1234",
            "expires_at": "2030-01-01T00:00:00Z",
            "issued_at": "2024-01-01T00:00:00Z",
            "tier": tier,
            "features": [],
            "limits": {},
            "metadata": {},
        }
        return response

    @patch("penguin_licensing.client.requests.Session.post")
    def test_transport_error_returns_cached(self, mock_post):
        """A connection failure on a forced refresh serves the cached tier."""
        import requests

        mock_post.side_effect = [
            self._ok_response("enterprise"),
            requests.ConnectionError("unreachable"),
        ]

        client = LicenseClient(license_key="PENG-TEST-1234")
        assert client.validate().tier == "enterprise"
        assert mock_post.call_count == 1

        result = client.validate(force_refresh=True)
        assert mock_post.call_count == 2
        assert result.tier == "enterprise"
        assert result is client._cached_validation

    @patch("penguin_licensing.client.requests.Session.post")
    def test_transport_error_without_cache_falls_back_to_community(self, mock_post):
        """With no cached value a connection failure degrades to community."""
        import requests

        mock_post.side_effect = requests.ConnectionError("unreachable")

        client = LicenseClient(license_key="PENG-TEST-1234")
        result = client.validate()

        assert result.tier == "community"
        assert mock_post.call_count == 1


class TestGetLicenseClientThreadSafety:
    """The shared client must be constructed exactly once under concurrency."""

    def test_concurrent_cold_start_constructs_one_instance(self):
        """16 threads racing a cold module state get one shared client.

        A second instance would carry its own empty validation cache and
        connection pool, silently voiding the warm-cache-survives-outage
        guarantee the decorators depend on.
        """
        import threading
        import time

        import penguin_licensing.client as client_module

        thread_count = 16
        constructed = []
        constructed_lock = threading.Lock()
        real_init = LicenseClient.__init__

        def slow_init(self, *args, **kwargs):
            # Widen the check-then-act window so an unguarded singleton loses.
            time.sleep(0.02)
            real_init(self, *args, **kwargs)
            with constructed_lock:
                constructed.append(self)

        barrier = threading.Barrier(thread_count)
        results = []
        results_lock = threading.Lock()
        errors = []

        def worker():
            try:
                barrier.wait()
                client = get_license_client()
                with results_lock:
                    results.append(client)
            except Exception as exc:  # pragma: no cover - surfaced via assert below
                errors.append(exc)

        client_module._license_client = None
        try:
            with patch.object(LicenseClient, "__init__", slow_init):
                threads = [
                    threading.Thread(target=worker, name=f"lic-{i}")
                    for i in range(thread_count)
                ]
                for thread in threads:
                    thread.start()
                for thread in threads:
                    thread.join(timeout=10)
                assert not any(thread.is_alive() for thread in threads)

            assert errors == []
            assert len(constructed) == 1, (
                f"expected exactly 1 LicenseClient construction, got {len(constructed)}"
            )
            assert len(results) == thread_count
            assert all(client is results[0] for client in results)
            assert results[0] is client_module._license_client
        finally:
            client_module._license_client = None

    def test_reset_hook_still_rebuilds_client(self):
        """Clearing the module global still yields a fresh client."""
        import penguin_licensing.client as client_module

        client_module._license_client = None
        try:
            first = get_license_client()
            assert get_license_client() is first

            client_module._license_client = None
            second = get_license_client()
            assert second is not first
        finally:
            client_module._license_client = None


class TestLicenseClientDomainBypass:
    """A managed deployment host skips license enforcement entirely.

    Bypass is host-driven only — there is no env var or config flag — so
    these tests pin both the matching behaviour and the zero-network-call
    guarantee for every public entry point that gates on entitlement.
    """

    @patch("penguin_licensing.client.requests.Session.post")
    def test_validate_bypassed_makes_no_request(self, mock_post):
        """A bypass-domain deployment never calls the license server."""
        client = LicenseClient(
            license_key="PENG-TEST-1234", deployment_host="waddleai.penguintech.cloud"
        )

        result = client.validate()

        assert result.valid is True
        assert result.tier == "enterprise"
        mock_post.assert_not_called()

    @patch("penguin_licensing.client.requests.Session.post")
    def test_check_feature_bypassed_returns_true_for_any_feature(self, mock_post):
        """Bypass entitles every feature, not just ones in a features list."""
        client = LicenseClient(
            license_key="PENG-TEST-1234", deployment_host="elder.penguincloud.io"
        )

        assert client.check_feature("anything_at_all") is True
        mock_post.assert_not_called()

    @patch("penguin_licensing.client.requests.Session.post")
    def test_check_tier_bypassed_returns_true_for_enterprise(self, mock_post):
        """Bypass satisfies even the highest tier requirement."""
        client = LicenseClient(license_key="", deployment_host="penguintech.cloud")

        assert client.check_tier("enterprise") is True
        mock_post.assert_not_called()

    @patch("penguin_licensing.client.requests.Session.post")
    def test_non_bypass_host_runs_normal_flow(self, mock_post):
        """A look-alike host must not slip past the dot-boundary check."""
        mock_response = MagicMock()
        mock_response.status_code = 403
        mock_post.return_value = mock_response

        client = LicenseClient(
            license_key="PENG-TEST-1234", deployment_host="evil-penguintech.cloud"
        )

        result = client.validate()

        assert result.valid is False
        mock_post.assert_called_once()

    @patch("penguin_licensing.client.requests.Session.post")
    def test_lookalike_suffix_attack_host_not_bypassed(self, mock_post):
        """A domain merely containing the managed suffix must stay gated."""
        mock_response = MagicMock()
        mock_response.status_code = 403
        mock_post.return_value = mock_response

        client = LicenseClient(
            license_key="PENG-TEST-1234",
            deployment_host="penguintech.cloud.attacker.com",
        )

        result = client.validate()

        assert result.valid is False
        mock_post.assert_called_once()

    def test_no_deployment_host_is_not_bypassed(self):
        """No known host at all falls through to the normal license flow."""
        client = LicenseClient(license_key="")

        assert client._bypass_active() is False

    @patch("penguin_licensing.client.requests.Session.post")
    def test_set_deployment_host_updates_bypass_after_construction(self, mock_post):
        """A host learned after construction still activates bypass."""
        client = LicenseClient(license_key="PENG-TEST-1234")
        assert client._bypass_active() is False

        client.set_deployment_host("app.penguincloud.io")

        assert client._bypass_active() is True
        assert client.check_feature("anything") is True
        mock_post.assert_not_called()

    @patch("penguin_licensing.client.requests.Session.post")
    def test_extra_bypass_domains_cover_product_domain(self, mock_post):
        """A product's own domain can be added without a code change here."""
        client = LicenseClient(
            license_key="PENG-TEST-1234",
            deployment_host="waddleai.app",
            extra_bypass_domains=["waddleai.app"],
        )

        assert client.check_feature("anything") is True
        mock_post.assert_not_called()

    @patch("penguin_licensing.client.requests.Session.post")
    def test_extra_bypass_domains_do_not_widen_lookalike_hosts(self, mock_post):
        """A caller-supplied product domain still respects the dot boundary."""
        mock_response = MagicMock()
        mock_response.status_code = 403
        mock_post.return_value = mock_response

        client = LicenseClient(
            license_key="PENG-TEST-1234",
            deployment_host="evil-waddleai.app",
            extra_bypass_domains=["waddleai.app"],
        )

        result = client.validate()

        assert result.valid is False
        mock_post.assert_called_once()
