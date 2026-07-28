"""Unit tests for GCP Secret Manager adapter."""

from __future__ import annotations

import sys
from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest

from penguin_sal.adapters.gcp_sm import GCPSecretManagerAdapter
from penguin_sal.core.exceptions import (
    AuthenticationError,
    AuthorizationError,
    BackendError,
    ConnectionError,
    SecretNotFoundError,
)
from penguin_sal.core.types import ConnectionConfig, Secret

# Get the mocks from conftest (already injected into sys.modules)
_mock_secretmanager = sys.modules["google.cloud.secretmanager"]
_mock_api_core_exceptions = sys.modules["google.api_core.exceptions"]


class TestGCPSecretManagerAdapterInit:
    """Test GCPSecretManagerAdapter initialization."""

    def test_init_requires_project_param(self) -> None:
        """Project ID is required in config params."""
        config = ConnectionConfig(scheme="gcp-sm", host="secretmanager.googleapis.com")
        with pytest.raises(ValueError, match="project"):
            GCPSecretManagerAdapter(config)

    def test_init_with_valid_project(self) -> None:
        """Adapter initializes with valid project param."""
        config = ConnectionConfig(
            scheme="gcp-sm",
            host="secretmanager.googleapis.com",
            params={"project": "my-project"},
        )
        adapter = GCPSecretManagerAdapter(config)
        assert adapter.config == config
        assert adapter._project == "projects/my-project"
        assert not adapter._connected

    def test_init_stores_config(self) -> None:
        """Initialization stores the provided configuration."""
        config = ConnectionConfig(
            scheme="gcp-sm",
            host="example.com",
            params={"project": "test-proj"},
        )
        adapter = GCPSecretManagerAdapter(config)
        assert adapter.config is config


class TestInitConnection:
    """Test _init_connection method."""

    def test_init_connection_creates_client(self) -> None:
        """_init_connection creates a SecretManagerServiceClient."""
        mock_client = MagicMock()
        _mock_secretmanager.SecretManagerServiceClient.return_value = mock_client

        config = ConnectionConfig(
            scheme="gcp-sm",
            host="secretmanager.googleapis.com",
            params={"project": "my-project"},
        )
        adapter = GCPSecretManagerAdapter(config)
        adapter._init_connection()

        assert adapter._client is mock_client
        assert adapter._connected

    def test_init_connection_missing_sdk_raises_connection_error(self) -> None:
        """ImportError when SDK not installed raises ConnectionError."""
        _mock_secretmanager.SecretManagerServiceClient.side_effect = ImportError("no module")

        config = ConnectionConfig(
            scheme="gcp-sm",
            host="secretmanager.googleapis.com",
            params={"project": "my-project"},
        )
        adapter = GCPSecretManagerAdapter(config)

        with pytest.raises(ConnectionError, match="google-cloud-secret-manager"):
            adapter._init_connection()

    def test_init_connection_client_error_raises_connection_error(self) -> None:
        """Client initialization errors raise ConnectionError."""
        _mock_secretmanager.SecretManagerServiceClient.side_effect = RuntimeError("client init failed")

        config = ConnectionConfig(
            scheme="gcp-sm",
            host="secretmanager.googleapis.com",
            params={"project": "my-project"},
        )
        adapter = GCPSecretManagerAdapter(config)

        with pytest.raises(ConnectionError, match="Failed to initialize"):
            adapter._init_connection()


class TestAuthenticate:
    """Test authenticate method."""

    def test_authenticate_success(self) -> None:
        """authenticate calls list_secrets to verify credentials."""
        mock_client = MagicMock()
        _mock_secretmanager.SecretManagerServiceClient.return_value = mock_client
        mock_client.list_secrets.return_value = []

        config = ConnectionConfig(
            scheme="gcp-sm",
            host="secretmanager.googleapis.com",
            params={"project": "my-project"},
        )
        adapter = GCPSecretManagerAdapter(config)
        adapter._init_connection()
        adapter.authenticate()

        mock_client.list_secrets.assert_called_once()
        call_args = mock_client.list_secrets.call_args
        assert call_args[1]["request"]["parent"] == "projects/my-project"
        assert call_args[1]["request"]["page_size"] == 1

    def test_authenticate_unauthenticated_raises_authentication_error(self) -> None:
        """Unauthenticated exception raises AuthenticationError."""
        mock_client = MagicMock()
        _mock_secretmanager.SecretManagerServiceClient.return_value = mock_client
        mock_client.list_secrets.side_effect = _mock_api_core_exceptions.Unauthenticated(
            "invalid credentials"
        )

        config = ConnectionConfig(
            scheme="gcp-sm",
            host="secretmanager.googleapis.com",
            params={"project": "my-project"},
        )
        adapter = GCPSecretManagerAdapter(config)
        adapter._init_connection()

        with pytest.raises(AuthenticationError):
            adapter.authenticate()

    def test_authenticate_permission_denied_raises_authorization_error(self) -> None:
        """PermissionDenied exception raises AuthorizationError."""
        mock_client = MagicMock()
        _mock_secretmanager.SecretManagerServiceClient.return_value = mock_client
        mock_client.list_secrets.side_effect = _mock_api_core_exceptions.PermissionDenied("denied")

        config = ConnectionConfig(
            scheme="gcp-sm",
            host="secretmanager.googleapis.com",
            params={"project": "my-project"},
        )
        adapter = GCPSecretManagerAdapter(config)
        adapter._init_connection()

        with pytest.raises(AuthorizationError):
            adapter.authenticate()


class TestGet:
    """Test get method."""

    def test_get_returns_secret(self) -> None:
        """get retrieves a secret and returns Secret object."""
        mock_client = MagicMock()
        _mock_secretmanager.SecretManagerServiceClient.return_value = mock_client

        mock_response = MagicMock()
        mock_response.payload.data = b'{"key": "value"}'
        mock_response.name = "projects/my-project/secrets/db-password/versions/1"
        mock_response.create_time = MagicMock(
            isoformat=lambda: "2024-01-01T00:00:00Z",
            astimezone=lambda tz: datetime(2024, 1, 1, tzinfo=timezone.utc),
        )
        mock_client.access_secret_version.return_value = mock_response

        config = ConnectionConfig(
            scheme="gcp-sm",
            host="secretmanager.googleapis.com",
            params={"project": "my-project"},
        )
        adapter = GCPSecretManagerAdapter(config)
        adapter._init_connection()

        result = adapter.get("db-password")

        assert isinstance(result, Secret)
        assert result.key == "db-password"
        assert result.value == {"key": "value"}
        assert result.version == 1

    def test_get_specific_version(self) -> None:
        """get with version parameter accesses specific version."""
        mock_client = MagicMock()
        _mock_secretmanager.SecretManagerServiceClient.return_value = mock_client

        mock_response = MagicMock()
        mock_response.payload.data = b"secret-value"
        mock_response.name = "projects/my-project/secrets/my-secret/versions/5"
        mock_response.create_time = None
        mock_client.access_secret_version.return_value = mock_response

        config = ConnectionConfig(
            scheme="gcp-sm",
            host="secretmanager.googleapis.com",
            params={"project": "my-project"},
        )
        adapter = GCPSecretManagerAdapter(config)
        adapter._init_connection()

        result = adapter.get("my-secret", version=5)

        call_args = mock_client.access_secret_version.call_args
        assert "versions/5" in call_args[1]["request"]["name"]
        assert result.version == 5

    def test_get_not_found_raises_secret_not_found_error(self) -> None:
        """NotFound exception raises SecretNotFoundError."""
        mock_client = MagicMock()
        _mock_secretmanager.SecretManagerServiceClient.return_value = mock_client
        mock_client.access_secret_version.side_effect = _mock_api_core_exceptions.NotFound(
            "not found"
        )

        config = ConnectionConfig(
            scheme="gcp-sm",
            host="secretmanager.googleapis.com",
            params={"project": "my-project"},
        )
        adapter = GCPSecretManagerAdapter(config)
        adapter._init_connection()

        with pytest.raises(SecretNotFoundError, match="my-secret"):
            adapter.get("my-secret")


class TestSet:
    """Test set method."""

    def test_set_creates_and_updates_secret(self) -> None:
        """set creates secret if not exists, then adds version."""
        mock_client = MagicMock()
        _mock_secretmanager.SecretManagerServiceClient.return_value = mock_client

        mock_client.get_secret.side_effect = Exception("not found")
        mock_response = MagicMock()
        mock_response.name = "projects/my-project/secrets/api-key/versions/1"
        mock_client.add_secret_version.return_value = mock_response

        config = ConnectionConfig(
            scheme="gcp-sm",
            host="secretmanager.googleapis.com",
            params={"project": "my-project"},
        )
        adapter = GCPSecretManagerAdapter(config)
        adapter._init_connection()

        result = adapter.set("api-key", "secret-value")

        assert result.key == "api-key"
        assert result.value == "secret-value"
        assert result.version == 1
        mock_client.create_secret.assert_called_once()
        mock_client.add_secret_version.assert_called_once()

    def test_set_updates_existing_secret(self) -> None:
        """set updates existing secret without recreating."""
        mock_client = MagicMock()
        _mock_secretmanager.SecretManagerServiceClient.return_value = mock_client

        mock_client.get_secret.return_value = MagicMock()
        mock_response = MagicMock()
        mock_response.name = "projects/my-project/secrets/api-key/versions/2"
        mock_client.add_secret_version.return_value = mock_response

        config = ConnectionConfig(
            scheme="gcp-sm",
            host="secretmanager.googleapis.com",
            params={"project": "my-project"},
        )
        adapter = GCPSecretManagerAdapter(config)
        adapter._init_connection()

        result = adapter.set("api-key", "new-value")

        assert result.version == 2
        mock_client.create_secret.assert_not_called()
        mock_client.add_secret_version.assert_called_once()

    def test_set_dict_value_json_encodes(self) -> None:
        """set with dict value JSON encodes the payload."""
        mock_client = MagicMock()
        _mock_secretmanager.SecretManagerServiceClient.return_value = mock_client
        mock_client.get_secret.side_effect = Exception("not found")

        mock_response = MagicMock()
        mock_response.name = "projects/my-project/secrets/config/versions/1"
        mock_client.add_secret_version.return_value = mock_response

        config = ConnectionConfig(
            scheme="gcp-sm",
            host="secretmanager.googleapis.com",
            params={"project": "my-project"},
        )
        adapter = GCPSecretManagerAdapter(config)
        adapter._init_connection()

        test_dict = {"username": "admin", "password": "secret"}
        adapter.set("config", test_dict)

        call_args = mock_client.add_secret_version.call_args
        payload = call_args[1]["request"]["payload"]["data"]
        assert b"username" in payload
        assert b"admin" in payload

    def test_set_permission_denied_raises_authorization_error(self) -> None:
        """PermissionDenied on set raises AuthorizationError."""
        mock_client = MagicMock()
        _mock_secretmanager.SecretManagerServiceClient.return_value = mock_client
        # Make get_secret fail so create_secret will be attempted
        mock_client.get_secret.side_effect = Exception("not found")
        mock_client.create_secret.side_effect = _mock_api_core_exceptions.PermissionDenied(
            "denied"
        )

        config = ConnectionConfig(
            scheme="gcp-sm",
            host="secretmanager.googleapis.com",
            params={"project": "my-project"},
        )
        adapter = GCPSecretManagerAdapter(config)
        adapter._init_connection()

        with pytest.raises(AuthorizationError):
            adapter.set("api-key", "value")


class TestDelete:
    """Test delete method."""

    def test_delete_success(self) -> None:
        """delete removes a secret and returns True."""
        mock_client = MagicMock()
        _mock_secretmanager.SecretManagerServiceClient.return_value = mock_client

        config = ConnectionConfig(
            scheme="gcp-sm",
            host="secretmanager.googleapis.com",
            params={"project": "my-project"},
        )
        adapter = GCPSecretManagerAdapter(config)
        adapter._init_connection()

        result = adapter.delete("api-key")

        assert result is True
        mock_client.delete_secret.assert_called_once()

    def test_delete_not_found_returns_false(self) -> None:
        """delete returns False if secret doesn't exist."""
        mock_client = MagicMock()
        _mock_secretmanager.SecretManagerServiceClient.return_value = mock_client
        mock_client.delete_secret.side_effect = _mock_api_core_exceptions.NotFound("not found")

        config = ConnectionConfig(
            scheme="gcp-sm",
            host="secretmanager.googleapis.com",
            params={"project": "my-project"},
        )
        adapter = GCPSecretManagerAdapter(config)
        adapter._init_connection()

        result = adapter.delete("nonexistent")

        assert result is False


class TestList:
    """Test list method."""

    def test_list_returns_secret_names(self) -> None:
        """list returns all secret names in project."""
        mock_client = MagicMock()
        _mock_secretmanager.SecretManagerServiceClient.return_value = mock_client

        mock_secret1 = MagicMock()
        mock_secret1.name = "projects/my-project/secrets/db-password"
        mock_secret2 = MagicMock()
        mock_secret2.name = "projects/my-project/secrets/api-key"
        mock_client.list_secrets.return_value = [mock_secret1, mock_secret2]

        config = ConnectionConfig(
            scheme="gcp-sm",
            host="secretmanager.googleapis.com",
            params={"project": "my-project"},
        )
        adapter = GCPSecretManagerAdapter(config)
        adapter._init_connection()

        result = adapter.list()

        assert len(result.keys) == 2
        assert "db-password" in result.keys
        assert "api-key" in result.keys

    def test_list_with_prefix_filters(self) -> None:
        """list with prefix applies GCP filter."""
        mock_client = MagicMock()
        _mock_secretmanager.SecretManagerServiceClient.return_value = mock_client

        mock_secret = MagicMock()
        mock_secret.name = "projects/my-project/secrets/db-password"
        mock_client.list_secrets.return_value = [mock_secret]

        config = ConnectionConfig(
            scheme="gcp-sm",
            host="secretmanager.googleapis.com",
            params={"project": "my-project"},
        )
        adapter = GCPSecretManagerAdapter(config)
        adapter._init_connection()

        adapter.list(prefix="db-")

        call_args = mock_client.list_secrets.call_args
        assert "filter" in call_args[1]["request"]
        assert "db-*" in call_args[1]["request"]["filter"]

    def test_list_with_limit(self) -> None:
        """list with limit restricts returned keys."""
        mock_client = MagicMock()
        _mock_secretmanager.SecretManagerServiceClient.return_value = mock_client

        secrets = [MagicMock(name=f"projects/my-project/secrets/secret{i}") for i in range(5)]
        mock_client.list_secrets.return_value = secrets

        config = ConnectionConfig(
            scheme="gcp-sm",
            host="secretmanager.googleapis.com",
            params={"project": "my-project"},
        )
        adapter = GCPSecretManagerAdapter(config)
        adapter._init_connection()

        result = adapter.list(limit=3)

        assert len(result.keys) == 3


class TestExists:
    """Test exists method."""

    def test_exists_returns_true_when_secret_exists(self) -> None:
        """exists returns True if secret found."""
        mock_client = MagicMock()
        _mock_secretmanager.SecretManagerServiceClient.return_value = mock_client
        mock_client.get_secret.return_value = MagicMock()

        config = ConnectionConfig(
            scheme="gcp-sm",
            host="secretmanager.googleapis.com",
            params={"project": "my-project"},
        )
        adapter = GCPSecretManagerAdapter(config)
        adapter._init_connection()

        result = adapter.exists("api-key")

        assert result is True

    def test_exists_returns_false_when_not_found(self) -> None:
        """exists returns False if secret not found."""
        mock_client = MagicMock()
        _mock_secretmanager.SecretManagerServiceClient.return_value = mock_client
        mock_client.get_secret.side_effect = _mock_api_core_exceptions.NotFound("not found")

        config = ConnectionConfig(
            scheme="gcp-sm",
            host="secretmanager.googleapis.com",
            params={"project": "my-project"},
        )
        adapter = GCPSecretManagerAdapter(config)
        adapter._init_connection()

        result = adapter.exists("nonexistent")

        assert result is False

    def test_exists_returns_false_on_other_errors(self) -> None:
        """exists returns False on unexpected errors."""
        mock_client = MagicMock()
        _mock_secretmanager.SecretManagerServiceClient.return_value = mock_client
        mock_client.get_secret.side_effect = RuntimeError("unexpected error")

        config = ConnectionConfig(
            scheme="gcp-sm",
            host="secretmanager.googleapis.com",
            params={"project": "my-project"},
        )
        adapter = GCPSecretManagerAdapter(config)
        adapter._init_connection()

        result = adapter.exists("api-key")

        assert result is False


class TestHealthCheck:
    """Test health_check method."""

    def test_health_check_success(self) -> None:
        """health_check returns True when backend is reachable."""
        mock_client = MagicMock()
        _mock_secretmanager.SecretManagerServiceClient.return_value = mock_client
        mock_client.list_secrets.return_value = []

        config = ConnectionConfig(
            scheme="gcp-sm",
            host="secretmanager.googleapis.com",
            params={"project": "my-project"},
        )
        adapter = GCPSecretManagerAdapter(config)
        adapter._init_connection()

        result = adapter.health_check()

        assert result is True

    def test_health_check_returns_true_for_auth_errors(self) -> None:
        """health_check returns True for auth errors (service is reachable)."""
        mock_client = MagicMock()
        _mock_secretmanager.SecretManagerServiceClient.return_value = mock_client
        mock_client.list_secrets.side_effect = _mock_api_core_exceptions.Unauthenticated(
            "auth error"
        )

        config = ConnectionConfig(
            scheme="gcp-sm",
            host="secretmanager.googleapis.com",
            params={"project": "my-project"},
        )
        adapter = GCPSecretManagerAdapter(config)
        adapter._init_connection()

        result = adapter.health_check()

        assert result is True

    def test_health_check_returns_false_on_connection_error(self) -> None:
        """health_check returns False on connection errors."""
        mock_client = MagicMock()
        _mock_secretmanager.SecretManagerServiceClient.return_value = mock_client
        mock_client.list_secrets.side_effect = RuntimeError("connection failed")

        config = ConnectionConfig(
            scheme="gcp-sm",
            host="secretmanager.googleapis.com",
            params={"project": "my-project"},
        )
        adapter = GCPSecretManagerAdapter(config)
        adapter._init_connection()

        result = adapter.health_check()

        assert result is False


class TestClose:
    """Test close method."""

    def test_close_closes_client_transport(self) -> None:
        """close calls transport.close() on the client."""
        mock_client = MagicMock()
        mock_transport = MagicMock()
        mock_client.transport = mock_transport
        _mock_secretmanager.SecretManagerServiceClient.return_value = mock_client

        config = ConnectionConfig(
            scheme="gcp-sm",
            host="secretmanager.googleapis.com",
            params={"project": "my-project"},
        )
        adapter = GCPSecretManagerAdapter(config)
        adapter._init_connection()
        adapter.close()

        mock_transport.close.assert_called_once()
        assert not adapter._connected

    def test_close_handles_errors_gracefully(self) -> None:
        """close doesn't raise even if transport.close() fails."""
        mock_client = MagicMock()
        mock_transport = MagicMock()
        mock_transport.close.side_effect = RuntimeError("error")
        mock_client.transport = mock_transport
        _mock_secretmanager.SecretManagerServiceClient.return_value = mock_client

        config = ConnectionConfig(
            scheme="gcp-sm",
            host="secretmanager.googleapis.com",
            params={"project": "my-project"},
        )
        adapter = GCPSecretManagerAdapter(config)
        adapter._init_connection()

        adapter.close()
        assert not adapter._connected


class TestContextManager:
    """Test context manager support."""

    def test_with_statement_closes_on_exit(self) -> None:
        """Using adapter as context manager calls close()."""
        mock_client = MagicMock()
        mock_transport = MagicMock()
        mock_client.transport = mock_transport
        _mock_secretmanager.SecretManagerServiceClient.return_value = mock_client

        config = ConnectionConfig(
            scheme="gcp-sm",
            host="secretmanager.googleapis.com",
            params={"project": "my-project"},
        )

        with GCPSecretManagerAdapter(config) as adapter:
            adapter._init_connection()
            assert adapter._connected

        mock_transport.close.assert_called_once()
        assert not adapter._connected
