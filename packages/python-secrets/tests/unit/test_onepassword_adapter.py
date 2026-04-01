"""Unit tests for 1Password Connect adapter."""

from __future__ import annotations

import sys
from datetime import datetime
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

# Mock onepasswordconnectsdk before importing adapter
sys.modules["onepasswordconnectsdk"] = MagicMock()
sys.modules["onepasswordconnectsdk.client"] = MagicMock()
sys.modules["onepasswordconnectsdk.models"] = MagicMock()
sys.modules["onepasswordconnectsdk.models.item"] = MagicMock()

from penguin_sal.adapters.onepassword import OnePasswordAdapter
from penguin_sal.core.exceptions import (
    AuthenticationError,
    BackendError,
    ConnectionError,
    SecretNotFoundError,
)
from penguin_sal.core.types import ConnectionConfig, Secret, SecretList


class MockItem:
    """Mock 1Password Item."""

    def __init__(
        self,
        id: str,
        title: str,
        password: str | None = None,
        created_at: datetime | None = None,
        updated_at: datetime | None = None,
        fields: list[Any] | None = None,
    ) -> None:
        self.id = id
        self.title = title
        self.password = password
        self.created_at = created_at or datetime.now()
        self.updated_at = updated_at or datetime.now()
        self.fields = fields or []


@pytest.fixture
def config() -> ConnectionConfig:
    """Create a test connection config."""
    return ConnectionConfig(
        scheme="https",
        host="localhost",
        port=8080,
        password="test-token",
        params={"vault_id": "test-vault-id"},
    )


@pytest.fixture
def mock_client() -> MagicMock:
    """Create a mock 1Password client."""
    return MagicMock()


class TestOnePasswordAdapterInit:
    """Test adapter initialization."""

    def test_init_stores_config(self, config: ConnectionConfig) -> None:
        """Config is stored correctly."""
        adapter = OnePasswordAdapter(config)
        assert adapter.config is config
        assert adapter._connected is False

    def test_init_sets_attributes(self, config: ConnectionConfig) -> None:
        """Adapter attributes are initialized."""
        adapter = OnePasswordAdapter(config)
        assert adapter._client is None
        assert adapter._vault_id is None


class TestOnePasswordAdapterInitConnection:
    """Test connection initialization."""

    def test_init_connection_with_config(
        self, config: ConnectionConfig, mock_client: MagicMock
    ) -> None:
        """Connection initialized from config."""
        adapter = OnePasswordAdapter(config)
        # Mock sdk_new_client to raise so it falls back to Client init
        with patch("penguin_sal.adapters.onepassword.sdk_new_client", side_effect=Exception("no env")):
            with patch("penguin_sal.adapters.onepassword.Client", return_value=mock_client):
                adapter._init_connection()
                assert adapter._connected is True
                assert adapter._client is mock_client
                assert adapter._vault_id == "test-vault-id"

    def test_init_connection_env_fallback(
        self, config: ConnectionConfig, mock_client: MagicMock
    ) -> None:
        """Falls back to environment if available."""
        adapter = OnePasswordAdapter(config)
        with patch("penguin_sal.adapters.onepassword.sdk_new_client", return_value=mock_client):
            adapter._init_connection()
            assert adapter._client is mock_client

    def test_init_connection_missing_token(
        self, mock_client: MagicMock
    ) -> None:
        """ConnectionError raised without token."""
        config = ConnectionConfig(scheme="https", host="localhost")
        adapter = OnePasswordAdapter(config)

        with patch(
            "penguin_sal.adapters.onepassword.sdk_new_client",
            side_effect=Exception("env not set"),
        ):
            with pytest.raises(ConnectionError, match="token required"):
                adapter._init_connection()

    def test_init_connection_missing_vault_id(
        self, mock_client: MagicMock
    ) -> None:
        """ConnectionError raised without vault ID."""
        config = ConnectionConfig(
            scheme="https", host="localhost", password="token"
        )
        adapter = OnePasswordAdapter(config)

        with patch("penguin_sal.adapters.onepassword.Client", return_value=mock_client):
            with pytest.raises(ConnectionError, match="vault ID required"):
                adapter._init_connection()

    def test_init_connection_vault_param_fallback(
        self, mock_client: MagicMock
    ) -> None:
        """Accepts 'vault' param as fallback for 'vault_id'."""
        config = ConnectionConfig(
            scheme="https",
            host="localhost",
            password="token",
            params={"vault": "my-vault"},
        )
        adapter = OnePasswordAdapter(config)

        with patch("penguin_sal.adapters.onepassword.Client", return_value=mock_client):
            adapter._init_connection()
            assert adapter._vault_id == "my-vault"


class TestOnePasswordAdapterAuthenticate:
    """Test authentication."""

    def test_authenticate_success(
        self, config: ConnectionConfig, mock_client: MagicMock
    ) -> None:
        """Successful authentication."""
        adapter = OnePasswordAdapter(config)
        adapter._client = mock_client
        mock_client.vaults.list.return_value = []

        adapter.authenticate()  # Should not raise

    def test_authenticate_not_connected(self) -> None:
        """ConnectionError when not connected."""
        config = ConnectionConfig(scheme="https", host="localhost")
        adapter = OnePasswordAdapter(config)

        with pytest.raises(ConnectionError, match="Not connected"):
            adapter.authenticate()

    def test_authenticate_failure(
        self, config: ConnectionConfig, mock_client: MagicMock
    ) -> None:
        """AuthenticationError on failure."""
        adapter = OnePasswordAdapter(config)
        adapter._client = mock_client
        mock_client.vaults.list.side_effect = Exception("Invalid token")

        with pytest.raises(AuthenticationError, match="Failed to authenticate"):
            adapter.authenticate()


class TestOnePasswordAdapterGet:
    """Test secret retrieval."""

    def test_get_success(
        self, config: ConnectionConfig, mock_client: MagicMock
    ) -> None:
        """Retrieve a secret by key."""
        adapter = OnePasswordAdapter(config)
        adapter._client = mock_client
        adapter._vault_id = "test-vault"

        mock_item = MockItem(
            id="item-1", title="my-secret", password="secret-value"
        )
        mock_client.items.list.return_value = [mock_item]

        secret = adapter.get("my-secret")

        assert isinstance(secret, Secret)
        assert secret.key == "my-secret"
        assert secret.value == "secret-value"
        assert secret.version is None

    def test_get_from_field(
        self, config: ConnectionConfig, mock_client: MagicMock
    ) -> None:
        """Extract password from field if not in password attr."""
        adapter = OnePasswordAdapter(config)
        adapter._client = mock_client
        adapter._vault_id = "test-vault"

        field = MagicMock()
        field.type = "password"
        field.value = "field-password"

        mock_item = MockItem(id="item-1", title="my-secret", fields=[field])
        mock_client.items.list.return_value = [mock_item]

        secret = adapter.get("my-secret")
        assert secret.value == "field-password"

    def test_get_not_found(
        self, config: ConnectionConfig, mock_client: MagicMock
    ) -> None:
        """SecretNotFoundError when key doesn't exist."""
        adapter = OnePasswordAdapter(config)
        adapter._client = mock_client
        adapter._vault_id = "test-vault"

        mock_client.items.list.return_value = []

        with pytest.raises(
            SecretNotFoundError, match="Secret not found: missing-key"
        ):
            adapter.get("missing-key")

    def test_get_backend_error(
        self, config: ConnectionConfig, mock_client: MagicMock
    ) -> None:
        """BackendError on request failure."""
        adapter = OnePasswordAdapter(config)
        adapter._client = mock_client
        adapter._vault_id = "test-vault"

        mock_client.items.list.side_effect = Exception("Server error")

        with pytest.raises(BackendError, match="Failed to retrieve secret"):
            adapter.get("my-secret")

    def test_get_not_connected(self) -> None:
        """ConnectionError when not connected."""
        config = ConnectionConfig(scheme="https", host="localhost")
        adapter = OnePasswordAdapter(config)

        with pytest.raises(ConnectionError, match="Not connected"):
            adapter.get("my-secret")


class TestOnePasswordAdapterSet:
    """Test secret creation/update."""

    def test_set_new_secret(
        self, config: ConnectionConfig, mock_client: MagicMock
    ) -> None:
        """Create a new secret."""
        adapter = OnePasswordAdapter(config)
        adapter._client = mock_client
        adapter._vault_id = "test-vault"

        mock_client.items.list.return_value = []
        mock_client.items.create.return_value = MagicMock()

        with patch("onepasswordconnectsdk.models.item.Item") as MockItem:
            with patch("onepasswordconnectsdk.models.item.ItemPassword") as MockItemPassword:
                secret = adapter.set("new-secret", "secret-value")
                assert secret.key == "new-secret"
                mock_client.items.create.assert_called_once()

    def test_set_update_existing(
        self, config: ConnectionConfig, mock_client: MagicMock
    ) -> None:
        """Update an existing secret."""
        adapter = OnePasswordAdapter(config)
        adapter._client = mock_client
        adapter._vault_id = "test-vault"

        mock_item = MockItem(
            id="item-1", title="my-secret", password="old-value"
        )
        mock_client.items.list.return_value = [mock_item]

        secret = adapter.set("my-secret", "new-value")

        assert secret.value == "new-value"
        mock_client.items.update.assert_called_once()

    def test_set_bytes_value(
        self, config: ConnectionConfig, mock_client: MagicMock
    ) -> None:
        """Handle bytes values."""
        adapter = OnePasswordAdapter(config)
        adapter._client = mock_client
        adapter._vault_id = "test-vault"

        mock_client.items.list.return_value = []
        mock_client.items.create.return_value = MagicMock()

        with patch("onepasswordconnectsdk.models.item.Item") as MockItem:
            with patch("onepasswordconnectsdk.models.item.ItemPassword"):
                secret = adapter.set("my-secret", b"bytes-value")
                assert secret.key == "my-secret"
                assert "bytes-value" in secret.value or secret.value == "b'bytes-value'"

    def test_set_not_connected(self) -> None:
        """ConnectionError when not connected."""
        config = ConnectionConfig(scheme="https", host="localhost")
        adapter = OnePasswordAdapter(config)

        with pytest.raises(ConnectionError, match="Not connected"):
            adapter.set("my-secret", "value")


class TestOnePasswordAdapterDelete:
    """Test secret deletion."""

    def test_delete_success(
        self, config: ConnectionConfig, mock_client: MagicMock
    ) -> None:
        """Delete an existing secret."""
        adapter = OnePasswordAdapter(config)
        adapter._client = mock_client
        adapter._vault_id = "test-vault"

        mock_item = MockItem(id="item-1", title="my-secret")
        mock_client.items.list.return_value = [mock_item]

        result = adapter.delete("my-secret")

        assert result is True
        mock_client.items.delete.assert_called_once_with("test-vault", "item-1")

    def test_delete_not_found(
        self, config: ConnectionConfig, mock_client: MagicMock
    ) -> None:
        """Return False when secret doesn't exist."""
        adapter = OnePasswordAdapter(config)
        adapter._client = mock_client
        adapter._vault_id = "test-vault"

        mock_client.items.list.return_value = []

        result = adapter.delete("missing-secret")

        assert result is False
        mock_client.items.delete.assert_not_called()

    def test_delete_backend_error(
        self, config: ConnectionConfig, mock_client: MagicMock
    ) -> None:
        """BackendError on deletion failure."""
        adapter = OnePasswordAdapter(config)
        adapter._client = mock_client
        adapter._vault_id = "test-vault"

        mock_client.items.list.side_effect = Exception("Server error")

        with pytest.raises(BackendError, match="Failed to delete secret"):
            adapter.delete("my-secret")

    def test_delete_not_connected(self) -> None:
        """ConnectionError when not connected."""
        config = ConnectionConfig(scheme="https", host="localhost")
        adapter = OnePasswordAdapter(config)

        with pytest.raises(ConnectionError, match="Not connected"):
            adapter.delete("my-secret")


class TestOnePasswordAdapterList:
    """Test secret listing."""

    def test_list_all(self, config: ConnectionConfig, mock_client: MagicMock) -> None:
        """List all secrets in vault."""
        adapter = OnePasswordAdapter(config)
        adapter._client = mock_client
        adapter._vault_id = "test-vault"

        items = [
            MockItem(id="1", title="secret1"),
            MockItem(id="2", title="secret2"),
            MockItem(id="3", title="secret3"),
        ]
        mock_client.items.list.return_value = items

        result = adapter.list()

        assert isinstance(result, SecretList)
        assert result.keys == ["secret1", "secret2", "secret3"]

    def test_list_with_prefix(
        self, config: ConnectionConfig, mock_client: MagicMock
    ) -> None:
        """Filter by prefix."""
        adapter = OnePasswordAdapter(config)
        adapter._client = mock_client
        adapter._vault_id = "test-vault"

        items = [
            MockItem(id="1", title="prod-db"),
            MockItem(id="2", title="prod-api"),
            MockItem(id="3", title="dev-db"),
        ]
        mock_client.items.list.return_value = items

        result = adapter.list(prefix="prod-")

        assert result.keys == ["prod-db", "prod-api"]

    def test_list_with_limit(
        self, config: ConnectionConfig, mock_client: MagicMock
    ) -> None:
        """Respect limit parameter."""
        adapter = OnePasswordAdapter(config)
        adapter._client = mock_client
        adapter._vault_id = "test-vault"

        items = [
            MockItem(id="1", title="secret1"),
            MockItem(id="2", title="secret2"),
            MockItem(id="3", title="secret3"),
        ]
        mock_client.items.list.return_value = items

        result = adapter.list(limit=2)

        assert len(result.keys) == 2

    def test_list_not_connected(self) -> None:
        """ConnectionError when not connected."""
        config = ConnectionConfig(scheme="https", host="localhost")
        adapter = OnePasswordAdapter(config)

        with pytest.raises(ConnectionError, match="Not connected"):
            adapter.list()


class TestOnePasswordAdapterExists:
    """Test secret existence check."""

    def test_exists_true(
        self, config: ConnectionConfig, mock_client: MagicMock
    ) -> None:
        """Return True if secret exists."""
        adapter = OnePasswordAdapter(config)
        adapter._client = mock_client
        adapter._vault_id = "test-vault"

        items = [MockItem(id="1", title="my-secret")]
        mock_client.items.list.return_value = items

        assert adapter.exists("my-secret") is True

    def test_exists_false(
        self, config: ConnectionConfig, mock_client: MagicMock
    ) -> None:
        """Return False if secret doesn't exist."""
        adapter = OnePasswordAdapter(config)
        adapter._client = mock_client
        adapter._vault_id = "test-vault"

        mock_client.items.list.return_value = []

        assert adapter.exists("missing-secret") is False

    def test_exists_not_connected(self) -> None:
        """Return False when not connected."""
        config = ConnectionConfig(scheme="https", host="localhost")
        adapter = OnePasswordAdapter(config)

        assert adapter.exists("my-secret") is False

    def test_exists_backend_error(
        self, config: ConnectionConfig, mock_client: MagicMock
    ) -> None:
        """Return False on backend error."""
        adapter = OnePasswordAdapter(config)
        adapter._client = mock_client
        adapter._vault_id = "test-vault"

        mock_client.items.list.side_effect = Exception("Server error")

        assert adapter.exists("my-secret") is False


class TestOnePasswordAdapterHealthCheck:
    """Test health checking."""

    def test_health_check_healthy(
        self, config: ConnectionConfig, mock_client: MagicMock
    ) -> None:
        """Return True when backend is healthy."""
        adapter = OnePasswordAdapter(config)
        adapter._client = mock_client
        mock_client.vaults.list.return_value = []

        assert adapter.health_check() is True

    def test_health_check_unhealthy(
        self, config: ConnectionConfig, mock_client: MagicMock
    ) -> None:
        """Return False when backend is unreachable."""
        adapter = OnePasswordAdapter(config)
        adapter._client = mock_client
        mock_client.vaults.list.side_effect = Exception("Connection refused")

        assert adapter.health_check() is False

    def test_health_check_not_connected(self) -> None:
        """Return False when not connected."""
        config = ConnectionConfig(scheme="https", host="localhost")
        adapter = OnePasswordAdapter(config)

        assert adapter.health_check() is False


class TestOnePasswordAdapterClose:
    """Test connection closing."""

    def test_close_clears_state(
        self, config: ConnectionConfig, mock_client: MagicMock
    ) -> None:
        """Close releases resources."""
        adapter = OnePasswordAdapter(config)
        adapter._client = mock_client
        adapter._vault_id = "test-vault"
        adapter._connected = True

        adapter.close()

        assert adapter._client is None
        assert adapter._vault_id is None
        assert adapter._connected is False


class TestOnePasswordAdapterContextManager:
    """Test context manager protocol."""

    def test_with_statement(
        self, config: ConnectionConfig, mock_client: MagicMock
    ) -> None:
        """Context manager cleanup."""
        with patch("penguin_sal.adapters.onepassword.Client", return_value=mock_client):
            with OnePasswordAdapter(config) as adapter:
                adapter._init_connection()
                assert adapter._connected is True

            assert adapter._connected is False
