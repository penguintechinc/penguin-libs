"""Tests for DopplerAdapter."""

from __future__ import annotations

import sys
from datetime import datetime
from typing import Any
from unittest.mock import MagicMock, Mock, patch

import pytest

from penguin_sal.adapters.doppler import DopplerAdapter
from penguin_sal.core.exceptions import (
    AuthenticationError,
    BackendError,
    ConnectionError,
    SecretNotFoundError,
)
from penguin_sal.core.types import ConnectionConfig, Secret, SecretList


@pytest.fixture
def mock_doppler_sdk() -> Any:
    """Mock the dopplersdk module via sys.modules injection."""
    mock = MagicMock()
    sys.modules["dopplersdk"] = mock
    yield mock
    # Cleanup
    if "dopplersdk" in sys.modules:
        del sys.modules["dopplersdk"]


@pytest.fixture
def config_with_token() -> ConnectionConfig:
    """Create a ConnectionConfig with Doppler token in password."""
    return ConnectionConfig(
        scheme="doppler",
        host="api.doppler.com",
        password="service_token_123",
        params={
            "project": "my-project",
            "config": "prod",
        },
    )


@pytest.fixture
def config_with_token_in_params() -> ConnectionConfig:
    """Create a ConnectionConfig with Doppler token in params."""
    return ConnectionConfig(
        scheme="doppler",
        host="api.doppler.com",
        params={
            "token": "service_token_456",
            "project": "my-project",
            "config": "staging",
        },
    )


@pytest.fixture
def config_minimal() -> ConnectionConfig:
    """Create a minimal ConnectionConfig."""
    return ConnectionConfig(
        scheme="doppler",
        host="api.doppler.com",
        password="service_token_789",
        params={"project": "my-project"},
    )


class TestDopplerAdapterInit:
    """Test DopplerAdapter initialization."""

    def test_init_stores_config(self, config_with_token: ConnectionConfig) -> None:
        adapter = DopplerAdapter(config_with_token)
        assert adapter.config is config_with_token
        assert adapter._connected is False

    def test_init_sets_client_to_none(self, config_with_token: ConnectionConfig) -> None:
        adapter = DopplerAdapter(config_with_token)
        assert adapter._client is None


class TestDopplerAdapterInitConnection:
    """Test _init_connection method."""

    def test_init_connection_with_password_token(
        self, mock_doppler_sdk: Any, config_with_token: ConnectionConfig
    ) -> None:
        mock_client = MagicMock()
        mock_doppler_sdk.Doppler.return_value = mock_client

        adapter = DopplerAdapter(config_with_token)
        adapter._init_connection()

        assert adapter._connected is True
        assert adapter._client is mock_client
        assert adapter._project == "my-project"
        assert adapter._config_name == "prod"
        mock_doppler_sdk.Doppler.assert_called_once_with(token="service_token_123")

    def test_init_connection_with_params_token(
        self, mock_doppler_sdk: Any, config_with_token_in_params: ConnectionConfig
    ) -> None:
        mock_client = MagicMock()
        mock_doppler_sdk.Doppler.return_value = mock_client

        adapter = DopplerAdapter(config_with_token_in_params)
        adapter._init_connection()

        assert adapter._connected is True
        mock_doppler_sdk.Doppler.assert_called_once_with(token="service_token_456")

    def test_init_connection_default_config_name(
        self, mock_doppler_sdk: Any, config_minimal: ConnectionConfig
    ) -> None:
        mock_client = MagicMock()
        mock_doppler_sdk.Doppler.return_value = mock_client

        adapter = DopplerAdapter(config_minimal)
        adapter._init_connection()

        assert adapter._config_name == "dev"

    def test_init_connection_missing_token(
        self, mock_doppler_sdk: Any
    ) -> None:
        config = ConnectionConfig(
            scheme="doppler", host="api.doppler.com", params={"project": "my-project"}
        )

        adapter = DopplerAdapter(config)

        with pytest.raises(ValueError, match="token required"):
            adapter._init_connection()

    def test_init_connection_missing_project(
        self, mock_doppler_sdk: Any
    ) -> None:
        config = ConnectionConfig(
            scheme="doppler",
            host="api.doppler.com",
            password="service_token",
        )

        adapter = DopplerAdapter(config)

        with pytest.raises(ValueError, match="project required"):
            adapter._init_connection()

    def test_init_connection_sdk_not_installed(
        self, config_with_token: ConnectionConfig
    ) -> None:
        # Inject ImportError into sys.modules for dopplersdk
        original = sys.modules.get("dopplersdk")
        sys.modules["dopplersdk"] = None  # Simulate missing module

        try:
            adapter = DopplerAdapter(config_with_token)

            # Mock the import to raise ImportError
            with patch("builtins.__import__", side_effect=ImportError("No module named 'dopplersdk'")):
                with pytest.raises(ImportError, match="dopplersdk is required"):
                    adapter._init_connection()
        finally:
            # Restore original state
            if original is None:
                sys.modules.pop("dopplersdk", None)
            else:
                sys.modules["dopplersdk"] = original


class TestDopplerAdapterAuthenticate:
    """Test authenticate method."""

    def test_authenticate_success(
        self, mock_doppler_sdk: Any, config_with_token: ConnectionConfig
    ) -> None:
        mock_client = MagicMock()
        mock_doppler_sdk.Doppler.return_value = mock_client
        mock_client.secrets.list.return_value = {"secrets": {"MY_KEY": {}}}

        adapter = DopplerAdapter(config_with_token)
        adapter._init_connection()
        adapter.authenticate()

        mock_client.secrets.list.assert_called_once()

    def test_authenticate_not_connected(
        self, config_with_token: ConnectionConfig
    ) -> None:
        adapter = DopplerAdapter(config_with_token)

        with pytest.raises(ConnectionError, match="not initialized"):
            adapter.authenticate()

    def test_authenticate_invalid_token(
        self, mock_doppler_sdk: Any, config_with_token: ConnectionConfig
    ) -> None:
        mock_client = MagicMock()
        mock_doppler_sdk.Doppler.return_value = mock_client
        mock_client.secrets.list.side_effect = Exception("Invalid token")

        adapter = DopplerAdapter(config_with_token)
        adapter._init_connection()

        with pytest.raises(AuthenticationError):
            adapter.authenticate()

    def test_authenticate_unauthorized(
        self, mock_doppler_sdk: Any, config_with_token: ConnectionConfig
    ) -> None:
        mock_client = MagicMock()
        mock_doppler_sdk.Doppler.return_value = mock_client
        mock_client.secrets.list.side_effect = Exception("Unauthorized")

        adapter = DopplerAdapter(config_with_token)
        adapter._init_connection()

        with pytest.raises(AuthenticationError):
            adapter.authenticate()

    def test_authenticate_backend_error(
        self, mock_doppler_sdk: Any, config_with_token: ConnectionConfig
    ) -> None:
        mock_client = MagicMock()
        mock_doppler_sdk.Doppler.return_value = mock_client
        mock_client.secrets.list.side_effect = Exception("Server error")

        adapter = DopplerAdapter(config_with_token)
        adapter._init_connection()

        with pytest.raises(BackendError, match="doppler"):
            adapter.authenticate()


class TestDopplerAdapterGet:
    """Test get method."""

    def test_get_success(
        self, mock_doppler_sdk: Any, config_with_token: ConnectionConfig
    ) -> None:
        mock_client = MagicMock()
        mock_doppler_sdk.Doppler.return_value = mock_client
        mock_client.secrets.get.return_value = {
            "secret": {"name": "MY_KEY", "raw": "my-secret-value"}
        }

        adapter = DopplerAdapter(config_with_token)
        adapter._init_connection()
        result = adapter.get("MY_KEY")

        assert isinstance(result, Secret)
        assert result.key == "MY_KEY"
        assert result.value == "my-secret-value"
        assert result.version is None

    def test_get_not_connected(self, config_with_token: ConnectionConfig) -> None:
        adapter = DopplerAdapter(config_with_token)

        with pytest.raises(ConnectionError, match="not initialized"):
            adapter.get("MY_KEY")

    def test_get_secret_not_found(
        self, mock_doppler_sdk: Any, config_with_token: ConnectionConfig
    ) -> None:
        mock_client = MagicMock()
        mock_doppler_sdk.Doppler.return_value = mock_client
        mock_client.secrets.get.side_effect = Exception("Secret not found")

        adapter = DopplerAdapter(config_with_token)
        adapter._init_connection()

        with pytest.raises(SecretNotFoundError, match="MY_KEY"):
            adapter.get("MY_KEY")

    def test_get_404_error(
        self, mock_doppler_sdk: Any, config_with_token: ConnectionConfig
    ) -> None:
        mock_client = MagicMock()
        mock_doppler_sdk.Doppler.return_value = mock_client
        mock_client.secrets.get.side_effect = Exception("404 Not found")

        adapter = DopplerAdapter(config_with_token)
        adapter._init_connection()

        with pytest.raises(SecretNotFoundError):
            adapter.get("MISSING_KEY")

    def test_get_backend_error(
        self, mock_doppler_sdk: Any, config_with_token: ConnectionConfig
    ) -> None:
        mock_client = MagicMock()
        mock_doppler_sdk.Doppler.return_value = mock_client
        mock_client.secrets.get.side_effect = Exception("API error")

        adapter = DopplerAdapter(config_with_token)
        adapter._init_connection()

        with pytest.raises(BackendError, match="doppler"):
            adapter.get("MY_KEY")

    def test_get_missing_secret_in_response(
        self, mock_doppler_sdk: Any, config_with_token: ConnectionConfig
    ) -> None:
        mock_client = MagicMock()
        mock_doppler_sdk.Doppler.return_value = mock_client
        mock_client.secrets.get.return_value = {}

        adapter = DopplerAdapter(config_with_token)
        adapter._init_connection()

        with pytest.raises(SecretNotFoundError):
            adapter.get("MY_KEY")


class TestDopplerAdapterSet:
    """Test set method."""

    def test_set_string_value(
        self, mock_doppler_sdk: Any, config_with_token: ConnectionConfig
    ) -> None:
        mock_client = MagicMock()
        mock_doppler_sdk.Doppler.return_value = mock_client
        mock_client.secrets.update.return_value = {"secret": {"name": "MY_KEY"}}

        adapter = DopplerAdapter(config_with_token)
        adapter._init_connection()
        result = adapter.set("MY_KEY", "new-value")

        assert isinstance(result, Secret)
        assert result.key == "MY_KEY"
        assert result.value == "new-value"
        mock_client.secrets.update.assert_called_once_with(
            project="my-project",
            config="prod",
            name="MY_KEY",
            value="new-value",
        )

    def test_set_bytes_value(
        self, mock_doppler_sdk: Any, config_with_token: ConnectionConfig
    ) -> None:
        mock_client = MagicMock()
        mock_doppler_sdk.Doppler.return_value = mock_client
        mock_client.secrets.update.return_value = {"secret": {"name": "MY_KEY"}}

        adapter = DopplerAdapter(config_with_token)
        adapter._init_connection()
        result = adapter.set("MY_KEY", b"binary-value")

        assert result.value == "binary-value"

    def test_set_dict_value(
        self, mock_doppler_sdk: Any, config_with_token: ConnectionConfig
    ) -> None:
        mock_client = MagicMock()
        mock_doppler_sdk.Doppler.return_value = mock_client
        mock_client.secrets.update.return_value = {"secret": {"name": "MY_KEY"}}

        adapter = DopplerAdapter(config_with_token)
        adapter._init_connection()
        result = adapter.set("MY_KEY", {"nested": "dict"})

        assert '"nested": "dict"' in result.value

    def test_set_with_metadata(
        self, mock_doppler_sdk: Any, config_with_token: ConnectionConfig
    ) -> None:
        mock_client = MagicMock()
        mock_doppler_sdk.Doppler.return_value = mock_client
        mock_client.secrets.update.return_value = {"secret": {"name": "MY_KEY"}}

        adapter = DopplerAdapter(config_with_token)
        adapter._init_connection()
        result = adapter.set(
            "MY_KEY", "value", metadata={"owner": "admin", "env": "prod"}
        )

        assert result.metadata == {"owner": "admin", "env": "prod"}

    def test_set_not_connected(self, config_with_token: ConnectionConfig) -> None:
        adapter = DopplerAdapter(config_with_token)

        with pytest.raises(ConnectionError, match="not initialized"):
            adapter.set("MY_KEY", "value")

    def test_set_backend_error(
        self, mock_doppler_sdk: Any, config_with_token: ConnectionConfig
    ) -> None:
        mock_client = MagicMock()
        mock_doppler_sdk.Doppler.return_value = mock_client
        mock_client.secrets.update.side_effect = Exception("Update failed")

        adapter = DopplerAdapter(config_with_token)
        adapter._init_connection()

        with pytest.raises(BackendError, match="doppler"):
            adapter.set("MY_KEY", "value")


class TestDopplerAdapterDelete:
    """Test delete method."""

    def test_delete_success(
        self, mock_doppler_sdk: Any, config_with_token: ConnectionConfig
    ) -> None:
        mock_client = MagicMock()
        mock_doppler_sdk.Doppler.return_value = mock_client
        mock_client.secrets.update.return_value = {"secret": {"name": "MY_KEY"}}

        adapter = DopplerAdapter(config_with_token)
        adapter._init_connection()
        result = adapter.delete("MY_KEY")

        assert result is True
        mock_client.secrets.update.assert_called_once_with(
            project="my-project",
            config="prod",
            name="MY_KEY",
            value="",
        )

    def test_delete_not_connected(self, config_with_token: ConnectionConfig) -> None:
        adapter = DopplerAdapter(config_with_token)

        with pytest.raises(ConnectionError, match="not initialized"):
            adapter.delete("MY_KEY")

    def test_delete_backend_error(
        self, mock_doppler_sdk: Any, config_with_token: ConnectionConfig
    ) -> None:
        mock_client = MagicMock()
        mock_doppler_sdk.Doppler.return_value = mock_client
        mock_client.secrets.update.side_effect = Exception("Delete failed")

        adapter = DopplerAdapter(config_with_token)
        adapter._init_connection()

        with pytest.raises(BackendError, match="doppler"):
            adapter.delete("MY_KEY")


class TestDopplerAdapterList:
    """Test list method."""

    def test_list_all_secrets(
        self, mock_doppler_sdk: Any, config_with_token: ConnectionConfig
    ) -> None:
        mock_client = MagicMock()
        mock_doppler_sdk.Doppler.return_value = mock_client
        mock_client.secrets.list.return_value = {
            "secrets": {
                "KEY_A": {},
                "KEY_B": {},
                "KEY_C": {},
            }
        }

        adapter = DopplerAdapter(config_with_token)
        adapter._init_connection()
        result = adapter.list()

        assert isinstance(result, SecretList)
        assert set(result.keys) == {"KEY_A", "KEY_B", "KEY_C"}
        assert result.cursor is None

    def test_list_with_prefix(
        self, mock_doppler_sdk: Any, config_with_token: ConnectionConfig
    ) -> None:
        mock_client = MagicMock()
        mock_doppler_sdk.Doppler.return_value = mock_client
        mock_client.secrets.list.return_value = {
            "secrets": {
                "DB_HOST": {},
                "DB_PORT": {},
                "APP_NAME": {},
                "API_KEY": {},
            }
        }

        adapter = DopplerAdapter(config_with_token)
        adapter._init_connection()
        result = adapter.list(prefix="DB_")

        assert set(result.keys) == {"DB_HOST", "DB_PORT"}

    def test_list_with_limit(
        self, mock_doppler_sdk: Any, config_with_token: ConnectionConfig
    ) -> None:
        mock_client = MagicMock()
        mock_doppler_sdk.Doppler.return_value = mock_client
        mock_client.secrets.list.return_value = {
            "secrets": {
                "KEY_A": {},
                "KEY_B": {},
                "KEY_C": {},
            }
        }

        adapter = DopplerAdapter(config_with_token)
        adapter._init_connection()
        result = adapter.list(limit=2)

        assert len(result.keys) == 2

    def test_list_empty(
        self, mock_doppler_sdk: Any, config_with_token: ConnectionConfig
    ) -> None:
        mock_client = MagicMock()
        mock_doppler_sdk.Doppler.return_value = mock_client
        mock_client.secrets.list.return_value = {"secrets": {}}

        adapter = DopplerAdapter(config_with_token)
        adapter._init_connection()
        result = adapter.list()

        assert result.keys == []

    def test_list_not_connected(self, config_with_token: ConnectionConfig) -> None:
        adapter = DopplerAdapter(config_with_token)

        with pytest.raises(ConnectionError, match="not initialized"):
            adapter.list()

    def test_list_backend_error(
        self, mock_doppler_sdk: Any, config_with_token: ConnectionConfig
    ) -> None:
        mock_client = MagicMock()
        mock_doppler_sdk.Doppler.return_value = mock_client
        mock_client.secrets.list.side_effect = Exception("List failed")

        adapter = DopplerAdapter(config_with_token)
        adapter._init_connection()

        with pytest.raises(BackendError, match="doppler"):
            adapter.list()


class TestDopplerAdapterExists:
    """Test exists method."""

    def test_exists_true(
        self, mock_doppler_sdk: Any, config_with_token: ConnectionConfig
    ) -> None:
        mock_client = MagicMock()
        mock_doppler_sdk.Doppler.return_value = mock_client
        mock_client.secrets.list.return_value = {
            "secrets": {"MY_KEY": {}, "OTHER_KEY": {}}
        }

        adapter = DopplerAdapter(config_with_token)
        adapter._init_connection()
        result = adapter.exists("MY_KEY")

        assert result is True

    def test_exists_false(
        self, mock_doppler_sdk: Any, config_with_token: ConnectionConfig
    ) -> None:
        mock_client = MagicMock()
        mock_doppler_sdk.Doppler.return_value = mock_client
        mock_client.secrets.list.return_value = {
            "secrets": {"MY_KEY": {}, "OTHER_KEY": {}}
        }

        adapter = DopplerAdapter(config_with_token)
        adapter._init_connection()
        result = adapter.exists("MISSING_KEY")

        assert result is False

    def test_exists_not_connected(self, config_with_token: ConnectionConfig) -> None:
        adapter = DopplerAdapter(config_with_token)

        with pytest.raises(ConnectionError, match="not initialized"):
            adapter.exists("MY_KEY")

    def test_exists_backend_error(
        self, mock_doppler_sdk: Any, config_with_token: ConnectionConfig
    ) -> None:
        mock_client = MagicMock()
        mock_doppler_sdk.Doppler.return_value = mock_client
        mock_client.secrets.list.side_effect = Exception("Check failed")

        adapter = DopplerAdapter(config_with_token)
        adapter._init_connection()

        with pytest.raises(BackendError, match="doppler"):
            adapter.exists("MY_KEY")


class TestDopplerAdapterHealthCheck:
    """Test health_check method."""

    def test_health_check_success(
        self, mock_doppler_sdk: Any, config_with_token: ConnectionConfig
    ) -> None:
        mock_client = MagicMock()
        mock_doppler_sdk.Doppler.return_value = mock_client
        mock_client.secrets.list.return_value = {"secrets": {}}

        adapter = DopplerAdapter(config_with_token)
        adapter._init_connection()
        result = adapter.health_check()

        assert result is True

    def test_health_check_failure(
        self, mock_doppler_sdk: Any, config_with_token: ConnectionConfig
    ) -> None:
        mock_client = MagicMock()
        mock_doppler_sdk.Doppler.return_value = mock_client
        mock_client.secrets.list.side_effect = Exception("Connection failed")

        adapter = DopplerAdapter(config_with_token)
        adapter._init_connection()
        result = adapter.health_check()

        assert result is False

    def test_health_check_not_connected(
        self, config_with_token: ConnectionConfig
    ) -> None:
        adapter = DopplerAdapter(config_with_token)
        result = adapter.health_check()

        assert result is False


class TestDopplerAdapterClose:
    """Test close method."""

    def test_close_clears_client(
        self, mock_doppler_sdk: Any, config_with_token: ConnectionConfig
    ) -> None:
        mock_client = MagicMock()
        mock_doppler_sdk.Doppler.return_value = mock_client

        adapter = DopplerAdapter(config_with_token)
        adapter._init_connection()
        assert adapter._connected is True

        adapter.close()

        assert adapter._client is None
        assert adapter._connected is False

    def test_close_idempotent(self, config_with_token: ConnectionConfig) -> None:
        adapter = DopplerAdapter(config_with_token)
        adapter.close()
        adapter.close()

        assert adapter._connected is False


class TestDopplerAdapterContextManager:
    """Test context manager protocol."""

    def test_with_statement(
        self, mock_doppler_sdk: Any, config_with_token: ConnectionConfig
    ) -> None:
        mock_client = MagicMock()
        mock_doppler_sdk.Doppler.return_value = mock_client

        with DopplerAdapter(config_with_token) as adapter:
            adapter._init_connection()
            assert adapter._connected is True

        assert adapter._connected is False

    def test_with_statement_exception(
        self, mock_doppler_sdk: Any, config_with_token: ConnectionConfig
    ) -> None:
        mock_client = MagicMock()
        mock_doppler_sdk.Doppler.return_value = mock_client

        try:
            with DopplerAdapter(config_with_token) as adapter:
                adapter._init_connection()
                raise ValueError("test error")
        except ValueError:
            pass

        assert adapter._connected is False
