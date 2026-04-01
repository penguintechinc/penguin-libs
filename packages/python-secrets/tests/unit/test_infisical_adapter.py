"""Tests for InfisicalAdapter."""

from __future__ import annotations

import sys
from datetime import datetime
from unittest.mock import MagicMock, Mock, patch

import pytest

# Mock infisicalsdk before importing the adapter
sys.modules["infisicalsdk"] = MagicMock()

from penguin_sal.adapters.infisical import InfisicalAdapter
from penguin_sal.core.exceptions import (
    AdapterNotInstalledError,
    AuthenticationError,
    BackendError,
    ConnectionError,
    SecretNotFoundError,
)
from penguin_sal.core.types import ConnectionConfig, Secret, SecretList


class TestInfisicalAdapterInit:
    """Test InfisicalAdapter initialization."""

    def test_init_stores_config(self) -> None:
        config = ConnectionConfig(
            scheme="infisical",
            host="infisical.example.com",
            port=443,
            params={"project_id": "proj-123"},
        )
        adapter = InfisicalAdapter(config)
        assert adapter.config is config
        assert adapter._connected is False

    def test_init_client_is_none(self) -> None:
        config = ConnectionConfig(
            scheme="infisical",
            host="infisical.example.com",
            params={"project_id": "proj-123"},
        )
        adapter = InfisicalAdapter(config)
        assert adapter._client is None


class TestInfisicalAdapterConnection:
    """Test connection initialization."""

    @patch("infisicalsdk.InfisicalClient")
    def test_init_connection_creates_client(self, mock_client_class: Mock) -> None:
        mock_client = MagicMock()
        mock_client_class.return_value = mock_client

        config = ConnectionConfig(
            scheme="infisical",
            host="infisical.example.com",
            port=443,
            params={"project_id": "proj-123"},
        )
        adapter = InfisicalAdapter(config)
        adapter._init_connection()

        mock_client_class.assert_called_once_with(
            site_url="https://infisical.example.com"
        )
        assert adapter._client is mock_client
        assert adapter._connected is True

    @patch("infisicalsdk.InfisicalClient")
    def test_init_connection_custom_port(self, mock_client_class: Mock) -> None:
        mock_client = MagicMock()
        mock_client_class.return_value = mock_client

        config = ConnectionConfig(
            scheme="infisical",
            host="infisical.example.com",
            port=8080,
            params={"project_id": "proj-123"},
        )
        adapter = InfisicalAdapter(config)
        adapter._init_connection()

        mock_client_class.assert_called_once_with(
            site_url="https://infisical.example.com:8080"
        )

    @patch("infisicalsdk.InfisicalClient")
    def test_init_connection_client_failure(self, mock_client_class: Mock) -> None:
        mock_client_class.side_effect = RuntimeError("Connection failed")

        config = ConnectionConfig(
            scheme="infisical",
            host="infisical.example.com",
            params={"project_id": "proj-123"},
        )
        adapter = InfisicalAdapter(config)

        with pytest.raises(ConnectionError, match="Failed to initialize"):
            adapter._init_connection()

    def test_init_connection_missing_sdk(self) -> None:
        config = ConnectionConfig(
            scheme="infisical",
            host="infisical.example.com",
            params={"project_id": "proj-123"},
        )
        adapter = InfisicalAdapter(config)

        # Mock the import to raise ImportError
        with patch.dict(sys.modules, {"infisicalsdk": None}):
            with pytest.raises(AdapterNotInstalledError, match="infisical"):
                adapter._init_connection()


class TestInfisicalAdapterAuthentication:
    """Test authentication methods."""

    @patch("infisicalsdk.InfisicalClient")
    def test_authenticate_with_password(self, mock_client_class: Mock) -> None:
        mock_client = MagicMock()
        mock_client_class.return_value = mock_client

        config = ConnectionConfig(
            scheme="infisical",
            host="infisical.example.com",
            password="my-token-123",
            params={"project_id": "proj-123"},
        )
        adapter = InfisicalAdapter(config)
        adapter._init_connection()
        adapter.authenticate()

        mock_client.auth.assert_called_once_with(token="my-token-123")

    @patch("infisicalsdk.InfisicalClient")
    def test_authenticate_with_params_token(self, mock_client_class: Mock) -> None:
        mock_client = MagicMock()
        mock_client_class.return_value = mock_client

        config = ConnectionConfig(
            scheme="infisical",
            host="infisical.example.com",
            params={"project_id": "proj-123", "token": "param-token-456"},
        )
        adapter = InfisicalAdapter(config)
        adapter._init_connection()
        adapter.authenticate()

        mock_client.auth.assert_called_once_with(token="param-token-456")

    @patch("infisicalsdk.InfisicalClient")
    def test_authenticate_no_token(self, mock_client_class: Mock) -> None:
        mock_client = MagicMock()
        mock_client_class.return_value = mock_client

        config = ConnectionConfig(
            scheme="infisical",
            host="infisical.example.com",
            params={"project_id": "proj-123"},
        )
        adapter = InfisicalAdapter(config)
        adapter._init_connection()

        with pytest.raises(AuthenticationError, match="No authentication token"):
            adapter.authenticate()

    @patch("infisicalsdk.InfisicalClient")
    def test_authenticate_auth_failure(self, mock_client_class: Mock) -> None:
        mock_client = MagicMock()
        mock_client.auth.side_effect = Exception("Invalid token")
        mock_client_class.return_value = mock_client

        config = ConnectionConfig(
            scheme="infisical",
            host="infisical.example.com",
            password="bad-token",
            params={"project_id": "proj-123"},
        )
        adapter = InfisicalAdapter(config)
        adapter._init_connection()

        with pytest.raises(AuthenticationError, match="authentication failed"):
            adapter.authenticate()


class TestInfisicalAdapterGet:
    """Test get() method."""

    @patch("infisicalsdk.InfisicalClient")
    def test_get_returns_secret(self, mock_client_class: Mock) -> None:
        mock_client = MagicMock()
        mock_client.getSecret.return_value = {
            "secretName": "db-password",
            "secretValue": "secret123",
            "createdAt": "2025-01-15T10:00:00Z",
            "updatedAt": "2025-01-15T10:00:00Z",
        }
        mock_client_class.return_value = mock_client

        config = ConnectionConfig(
            scheme="infisical",
            host="infisical.example.com",
            password="token",
            params={"project_id": "proj-123", "environment": "prod"},
        )
        adapter = InfisicalAdapter(config)
        adapter._init_connection()
        adapter._client = mock_client  # Skip auth

        result = adapter.get("db-password")

        assert isinstance(result, Secret)
        assert result.key == "db-password"
        assert result.value == "secret123"
        mock_client.getSecret.assert_called_once_with(
            secretName="db-password",
            projectId="proj-123",
            environment="prod",
        )

    @patch("infisicalsdk.InfisicalClient")
    def test_get_not_found(self, mock_client_class: Mock) -> None:
        mock_client = MagicMock()
        mock_client.getSecret.return_value = None
        mock_client_class.return_value = mock_client

        config = ConnectionConfig(
            scheme="infisical",
            host="infisical.example.com",
            password="token",
            params={"project_id": "proj-123"},
        )
        adapter = InfisicalAdapter(config)
        adapter._init_connection()
        adapter._client = mock_client

        with pytest.raises(SecretNotFoundError, match="db-password"):
            adapter.get("db-password")

    @patch("infisicalsdk.InfisicalClient")
    def test_get_missing_project_id(self, mock_client_class: Mock) -> None:
        mock_client_class.return_value = MagicMock()

        config = ConnectionConfig(
            scheme="infisical",
            host="infisical.example.com",
            password="token",
            params={},  # Missing project_id
        )
        adapter = InfisicalAdapter(config)
        adapter._init_connection()
        adapter._client = MagicMock()

        with pytest.raises(BackendError, match="project_id is required"):
            adapter.get("key")

    @patch("infisicalsdk.InfisicalClient")
    def test_get_backend_error(self, mock_client_class: Mock) -> None:
        mock_client = MagicMock()
        mock_client.getSecret.side_effect = RuntimeError("API error")
        mock_client_class.return_value = mock_client

        config = ConnectionConfig(
            scheme="infisical",
            host="infisical.example.com",
            password="token",
            params={"project_id": "proj-123"},
        )
        adapter = InfisicalAdapter(config)
        adapter._init_connection()
        adapter._client = mock_client

        with pytest.raises(BackendError, match="Failed to get secret"):
            adapter.get("key")


class TestInfisicalAdapterSet:
    """Test set() method."""

    @patch("infisicalsdk.InfisicalClient")
    def test_set_creates_secret(self, mock_client_class: Mock) -> None:
        mock_client = MagicMock()
        mock_client.createSecret.return_value = {
            "secretName": "api-key",
            "secretValue": "key123",
            "createdAt": "2025-01-15T10:00:00Z",
            "updatedAt": "2025-01-15T10:00:00Z",
        }
        mock_client_class.return_value = mock_client

        config = ConnectionConfig(
            scheme="infisical",
            host="infisical.example.com",
            password="token",
            params={"project_id": "proj-123", "environment": "staging"},
        )
        adapter = InfisicalAdapter(config)
        adapter._init_connection()
        adapter._client = mock_client

        result = adapter.set("api-key", "key123")

        assert isinstance(result, Secret)
        assert result.key == "api-key"
        assert result.value == "key123"
        mock_client.createSecret.assert_called_once_with(
            secretName="api-key",
            secretValue="key123",
            projectId="proj-123",
            environment="staging",
        )

    @patch("infisicalsdk.InfisicalClient")
    def test_set_bytes_value(self, mock_client_class: Mock) -> None:
        mock_client = MagicMock()
        mock_client.createSecret.return_value = {
            "secretName": "binary",
            "secretValue": "binary-data",
            "createdAt": "2025-01-15T10:00:00Z",
            "updatedAt": "2025-01-15T10:00:00Z",
        }
        mock_client_class.return_value = mock_client

        config = ConnectionConfig(
            scheme="infisical",
            host="infisical.example.com",
            password="token",
            params={"project_id": "proj-123"},
        )
        adapter = InfisicalAdapter(config)
        adapter._init_connection()
        adapter._client = mock_client

        result = adapter.set("binary", b"binary-data")

        assert result.value == "binary-data"
        mock_client.createSecret.assert_called_once()
        call_args = mock_client.createSecret.call_args
        assert call_args[1]["secretValue"] == "binary-data"

    @patch("infisicalsdk.InfisicalClient")
    def test_set_dict_value(self, mock_client_class: Mock) -> None:
        mock_client = MagicMock()
        mock_client.createSecret.return_value = {
            "secretName": "config",
            "secretValue": '{"host": "db"}',
            "createdAt": "2025-01-15T10:00:00Z",
            "updatedAt": "2025-01-15T10:00:00Z",
        }
        mock_client_class.return_value = mock_client

        config = ConnectionConfig(
            scheme="infisical",
            host="infisical.example.com",
            password="token",
            params={"project_id": "proj-123"},
        )
        adapter = InfisicalAdapter(config)
        adapter._init_connection()
        adapter._client = mock_client

        result = adapter.set("config", {"host": "db"})

        assert "host" in result.value
        call_args = mock_client.createSecret.call_args
        assert '"host"' in call_args[1]["secretValue"]

    @patch("infisicalsdk.InfisicalClient")
    def test_set_backend_error(self, mock_client_class: Mock) -> None:
        mock_client = MagicMock()
        mock_client.createSecret.side_effect = RuntimeError("API error")
        mock_client_class.return_value = mock_client

        config = ConnectionConfig(
            scheme="infisical",
            host="infisical.example.com",
            password="token",
            params={"project_id": "proj-123"},
        )
        adapter = InfisicalAdapter(config)
        adapter._init_connection()
        adapter._client = mock_client

        with pytest.raises(BackendError, match="Failed to set secret"):
            adapter.set("key", "value")


class TestInfisicalAdapterDelete:
    """Test delete() method."""

    @patch("infisicalsdk.InfisicalClient")
    def test_delete_existing_secret(self, mock_client_class: Mock) -> None:
        mock_client = MagicMock()
        mock_client.getSecret.return_value = {"secretName": "key", "secretValue": "val"}
        mock_client_class.return_value = mock_client

        config = ConnectionConfig(
            scheme="infisical",
            host="infisical.example.com",
            password="token",
            params={"project_id": "proj-123"},
        )
        adapter = InfisicalAdapter(config)
        adapter._init_connection()
        adapter._client = mock_client

        result = adapter.delete("key")

        assert result is True
        mock_client.deleteSecret.assert_called_once_with(
            secretName="key",
            projectId="proj-123",
            environment="dev",
        )

    @patch("infisicalsdk.InfisicalClient")
    def test_delete_nonexistent_secret(self, mock_client_class: Mock) -> None:
        mock_client = MagicMock()
        mock_client.getSecret.return_value = None
        mock_client_class.return_value = mock_client

        config = ConnectionConfig(
            scheme="infisical",
            host="infisical.example.com",
            password="token",
            params={"project_id": "proj-123"},
        )
        adapter = InfisicalAdapter(config)
        adapter._init_connection()
        adapter._client = mock_client

        result = adapter.delete("nonexistent")

        assert result is False
        mock_client.deleteSecret.assert_not_called()

    @patch("infisicalsdk.InfisicalClient")
    def test_delete_backend_error(self, mock_client_class: Mock) -> None:
        mock_client = MagicMock()
        mock_client.getSecret.return_value = {"secretName": "key"}
        mock_client.deleteSecret.side_effect = RuntimeError("API error")
        mock_client_class.return_value = mock_client

        config = ConnectionConfig(
            scheme="infisical",
            host="infisical.example.com",
            password="token",
            params={"project_id": "proj-123"},
        )
        adapter = InfisicalAdapter(config)
        adapter._init_connection()
        adapter._client = mock_client

        with pytest.raises(BackendError, match="Failed to delete secret"):
            adapter.delete("key")


class TestInfisicalAdapterList:
    """Test list() method."""

    @patch("infisicalsdk.InfisicalClient")
    def test_list_returns_all_keys(self, mock_client_class: Mock) -> None:
        mock_client = MagicMock()
        mock_client.listSecrets.return_value = [
            {"secretName": "db-password"},
            {"secretName": "api-key"},
            {"secretName": "db-host"},
        ]
        mock_client_class.return_value = mock_client

        config = ConnectionConfig(
            scheme="infisical",
            host="infisical.example.com",
            password="token",
            params={"project_id": "proj-123"},
        )
        adapter = InfisicalAdapter(config)
        adapter._init_connection()
        adapter._client = mock_client

        result = adapter.list()

        assert isinstance(result, SecretList)
        assert len(result.keys) == 3
        assert "db-password" in result.keys
        assert "api-key" in result.keys

    @patch("infisicalsdk.InfisicalClient")
    def test_list_with_prefix_filter(self, mock_client_class: Mock) -> None:
        mock_client = MagicMock()
        mock_client.listSecrets.return_value = [
            {"secretName": "db-password"},
            {"secretName": "api-key"},
            {"secretName": "db-host"},
        ]
        mock_client_class.return_value = mock_client

        config = ConnectionConfig(
            scheme="infisical",
            host="infisical.example.com",
            password="token",
            params={"project_id": "proj-123"},
        )
        adapter = InfisicalAdapter(config)
        adapter._init_connection()
        adapter._client = mock_client

        result = adapter.list(prefix="db-")

        assert len(result.keys) == 2
        assert "db-password" in result.keys
        assert "db-host" in result.keys
        assert "api-key" not in result.keys

    @patch("infisicalsdk.InfisicalClient")
    def test_list_with_limit(self, mock_client_class: Mock) -> None:
        mock_client = MagicMock()
        mock_client.listSecrets.return_value = [
            {"secretName": "key1"},
            {"secretName": "key2"},
            {"secretName": "key3"},
        ]
        mock_client_class.return_value = mock_client

        config = ConnectionConfig(
            scheme="infisical",
            host="infisical.example.com",
            password="token",
            params={"project_id": "proj-123"},
        )
        adapter = InfisicalAdapter(config)
        adapter._init_connection()
        adapter._client = mock_client

        result = adapter.list(limit=2)

        assert len(result.keys) == 2
        assert result.keys == ["key1", "key2"]

    @patch("infisicalsdk.InfisicalClient")
    def test_list_backend_error(self, mock_client_class: Mock) -> None:
        mock_client = MagicMock()
        mock_client.listSecrets.side_effect = RuntimeError("API error")
        mock_client_class.return_value = mock_client

        config = ConnectionConfig(
            scheme="infisical",
            host="infisical.example.com",
            password="token",
            params={"project_id": "proj-123"},
        )
        adapter = InfisicalAdapter(config)
        adapter._init_connection()
        adapter._client = mock_client

        with pytest.raises(BackendError, match="Failed to list secrets"):
            adapter.list()


class TestInfisicalAdapterExists:
    """Test exists() method."""

    @patch("infisicalsdk.InfisicalClient")
    def test_exists_returns_true(self, mock_client_class: Mock) -> None:
        mock_client = MagicMock()
        mock_client.getSecret.return_value = {"secretName": "key", "secretValue": "val"}
        mock_client_class.return_value = mock_client

        config = ConnectionConfig(
            scheme="infisical",
            host="infisical.example.com",
            password="token",
            params={"project_id": "proj-123"},
        )
        adapter = InfisicalAdapter(config)
        adapter._init_connection()
        adapter._client = mock_client

        assert adapter.exists("key") is True

    @patch("infisicalsdk.InfisicalClient")
    def test_exists_returns_false(self, mock_client_class: Mock) -> None:
        mock_client = MagicMock()
        mock_client.getSecret.return_value = None
        mock_client_class.return_value = mock_client

        config = ConnectionConfig(
            scheme="infisical",
            host="infisical.example.com",
            password="token",
            params={"project_id": "proj-123"},
        )
        adapter = InfisicalAdapter(config)
        adapter._init_connection()
        adapter._client = mock_client

        assert adapter.exists("nonexistent") is False


class TestInfisicalAdapterHealthCheck:
    """Test health_check() method."""

    @patch("infisicalsdk.InfisicalClient")
    def test_health_check_success(self, mock_client_class: Mock) -> None:
        mock_client = MagicMock()
        mock_client.listSecrets.return_value = [{"secretName": "key"}]
        mock_client_class.return_value = mock_client

        config = ConnectionConfig(
            scheme="infisical",
            host="infisical.example.com",
            password="token",
            params={"project_id": "proj-123"},
        )
        adapter = InfisicalAdapter(config)
        adapter._init_connection()
        adapter._client = mock_client

        assert adapter.health_check() is True

    @patch("infisicalsdk.InfisicalClient")
    def test_health_check_no_project_id(self, mock_client_class: Mock) -> None:
        mock_client_class.return_value = MagicMock()

        config = ConnectionConfig(
            scheme="infisical",
            host="infisical.example.com",
            password="token",
            params={},
        )
        adapter = InfisicalAdapter(config)
        adapter._init_connection()
        adapter._client = MagicMock()

        assert adapter.health_check() is False

    @patch("infisicalsdk.InfisicalClient")
    def test_health_check_backend_unavailable(self, mock_client_class: Mock) -> None:
        mock_client = MagicMock()
        mock_client.listSecrets.side_effect = RuntimeError("Connection refused")
        mock_client_class.return_value = mock_client

        config = ConnectionConfig(
            scheme="infisical",
            host="infisical.example.com",
            password="token",
            params={"project_id": "proj-123"},
        )
        adapter = InfisicalAdapter(config)
        adapter._init_connection()
        adapter._client = mock_client

        assert adapter.health_check() is False


class TestInfisicalAdapterClose:
    """Test close() method."""

    @patch("infisicalsdk.InfisicalClient")
    def test_close_clears_client(self, mock_client_class: Mock) -> None:
        mock_client = MagicMock()
        mock_client_class.return_value = mock_client

        config = ConnectionConfig(
            scheme="infisical",
            host="infisical.example.com",
            params={"project_id": "proj-123"},
        )
        adapter = InfisicalAdapter(config)
        adapter._init_connection()
        assert adapter._client is not None
        assert adapter._connected is True

        adapter.close()

        assert adapter._client is None
        assert adapter._connected is False


class TestInfisicalAdapterContextManager:
    """Test context manager protocol."""

    @patch("infisicalsdk.InfisicalClient")
    def test_with_statement(self, mock_client_class: Mock) -> None:
        mock_client = MagicMock()
        mock_client.listSecrets.return_value = []
        mock_client_class.return_value = mock_client

        config = ConnectionConfig(
            scheme="infisical",
            host="infisical.example.com",
            password="token",
            params={"project_id": "proj-123"},
        )

        with InfisicalAdapter(config) as adapter:
            adapter._init_connection()
            assert adapter._client is not None

        assert adapter._client is None


class TestInfisicalAdapterTimestampParsing:
    """Test timestamp parsing."""

    def test_parse_iso_timestamp_with_z(self) -> None:
        ts = "2025-01-15T10:30:45Z"
        result = InfisicalAdapter._parse_timestamp(ts)
        assert isinstance(result, datetime)
        assert result.year == 2025
        assert result.month == 1
        assert result.day == 15

    def test_parse_iso_timestamp_with_offset(self) -> None:
        ts = "2025-01-15T10:30:45+00:00"
        result = InfisicalAdapter._parse_timestamp(ts)
        assert isinstance(result, datetime)

    def test_parse_invalid_timestamp(self) -> None:
        result = InfisicalAdapter._parse_timestamp("not-a-date")
        assert result is None

    def test_parse_none_timestamp(self) -> None:
        result = InfisicalAdapter._parse_timestamp(None)
        assert result is None
