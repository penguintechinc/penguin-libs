"""Unit tests for Passbolt adapter."""

from __future__ import annotations

import sys
from datetime import datetime
from unittest.mock import MagicMock, Mock, patch

import pytest

from penguin_sal.adapters.passbolt import PassboltAdapter
from penguin_sal.core.exceptions import (
    AuthenticationError,
    BackendError,
    ConnectionError,
    SecretNotFoundError,
)
from penguin_sal.core.types import ConnectionConfig


@pytest.fixture
def config() -> ConnectionConfig:
    """Create a test configuration."""
    return ConnectionConfig(
        scheme="passbolt",
        host="https://passbolt.example.com",
        username="user@example.com",
        password="passphrase",
        params={
            "private_key_path": "/path/to/key.asc",
            "fingerprint": "ABCD1234",
        },
    )


@pytest.fixture(autouse=True)
def mock_passbolt_module() -> Mock:
    """Mock the passbolt_python_api module before tests run."""
    mock_module = MagicMock()
    sys.modules["passbolt_python_api"] = mock_module
    yield mock_module
    # Clean up after tests
    sys.modules.pop("passbolt_python_api", None)


@pytest.fixture
def mock_api() -> Mock:
    """Create a mock Passbolt API client."""
    return MagicMock()


class TestPassboltAdapterInit:
    """Test adapter initialization."""

    def test_init_stores_config(self, config: ConnectionConfig) -> None:
        """Test that config is stored."""
        adapter = PassboltAdapter(config)
        assert adapter.config is config

    def test_init_connected_is_false(
        self, config: ConnectionConfig
    ) -> None:
        """Test that _connected starts as False."""
        adapter = PassboltAdapter(config)
        assert adapter._connected is False

    def test_init_client_is_none(
        self, config: ConnectionConfig
    ) -> None:
        """Test that _client starts as None."""
        adapter = PassboltAdapter(config)
        assert adapter._client is None


class TestInitConnection:
    """Test _init_connection method."""

    @patch("passbolt_python_api.PassboltAPI", create=True)
    def test_init_connection_success(
        self,
        mock_passbolt_class: Mock,
        config: ConnectionConfig,
        mock_api: Mock,
    ) -> None:
        """Test successful connection initialization."""
        mock_passbolt_class.return_value = mock_api
        adapter = PassboltAdapter(config)

        adapter._init_connection()

        assert adapter._client is mock_api
        assert adapter._connected is True
        mock_passbolt_class.assert_called_once()

    def test_init_connection_missing_sdk(
        self, config: ConnectionConfig
    ) -> None:
        """Test error when passbolt SDK is not installed."""
        # Remove the mock module to simulate missing SDK
        sys.modules.pop("passbolt_python_api", None)
        adapter = PassboltAdapter(config)
        with pytest.raises(
            ImportError, match="passbolt-python-api required"
        ):
            adapter._init_connection()
        # Re-add the mock for other tests
        mock_module = MagicMock()
        sys.modules["passbolt_python_api"] = mock_module

    @patch("passbolt_python_api.PassboltAPI", create=True)
    def test_init_connection_failure(
        self,
        mock_passbolt_class: Mock,
        config: ConnectionConfig,
    ) -> None:
        """Test error handling during connection."""
        mock_passbolt_class.side_effect = RuntimeError("Connection failed")
        adapter = PassboltAdapter(config)

        with pytest.raises(
            ConnectionError, match="Failed to initialize Passbolt client"
        ):
            adapter._init_connection()

    @patch("passbolt_python_api.PassboltAPI", create=True)
    def test_init_connection_adds_https(
        self,
        mock_passbolt_class: Mock,
        mock_api: Mock,
    ) -> None:
        """Test that HTTPS is added to URL if not present."""
        mock_passbolt_class.return_value = mock_api
        config = ConnectionConfig(
            scheme="passbolt",
            host="passbolt.example.com",
            username="user@example.com",
            password="pass",
            params={"private_key_path": "/path/to/key.asc"},
        )
        adapter = PassboltAdapter(config)
        adapter._init_connection()

        call_args = mock_passbolt_class.call_args
        assert call_args
        assert "https" in call_args[1]["url"]


class TestAuthenticate:
    """Test authenticate method."""

    @patch("passbolt_python_api.PassboltAPI", create=True)
    def test_authenticate_success(
        self,
        mock_passbolt_class: Mock,
        config: ConnectionConfig,
        mock_api: Mock,
    ) -> None:
        """Test successful authentication."""
        mock_passbolt_class.return_value = mock_api
        mock_api.login.return_value = None
        adapter = PassboltAdapter(config)

        adapter.authenticate()

        mock_api.login.assert_called_once()

    @patch("passbolt_python_api.PassboltAPI", create=True)
    def test_authenticate_failure(
        self,
        mock_passbolt_class: Mock,
        config: ConnectionConfig,
        mock_api: Mock,
    ) -> None:
        """Test authentication failure."""
        mock_passbolt_class.return_value = mock_api
        mock_api.login.side_effect = Exception("Auth failed")
        adapter = PassboltAdapter(config)
        adapter._client = mock_api

        with pytest.raises(
            AuthenticationError, match="Passbolt authentication failed"
        ):
            adapter.authenticate()

    @patch("passbolt_python_api.PassboltAPI", create=True)
    def test_authenticate_initializes_connection(
        self,
        mock_passbolt_class: Mock,
        config: ConnectionConfig,
        mock_api: Mock,
    ) -> None:
        """Test that authenticate initializes connection if needed."""
        mock_passbolt_class.return_value = mock_api
        adapter = PassboltAdapter(config)
        assert adapter._client is None

        adapter.authenticate()

        assert adapter._client is mock_api


class TestGet:
    """Test get method."""

    @patch("passbolt_python_api.PassboltAPI", create=True)
    def test_get_success(
        self,
        mock_passbolt_class: Mock,
        config: ConnectionConfig,
        mock_api: Mock,
    ) -> None:
        """Test successful secret retrieval."""
        mock_passbolt_class.return_value = mock_api
        mock_api.get_resources.return_value = [
            {
                "id": "resource-123",
                "name": "my-secret",
                "created": "2025-01-01T00:00:00Z",
                "modified": "2025-01-02T00:00:00Z",
            }
        ]
        mock_api.get_secret.return_value = {"password": "secret-value"}

        adapter = PassboltAdapter(config)
        adapter._client = mock_api
        result = adapter.get("my-secret")

        assert result.key == "my-secret"
        assert result.value == "secret-value"
        assert result.version == 1
        assert isinstance(result.created_at, datetime)
        assert isinstance(result.updated_at, datetime)

    @patch("passbolt_python_api.PassboltAPI", create=True)
    def test_get_not_found(
        self,
        mock_passbolt_class: Mock,
        config: ConnectionConfig,
        mock_api: Mock,
    ) -> None:
        """Test get raises error when secret not found."""
        mock_passbolt_class.return_value = mock_api
        mock_api.get_resources.return_value = []

        adapter = PassboltAdapter(config)
        adapter._client = mock_api

        with pytest.raises(
            SecretNotFoundError, match="my-secret"
        ):
            adapter.get("my-secret")

    @patch("passbolt_python_api.PassboltAPI", create=True)
    def test_get_api_error(
        self,
        mock_passbolt_class: Mock,
        config: ConnectionConfig,
        mock_api: Mock,
    ) -> None:
        """Test get wraps API errors."""
        mock_passbolt_class.return_value = mock_api
        mock_api.get_resources.side_effect = RuntimeError("API error")

        adapter = PassboltAdapter(config)
        adapter._client = mock_api

        with pytest.raises(BackendError, match="Failed to retrieve secret"):
            adapter.get("my-secret")


class TestSet:
    """Test set method."""

    @patch("passbolt_python_api.PassboltAPI", create=True)
    def test_set_create_new(
        self,
        mock_passbolt_class: Mock,
        config: ConnectionConfig,
        mock_api: Mock,
    ) -> None:
        """Test creating a new resource."""
        mock_passbolt_class.return_value = mock_api
        mock_api.get_resources.return_value = []
        mock_api.create_resource.return_value = {
            "id": "resource-456",
            "name": "new-secret",
        }

        adapter = PassboltAdapter(config)
        adapter._client = mock_api
        result = adapter.set("new-secret", "new-value")

        assert result.key == "new-secret"
        assert result.value == "new-value"
        mock_api.create_resource.assert_called_once()

    @patch("passbolt_python_api.PassboltAPI", create=True)
    def test_set_update_existing(
        self,
        mock_passbolt_class: Mock,
        config: ConnectionConfig,
        mock_api: Mock,
    ) -> None:
        """Test updating an existing resource."""
        mock_passbolt_class.return_value = mock_api
        mock_api.get_resources.return_value = [
            {"id": "resource-123", "name": "existing-secret"}
        ]

        adapter = PassboltAdapter(config)
        adapter._client = mock_api
        result = adapter.set("existing-secret", "updated-value")

        assert result.key == "existing-secret"
        assert result.value == "updated-value"
        mock_api.update_secret.assert_called_once()

    @patch("passbolt_python_api.PassboltAPI", create=True)
    def test_set_bytes_value(
        self,
        mock_passbolt_class: Mock,
        config: ConnectionConfig,
        mock_api: Mock,
    ) -> None:
        """Test setting with bytes value."""
        mock_passbolt_class.return_value = mock_api
        mock_api.get_resources.return_value = []

        adapter = PassboltAdapter(config)
        adapter._client = mock_api
        result = adapter.set("secret", b"byte-value")

        assert result.value == "byte-value"

    @patch("passbolt_python_api.PassboltAPI", create=True)
    def test_set_dict_value(
        self,
        mock_passbolt_class: Mock,
        config: ConnectionConfig,
        mock_api: Mock,
    ) -> None:
        """Test setting with dict value."""
        mock_passbolt_class.return_value = mock_api
        mock_api.get_resources.return_value = []

        adapter = PassboltAdapter(config)
        adapter._client = mock_api
        result = adapter.set("secret", {"key": "value"})

        assert isinstance(result.value, str)
        assert "key" in result.value

    @patch("passbolt_python_api.PassboltAPI", create=True)
    def test_set_with_metadata(
        self,
        mock_passbolt_class: Mock,
        config: ConnectionConfig,
        mock_api: Mock,
    ) -> None:
        """Test setting with metadata."""
        mock_passbolt_class.return_value = mock_api
        mock_api.get_resources.return_value = []

        adapter = PassboltAdapter(config)
        adapter._client = mock_api
        metadata = {"username": "user", "uri": "https://example.com"}
        result = adapter.set("secret", "value", metadata=metadata)

        assert result.metadata == metadata

    @patch("passbolt_python_api.PassboltAPI", create=True)
    def test_set_api_error(
        self,
        mock_passbolt_class: Mock,
        config: ConnectionConfig,
        mock_api: Mock,
    ) -> None:
        """Test set wraps API errors."""
        mock_passbolt_class.return_value = mock_api
        mock_api.get_resources.side_effect = RuntimeError("API error")

        adapter = PassboltAdapter(config)
        adapter._client = mock_api

        with pytest.raises(BackendError, match="Failed to set secret"):
            adapter.set("secret", "value")


class TestDelete:
    """Test delete method."""

    @patch("passbolt_python_api.PassboltAPI", create=True)
    def test_delete_success(
        self,
        mock_passbolt_class: Mock,
        config: ConnectionConfig,
        mock_api: Mock,
    ) -> None:
        """Test successful deletion."""
        mock_passbolt_class.return_value = mock_api
        mock_api.get_resources.return_value = [
            {"id": "resource-123", "name": "secret-to-delete"}
        ]

        adapter = PassboltAdapter(config)
        adapter._client = mock_api
        result = adapter.delete("secret-to-delete")

        assert result is True
        mock_api.delete_resource.assert_called_once_with("resource-123")

    @patch("passbolt_python_api.PassboltAPI", create=True)
    def test_delete_not_found(
        self,
        mock_passbolt_class: Mock,
        config: ConnectionConfig,
        mock_api: Mock,
    ) -> None:
        """Test delete returns False when resource not found."""
        mock_passbolt_class.return_value = mock_api
        mock_api.get_resources.return_value = []

        adapter = PassboltAdapter(config)
        adapter._client = mock_api
        result = adapter.delete("nonexistent")

        assert result is False

    @patch("passbolt_python_api.PassboltAPI", create=True)
    def test_delete_api_error(
        self,
        mock_passbolt_class: Mock,
        config: ConnectionConfig,
        mock_api: Mock,
    ) -> None:
        """Test delete wraps API errors."""
        mock_passbolt_class.return_value = mock_api
        mock_api.get_resources.side_effect = RuntimeError("API error")

        adapter = PassboltAdapter(config)
        adapter._client = mock_api

        with pytest.raises(BackendError, match="Failed to delete secret"):
            adapter.delete("secret")


class TestList:
    """Test list method."""

    @patch("passbolt_python_api.PassboltAPI", create=True)
    def test_list_all(
        self,
        mock_passbolt_class: Mock,
        config: ConnectionConfig,
        mock_api: Mock,
    ) -> None:
        """Test listing all resources."""
        mock_passbolt_class.return_value = mock_api
        mock_api.get_resources.return_value = [
            {"id": "1", "name": "secret1"},
            {"id": "2", "name": "secret2"},
            {"id": "3", "name": "secret3"},
        ]

        adapter = PassboltAdapter(config)
        adapter._client = mock_api
        result = adapter.list()

        assert len(result.keys) == 3
        assert "secret1" in result.keys
        assert "secret2" in result.keys
        assert "secret3" in result.keys

    @patch("passbolt_python_api.PassboltAPI", create=True)
    def test_list_with_prefix(
        self,
        mock_passbolt_class: Mock,
        config: ConnectionConfig,
        mock_api: Mock,
    ) -> None:
        """Test listing with prefix filter."""
        mock_passbolt_class.return_value = mock_api
        mock_api.get_resources.return_value = [
            {"id": "1", "name": "prod-secret1"},
            {"id": "2", "name": "prod-secret2"},
            {"id": "3", "name": "dev-secret1"},
        ]

        adapter = PassboltAdapter(config)
        adapter._client = mock_api
        result = adapter.list(prefix="prod-")

        assert len(result.keys) == 2
        assert "prod-secret1" in result.keys
        assert "prod-secret2" in result.keys

    @patch("passbolt_python_api.PassboltAPI", create=True)
    def test_list_with_limit(
        self,
        mock_passbolt_class: Mock,
        config: ConnectionConfig,
        mock_api: Mock,
    ) -> None:
        """Test listing with limit."""
        mock_passbolt_class.return_value = mock_api
        mock_api.get_resources.return_value = [
            {"id": "1", "name": "secret1"},
            {"id": "2", "name": "secret2"},
            {"id": "3", "name": "secret3"},
        ]

        adapter = PassboltAdapter(config)
        adapter._client = mock_api
        result = adapter.list(limit=2)

        assert len(result.keys) == 2

    @patch("passbolt_python_api.PassboltAPI", create=True)
    def test_list_api_error(
        self,
        mock_passbolt_class: Mock,
        config: ConnectionConfig,
        mock_api: Mock,
    ) -> None:
        """Test list wraps API errors."""
        mock_passbolt_class.return_value = mock_api
        mock_api.get_resources.side_effect = RuntimeError("API error")

        adapter = PassboltAdapter(config)
        adapter._client = mock_api

        with pytest.raises(BackendError, match="Failed to list secrets"):
            adapter.list()


class TestExists:
    """Test exists method."""

    @patch("passbolt_python_api.PassboltAPI", create=True)
    def test_exists_true(
        self,
        mock_passbolt_class: Mock,
        config: ConnectionConfig,
        mock_api: Mock,
    ) -> None:
        """Test exists returns True for existing resource."""
        mock_passbolt_class.return_value = mock_api
        mock_api.get_resources.return_value = [
            {"id": "1", "name": "secret"}
        ]

        adapter = PassboltAdapter(config)
        adapter._client = mock_api
        assert adapter.exists("secret") is True

    @patch("passbolt_python_api.PassboltAPI", create=True)
    def test_exists_false(
        self,
        mock_passbolt_class: Mock,
        config: ConnectionConfig,
        mock_api: Mock,
    ) -> None:
        """Test exists returns False for nonexistent resource."""
        mock_passbolt_class.return_value = mock_api
        mock_api.get_resources.return_value = []

        adapter = PassboltAdapter(config)
        adapter._client = mock_api
        assert adapter.exists("nonexistent") is False

    @patch("passbolt_python_api.PassboltAPI", create=True)
    def test_exists_handles_error(
        self,
        mock_passbolt_class: Mock,
        config: ConnectionConfig,
        mock_api: Mock,
    ) -> None:
        """Test exists returns False on error."""
        mock_passbolt_class.return_value = mock_api
        mock_api.get_resources.side_effect = RuntimeError("API error")

        adapter = PassboltAdapter(config)
        adapter._client = mock_api
        assert adapter.exists("secret") is False


class TestHealthCheck:
    """Test health_check method."""

    @patch("passbolt_python_api.PassboltAPI", create=True)
    def test_health_check_success(
        self,
        mock_passbolt_class: Mock,
        config: ConnectionConfig,
        mock_api: Mock,
    ) -> None:
        """Test health check returns True when server is healthy."""
        mock_passbolt_class.return_value = mock_api
        mock_api.get_server.return_value = {"name": "Passbolt"}

        adapter = PassboltAdapter(config)
        adapter._client = mock_api
        assert adapter.health_check() is True

    @patch("passbolt_python_api.PassboltAPI", create=True)
    def test_health_check_failure(
        self,
        mock_passbolt_class: Mock,
        config: ConnectionConfig,
        mock_api: Mock,
    ) -> None:
        """Test health check returns False on error."""
        mock_passbolt_class.return_value = mock_api
        mock_api.get_server.side_effect = RuntimeError("Connection failed")

        adapter = PassboltAdapter(config)
        adapter._client = mock_api
        assert adapter.health_check() is False

    @patch("passbolt_python_api.PassboltAPI", create=True)
    def test_health_check_initializes_connection(
        self,
        mock_passbolt_class: Mock,
        config: ConnectionConfig,
        mock_api: Mock,
    ) -> None:
        """Test health check initializes connection if needed."""
        mock_passbolt_class.return_value = mock_api
        mock_api.get_server.return_value = {}

        adapter = PassboltAdapter(config)
        assert adapter._client is None

        result = adapter.health_check()

        assert result is True
        assert adapter._client is mock_api


class TestClose:
    """Test close method."""

    @patch("passbolt_python_api.PassboltAPI", create=True)
    def test_close_success(
        self,
        mock_passbolt_class: Mock,
        config: ConnectionConfig,
        mock_api: Mock,
    ) -> None:
        """Test closing the connection."""
        mock_passbolt_class.return_value = mock_api
        adapter = PassboltAdapter(config)
        adapter._client = mock_api
        adapter._connected = True

        adapter.close()

        mock_api.logout.assert_called_once()
        assert adapter._connected is False
        assert adapter._client is None

    def test_close_with_no_client(
        self, config: ConnectionConfig
    ) -> None:
        """Test close handles missing client gracefully."""
        adapter = PassboltAdapter(config)
        adapter._connected = True

        adapter.close()

        assert adapter._connected is False

    @patch("passbolt_python_api.PassboltAPI", create=True)
    def test_close_handles_error(
        self,
        mock_passbolt_class: Mock,
        config: ConnectionConfig,
        mock_api: Mock,
    ) -> None:
        """Test close handles logout errors gracefully."""
        mock_passbolt_class.return_value = mock_api
        mock_api.logout.side_effect = RuntimeError("Logout failed")

        adapter = PassboltAdapter(config)
        adapter._client = mock_api
        adapter._connected = True

        adapter.close()

        assert adapter._connected is False


class TestContextManager:
    """Test context manager protocol."""

    @patch("passbolt_python_api.PassboltAPI", create=True)
    def test_with_statement(
        self,
        mock_passbolt_class: Mock,
        config: ConnectionConfig,
        mock_api: Mock,
    ) -> None:
        """Test using adapter as context manager."""
        mock_passbolt_class.return_value = mock_api

        with PassboltAdapter(config) as adapter:
            adapter._client = mock_api
            assert isinstance(adapter, PassboltAdapter)

        mock_api.logout.assert_called_once()

    @patch("passbolt_python_api.PassboltAPI", create=True)
    def test_with_statement_exception(
        self,
        mock_passbolt_class: Mock,
        config: ConnectionConfig,
        mock_api: Mock,
    ) -> None:
        """Test context manager closes on exception."""
        mock_passbolt_class.return_value = mock_api

        try:
            with PassboltAdapter(config) as adapter:
                adapter._client = mock_api
                raise ValueError("test error")
        except ValueError:
            pass

        mock_api.logout.assert_called_once()
