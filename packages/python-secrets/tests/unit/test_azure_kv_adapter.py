"""Unit tests for Azure Key Vault adapter."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from unittest.mock import MagicMock, Mock, patch

import pytest

from penguin_sal.adapters.azure_kv import AzureKeyVaultAdapter
from penguin_sal.core.exceptions import (
    AuthenticationError,
    BackendError,
    ConnectionError,
    SecretNotFoundError,
)
from penguin_sal.core.types import ConnectionConfig, Secret, SecretList


class MockSecretProperties:
    """Mock for Azure SecretProperties."""

    def __init__(
        self,
        name: str,
        version: str | None = None,
        created_on: datetime | None = None,
        updated_on: datetime | None = None,
        tags: dict[str, str] | None = None,
    ) -> None:
        self.name = name
        self.version = version or "v1"
        self.created_on = created_on or datetime.now()
        self.updated_on = updated_on or datetime.now()
        self.tags = tags or {}


class MockSecret:
    """Mock for Azure Secret."""

    def __init__(
        self,
        name: str,
        value: str,
        version: str | None = None,
        tags: dict[str, str] | None = None,
    ) -> None:
        self.name = name
        self.value = value
        self.version = version or "v1"
        self.properties = MockSecretProperties(
            name=name, version=version, tags=tags
        )


class ResourceNotFoundErrorMock(Exception):
    """Mock for Azure ResourceNotFoundError."""

    pass


@pytest.fixture
def mock_azure_imports(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """Mock Azure SDK imports."""
    mock_credential = Mock()
    mock_client = MagicMock()

    original_import = __import__

    def mock_import(
        name: str,
        globals: dict[str, Any] | None = None,
        locals: dict[str, Any] | None = None,
        fromlist: tuple[str, ...] | None = None,
        level: int = 0,
    ) -> Any:
        if "azure.identity" in name:
            module = Mock()
            module.DefaultAzureCredential = Mock(return_value=mock_credential)
            module.ClientSecretCredential = Mock(return_value=mock_credential)
            return module
        elif "azure.keyvault.secrets" in name:
            module = Mock()
            module.SecretClient = Mock(return_value=mock_client)
            return module
        elif "azure.core.exceptions" in name:
            module = Mock()
            module.ResourceNotFoundError = ResourceNotFoundErrorMock
            return module
        return original_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr("builtins.__import__", mock_import)
    return {
        "credential": mock_credential,
        "client": mock_client,
    }


class TestAzureKeyVaultAdapterInit:
    """Test adapter initialization."""

    def test_init_with_managed_identity(
        self, mock_azure_imports: dict[str, Any]
    ) -> None:
        """Test initialization with managed identity (DefaultAzureCredential)."""
        config = ConnectionConfig(
            scheme="azure-kv", host="my-vault.vault.azure.net"
        )

        adapter = AzureKeyVaultAdapter(config)

        assert adapter.config is config
        assert adapter._connected is True
        assert adapter._client is mock_azure_imports["client"]

    def test_init_with_service_principal(
        self, mock_azure_imports: dict[str, Any]
    ) -> None:
        """Test initialization with service principal credentials."""
        config = ConnectionConfig(
            scheme="azure-kv",
            host="my-vault.vault.azure.net",
            username="client-id",
            password="client-secret",
            params={"tenant_id": "my-tenant-id"},
        )

        adapter = AzureKeyVaultAdapter(config)

        assert adapter._connected is True
        assert adapter._client is mock_azure_imports["client"]

    def test_init_with_vault_url_param(
        self, mock_azure_imports: dict[str, Any]
    ) -> None:
        """Test initialization with explicit vault_url parameter."""
        config = ConnectionConfig(
            scheme="azure-kv",
            host="localhost",
            params={"vault_url": "https://custom-vault.vault.azure.net"},
        )

        adapter = AzureKeyVaultAdapter(config)

        assert adapter._connected is True

    def test_init_missing_azure_sdk(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test initialization fails gracefully when Azure SDK is missing."""
        original_import = __import__

        def mock_failing_import(
            name: str,
            globals: dict[str, Any] | None = None,
            locals: dict[str, Any] | None = None,
            fromlist: tuple[str, ...] | None = None,
            level: int = 0,
        ) -> Any:
            if "azure" in name:
                raise ImportError("No module named 'azure'")
            return original_import(name, globals, locals, fromlist, level)

        monkeypatch.setattr("builtins.__import__", mock_failing_import)

        config = ConnectionConfig(scheme="azure-kv", host="my-vault.vault.azure.net")

        with pytest.raises(BackendError, match="Azure SDK not installed"):
            AzureKeyVaultAdapter(config)

    def test_init_connection_failure(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test initialization fails when client initialization raises."""
        original_import = __import__

        def mock_import_with_failure(
            name: str,
            globals: dict[str, Any] | None = None,
            locals: dict[str, Any] | None = None,
            fromlist: tuple[str, ...] | None = None,
            level: int = 0,
        ) -> Any:
            if "azure.identity" in name:
                module = Mock()
                module.DefaultAzureCredential = Mock(return_value=Mock())
                module.ClientSecretCredential = Mock(return_value=Mock())
                return module
            elif "azure.keyvault.secrets" in name:
                module = Mock()
                # Make SecretClient constructor raise
                module.SecretClient = Mock(side_effect=RuntimeError("Connection failed"))
                return module
            elif "azure.core.exceptions" in name:
                module = Mock()
                module.ResourceNotFoundError = ResourceNotFoundErrorMock
                return module
            return original_import(name, globals, locals, fromlist, level)

        monkeypatch.setattr("builtins.__import__", mock_import_with_failure)

        config = ConnectionConfig(scheme="azure-kv", host="my-vault.vault.azure.net")

        with pytest.raises(ConnectionError, match="Failed to initialize"):
            AzureKeyVaultAdapter(config)


class TestAzureKeyVaultAdapterAuthenticate:
    """Test authentication verification."""

    def test_authenticate_success(
        self, mock_azure_imports: dict[str, Any]
    ) -> None:
        """Test successful authentication."""
        mock_azure_imports["client"].list_properties_of_secrets = Mock(return_value=[])

        config = ConnectionConfig(scheme="azure-kv", host="my-vault.vault.azure.net")
        adapter = AzureKeyVaultAdapter(config)

        # Should not raise
        adapter.authenticate()

    def test_authenticate_authentication_error(
        self, mock_azure_imports: dict[str, Any]
    ) -> None:
        """Test authentication fails with 401-like error."""

        def mock_failing_list(*args: Any, **kwargs: Any) -> None:
            raise Exception("Unauthorized")

        mock_azure_imports["client"].list_properties_of_secrets = mock_failing_list

        config = ConnectionConfig(scheme="azure-kv", host="my-vault.vault.azure.net")
        adapter = AzureKeyVaultAdapter(config)

        with pytest.raises(AuthenticationError):
            adapter.authenticate()

    def test_authenticate_connection_error(
        self, mock_azure_imports: dict[str, Any]
    ) -> None:
        """Test authentication fails with connection error."""

        def mock_failing_list(*args: Any, **kwargs: Any) -> None:
            raise Exception("Unable to reach vault")

        mock_azure_imports["client"].list_properties_of_secrets = mock_failing_list

        config = ConnectionConfig(scheme="azure-kv", host="my-vault.vault.azure.net")
        adapter = AzureKeyVaultAdapter(config)

        with pytest.raises(ConnectionError):
            adapter.authenticate()

    def test_authenticate_no_client(self) -> None:
        """Test authentication fails if client is None."""
        with patch.object(
            AzureKeyVaultAdapter, "_init_connection", return_value=None
        ):
            config = ConnectionConfig(scheme="azure-kv", host="my-vault.vault.azure.net")
            adapter = AzureKeyVaultAdapter.__new__(AzureKeyVaultAdapter)
            adapter.config = config
            adapter._client = None
            adapter._connected = False

            with pytest.raises(ConnectionError, match="Client not initialized"):
                adapter.authenticate()


class TestAzureKeyVaultAdapterGet:
    """Test secret retrieval."""

    def test_get_success(self, mock_azure_imports: dict[str, Any]) -> None:
        """Test successful secret retrieval."""
        mock_secret = MockSecret(
            name="my-secret",
            value="my-value",
            version="v1",
            tags={"env": "prod"},
        )
        mock_azure_imports["client"].get_secret = Mock(return_value=mock_secret)

        config = ConnectionConfig(scheme="azure-kv", host="my-vault.vault.azure.net")
        adapter = AzureKeyVaultAdapter(config)
        result = adapter.get("my-secret")

        assert isinstance(result, Secret)
        assert result.key == "my-secret"
        assert result.value == "my-value"
        assert result.version == "v1"
        assert result.metadata == {"env": "prod"}

    def test_get_with_version(self, mock_azure_imports: dict[str, Any]) -> None:
        """Test secret retrieval with specific version."""
        mock_secret = MockSecret(
            name="my-secret", value="old-value", version="v2"
        )
        mock_azure_imports["client"].get_secret = Mock(return_value=mock_secret)

        config = ConnectionConfig(scheme="azure-kv", host="my-vault.vault.azure.net")
        adapter = AzureKeyVaultAdapter(config)
        result = adapter.get("my-secret", version="v2")

        mock_azure_imports["client"].get_secret.assert_called_with(
            "my-secret", version="v2"
        )
        assert result.value == "old-value"

    def test_get_not_found(self, mock_azure_imports: dict[str, Any]) -> None:
        """Test retrieval of non-existent secret."""
        mock_azure_imports["client"].get_secret = Mock(
            side_effect=ResourceNotFoundErrorMock()
        )

        config = ConnectionConfig(scheme="azure-kv", host="my-vault.vault.azure.net")
        adapter = AzureKeyVaultAdapter(config)

        with pytest.raises(SecretNotFoundError, match="my-secret"):
            adapter.get("my-secret")

    def test_get_backend_error(self, mock_azure_imports: dict[str, Any]) -> None:
        """Test retrieval fails with backend error."""
        mock_azure_imports["client"].get_secret = Mock(
            side_effect=RuntimeError("Vault error")
        )

        config = ConnectionConfig(scheme="azure-kv", host="my-vault.vault.azure.net")
        adapter = AzureKeyVaultAdapter(config)

        with pytest.raises(BackendError, match="Failed to retrieve secret"):
            adapter.get("my-secret")


class TestAzureKeyVaultAdapterSet:
    """Test secret creation/update."""

    def test_set_string_value(self, mock_azure_imports: dict[str, Any]) -> None:
        """Test setting a string secret."""
        mock_secret = MockSecret(
            name="my-secret", value="my-value", version="v1"
        )
        mock_azure_imports["client"].set_secret = Mock(return_value=mock_secret)

        config = ConnectionConfig(scheme="azure-kv", host="my-vault.vault.azure.net")
        adapter = AzureKeyVaultAdapter(config)
        result = adapter.set("my-secret", "my-value")

        mock_azure_imports["client"].set_secret.assert_called_with(
            "my-secret", "my-value", tags={}
        )
        assert result.key == "my-secret"
        assert result.value == "my-value"

    def test_set_bytes_value(self, mock_azure_imports: dict[str, Any]) -> None:
        """Test setting a bytes secret."""
        mock_secret = MockSecret(
            name="my-secret", value="byte-value", version="v1"
        )
        mock_azure_imports["client"].set_secret = Mock(return_value=mock_secret)

        config = ConnectionConfig(scheme="azure-kv", host="my-vault.vault.azure.net")
        adapter = AzureKeyVaultAdapter(config)
        result = adapter.set("my-secret", b"byte-value")

        mock_azure_imports["client"].set_secret.assert_called_with(
            "my-secret", "byte-value", tags={}
        )
        assert result.value == "byte-value"

    def test_set_dict_value(self, mock_azure_imports: dict[str, Any]) -> None:
        """Test setting a dict secret (JSON-encoded)."""
        mock_secret = MockSecret(
            name="my-secret",
            value='{"key":"value"}',
            version="v1",
        )
        mock_azure_imports["client"].set_secret = Mock(return_value=mock_secret)

        config = ConnectionConfig(scheme="azure-kv", host="my-vault.vault.azure.net")
        adapter = AzureKeyVaultAdapter(config)
        result = adapter.set("my-secret", {"key": "value"})

        call_args = mock_azure_imports["client"].set_secret.call_args
        assert call_args[0][0] == "my-secret"
        assert '"key"' in call_args[0][1]
        assert '"value"' in call_args[0][1]

    def test_set_with_metadata(self, mock_azure_imports: dict[str, Any]) -> None:
        """Test setting a secret with metadata."""
        mock_secret = MockSecret(
            name="my-secret",
            value="my-value",
            version="v1",
            tags={"env": "prod", "app": "myapp"},
        )
        mock_azure_imports["client"].set_secret = Mock(return_value=mock_secret)

        config = ConnectionConfig(scheme="azure-kv", host="my-vault.vault.azure.net")
        adapter = AzureKeyVaultAdapter(config)
        result = adapter.set(
            "my-secret", "my-value", metadata={"env": "prod", "app": "myapp"}
        )

        mock_azure_imports["client"].set_secret.assert_called_with(
            "my-secret",
            "my-value",
            tags={"env": "prod", "app": "myapp"},
        )
        assert result.metadata == {"env": "prod", "app": "myapp"}

    def test_set_backend_error(self, mock_azure_imports: dict[str, Any]) -> None:
        """Test set fails with backend error."""
        mock_azure_imports["client"].set_secret = Mock(
            side_effect=RuntimeError("Vault error")
        )

        config = ConnectionConfig(scheme="azure-kv", host="my-vault.vault.azure.net")
        adapter = AzureKeyVaultAdapter(config)

        with pytest.raises(BackendError, match="Failed to set secret"):
            adapter.set("my-secret", "my-value")


class TestAzureKeyVaultAdapterDelete:
    """Test secret deletion."""

    def test_delete_success(self, mock_azure_imports: dict[str, Any]) -> None:
        """Test successful secret deletion."""
        mock_azure_imports["client"].begin_delete_secret = Mock()
        mock_azure_imports["client"].purge_deleted_secret = Mock()

        config = ConnectionConfig(scheme="azure-kv", host="my-vault.vault.azure.net")
        adapter = AzureKeyVaultAdapter(config)
        result = adapter.delete("my-secret")

        assert result is True
        mock_azure_imports["client"].begin_delete_secret.assert_called_with(
            "my-secret"
        )
        mock_azure_imports["client"].purge_deleted_secret.assert_called_with(
            "my-secret"
        )

    def test_delete_not_found(self, mock_azure_imports: dict[str, Any]) -> None:
        """Test deletion of non-existent secret returns False."""
        mock_azure_imports["client"].begin_delete_secret = Mock(
            side_effect=ResourceNotFoundErrorMock()
        )

        config = ConnectionConfig(scheme="azure-kv", host="my-vault.vault.azure.net")
        adapter = AzureKeyVaultAdapter(config)
        result = adapter.delete("non-existent")

        assert result is False

    def test_delete_backend_error(self, mock_azure_imports: dict[str, Any]) -> None:
        """Test deletion fails with backend error."""
        mock_azure_imports["client"].begin_delete_secret = Mock(
            side_effect=RuntimeError("Vault error")
        )

        config = ConnectionConfig(scheme="azure-kv", host="my-vault.vault.azure.net")
        adapter = AzureKeyVaultAdapter(config)

        with pytest.raises(BackendError, match="Failed to delete secret"):
            adapter.delete("my-secret")


class TestAzureKeyVaultAdapterList:
    """Test secret listing."""

    def test_list_all(self, mock_azure_imports: dict[str, Any]) -> None:
        """Test listing all secrets."""
        mock_properties = [
            MockSecretProperties(name="secret1"),
            MockSecretProperties(name="secret2"),
            MockSecretProperties(name="secret3"),
        ]
        mock_azure_imports["client"].list_properties_of_secrets = Mock(
            return_value=mock_properties
        )

        config = ConnectionConfig(scheme="azure-kv", host="my-vault.vault.azure.net")
        adapter = AzureKeyVaultAdapter(config)
        result = adapter.list()

        assert isinstance(result, SecretList)
        assert result.keys == ["secret1", "secret2", "secret3"]

    def test_list_with_prefix(self, mock_azure_imports: dict[str, Any]) -> None:
        """Test listing secrets with prefix filter."""
        mock_properties = [
            MockSecretProperties(name="app-secret1"),
            MockSecretProperties(name="app-secret2"),
            MockSecretProperties(name="db-secret1"),
        ]
        mock_azure_imports["client"].list_properties_of_secrets = Mock(
            return_value=mock_properties
        )

        config = ConnectionConfig(scheme="azure-kv", host="my-vault.vault.azure.net")
        adapter = AzureKeyVaultAdapter(config)
        result = adapter.list(prefix="app-")

        assert result.keys == ["app-secret1", "app-secret2"]

    def test_list_with_limit(self, mock_azure_imports: dict[str, Any]) -> None:
        """Test listing secrets with limit."""
        mock_properties = [
            MockSecretProperties(name="secret1"),
            MockSecretProperties(name="secret2"),
            MockSecretProperties(name="secret3"),
        ]
        mock_azure_imports["client"].list_properties_of_secrets = Mock(
            return_value=mock_properties
        )

        config = ConnectionConfig(scheme="azure-kv", host="my-vault.vault.azure.net")
        adapter = AzureKeyVaultAdapter(config)
        result = adapter.list(limit=2)

        assert result.keys == ["secret1", "secret2"]

    def test_list_empty(self, mock_azure_imports: dict[str, Any]) -> None:
        """Test listing when vault is empty."""
        mock_azure_imports["client"].list_properties_of_secrets = Mock(
            return_value=[]
        )

        config = ConnectionConfig(scheme="azure-kv", host="my-vault.vault.azure.net")
        adapter = AzureKeyVaultAdapter(config)
        result = adapter.list()

        assert result.keys == []

    def test_list_backend_error(self, mock_azure_imports: dict[str, Any]) -> None:
        """Test list fails with backend error."""
        mock_azure_imports["client"].list_properties_of_secrets = Mock(
            side_effect=RuntimeError("Vault error")
        )

        config = ConnectionConfig(scheme="azure-kv", host="my-vault.vault.azure.net")
        adapter = AzureKeyVaultAdapter(config)

        with pytest.raises(BackendError, match="Failed to list secrets"):
            adapter.list()


class TestAzureKeyVaultAdapterExists:
    """Test secret existence check."""

    def test_exists_true(self, mock_azure_imports: dict[str, Any]) -> None:
        """Test exists returns True for existing secret."""
        mock_secret = MockSecret(name="my-secret", value="value")
        mock_azure_imports["client"].get_secret = Mock(return_value=mock_secret)

        config = ConnectionConfig(scheme="azure-kv", host="my-vault.vault.azure.net")
        adapter = AzureKeyVaultAdapter(config)
        result = adapter.exists("my-secret")

        assert result is True

    def test_exists_false(self, mock_azure_imports: dict[str, Any]) -> None:
        """Test exists returns False for non-existent secret."""
        mock_azure_imports["client"].get_secret = Mock(
            side_effect=ResourceNotFoundErrorMock()
        )

        config = ConnectionConfig(scheme="azure-kv", host="my-vault.vault.azure.net")
        adapter = AzureKeyVaultAdapter(config)
        result = adapter.exists("my-secret")

        assert result is False

    def test_exists_error_returns_false(
        self, mock_azure_imports: dict[str, Any]
    ) -> None:
        """Test exists returns False on unexpected error."""
        mock_azure_imports["client"].get_secret = Mock(
            side_effect=RuntimeError("Unexpected error")
        )

        config = ConnectionConfig(scheme="azure-kv", host="my-vault.vault.azure.net")
        adapter = AzureKeyVaultAdapter(config)
        result = adapter.exists("my-secret")

        assert result is False


class TestAzureKeyVaultAdapterHealthCheck:
    """Test health check."""

    def test_health_check_success(self, mock_azure_imports: dict[str, Any]) -> None:
        """Test successful health check."""
        mock_azure_imports["client"].list_properties_of_secrets = Mock(
            return_value=[]
        )

        config = ConnectionConfig(scheme="azure-kv", host="my-vault.vault.azure.net")
        adapter = AzureKeyVaultAdapter(config)
        result = adapter.health_check()

        assert result is True

    def test_health_check_failure(self, mock_azure_imports: dict[str, Any]) -> None:
        """Test health check fails when vault is unreachable."""
        mock_azure_imports["client"].list_properties_of_secrets = Mock(
            side_effect=RuntimeError("Connection timeout")
        )

        config = ConnectionConfig(scheme="azure-kv", host="my-vault.vault.azure.net")
        adapter = AzureKeyVaultAdapter(config)
        result = adapter.health_check()

        assert result is False

    def test_health_check_no_client(self) -> None:
        """Test health check returns False if client is None."""
        with patch.object(
            AzureKeyVaultAdapter, "_init_connection", return_value=None
        ):
            config = ConnectionConfig(scheme="azure-kv", host="my-vault.vault.azure.net")
            adapter = AzureKeyVaultAdapter.__new__(AzureKeyVaultAdapter)
            adapter.config = config
            adapter._client = None
            adapter._connected = False

            result = adapter.health_check()

            assert result is False


class TestAzureKeyVaultAdapterClose:
    """Test connection close."""

    def test_close_success(self, mock_azure_imports: dict[str, Any]) -> None:
        """Test successful close."""
        config = ConnectionConfig(scheme="azure-kv", host="my-vault.vault.azure.net")
        adapter = AzureKeyVaultAdapter(config)

        adapter.close()

        mock_azure_imports["client"].close.assert_called_once()
        assert adapter._client is None
        assert adapter._connected is False

    def test_close_idempotent(self, mock_azure_imports: dict[str, Any]) -> None:
        """Test close is idempotent."""
        config = ConnectionConfig(scheme="azure-kv", host="my-vault.vault.azure.net")
        adapter = AzureKeyVaultAdapter(config)

        adapter.close()
        adapter.close()  # Should not raise

        assert adapter._connected is False

    def test_close_error_handling(self, mock_azure_imports: dict[str, Any]) -> None:
        """Test close handles client errors gracefully."""
        mock_azure_imports["client"].close = Mock(
            side_effect=RuntimeError("Close failed")
        )

        config = ConnectionConfig(scheme="azure-kv", host="my-vault.vault.azure.net")
        adapter = AzureKeyVaultAdapter(config)

        adapter.close()  # Should not raise

        assert adapter._client is None
        assert adapter._connected is False
