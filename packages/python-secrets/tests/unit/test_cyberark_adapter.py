"""Unit tests for CyberArk Conjur adapter."""

from __future__ import annotations

import sys
from datetime import datetime
from unittest.mock import MagicMock, Mock, patch

import pytest

from penguin_sal.core.exceptions import (
    AdapterNotInstalledError,
    AuthenticationError,
    BackendError,
    ConnectionError,
    SecretNotFoundError,
)
from penguin_sal.core.types import ConnectionConfig

# Mock the conjur module before importing the adapter
# This allows tests to run without the actual conjur SDK installed
_mock_conjur_api = MagicMock()
sys.modules["conjur"] = MagicMock()
sys.modules["conjur"].api = _mock_conjur_api

# Now we can safely import the adapter
from penguin_sal.adapters.cyberark import CyberArkAdapter


@pytest.fixture
def valid_config() -> ConnectionConfig:
    """Fixture for valid Conjur connection config."""
    return ConnectionConfig(
        scheme="cyberark",
        host="conjur.example.com",
        port=8443,
        username="admin",
        password="api-key-123",
        params={"account": "default"},
    )


@pytest.fixture
def mock_conjur_client() -> Mock:
    """Fixture for mocked Conjur client."""
    return Mock()


@patch("penguin_sal.adapters.cyberark.conjur_api")
class TestCyberArkAdapterInit:
    """Test adapter initialization."""

    def test_init_success(self, mock_conjur_api: Mock, valid_config: ConnectionConfig) -> None:
        """Successful initialization creates client."""
        mock_client = Mock()
        mock_conjur_api.ConjurClient.return_value = mock_client

        adapter = CyberArkAdapter(valid_config)

        assert adapter.config == valid_config
        assert adapter.client == mock_client
        assert adapter._connected is True
        mock_conjur_api.ConjurClient.assert_called_once_with(
            url="https://conjur.example.com:8443",
            account="default",
        )

    def test_init_missing_account_raises_connection_error(self, mock_conjur_api: Mock) -> None:
        """Missing account in params raises ConnectionError."""
        config = ConnectionConfig(
            scheme="cyberark",
            host="conjur.example.com",
            port=8443,
            username="admin",
            password="api-key-123",
            params={},
        )

        with pytest.raises(ConnectionError, match="Account must be specified"):
            CyberArkAdapter(config)

    def test_init_client_creation_failure(self, mock_conjur_api: Mock) -> None:
        """Client creation failure raises ConnectionError."""
        mock_conjur_api.ConjurClient.side_effect = Exception("Connection failed")
        valid_config = ConnectionConfig(
            scheme="cyberark",
            host="conjur.example.com",
            port=8443,
            username="admin",
            password="api-key-123",
            params={"account": "default"},
        )

        with pytest.raises(ConnectionError):
            CyberArkAdapter(valid_config)


class TestAdapterNotInstalledError:
    """Test adapter import error handling."""

    def test_init_missing_conjur_raises_adapter_not_installed(
        self, valid_config: ConnectionConfig
    ) -> None:
        """Missing conjur SDK raises AdapterNotInstalledError."""
        # Patch conjur_api at the module level to be None
        with patch("penguin_sal.adapters.cyberark.conjur_api", None):
            with pytest.raises(AdapterNotInstalledError, match="cyberark"):
                CyberArkAdapter(valid_config)


@patch("penguin_sal.adapters.cyberark.conjur_api")
class TestAuthenticate:
    """Test authentication."""

    def test_authenticate_success(self, mock_conjur_api: Mock, valid_config: ConnectionConfig) -> None:
        """Successful authentication calls login."""
        mock_client = Mock()
        mock_conjur_api.ConjurClient.return_value = mock_client

        adapter = CyberArkAdapter(valid_config)
        adapter.authenticate()

        mock_client.login.assert_called_once_with("admin", "api-key-123")
        assert adapter._connected is True

    def test_authenticate_missing_login_raises_error(self, mock_conjur_api: Mock) -> None:
        """Missing login raises AuthenticationError."""
        mock_client = Mock()
        mock_conjur_api.ConjurClient.return_value = mock_client

        config = ConnectionConfig(
            scheme="cyberark",
            host="conjur.example.com",
            port=8443,
            username=None,
            password="api-key",
            params={"account": "default"},
        )

        adapter = CyberArkAdapter(config)

        with pytest.raises(AuthenticationError, match="required"):
            adapter.authenticate()

    def test_authenticate_login_failure_raises_error(
        self, mock_conjur_api: Mock, valid_config: ConnectionConfig
    ) -> None:
        """Authentication failure raises AuthenticationError."""
        mock_client = Mock()
        mock_client.login.side_effect = Exception("Invalid credentials")
        mock_conjur_api.ConjurClient.return_value = mock_client

        adapter = CyberArkAdapter(valid_config)

        with pytest.raises(AuthenticationError, match="Failed to authenticate"):
            adapter.authenticate()

    def test_authenticate_not_initialized_raises_error(self, mock_conjur_api: Mock, valid_config: ConnectionConfig) -> None:
        """Calling authenticate when not initialized raises error."""
        mock_client = Mock()
        mock_conjur_api.ConjurClient.return_value = mock_client

        adapter = CyberArkAdapter(valid_config)
        adapter.client = None

        with pytest.raises((ConnectionError, AuthenticationError)):
            adapter.authenticate()


@patch("penguin_sal.adapters.cyberark.conjur_api")
class TestGet:
    """Test secret retrieval."""

    def test_get_success_string_value(self, mock_conjur_api: Mock, valid_config: ConnectionConfig) -> None:
        """Get returns Secret with string value."""
        mock_client = Mock()
        mock_client.get_secret.return_value = "secret-value"
        mock_conjur_api.ConjurClient.return_value = mock_client

        adapter = CyberArkAdapter(valid_config)
        secret = adapter.get("prod/db/password")

        assert secret.key == "prod/db/password"
        assert secret.value == "secret-value"
        assert secret.version is None
        mock_client.get_secret.assert_called_once_with("prod/db/password")

    def test_get_success_bytes_value(self, mock_conjur_api: Mock, valid_config: ConnectionConfig) -> None:
        """Get decodes bytes value."""
        mock_client = Mock()
        mock_client.get_secret.return_value = b"secret-bytes"
        mock_conjur_api.ConjurClient.return_value = mock_client

        adapter = CyberArkAdapter(valid_config)
        secret = adapter.get("prod/db/password")

        assert secret.value == "secret-bytes"

    def test_get_not_found_raises_error(self, mock_conjur_api: Mock, valid_config: ConnectionConfig) -> None:
        """Get non-existent key raises SecretNotFoundError."""
        mock_client = Mock()
        mock_client.get_secret.side_effect = Exception("404 Not Found")
        mock_conjur_api.ConjurClient.return_value = mock_client

        adapter = CyberArkAdapter(valid_config)

        with pytest.raises(SecretNotFoundError) as exc_info:
            adapter.get("nonexistent/key")

        assert exc_info.value.key == "nonexistent/key"
        assert exc_info.value.backend == "cyberark"

    def test_get_none_value_raises_error(self, mock_conjur_api: Mock, valid_config: ConnectionConfig) -> None:
        """Get with None return value raises SecretNotFoundError."""
        mock_client = Mock()
        mock_client.get_secret.return_value = None
        mock_conjur_api.ConjurClient.return_value = mock_client

        adapter = CyberArkAdapter(valid_config)

        with pytest.raises(SecretNotFoundError):
            adapter.get("missing/key")

    def test_get_backend_error_wraps_exception(
        self, mock_conjur_api: Mock, valid_config: ConnectionConfig
    ) -> None:
        """Other errors are wrapped in BackendError."""
        mock_client = Mock()
        original_error = Exception("Connection timeout")
        mock_client.get_secret.side_effect = original_error
        mock_conjur_api.ConjurClient.return_value = mock_client

        adapter = CyberArkAdapter(valid_config)

        with pytest.raises(BackendError) as exc_info:
            adapter.get("prod/db/password")

        assert exc_info.value.backend == "cyberark"
        assert exc_info.value.original_error is original_error


@patch("penguin_sal.adapters.cyberark.conjur_api")
class TestSet:
    """Test secret creation and updates."""

    def test_set_success_string_value(self, mock_conjur_api: Mock, valid_config: ConnectionConfig) -> None:
        """Set with string value succeeds."""
        mock_client = Mock()
        mock_conjur_api.ConjurClient.return_value = mock_client

        adapter = CyberArkAdapter(valid_config)
        secret = adapter.set("prod/db/password", "new-password")

        assert secret.key == "prod/db/password"
        assert secret.value == "new-password"
        assert secret.created_at is not None
        mock_client.set_secret.assert_called_once_with("prod/db/password", "new-password")

    def test_set_success_bytes_value(self, mock_conjur_api: Mock, valid_config: ConnectionConfig) -> None:
        """Set with bytes value is converted to string."""
        mock_client = Mock()
        mock_conjur_api.ConjurClient.return_value = mock_client

        adapter = CyberArkAdapter(valid_config)
        secret = adapter.set("prod/db/password", b"binary-secret")

        assert secret.value == "binary-secret"
        mock_client.set_secret.assert_called_once_with("prod/db/password", "binary-secret")

    def test_set_success_dict_value(self, mock_conjur_api: Mock, valid_config: ConnectionConfig) -> None:
        """Set with dict value is JSON serialized."""
        mock_client = Mock()
        mock_conjur_api.ConjurClient.return_value = mock_client

        adapter = CyberArkAdapter(valid_config)
        data = {"username": "admin", "password": "secret"}
        secret = adapter.set("prod/db/creds", data)

        assert '"username": "admin"' in secret.value
        mock_client.set_secret.assert_called_once()
        call_args = mock_client.set_secret.call_args
        assert "prod/db/creds" in call_args[0]

    def test_set_metadata_ignored(self, mock_conjur_api: Mock, valid_config: ConnectionConfig) -> None:
        """Set metadata is accepted but ignored."""
        mock_client = Mock()
        mock_conjur_api.ConjurClient.return_value = mock_client

        adapter = CyberArkAdapter(valid_config)
        secret = adapter.set(
            "prod/db/password",
            "value",
            metadata={"owner": "admin"},
        )

        assert secret.metadata is None

    def test_set_failure_raises_backend_error(
        self, mock_conjur_api: Mock, valid_config: ConnectionConfig
    ) -> None:
        """Set failure raises BackendError."""
        mock_client = Mock()
        original_error = Exception("Permission denied")
        mock_client.set_secret.side_effect = original_error
        mock_conjur_api.ConjurClient.return_value = mock_client

        adapter = CyberArkAdapter(valid_config)

        with pytest.raises(BackendError) as exc_info:
            adapter.set("prod/db/password", "value")

        assert exc_info.value.backend == "cyberark"
        assert exc_info.value.original_error is original_error


@patch("penguin_sal.adapters.cyberark.conjur_api")
class TestDelete:
    """Test secret deletion."""

    def test_delete_raises_backend_error(self, mock_conjur_api: Mock, valid_config: ConnectionConfig) -> None:
        """Delete raises BackendError (not supported)."""
        mock_client = Mock()
        mock_conjur_api.ConjurClient.return_value = mock_client

        adapter = CyberArkAdapter(valid_config)

        with pytest.raises(BackendError, match="does not support variable deletion"):
            adapter.delete("prod/db/password")


@patch("penguin_sal.adapters.cyberark.conjur_api")
class TestList:
    """Test secret listing."""

    def test_list_success(self, mock_conjur_api: Mock, valid_config: ConnectionConfig) -> None:
        """List returns SecretList with keys."""
        mock_client = Mock()
        mock_client.list_resources.return_value = [
            {"id": "default:variable:prod/db/password"},
            {"id": "default:variable:prod/db/username"},
            {"id": "default:variable:dev/api/key"},
        ]
        mock_conjur_api.ConjurClient.return_value = mock_client

        adapter = CyberArkAdapter(valid_config)
        result = adapter.list()

        assert len(result.keys) == 3
        assert "prod/db/password" in result.keys
        assert "prod/db/username" in result.keys
        assert "dev/api/key" in result.keys
        mock_client.list_resources.assert_called_once_with(kind="variable")

    def test_list_with_prefix(self, mock_conjur_api: Mock, valid_config: ConnectionConfig) -> None:
        """List filters by prefix."""
        mock_client = Mock()
        mock_client.list_resources.return_value = [
            {"id": "default:variable:prod/db/password"},
            {"id": "default:variable:prod/db/username"},
            {"id": "default:variable:dev/api/key"},
        ]
        mock_conjur_api.ConjurClient.return_value = mock_client

        adapter = CyberArkAdapter(valid_config)
        result = adapter.list(prefix="prod/")

        assert len(result.keys) == 2
        assert "prod/db/password" in result.keys
        assert "prod/db/username" in result.keys

    def test_list_with_limit(self, mock_conjur_api: Mock, valid_config: ConnectionConfig) -> None:
        """List respects limit parameter."""
        mock_client = Mock()
        mock_client.list_resources.return_value = [
            {"id": "default:variable:key1"},
            {"id": "default:variable:key2"},
            {"id": "default:variable:key3"},
        ]
        mock_conjur_api.ConjurClient.return_value = mock_client

        adapter = CyberArkAdapter(valid_config)
        result = adapter.list(limit=2)

        assert len(result.keys) == 2

    def test_list_empty_result(self, mock_conjur_api: Mock, valid_config: ConnectionConfig) -> None:
        """List returns empty list when no resources."""
        mock_client = Mock()
        mock_client.list_resources.return_value = []
        mock_conjur_api.ConjurClient.return_value = mock_client

        adapter = CyberArkAdapter(valid_config)
        result = adapter.list()

        assert result.keys == []
        assert result.cursor is None

    def test_list_malformed_id(self, mock_conjur_api: Mock, valid_config: ConnectionConfig) -> None:
        """List handles resources without colons gracefully."""
        mock_client = Mock()
        mock_client.list_resources.return_value = [
            {"id": "key1"},
            {"id": "default:variable:key2"},
        ]
        mock_conjur_api.ConjurClient.return_value = mock_client

        adapter = CyberArkAdapter(valid_config)
        result = adapter.list()

        assert "key1" in result.keys
        assert "key2" in result.keys

    def test_list_failure_raises_backend_error(self, mock_conjur_api: Mock, valid_config: ConnectionConfig) -> None:
        """List failure raises BackendError."""
        mock_client = Mock()
        original_error = Exception("API error")
        mock_client.list_resources.side_effect = original_error
        mock_conjur_api.ConjurClient.return_value = mock_client

        adapter = CyberArkAdapter(valid_config)

        with pytest.raises(BackendError) as exc_info:
            adapter.list()

        assert exc_info.value.backend == "cyberark"


@patch("penguin_sal.adapters.cyberark.conjur_api")
class TestExists:
    """Test secret existence check."""

    def test_exists_true(self, mock_conjur_api: Mock, valid_config: ConnectionConfig) -> None:
        """Exists returns True when secret exists."""
        mock_client = Mock()
        mock_client.get_secret.return_value = "secret-value"
        mock_conjur_api.ConjurClient.return_value = mock_client

        adapter = CyberArkAdapter(valid_config)
        result = adapter.exists("prod/db/password")

        assert result is True

    def test_exists_false_404(self, mock_conjur_api: Mock, valid_config: ConnectionConfig) -> None:
        """Exists returns False on 404."""
        mock_client = Mock()
        mock_client.get_secret.side_effect = Exception("404 Not Found")
        mock_conjur_api.ConjurClient.return_value = mock_client

        adapter = CyberArkAdapter(valid_config)
        result = adapter.exists("nonexistent/key")

        assert result is False

    def test_exists_false_not_found(self, mock_conjur_api: Mock, valid_config: ConnectionConfig) -> None:
        """Exists returns False on 'not found' error."""
        mock_client = Mock()
        mock_client.get_secret.side_effect = Exception("not found")
        mock_conjur_api.ConjurClient.return_value = mock_client

        adapter = CyberArkAdapter(valid_config)
        result = adapter.exists("missing/key")

        assert result is False

    def test_exists_false_other_error(self, mock_conjur_api: Mock, valid_config: ConnectionConfig) -> None:
        """Exists returns False on other errors (cannot determine)."""
        mock_client = Mock()
        mock_client.get_secret.side_effect = Exception("Connection error")
        mock_conjur_api.ConjurClient.return_value = mock_client

        adapter = CyberArkAdapter(valid_config)
        result = adapter.exists("prod/db/password")

        assert result is False


@patch("penguin_sal.adapters.cyberark.conjur_api")
class TestHealthCheck:
    """Test health checking."""

    def test_health_check_success(self, mock_conjur_api: Mock, valid_config: ConnectionConfig) -> None:
        """Health check returns True when healthy."""
        mock_client = Mock()
        mock_client.info.return_value = {"status": "ok"}
        mock_conjur_api.ConjurClient.return_value = mock_client

        adapter = CyberArkAdapter(valid_config)
        result = adapter.health_check()

        assert result is True
        mock_client.info.assert_called_once()

    def test_health_check_failure(self, mock_conjur_api: Mock, valid_config: ConnectionConfig) -> None:
        """Health check returns False on error."""
        mock_client = Mock()
        mock_client.info.side_effect = Exception("Connection failed")
        mock_conjur_api.ConjurClient.return_value = mock_client

        adapter = CyberArkAdapter(valid_config)
        result = adapter.health_check()

        assert result is False


@patch("penguin_sal.adapters.cyberark.conjur_api")
class TestClose:
    """Test closing connections."""

    def test_close_clears_client(self, mock_conjur_api: Mock, valid_config: ConnectionConfig) -> None:
        """Close clears the client reference."""
        mock_client = Mock()
        mock_conjur_api.ConjurClient.return_value = mock_client

        adapter = CyberArkAdapter(valid_config)
        assert adapter.client is not None
        assert adapter._connected is True

        adapter.close()

        assert adapter.client is None
        assert adapter._connected is False

    def test_close_called_multiple_times(self, mock_conjur_api: Mock, valid_config: ConnectionConfig) -> None:
        """Close can be called multiple times safely."""
        mock_client = Mock()
        mock_conjur_api.ConjurClient.return_value = mock_client

        adapter = CyberArkAdapter(valid_config)
        adapter.close()
        adapter.close()  # Should not raise

        assert adapter.client is None


@patch("penguin_sal.adapters.cyberark.conjur_api")
class TestContextManager:
    """Test context manager protocol."""

    def test_context_manager_closes_on_exit(self, mock_conjur_api: Mock, valid_config: ConnectionConfig) -> None:
        """Context manager closes adapter on exit."""
        mock_client = Mock()
        mock_conjur_api.ConjurClient.return_value = mock_client

        with CyberArkAdapter(valid_config) as adapter:
            assert adapter.client is not None
            assert adapter._connected is True

        assert adapter.client is None
        assert adapter._connected is False

    def test_context_manager_closes_on_exception(self, mock_conjur_api: Mock, valid_config: ConnectionConfig) -> None:
        """Context manager closes adapter even on exception."""
        mock_client = Mock()
        mock_conjur_api.ConjurClient.return_value = mock_client

        try:
            with CyberArkAdapter(valid_config) as adapter:
                raise ValueError("Test error")
        except ValueError:
            pass

        assert adapter.client is None
        assert adapter._connected is False
