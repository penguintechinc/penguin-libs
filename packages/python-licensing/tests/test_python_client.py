"""Tests for the PenguinTech License Server Python client (python_client module)."""

import time
from unittest.mock import MagicMock, patch

import pytest
import requests

from penguin_licensing.python_client import (
    FeatureNotAvailableError,
    LicenseValidationError,
    PenguinTechLicenseClient,
    check_feature,
    get_client,
    initialize_licensing,
    requires_feature,
    send_keepalive,
)


class TestExceptions:
    """Tests for custom exception classes."""

    def test_feature_not_available_error(self):
        """FeatureNotAvailableError stores feature name and message."""
        err = FeatureNotAvailableError("sso")
        assert err.feature == "sso"
        assert "sso" in str(err)
        assert "requires license upgrade" in str(err)

    def test_license_validation_error(self):
        """LicenseValidationError is a plain exception."""
        err = LicenseValidationError("bad license")
        assert "bad license" in str(err)


class TestPenguinTechLicenseClientInit:
    """Tests for PenguinTechLicenseClient constructor."""

    def test_init_with_all_params(self):
        """Client stores all constructor params."""
        client = PenguinTechLicenseClient(
            license_key="PENG-1111-2222-3333-4444-ABCD",
            product="myapp",
            base_url="https://custom.server.io",
            timeout=60,
        )
        assert client.license_key == "PENG-1111-2222-3333-4444-ABCD"
        assert client.product == "myapp"
        assert client.base_url == "https://custom.server.io"
        assert client.timeout == 60
        assert client.server_id is None

    def test_init_default_base_url(self):
        """Client uses default base_url when not provided."""
        client = PenguinTechLicenseClient(
            license_key="PENG-1111-2222-3333-4444-ABCD", product="myapp"
        )
        assert client.base_url == "https://license.penguintech.io"

    def test_init_session_headers(self):
        """Client configures session with auth and content-type headers."""
        client = PenguinTechLicenseClient(
            license_key="PENG-1111-2222-3333-4444-ABCD", product="myapp"
        )
        assert "Bearer PENG-1111-2222-3333-4444-ABCD" in client.session.headers["Authorization"]
        assert client.session.headers["Content-Type"] == "application/json"


class TestFromEnv:
    """Tests for PenguinTechLicenseClient.from_env class method."""

    @patch.dict("os.environ", {"LICENSE_KEY": "PENG-1111-2222-3333-4444-ABCD", "PRODUCT_NAME": "myapp"})
    def test_from_env_success(self):
        """from_env creates client from environment variables."""
        client = PenguinTechLicenseClient.from_env()
        assert client is not None
        assert client.license_key == "PENG-1111-2222-3333-4444-ABCD"
        assert client.product == "myapp"

    @patch.dict("os.environ", {"LICENSE_KEY": "PENG-1111-2222-3333-4444-ABCD", "PRODUCT_NAME": "myapp", "LICENSE_SERVER_URL": "https://custom.io"})
    def test_from_env_with_custom_url(self):
        """from_env uses LICENSE_SERVER_URL when set."""
        client = PenguinTechLicenseClient.from_env()
        assert client is not None
        assert client.base_url == "https://custom.io"

    @patch.dict("os.environ", {}, clear=True)
    def test_from_env_missing_vars(self):
        """from_env returns None when required env vars are missing."""
        result = PenguinTechLicenseClient.from_env()
        assert result is None

    @patch.dict("os.environ", {"LICENSE_KEY": "", "PRODUCT_NAME": ""})
    def test_from_env_empty_vars(self):
        """from_env returns None when env vars are empty."""
        result = PenguinTechLicenseClient.from_env()
        assert result is None

    @patch.dict("os.environ", {"LICENSE_KEY": "PENG-1111-2222-3333-4444-ABCD", "PRODUCT_NAME": "myapp"})
    def test_from_env_custom_timeout(self):
        """from_env passes timeout parameter."""
        client = PenguinTechLicenseClient.from_env(timeout=60)
        assert client is not None
        assert client.timeout == 60


class TestValidate:
    """Tests for PenguinTechLicenseClient.validate."""

    def _make_client(self):
        return PenguinTechLicenseClient(
            license_key="PENG-1111-2222-3333-4444-ABCD", product="myapp"
        )

    @patch("penguin_licensing.python_client.requests.Session.post")
    def test_validate_success(self, mock_post):
        """validate returns data on success."""
        mock_resp = MagicMock()
        mock_resp.raise_for_status.return_value = None
        mock_resp.json.return_value = {
            "valid": True,
            "features": [{"name": "sso", "entitled": True}],
            "metadata": {"server_id": "srv-abc"},
        }
        mock_post.return_value = mock_resp

        client = self._make_client()
        result = client.validate()

        assert result["valid"] is True
        assert client.server_id == "srv-abc"

    @patch("penguin_licensing.python_client.requests.Session.post")
    def test_validate_invalid_license(self, mock_post):
        """validate raises LicenseValidationError when license is invalid."""
        mock_resp = MagicMock()
        mock_resp.raise_for_status.return_value = None
        mock_resp.json.return_value = {"valid": False, "message": "Expired"}
        mock_post.return_value = mock_resp

        client = self._make_client()
        with pytest.raises(LicenseValidationError, match="Expired"):
            client.validate()

    @patch("penguin_licensing.python_client.requests.Session.post")
    def test_validate_http_error(self, mock_post):
        """validate raises LicenseValidationError on HTTP errors."""
        mock_resp = MagicMock()
        mock_resp.raise_for_status.side_effect = requests.HTTPError("403")
        mock_post.return_value = mock_resp

        client = self._make_client()
        with pytest.raises(LicenseValidationError, match="request failed"):
            client.validate()

    @patch("penguin_licensing.python_client.requests.Session.post")
    def test_validate_connection_error(self, mock_post):
        """validate raises LicenseValidationError on connection errors."""
        mock_post.side_effect = requests.ConnectionError("unreachable")

        client = self._make_client()
        with pytest.raises(LicenseValidationError, match="request failed"):
            client.validate()

    @patch("penguin_licensing.python_client.requests.Session.post")
    def test_validate_no_server_id_in_metadata(self, mock_post):
        """validate works without server_id in metadata."""
        mock_resp = MagicMock()
        mock_resp.raise_for_status.return_value = None
        mock_resp.json.return_value = {
            "valid": True,
            "features": [],
            "metadata": {},
        }
        mock_post.return_value = mock_resp

        client = self._make_client()
        result = client.validate()
        assert result["valid"] is True
        assert client.server_id is None

    @patch("penguin_licensing.python_client.requests.Session.post")
    def test_validate_no_metadata_key(self, mock_post):
        """validate works when metadata key is absent."""
        mock_resp = MagicMock()
        mock_resp.raise_for_status.return_value = None
        mock_resp.json.return_value = {"valid": True, "features": []}
        mock_post.return_value = mock_resp

        client = self._make_client()
        result = client.validate()
        assert result["valid"] is True
        assert client.server_id is None

    @patch("penguin_licensing.python_client.requests.Session.post")
    def test_validate_updates_feature_cache(self, mock_post):
        """validate populates the feature cache from response."""
        mock_resp = MagicMock()
        mock_resp.raise_for_status.return_value = None
        mock_resp.json.return_value = {
            "valid": True,
            "features": [
                {"name": "sso", "entitled": True},
                {"name": "analytics", "entitled": False},
            ],
        }
        mock_post.return_value = mock_resp

        client = self._make_client()
        client.validate()
        assert client._feature_cache == {"sso": True, "analytics": False}
        assert client._cache_timestamp is not None


class TestCheckFeature:
    """Tests for PenguinTechLicenseClient.check_feature."""

    def _make_client(self):
        return PenguinTechLicenseClient(
            license_key="PENG-1111-2222-3333-4444-ABCD", product="myapp"
        )

    def test_check_feature_from_cache(self):
        """check_feature returns cached value when cache is valid."""
        client = self._make_client()
        client._feature_cache = {"sso": True}
        client._cache_timestamp = time.time()

        assert client.check_feature("sso") is True

    def test_check_feature_cache_miss_not_in_cache(self):
        """check_feature fetches from server when feature not in cache."""
        client = self._make_client()
        client._feature_cache = {"other": True}
        client._cache_timestamp = time.time()

        with patch.object(client.session, "post") as mock_post:
            mock_resp = MagicMock()
            mock_resp.raise_for_status.return_value = None
            mock_resp.json.return_value = {
                "features": [{"entitled": True}]
            }
            mock_post.return_value = mock_resp

            result = client.check_feature("sso")
            assert result is True

    @patch("penguin_licensing.python_client.requests.Session.post")
    def test_check_feature_no_cache(self, mock_post):
        """check_feature fetches from server when no cache exists."""
        mock_resp = MagicMock()
        mock_resp.raise_for_status.return_value = None
        mock_resp.json.return_value = {
            "features": [{"entitled": True}]
        }
        mock_post.return_value = mock_resp

        client = self._make_client()
        assert client.check_feature("sso") is True

    @patch("penguin_licensing.python_client.requests.Session.post")
    def test_check_feature_no_use_cache(self, mock_post):
        """check_feature skips cache when use_cache=False."""
        mock_resp = MagicMock()
        mock_resp.raise_for_status.return_value = None
        mock_resp.json.return_value = {
            "features": [{"entitled": False}]
        }
        mock_post.return_value = mock_resp

        client = self._make_client()
        client._feature_cache = {"sso": True}
        client._cache_timestamp = time.time()

        # Even though cache says True, use_cache=False fetches from server
        result = client.check_feature("sso", use_cache=False)
        assert result is False

    @patch("penguin_licensing.python_client.requests.Session.post")
    def test_check_feature_empty_features_list(self, mock_post):
        """check_feature returns False when features list is empty."""
        mock_resp = MagicMock()
        mock_resp.raise_for_status.return_value = None
        mock_resp.json.return_value = {"features": []}
        mock_post.return_value = mock_resp

        client = self._make_client()
        assert client.check_feature("sso") is False

    @patch("penguin_licensing.python_client.requests.Session.post")
    def test_check_feature_request_error(self, mock_post):
        """check_feature returns False on request errors."""
        mock_post.side_effect = requests.ConnectionError("fail")

        client = self._make_client()
        assert client.check_feature("sso") is False

    def test_check_feature_expired_cache(self):
        """check_feature refetches when cache is expired."""
        client = self._make_client()
        client._feature_cache = {"sso": True}
        client._cache_timestamp = time.time() - 600  # expired

        with patch.object(client.session, "post") as mock_post:
            mock_resp = MagicMock()
            mock_resp.raise_for_status.return_value = None
            mock_resp.json.return_value = {
                "features": [{"entitled": False}]
            }
            mock_post.return_value = mock_resp

            result = client.check_feature("sso")
            assert result is False


class TestKeepalive:
    """Tests for PenguinTechLicenseClient.keepalive."""

    def _make_client(self):
        return PenguinTechLicenseClient(
            license_key="PENG-1111-2222-3333-4444-ABCD", product="myapp"
        )

    @patch("penguin_licensing.python_client.requests.Session.post")
    def test_keepalive_with_server_id(self, mock_post):
        """keepalive sends request when server_id already set."""
        mock_resp = MagicMock()
        mock_resp.raise_for_status.return_value = None
        mock_resp.json.return_value = {"success": True}
        mock_post.return_value = mock_resp

        client = self._make_client()
        client.server_id = "srv-abc"
        result = client.keepalive()
        assert result == {"success": True}

    @patch("penguin_licensing.python_client.requests.Session.post")
    def test_keepalive_validates_first_when_no_server_id(self, mock_post):
        """keepalive calls validate first when server_id is not set."""
        validate_resp = MagicMock()
        validate_resp.raise_for_status.return_value = None
        validate_resp.json.return_value = {
            "valid": True,
            "features": [],
            "metadata": {"server_id": "srv-xyz"},
        }

        keepalive_resp = MagicMock()
        keepalive_resp.raise_for_status.return_value = None
        keepalive_resp.json.return_value = {"success": True}

        mock_post.side_effect = [validate_resp, keepalive_resp]

        client = self._make_client()
        result = client.keepalive()
        assert result == {"success": True}

    @patch("penguin_licensing.python_client.requests.Session.post")
    def test_keepalive_validate_raises(self, mock_post):
        """keepalive raises when validate raises LicenseValidationError."""
        validate_resp = MagicMock()
        validate_resp.raise_for_status.return_value = None
        validate_resp.json.return_value = {
            "valid": False,
            "message": "expired",
        }
        mock_post.return_value = validate_resp

        client = self._make_client()
        with pytest.raises(LicenseValidationError):
            client.keepalive()

    def test_keepalive_validate_returns_invalid_without_raising(self):
        """keepalive raises when validate returns invalid dict (mocked validate)."""
        client = self._make_client()
        # Mock validate to return invalid without raising
        with patch.object(client, "validate", return_value={"valid": False}):
            with pytest.raises(LicenseValidationError, match="Failed to validate"):
                client.keepalive()

    @patch("penguin_licensing.python_client.requests.Session.post")
    def test_keepalive_with_usage_data(self, mock_post):
        """keepalive includes usage_data in payload."""
        mock_resp = MagicMock()
        mock_resp.raise_for_status.return_value = None
        mock_resp.json.return_value = {"success": True}
        mock_post.return_value = mock_resp

        client = self._make_client()
        client.server_id = "srv-abc"
        client.keepalive(usage_data={"users": 42})

        call_args = mock_post.call_args
        payload = call_args[1]["json"]
        assert payload["users"] == 42
        assert payload["product"] == "myapp"
        assert payload["server_id"] == "srv-abc"

    @patch("penguin_licensing.python_client.requests.Session.post")
    def test_keepalive_request_error(self, mock_post):
        """keepalive raises LicenseValidationError on request error."""
        mock_post.side_effect = requests.ConnectionError("fail")

        client = self._make_client()
        client.server_id = "srv-abc"
        with pytest.raises(LicenseValidationError, match="Keepalive request failed"):
            client.keepalive()


class TestGetAllFeatures:
    """Tests for PenguinTechLicenseClient.get_all_features."""

    def _make_client(self):
        return PenguinTechLicenseClient(
            license_key="PENG-1111-2222-3333-4444-ABCD", product="myapp"
        )

    def test_get_all_features_from_valid_cache(self):
        """get_all_features returns cached features when cache is valid."""
        client = self._make_client()
        client._feature_cache = {"sso": True, "analytics": False}
        client._cache_timestamp = time.time()

        result = client.get_all_features()
        assert result == {"sso": True, "analytics": False}

    @patch("penguin_licensing.python_client.requests.Session.post")
    def test_get_all_features_refreshes_when_cache_invalid(self, mock_post):
        """get_all_features calls validate when cache is expired."""
        mock_resp = MagicMock()
        mock_resp.raise_for_status.return_value = None
        mock_resp.json.return_value = {
            "valid": True,
            "features": [{"name": "sso", "entitled": True}],
            "metadata": {},
        }
        mock_post.return_value = mock_resp

        client = self._make_client()
        result = client.get_all_features()
        assert result == {"sso": True}

    @patch("penguin_licensing.python_client.requests.Session.post")
    def test_get_all_features_validation_error(self, mock_post):
        """get_all_features returns empty dict when validation fails."""
        mock_post.side_effect = requests.ConnectionError("fail")

        client = self._make_client()
        result = client.get_all_features()
        assert result == {}

    def test_get_all_features_returns_copy(self):
        """get_all_features returns a copy, not the internal dict."""
        client = self._make_client()
        client._feature_cache = {"sso": True}
        client._cache_timestamp = time.time()

        result = client.get_all_features()
        result["sso"] = False
        assert client._feature_cache["sso"] is True


class TestUpdateFeatureCache:
    """Tests for _update_feature_cache."""

    def test_update_feature_cache_basic(self):
        """_update_feature_cache populates cache from feature list."""
        client = PenguinTechLicenseClient(
            license_key="PENG-1111-2222-3333-4444-ABCD", product="myapp"
        )
        client._update_feature_cache([
            {"name": "sso", "entitled": True},
            {"name": "analytics", "entitled": False},
        ])
        assert client._feature_cache == {"sso": True, "analytics": False}
        assert client._cache_timestamp is not None

    def test_update_feature_cache_skips_missing_name(self):
        """_update_feature_cache skips entries without name."""
        client = PenguinTechLicenseClient(
            license_key="PENG-1111-2222-3333-4444-ABCD", product="myapp"
        )
        client._update_feature_cache([
            {"entitled": True},
            {"name": "sso", "entitled": True},
        ])
        assert client._feature_cache == {"sso": True}

    def test_update_feature_cache_default_entitled(self):
        """_update_feature_cache defaults entitled to False."""
        client = PenguinTechLicenseClient(
            license_key="PENG-1111-2222-3333-4444-ABCD", product="myapp"
        )
        client._update_feature_cache([{"name": "sso"}])
        assert client._feature_cache == {"sso": False}

    def test_update_feature_cache_clears_old_cache(self):
        """_update_feature_cache replaces existing cache."""
        client = PenguinTechLicenseClient(
            license_key="PENG-1111-2222-3333-4444-ABCD", product="myapp"
        )
        client._feature_cache = {"old_feature": True}
        client._update_feature_cache([{"name": "new_feature", "entitled": True}])
        assert "old_feature" not in client._feature_cache
        assert client._feature_cache == {"new_feature": True}


class TestIsCacheValid:
    """Tests for _is_cache_valid."""

    def test_cache_valid_no_timestamp(self):
        """_is_cache_valid returns False when no timestamp."""
        client = PenguinTechLicenseClient(
            license_key="PENG-1111-2222-3333-4444-ABCD", product="myapp"
        )
        assert client._is_cache_valid() is False

    def test_cache_valid_fresh(self):
        """_is_cache_valid returns True for fresh cache."""
        client = PenguinTechLicenseClient(
            license_key="PENG-1111-2222-3333-4444-ABCD", product="myapp"
        )
        client._cache_timestamp = time.time()
        assert client._is_cache_valid() is True

    def test_cache_valid_expired(self):
        """_is_cache_valid returns False for expired cache."""
        client = PenguinTechLicenseClient(
            license_key="PENG-1111-2222-3333-4444-ABCD", product="myapp"
        )
        client._cache_timestamp = time.time() - 600
        assert client._is_cache_valid() is False


class TestIsValidLicenseKey:
    """Tests for PenguinTechLicenseClient.is_valid_license_key static method."""

    def test_valid_key(self):
        assert PenguinTechLicenseClient.is_valid_license_key("PENG-1111-2222-3333-4444-ABCD") is True

    def test_invalid_empty(self):
        assert PenguinTechLicenseClient.is_valid_license_key("") is False

    def test_invalid_none(self):
        assert PenguinTechLicenseClient.is_valid_license_key(None) is False

    def test_invalid_wrong_prefix(self):
        assert PenguinTechLicenseClient.is_valid_license_key("TEST-1111-2222-3333-4444-ABCD") is False

    def test_invalid_wrong_length(self):
        assert PenguinTechLicenseClient.is_valid_license_key("PENG-1111-2222") is False

    def test_invalid_wrong_dash_count(self):
        assert PenguinTechLicenseClient.is_valid_license_key("PENG-1111-2222-3333-4444ABCDE") is False


class TestGetClient:
    """Tests for get_client module-level function."""

    def setup_method(self):
        """Reset global client before each test."""
        import penguin_licensing.python_client as mod
        mod._global_client = None

    def teardown_method(self):
        """Reset global client after each test."""
        import penguin_licensing.python_client as mod
        mod._global_client = None

    @patch.dict("os.environ", {"LICENSE_KEY": "PENG-1111-2222-3333-4444-ABCD", "PRODUCT_NAME": "myapp"})
    def test_get_client_creates_from_env(self):
        """get_client creates client from env on first call."""
        client = get_client()
        assert client is not None
        assert client.license_key == "PENG-1111-2222-3333-4444-ABCD"

    @patch.dict("os.environ", {"LICENSE_KEY": "PENG-1111-2222-3333-4444-ABCD", "PRODUCT_NAME": "myapp"})
    def test_get_client_returns_same_instance(self):
        """get_client returns same instance on repeated calls."""
        c1 = get_client()
        c2 = get_client()
        assert c1 is c2

    @patch.dict("os.environ", {}, clear=True)
    def test_get_client_returns_none_no_env(self):
        """get_client returns None when env vars not set."""
        result = get_client()
        assert result is None


class TestRequiresFeature:
    """Tests for requires_feature decorator."""

    def test_requires_feature_allows_when_entitled(self):
        """requires_feature allows function when feature is enabled."""
        mock_client = MagicMock()
        mock_client.check_feature.return_value = True

        @requires_feature("sso", client=mock_client)
        def my_func(x):
            return x * 2

        assert my_func(5) == 10
        mock_client.check_feature.assert_called_once_with("sso")

    def test_requires_feature_blocks_when_not_entitled(self):
        """requires_feature raises FeatureNotAvailableError when feature disabled."""
        mock_client = MagicMock()
        mock_client.check_feature.return_value = False

        @requires_feature("sso", client=mock_client)
        def my_func(x):
            return x * 2

        with pytest.raises(FeatureNotAvailableError):
            my_func(5)

    def test_requires_feature_raises_when_no_client(self):
        """requires_feature raises when no client available."""
        import penguin_licensing.python_client as mod
        mod._global_client = None

        with patch.dict("os.environ", {}, clear=True):
            @requires_feature("sso")
            def my_func(x):
                return x * 2

            with pytest.raises(FeatureNotAvailableError):
                my_func(5)

        mod._global_client = None

    def test_requires_feature_preserves_function_name(self):
        """requires_feature preserves the wrapped function name."""
        mock_client = MagicMock()
        mock_client.check_feature.return_value = True

        @requires_feature("sso", client=mock_client)
        def my_named_func():
            pass

        assert my_named_func.__name__ == "my_named_func"

    def test_requires_feature_uses_global_client(self):
        """requires_feature falls back to global client."""
        import penguin_licensing.python_client as mod

        mock_client = MagicMock()
        mock_client.check_feature.return_value = True
        mod._global_client = mock_client

        @requires_feature("sso")
        def my_func():
            return 42

        assert my_func() == 42
        mock_client.check_feature.assert_called_once_with("sso")

        mod._global_client = None


class TestInitializeLicensing:
    """Tests for initialize_licensing function."""

    def setup_method(self):
        import penguin_licensing.python_client as mod
        mod._global_client = None

    def teardown_method(self):
        import penguin_licensing.python_client as mod
        mod._global_client = None

    @patch("penguin_licensing.python_client.requests.Session.post")
    def test_initialize_licensing_success(self, mock_post):
        """initialize_licensing validates and sets global client."""
        mock_resp = MagicMock()
        mock_resp.raise_for_status.return_value = None
        mock_resp.json.return_value = {
            "valid": True,
            "customer": "Test Co",
            "tier": "enterprise",
            "features": [{"name": "sso", "entitled": True}],
            "metadata": {},
        }
        mock_post.return_value = mock_resp

        result = initialize_licensing(
            license_key="PENG-1111-2222-3333-4444-ABCD", product="myapp"
        )
        assert result["valid"] is True

        import penguin_licensing.python_client as mod
        assert mod._global_client is not None

    def test_initialize_licensing_missing_key(self):
        """initialize_licensing raises when license_key and env var both missing."""
        with patch.dict("os.environ", {}, clear=True):
            with pytest.raises(LicenseValidationError, match="required"):
                initialize_licensing()

    def test_initialize_licensing_missing_product(self):
        """initialize_licensing raises when product and env var both missing."""
        with patch.dict("os.environ", {"LICENSE_KEY": "PENG-1111-2222-3333-4444-ABCD"}, clear=True):
            with pytest.raises(LicenseValidationError, match="required"):
                initialize_licensing()

    @patch.dict("os.environ", {"LICENSE_KEY": "PENG-1111-2222-3333-4444-ABCD", "PRODUCT_NAME": "myapp"})
    @patch("penguin_licensing.python_client.requests.Session.post")
    def test_initialize_licensing_from_env(self, mock_post):
        """initialize_licensing reads from env vars when params not provided."""
        mock_resp = MagicMock()
        mock_resp.raise_for_status.return_value = None
        mock_resp.json.return_value = {
            "valid": True,
            "customer": "Env Co",
            "tier": "professional",
            "features": [],
            "metadata": {},
        }
        mock_post.return_value = mock_resp

        result = initialize_licensing()
        assert result["valid"] is True
        assert result["customer"] == "Env Co"

    @patch("penguin_licensing.python_client.requests.Session.post")
    def test_initialize_licensing_logs_features(self, mock_post):
        """initialize_licensing logs entitled features."""
        mock_resp = MagicMock()
        mock_resp.raise_for_status.return_value = None
        mock_resp.json.return_value = {
            "valid": True,
            "customer": "Test Co",
            "tier": "enterprise",
            "features": [
                {"name": "sso", "entitled": True},
                {"name": "analytics", "entitled": False},
            ],
            "metadata": {},
        }
        mock_post.return_value = mock_resp

        result = initialize_licensing(
            license_key="PENG-1111-2222-3333-4444-ABCD", product="myapp"
        )
        assert len(result["features"]) == 2


class TestCheckFeatureModuleLevel:
    """Tests for check_feature module-level convenience function."""

    def setup_method(self):
        import penguin_licensing.python_client as mod
        mod._global_client = None

    def teardown_method(self):
        import penguin_licensing.python_client as mod
        mod._global_client = None

    def test_check_feature_no_client(self):
        """check_feature returns False when no global client."""
        with patch.dict("os.environ", {}, clear=True):
            assert check_feature("sso") is False

    def test_check_feature_with_client(self):
        """check_feature delegates to global client."""
        import penguin_licensing.python_client as mod

        mock_client = MagicMock()
        mock_client.check_feature.return_value = True
        mod._global_client = mock_client

        assert check_feature("sso") is True
        mock_client.check_feature.assert_called_once_with("sso")


class TestSendKeepalive:
    """Tests for send_keepalive module-level convenience function."""

    def setup_method(self):
        import penguin_licensing.python_client as mod
        mod._global_client = None

    def teardown_method(self):
        import penguin_licensing.python_client as mod
        mod._global_client = None

    def test_send_keepalive_no_client(self):
        """send_keepalive returns False when no global client."""
        with patch.dict("os.environ", {}, clear=True):
            assert send_keepalive() is False

    def test_send_keepalive_success(self):
        """send_keepalive returns True on success."""
        import penguin_licensing.python_client as mod

        mock_client = MagicMock()
        mock_client.keepalive.return_value = {"success": True}
        mod._global_client = mock_client

        assert send_keepalive({"users": 10}) is True

    def test_send_keepalive_validation_error(self):
        """send_keepalive returns False on LicenseValidationError."""
        import penguin_licensing.python_client as mod

        mock_client = MagicMock()
        mock_client.keepalive.side_effect = LicenseValidationError("fail")
        mod._global_client = mock_client

        assert send_keepalive() is False
