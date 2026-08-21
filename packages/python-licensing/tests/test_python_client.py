"""Tests for the PenguinTech License Server Python client (python_client module)."""

import time
from datetime import UTC
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

    @patch.dict(
        "os.environ", {"LICENSE_KEY": "PENG-1111-2222-3333-4444-ABCD", "PRODUCT_NAME": "myapp"}
    )
    def test_from_env_success(self):
        """from_env creates client from environment variables."""
        client = PenguinTechLicenseClient.from_env()
        assert client is not None
        assert client.license_key == "PENG-1111-2222-3333-4444-ABCD"
        assert client.product == "myapp"

    @patch.dict(
        "os.environ",
        {
            "LICENSE_KEY": "PENG-1111-2222-3333-4444-ABCD",
            "PRODUCT_NAME": "myapp",
            "LICENSE_SERVER_URL": "https://custom.io",
        },
    )
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

    @patch.dict(
        "os.environ", {"LICENSE_KEY": "PENG-1111-2222-3333-4444-ABCD", "PRODUCT_NAME": "myapp"}
    )
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
        """Validate returns data on success."""
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
        """Validate raises LicenseValidationError when license is invalid."""
        mock_resp = MagicMock()
        mock_resp.raise_for_status.return_value = None
        mock_resp.json.return_value = {"valid": False, "message": "Expired"}
        mock_post.return_value = mock_resp

        client = self._make_client()
        with pytest.raises(LicenseValidationError, match="Expired"):
            client.validate()

    @patch("penguin_licensing.python_client.requests.Session.post")
    def test_validate_http_error(self, mock_post):
        """Validate raises LicenseValidationError on HTTP errors."""
        mock_resp = MagicMock()
        mock_resp.raise_for_status.side_effect = requests.HTTPError("403")
        mock_post.return_value = mock_resp

        client = self._make_client()
        with pytest.raises(LicenseValidationError, match="request failed"):
            client.validate()

    @patch("penguin_licensing.python_client.requests.Session.post")
    def test_validate_connection_error(self, mock_post):
        """Validate raises LicenseValidationError on connection errors."""
        mock_post.side_effect = requests.ConnectionError("unreachable")

        client = self._make_client()
        with pytest.raises(LicenseValidationError, match="request failed"):
            client.validate()

    @patch("penguin_licensing.python_client.requests.Session.post")
    def test_validate_no_server_id_in_metadata(self, mock_post):
        """Validate works without server_id in metadata."""
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
        """Validate works when metadata key is absent."""
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
        """Validate populates the feature cache from response."""
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
            mock_resp.json.return_value = {"features": [{"entitled": True}]}
            mock_post.return_value = mock_resp

            result = client.check_feature("sso")
            assert result is True

    @patch("penguin_licensing.python_client.requests.Session.post")
    def test_check_feature_no_cache(self, mock_post):
        """check_feature fetches from server when no cache exists."""
        mock_resp = MagicMock()
        mock_resp.raise_for_status.return_value = None
        mock_resp.json.return_value = {"features": [{"entitled": True}]}
        mock_post.return_value = mock_resp

        client = self._make_client()
        assert client.check_feature("sso") is True

    @patch("penguin_licensing.python_client.requests.Session.post")
    def test_check_feature_no_use_cache(self, mock_post):
        """check_feature skips cache when use_cache=False."""
        mock_resp = MagicMock()
        mock_resp.raise_for_status.return_value = None
        mock_resp.json.return_value = {"features": [{"entitled": False}]}
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
            mock_resp.json.return_value = {"features": [{"entitled": False}]}
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
        """Keepalive sends request when server_id already set."""
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
        """Keepalive calls validate first when server_id is not set."""
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
        """Keepalive raises when validate raises LicenseValidationError."""
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
        """Keepalive raises when validate returns invalid dict (mocked validate)."""
        client = self._make_client()
        # Mock validate to return invalid without raising
        with patch.object(client, "validate", return_value={"valid": False}):
            with pytest.raises(LicenseValidationError, match="Failed to validate"):
                client.keepalive()

    @patch("penguin_licensing.python_client.requests.Session.post")
    def test_keepalive_with_usage_data(self, mock_post):
        """Keepalive includes usage_data in payload."""
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
        """Keepalive raises LicenseValidationError on request error."""
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
        client._update_feature_cache(
            [
                {"name": "sso", "entitled": True},
                {"name": "analytics", "entitled": False},
            ]
        )
        assert client._feature_cache == {"sso": True, "analytics": False}
        assert client._cache_timestamp is not None

    def test_update_feature_cache_skips_missing_name(self):
        """_update_feature_cache skips entries without name."""
        client = PenguinTechLicenseClient(
            license_key="PENG-1111-2222-3333-4444-ABCD", product="myapp"
        )
        client._update_feature_cache(
            [
                {"entitled": True},
                {"name": "sso", "entitled": True},
            ]
        )
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
        assert (
            PenguinTechLicenseClient.is_valid_license_key("PENG-1111-2222-3333-4444-ABCD") is True
        )

    def test_invalid_empty(self):
        assert PenguinTechLicenseClient.is_valid_license_key("") is False

    def test_invalid_none(self):
        assert PenguinTechLicenseClient.is_valid_license_key(None) is False

    def test_invalid_wrong_prefix(self):
        assert (
            PenguinTechLicenseClient.is_valid_license_key("TEST-1111-2222-3333-4444-ABCD") is False
        )

    def test_invalid_wrong_length(self):
        assert PenguinTechLicenseClient.is_valid_license_key("PENG-1111-2222") is False

    def test_invalid_wrong_dash_count(self):
        assert (
            PenguinTechLicenseClient.is_valid_license_key("PENG-1111-2222-3333-4444ABCDE") is False
        )


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

    @patch.dict(
        "os.environ", {"LICENSE_KEY": "PENG-1111-2222-3333-4444-ABCD", "PRODUCT_NAME": "myapp"}
    )
    def test_get_client_creates_from_env(self):
        """get_client creates client from env on first call."""
        client = get_client()
        assert client is not None
        assert client.license_key == "PENG-1111-2222-3333-4444-ABCD"

    @patch.dict(
        "os.environ", {"LICENSE_KEY": "PENG-1111-2222-3333-4444-ABCD", "PRODUCT_NAME": "myapp"}
    )
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

        result = initialize_licensing(license_key="PENG-1111-2222-3333-4444-ABCD", product="myapp")
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

    @patch.dict(
        "os.environ", {"LICENSE_KEY": "PENG-1111-2222-3333-4444-ABCD", "PRODUCT_NAME": "myapp"}
    )
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

        result = initialize_licensing(license_key="PENG-1111-2222-3333-4444-ABCD", product="myapp")
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


def _valid_validate_response(tier="professional"):
    """Build a mock 200 /api/v2/validate response for the given tier."""
    response = MagicMock()
    response.status_code = 200
    response.raise_for_status.return_value = None
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


def _server_error_response(status_code=503):
    """Build a mock 5xx response that raises on raise_for_status()."""
    response = MagicMock()
    response.status_code = status_code
    response.raise_for_status.side_effect = requests.HTTPError(f"{status_code} Server Error")
    return response


class TestPenguinTechLicenseClientForceRefresh:
    """Tests for the force_refresh escape hatch on validate()."""

    @patch("penguin_licensing.python_client.requests.Session.post")
    def test_cache_hit_skips_server(self, mock_post):
        """A second validate() inside the TTL is served from cache."""
        mock_post.return_value = _valid_validate_response()

        client = PenguinTechLicenseClient("PENG-TEST-1234", "elder")
        client.validate()
        client.validate()

        assert mock_post.call_count == 1

    @patch("penguin_licensing.python_client.requests.Session.post")
    def test_force_refresh_recontacts_server(self, mock_post):
        """force_refresh=True bypasses a warm cache and re-hits the server."""
        mock_post.return_value = _valid_validate_response()

        client = PenguinTechLicenseClient("PENG-TEST-1234", "elder")
        client.validate()
        assert mock_post.call_count == 1

        client.validate(force_refresh=True)
        assert mock_post.call_count == 2


class TestPenguinTechLicenseClientFailClosed:
    """Tests for fail-closed behavior in PenguinTechLicenseClient."""

    @patch("penguin_licensing.python_client.requests.Session.post")
    def test_definitive_rejection_revocation(self, mock_post):
        """403 rejection raises LicenseValidationError (revocation)."""
        rejection_response = MagicMock()
        rejection_response.status_code = 403

        mock_post.return_value = rejection_response

        client = PenguinTechLicenseClient("PENG-TEST-1234", "elder")

        with pytest.raises(LicenseValidationError, match="revoked"):
            client.validate()

    @patch("penguin_licensing.python_client.requests.Session.post")
    def test_server_error_returns_cached(self, mock_post):
        """A forced refresh hitting a 5xx serves the last known-good value."""
        mock_post.side_effect = [
            _valid_validate_response("professional"),
            _server_error_response(503),
        ]

        client = PenguinTechLicenseClient("PENG-TEST-1234", "elder")

        result1 = client.validate()
        assert result1["tier"] == "professional"
        assert mock_post.call_count == 1

        # force_refresh so the server is genuinely re-contacted, not short-circuited
        # by the top-of-function cache check.
        result2 = client.validate(force_refresh=True)
        assert mock_post.call_count == 2
        assert result2["tier"] == "professional"
        assert result2 is client._cached_validation

    @patch("penguin_licensing.python_client.requests.Session.post")
    def test_transport_error_returns_cached(self, mock_post):
        """A forced refresh hitting a transport error serves the cached value."""
        mock_post.side_effect = [
            _valid_validate_response("professional"),
            requests.RequestException("Network error"),
        ]

        client = PenguinTechLicenseClient("PENG-TEST-1234", "elder")

        result1 = client.validate()
        assert result1["tier"] == "professional"
        assert mock_post.call_count == 1

        result2 = client.validate(force_refresh=True)
        assert mock_post.call_count == 2
        assert result2["tier"] == "professional"
        assert result2 is client._cached_validation

    @patch("penguin_licensing.python_client.requests.Session.post")
    def test_no_cache_transport_error_raises(self, mock_post):
        """With no cached value a transport error is fatal, never permissive."""
        mock_post.side_effect = requests.RequestException("Network error")

        client = PenguinTechLicenseClient("PENG-TEST-1234", "elder")

        with pytest.raises(LicenseValidationError, match="request failed"):
            client.validate()

        assert mock_post.call_count == 1
        assert client._cached_validation is None

    @patch("penguin_licensing.python_client.requests.Session.post")
    def test_revocation_drops_cached_entitlement(self, mock_post):
        """401/403/404 drops the cache instead of serving the stale tier."""
        rejection_response = MagicMock()
        rejection_response.status_code = 401

        mock_post.side_effect = [
            _valid_validate_response("professional"),
            rejection_response,
            rejection_response,
        ]

        client = PenguinTechLicenseClient("PENG-TEST-1234", "elder")

        assert client.validate()["tier"] == "professional"

        with pytest.raises(LicenseValidationError, match="revoked"):
            client.validate(force_refresh=True)

        assert mock_post.call_count == 2
        assert client._cached_validation is None
        assert client._validation_cache_expiry is None

        # The dropped cache must not resurface on an ordinary (non-forced) call.
        with pytest.raises(LicenseValidationError, match="revoked"):
            client.validate()

        assert mock_post.call_count == 3

    @patch("penguin_licensing.python_client.requests.Session.post")
    def test_expiry_within_grace_period(self, mock_post):
        """License expiry within 72h grace period still valid."""
        from datetime import datetime, timedelta

        expired_at = datetime.now(UTC) - timedelta(hours=24)
        expiry_response = MagicMock()
        expiry_response.status_code = 200
        expiry_response.json.return_value = {
            "valid": True,
            "customer": "Test Co",
            "product": "elder",
            "license_version": "2.0",
            "license_key": "PENG-TEST-1234",
            "expires_at": expired_at.isoformat().replace("+00:00", "Z"),
            "issued_at": "2024-01-01T00:00:00Z",
            "tier": "enterprise",
            "features": [],
            "limits": {},
            "metadata": {},
        }

        mock_post.return_value = expiry_response

        client = PenguinTechLicenseClient("PENG-TEST-1234", "elder")
        result = client.validate()

        # Should still be valid (within grace)
        assert result["valid"] is True
        assert result["tier"] == "enterprise"

    @patch("penguin_licensing.python_client.requests.Session.post")
    def test_expiry_beyond_grace_period(self, mock_post):
        """License expiry beyond 72h grace period rejected."""
        from datetime import datetime, timedelta

        expired_at = datetime.now(UTC) - timedelta(hours=75)
        expiry_response = MagicMock()
        expiry_response.status_code = 200
        expiry_response.json.return_value = {
            "valid": True,
            "customer": "Test Co",
            "product": "elder",
            "license_version": "2.0",
            "license_key": "PENG-TEST-1234",
            "expires_at": expired_at.isoformat().replace("+00:00", "Z"),
            "issued_at": "2024-01-01T00:00:00Z",
            "tier": "enterprise",
            "features": [],
            "limits": {},
            "metadata": {},
        }

        mock_post.return_value = expiry_response

        client = PenguinTechLicenseClient("PENG-TEST-1234", "elder")

        with pytest.raises(LicenseValidationError, match="grace"):
            client.validate()


class TestPenguinTechLicenseClientTLS:
    """TLS scheme enforcement on the license server URL."""

    def test_http_rejected_for_remote_host(self):
        """Plaintext HTTP to a remote host is refused at construction time."""
        with pytest.raises(ValueError, match="HTTPS"):
            PenguinTechLicenseClient(
                "PENG-TEST-1234", "elder", base_url="http://license.example.com"
            )

    def test_http_allowed_for_localhost(self):
        """HTTP is allowed for localhost (development stub)."""
        client = PenguinTechLicenseClient(
            "PENG-TEST-1234", "elder", base_url="http://localhost:8080"
        )
        assert client.base_url == "http://localhost:8080"

    def test_http_allowed_for_loopback_ip(self):
        """HTTP is allowed for 127.0.0.1 (development stub)."""
        client = PenguinTechLicenseClient(
            "PENG-TEST-1234", "elder", base_url="http://127.0.0.1:8080"
        )
        assert client.base_url == "http://127.0.0.1:8080"

    def test_https_accepted(self):
        """HTTPS is always accepted."""
        client = PenguinTechLicenseClient(
            "PENG-TEST-1234", "elder", base_url="https://license.example.com"
        )
        assert client.base_url == "https://license.example.com"

    def test_default_base_url_is_https(self):
        """The default license server URL passes enforcement."""
        client = PenguinTechLicenseClient("PENG-TEST-1234", "elder")
        assert client.base_url.startswith("https://")

    @patch.dict(
        "os.environ",
        {
            "LICENSE_KEY": "PENG-1111-2222-3333-4444-ABCD",
            "PRODUCT_NAME": "myapp",
            "LICENSE_SERVER_URL": "http://license.example.com",
        },
    )
    def test_from_env_rejects_plaintext_url(self):
        """An http LICENSE_SERVER_URL is refused rather than silently used."""
        with pytest.raises(ValueError, match="HTTPS"):
            PenguinTechLicenseClient.from_env()

    def test_both_clients_share_one_enforcement_helper(self):
        """Both client implementations delegate to the same URL helper."""
        from penguin_licensing.client import LicenseClient
        from penguin_licensing.urls import require_https_url

        bad_url = "http://license.example.com"

        with pytest.raises(ValueError) as python_client_exc:
            PenguinTechLicenseClient("PENG-TEST-1234", "elder", base_url=bad_url)
        with pytest.raises(ValueError) as client_exc:
            LicenseClient(license_key="PENG-TEST-1234", base_url=bad_url)
        with pytest.raises(ValueError) as helper_exc:
            require_https_url(bad_url)

        assert str(python_client_exc.value) == str(helper_exc.value)
        assert str(client_exc.value) == str(helper_exc.value)
