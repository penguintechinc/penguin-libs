"""Unit tests for Vault adapter."""

from __future__ import annotations

from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest
from hvac.exceptions import InvalidPath, Unauthorized, VaultError, VaultDown

from penguin_sal.adapters.vault import VaultAdapter
from penguin_sal.core.exceptions import (
    AuthenticationError,
    BackendError,
    ConnectionError,
    SecretNotFoundError,
)
from penguin_sal.core.types import ConnectionConfig


@pytest.fixture
def config() -> ConnectionConfig:
    """Create a test Vault config."""
    return ConnectionConfig(
        scheme="https",
        host="vault.example.com",
        port=8200,
        path="",
        username=None,
        password="test-token",
        params={
            "mount_point": "secret",
            "kv_version": "2",
        },
    )


@pytest.fixture
def adapter(config: ConnectionConfig) -> VaultAdapter:
    """Create a Vault adapter with mocked client."""
    adapter = VaultAdapter(config)
    adapter.client = MagicMock()
    adapter._connected = True
    return adapter


class TestVaultAdapterInit:
    """Tests for adapter initialization."""

    def test_init_connection_success(self, config: ConnectionConfig) -> None:
        """Test successful client initialization."""
        adapter = VaultAdapter(config)
        with patch("penguin_sal.adapters.vault.hvac.Client") as mock_client:
            adapter._init_connection()
            assert adapter.client is not None
            assert adapter._connected is True
            mock_client.assert_called_once()

    def test_init_connection_failure(self, config: ConnectionConfig) -> None:
        """Test client initialization failure."""
        adapter = VaultAdapter(config)
        with patch(
            "penguin_sal.adapters.vault.hvac.Client",
            side_effect=Exception("Connection failed"),
        ):
            with pytest.raises(ConnectionError):
                adapter._init_connection()

    def test_build_url(self, adapter: VaultAdapter) -> None:
        """Test URL building."""
        url = adapter._build_url()
        assert url == "https://vault.example.com:8200"

    def test_build_url_custom_port(
        self, config: ConnectionConfig
    ) -> None:
        """Test URL with custom port."""
        config.port = 9200
        adapter = VaultAdapter(config)
        url = adapter._build_url()
        assert url == "https://vault.example.com:9200"

    def test_clean_path(self, adapter: VaultAdapter) -> None:
        """Test path cleaning."""
        assert adapter._clean_path("/foo/bar/") == "foo/bar"
        assert adapter._clean_path("foo/bar") == "foo/bar"
        assert adapter._clean_path("/") == ""


class TestVaultAdapterAuth:
    """Tests for authentication."""

    def test_authenticate_with_token(self, adapter: VaultAdapter) -> None:
        """Test token authentication."""
        adapter.client.is_authenticated.return_value = True
        adapter.authenticate()
        assert adapter.client.token == "test-token"
        adapter.client.is_authenticated.assert_called_once()

    def test_authenticate_with_token_from_params(
        self, config: ConnectionConfig
    ) -> None:
        """Test token auth from params."""
        config.password = None
        config.params["token"] = "param-token"
        adapter = VaultAdapter(config)
        adapter.client = MagicMock()
        adapter.client.is_authenticated.return_value = True
        adapter.authenticate()
        assert adapter.client.token == "param-token"

    def test_authenticate_with_approle(self, config: ConnectionConfig) -> None:
        """Test AppRole authentication."""
        config.password = None
        config.params.update(
            {
                "role_id": "test-role",
                "secret_id": "test-secret",
            }
        )
        adapter = VaultAdapter(config)
        adapter.client = MagicMock()
        adapter.client.auth.approle.login.return_value = {
            "auth": {"client_token": "role-token"}
        }
        adapter.authenticate()
        assert adapter.client.token == "role-token"
        adapter.client.auth.approle.login.assert_called_once_with(
            role_id="test-role",
            secret_id="test-secret",
        )

    def test_authenticate_no_credentials(
        self, config: ConnectionConfig
    ) -> None:
        """Test auth failure when no credentials."""
        config.password = None
        config.params = {}
        adapter = VaultAdapter(config)
        adapter.client = MagicMock()
        with pytest.raises(AuthenticationError):
            adapter.authenticate()

    def test_authenticate_invalid_token(self, adapter: VaultAdapter) -> None:
        """Test token validation failure."""
        adapter.client.is_authenticated.return_value = False
        with pytest.raises(AuthenticationError):
            adapter.authenticate()

    def test_authenticate_no_client(self, config: ConnectionConfig) -> None:
        """Test auth fails without client."""
        adapter = VaultAdapter(config)
        adapter.client = None
        with pytest.raises(ConnectionError):
            adapter.authenticate()

    def test_authenticate_vault_error(self, adapter: VaultAdapter) -> None:
        """Test Vault API error during auth."""
        adapter.client.is_authenticated.side_effect = Unauthorized("Invalid token")
        with pytest.raises(AuthenticationError):
            adapter.authenticate()


class TestVaultAdapterGet:
    """Tests for secret retrieval."""

    def test_get_kv2_secret(self, adapter: VaultAdapter) -> None:
        """Test reading KV v2 secret."""
        adapter.client.secrets.kv.v2.read_secret_version.return_value = {
            "data": {
                "data": {"key1": "value1"},
                "metadata": {
                    "version": 1,
                    "created_time": "2024-01-01T00:00:00Z",
                    "updated_time": "2024-01-01T00:00:00Z",
                },
            }
        }
        secret = adapter.get("test/secret")
        assert secret.key == "test/secret"
        assert secret.value == {"key1": "value1"}
        assert secret.version == 1
        adapter.client.secrets.kv.v2.read_secret_version.assert_called_once()

    def test_get_kv2_secret_with_version(self, adapter: VaultAdapter) -> None:
        """Test reading specific KV v2 version."""
        adapter.client.secrets.kv.v2.read_secret_version.return_value = {
            "data": {
                "data": {"key": "old_value"},
                "metadata": {
                    "version": 2,
                    "created_time": "2024-01-01T00:00:00Z",
                    "updated_time": "2024-01-02T00:00:00Z",
                },
            }
        }
        secret = adapter.get("test/secret", version=2)
        assert secret.version == 2
        call_kwargs = adapter.client.secrets.kv.v2.read_secret_version.call_args[1]
        assert call_kwargs["version"] == 2

    def test_get_kv1_secret(self, config: ConnectionConfig) -> None:
        """Test reading KV v1 secret."""
        config.params["kv_version"] = "1"
        adapter = VaultAdapter(config)
        adapter.client = MagicMock()
        adapter._connected = True
        adapter.client.secrets.kv.v1.read_secret_version.return_value = {
            "data": {"password": "secret123"}
        }
        secret = adapter.get("admin/password")
        assert secret.key == "admin/password"
        assert secret.value == {"password": "secret123"}

    def test_get_not_found(self, adapter: VaultAdapter) -> None:
        """Test get raises SecretNotFoundError."""
        adapter.client.secrets.kv.v2.read_secret_version.side_effect = InvalidPath(
            ""
        )
        with pytest.raises(SecretNotFoundError) as exc:
            adapter.get("missing/secret")
        assert exc.value.key == "missing/secret"

    def test_get_authorization_error(self, adapter: VaultAdapter) -> None:
        """Test get raises BackendError on auth failure."""
        adapter.client.secrets.kv.v2.read_secret_version.side_effect = Unauthorized(
            "Permission denied"
        )
        with pytest.raises(BackendError):
            adapter.get("forbidden/secret")

    def test_get_no_client(self, config: ConnectionConfig) -> None:
        """Test get fails without client."""
        adapter = VaultAdapter(config)
        adapter.client = None
        with pytest.raises(ConnectionError):
            adapter.get("test/secret")

    def test_get_parses_timestamp(self, adapter: VaultAdapter) -> None:
        """Test timestamp parsing in get."""
        adapter.client.secrets.kv.v2.read_secret_version.return_value = {
            "data": {
                "data": {"key": "value"},
                "metadata": {
                    "version": 1,
                    "created_time": "2024-01-15T10:30:00Z",
                    "updated_time": "2024-01-16T14:45:30Z",
                },
            }
        }
        secret = adapter.get("test/secret")
        assert isinstance(secret.created_at, datetime)
        assert isinstance(secret.updated_at, datetime)


class TestVaultAdapterSet:
    """Tests for secret storage."""

    def test_set_kv2_dict(self, adapter: VaultAdapter) -> None:
        """Test writing KV v2 dict secret."""
        adapter.client.secrets.kv.v2.create_or_update_secret.return_value = {
            "data": {
                "metadata": {
                    "version": 1,
                    "created_time": "2024-01-01T00:00:00Z",
                    "updated_time": "2024-01-01T00:00:00Z",
                }
            }
        }
        value = {"username": "admin", "password": "secret"}
        secret = adapter.set("app/creds", value)
        assert secret.key == "app/creds"
        assert secret.value == value
        adapter.client.secrets.kv.v2.create_or_update_secret.assert_called_once()

    def test_set_kv2_string(self, adapter: VaultAdapter) -> None:
        """Test writing KV v2 string secret."""
        adapter.client.secrets.kv.v2.create_or_update_secret.return_value = {
            "data": {
                "metadata": {
                    "version": 1,
                    "created_time": "2024-01-01T00:00:00Z",
                    "updated_time": "2024-01-01T00:00:00Z",
                }
            }
        }
        secret = adapter.set("api/key", "abc123xyz")
        call_kwargs = adapter.client.secrets.kv.v2.create_or_update_secret.call_args[1]
        assert call_kwargs["secret"] == {"value": "abc123xyz"}

    def test_set_kv1_secret(self, config: ConnectionConfig) -> None:
        """Test writing KV v1 secret."""
        config.params["kv_version"] = "1"
        adapter = VaultAdapter(config)
        adapter.client = MagicMock()
        adapter._connected = True
        adapter.client.secrets.kv.v1.create_or_update_secret.return_value = None
        secret = adapter.set("password/root", {"password": "secret"})
        assert secret.key == "password/root"

    def test_set_authorization_error(self, adapter: VaultAdapter) -> None:
        """Test set raises BackendError on auth failure."""
        adapter.client.secrets.kv.v2.create_or_update_secret.side_effect = (
            Unauthorized("Permission denied")
        )
        with pytest.raises(BackendError):
            adapter.set("protected/secret", "value")

    def test_set_no_client(self, config: ConnectionConfig) -> None:
        """Test set fails without client."""
        adapter = VaultAdapter(config)
        adapter.client = None
        with pytest.raises(ConnectionError):
            adapter.set("test/secret", "value")


class TestVaultAdapterDelete:
    """Tests for secret deletion."""

    def test_delete_kv2_success(self, adapter: VaultAdapter) -> None:
        """Test successful KV v2 deletion."""
        adapter.client.secrets.kv.v2.delete_metadata_and_all_versions.return_value = (
            None
        )
        result = adapter.delete("app/secret")
        assert result is True
        adapter.client.secrets.kv.v2.delete_metadata_and_all_versions.assert_called_once()

    def test_delete_kv1_success(self, config: ConnectionConfig) -> None:
        """Test successful KV v1 deletion."""
        config.params["kv_version"] = "1"
        adapter = VaultAdapter(config)
        adapter.client = MagicMock()
        adapter._connected = True
        result = adapter.delete("app/secret")
        assert result is True
        adapter.client.secrets.kv.v1.delete_secret_version.assert_called_once()

    def test_delete_not_found(self, adapter: VaultAdapter) -> None:
        """Test delete returns False for missing secret."""
        adapter.client.secrets.kv.v2.delete_metadata_and_all_versions.side_effect = (
            InvalidPath("")
        )
        result = adapter.delete("missing/secret")
        assert result is False

    def test_delete_authorization_error(self, adapter: VaultAdapter) -> None:
        """Test delete raises BackendError on auth failure."""
        adapter.client.secrets.kv.v2.delete_metadata_and_all_versions.side_effect = (
            Unauthorized("Permission denied")
        )
        with pytest.raises(BackendError):
            adapter.delete("protected/secret")

    def test_delete_no_client(self, config: ConnectionConfig) -> None:
        """Test delete fails without client."""
        adapter = VaultAdapter(config)
        adapter.client = None
        with pytest.raises(ConnectionError):
            adapter.delete("test/secret")


class TestVaultAdapterList:
    """Tests for secret listing."""

    def test_list_kv2_success(self, adapter: VaultAdapter) -> None:
        """Test listing KV v2 secrets."""
        adapter.client.secrets.kv.v2.list_secrets.return_value = {
            "data": {"keys": ["secret1", "secret2", "secret3"]}
        }
        result = adapter.list("app/")
        assert result.keys == ["secret1", "secret2", "secret3"]
        assert result.cursor is None

    def test_list_kv1_success(self, config: ConnectionConfig) -> None:
        """Test listing KV v1 secrets."""
        config.params["kv_version"] = "1"
        adapter = VaultAdapter(config)
        adapter.client = MagicMock()
        adapter._connected = True
        adapter.client.secrets.kv.v1.list_secrets.return_value = {
            "data": {"keys": ["secret1", "secret2"]}
        }
        result = adapter.list("app/")
        assert result.keys == ["secret1", "secret2"]

    def test_list_with_limit(self, adapter: VaultAdapter) -> None:
        """Test list with limit."""
        adapter.client.secrets.kv.v2.list_secrets.return_value = {
            "data": {"keys": ["a", "b", "c", "d", "e"]}
        }
        result = adapter.list("", limit=3)
        assert result.keys == ["a", "b", "c"]

    def test_list_empty(self, adapter: VaultAdapter) -> None:
        """Test list with no results."""
        adapter.client.secrets.kv.v2.list_secrets.return_value = {"data": {}}
        result = adapter.list("nonexistent/")
        assert result.keys == []

    def test_list_not_found(self, adapter: VaultAdapter) -> None:
        """Test list returns empty for missing path."""
        adapter.client.secrets.kv.v2.list_secrets.side_effect = InvalidPath("")
        result = adapter.list("missing/")
        assert result.keys == []

    def test_list_authorization_error(self, adapter: VaultAdapter) -> None:
        """Test list raises BackendError on auth failure."""
        adapter.client.secrets.kv.v2.list_secrets.side_effect = Unauthorized(
            "Permission denied"
        )
        with pytest.raises(BackendError):
            adapter.list("protected/")

    def test_list_no_client(self, config: ConnectionConfig) -> None:
        """Test list fails without client."""
        adapter = VaultAdapter(config)
        adapter.client = None
        with pytest.raises(ConnectionError):
            adapter.list()


class TestVaultAdapterExists:
    """Tests for existence check."""

    def test_exists_true(self, adapter: VaultAdapter) -> None:
        """Test exists returns True when secret exists."""
        adapter.client.secrets.kv.v2.read_secret_version.return_value = {
            "data": {
                "data": {"key": "value"},
                "metadata": {
                    "version": 1,
                    "created_time": "2024-01-01T00:00:00Z",
                    "updated_time": "2024-01-01T00:00:00Z",
                },
            }
        }
        assert adapter.exists("existing/secret") is True

    def test_exists_false(self, adapter: VaultAdapter) -> None:
        """Test exists returns False when secret missing."""
        adapter.client.secrets.kv.v2.read_secret_version.side_effect = InvalidPath("")
        assert adapter.exists("missing/secret") is False

    def test_exists_no_client(self, config: ConnectionConfig) -> None:
        """Test exists returns False without client."""
        adapter = VaultAdapter(config)
        adapter.client = None
        assert adapter.exists("test/secret") is False

    def test_exists_handles_errors(self, adapter: VaultAdapter) -> None:
        """Test exists handles unexpected errors."""
        adapter.client.secrets.kv.v2.read_secret_version.side_effect = Exception(
            "Unexpected error"
        )
        assert adapter.exists("test/secret") is False


class TestVaultAdapterHealthCheck:
    """Tests for health checking."""

    def test_health_check_healthy(self, adapter: VaultAdapter) -> None:
        """Test health check when Vault is healthy."""
        adapter.client.sys.is_initialized.return_value = True
        adapter.client.sys.is_sealed.return_value = False
        assert adapter.health_check() is True

    def test_health_check_not_initialized(self, adapter: VaultAdapter) -> None:
        """Test health check when Vault not initialized."""
        adapter.client.sys.is_initialized.return_value = False
        assert adapter.health_check() is False

    def test_health_check_sealed(self, adapter: VaultAdapter) -> None:
        """Test health check when Vault is sealed."""
        adapter.client.sys.is_initialized.return_value = True
        adapter.client.sys.is_sealed.return_value = True
        assert adapter.health_check() is False

    def test_health_check_vault_down(self, adapter: VaultAdapter) -> None:
        """Test health check when Vault is down."""
        adapter.client.sys.is_initialized.side_effect = VaultDown()
        assert adapter.health_check() is False

    def test_health_check_no_client(self, config: ConnectionConfig) -> None:
        """Test health check without client."""
        adapter = VaultAdapter(config)
        adapter.client = None
        assert adapter.health_check() is False

    def test_health_check_api_error(self, adapter: VaultAdapter) -> None:
        """Test health check with API error."""
        adapter.client.sys.is_initialized.side_effect = VaultError()
        assert adapter.health_check() is False


class TestVaultAdapterClose:
    """Tests for connection closing."""

    def test_close_success(self, adapter: VaultAdapter) -> None:
        """Test closing connection."""
        adapter.close()
        assert adapter.client is None
        assert adapter._connected is False

    def test_close_no_client(self, config: ConnectionConfig) -> None:
        """Test close handles missing client."""
        adapter = VaultAdapter(config)
        adapter.client = None
        adapter.close()
        assert adapter.client is None


class TestVaultAdapterContextManager:
    """Tests for context manager protocol."""

    def test_context_manager(self, config: ConnectionConfig) -> None:
        """Test using adapter as context manager."""
        adapter = VaultAdapter(config)
        adapter.client = MagicMock()
        adapter._connected = True

        with adapter:
            assert adapter._connected is True

        assert adapter.client is None
