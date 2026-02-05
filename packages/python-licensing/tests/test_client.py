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
