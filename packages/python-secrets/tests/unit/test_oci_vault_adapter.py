"""Unit tests for OCI Vault adapter."""

from __future__ import annotations

import base64
import json
import sys
from datetime import datetime
from unittest.mock import MagicMock, Mock, patch

import pytest

# Mock OCI module before importing adapter to avoid import errors when SDK not installed
mock_oci = MagicMock()
mock_oci.exceptions.ServiceError = type("ServiceError", (Exception,), {"status": None})
mock_oci.exceptions.ConfigFileNotFound = FileNotFoundError
mock_oci.config.from_file = MagicMock()
mock_oci.config.validate_config = MagicMock()
mock_oci.vault = MagicMock()
mock_oci.vault.VaultsClient = MagicMock()
mock_oci.vault.SecretsClient = MagicMock()
mock_oci.vault.models = MagicMock()
mock_oci.vault.models.CreateSecretDetails = MagicMock()
mock_oci.vault.models.SecretContentDetails = MagicMock()
mock_oci.vault.models.ScheduleSecretDeletionDetails = MagicMock()
mock_oci.secrets = MagicMock()
mock_oci.secrets.SecretsClient = MagicMock()

sys.modules["oci"] = mock_oci
sys.modules["oci.config"] = mock_oci.config
sys.modules["oci.exceptions"] = mock_oci.exceptions
sys.modules["oci.vault"] = mock_oci.vault
sys.modules["oci.vault.models"] = mock_oci.vault.models
sys.modules["oci.secrets"] = mock_oci.secrets

from penguin_sal.adapters.oci_vault import OCIVaultAdapter
from penguin_sal.core.exceptions import (
    AdapterNotInstalledError,
    AuthenticationError,
    AuthorizationError,
    BackendError,
    ConnectionError,
    SecretNotFoundError,
)
from penguin_sal.core.types import ConnectionConfig


@pytest.fixture
def config() -> ConnectionConfig:
    """Create test connection config."""
    return ConnectionConfig(
        scheme="oci-vault",
        host="us-ashburn-1",
        params={
            "compartment_id": "ocid1.compartment.oc1..test",
            "vault_id": "ocid1.vault.oc1..test",
        },
    )


def _reset_all_mocks(mock_obj, depth=0):
    """Recursively reset all mock objects."""
    if depth > 5:  # Prevent infinite recursion
        return

    if hasattr(mock_obj, "reset_mock"):
        mock_obj.reset_mock()
        mock_obj.side_effect = None
        if hasattr(mock_obj, "return_value"):
            mock_obj.return_value = MagicMock()

    for attr in dir(mock_obj):
        if attr.startswith("_"):
            continue
        try:
            sub_obj = getattr(mock_obj, attr)
            if isinstance(sub_obj, MagicMock):
                _reset_all_mocks(sub_obj, depth + 1)
        except (AttributeError, TypeError):
            pass


@pytest.fixture(autouse=True)
def reset_mocks():
    """Reset all module mocks before each test."""
    mock_oci = sys.modules["oci"]

    # Deep reset all mocks
    _reset_all_mocks(mock_oci)

    yield


@pytest.fixture
def mock_oci():
    """Return the pre-mocked OCI module and reset mocks for each test."""
    mock_module = sys.modules["oci"]

    # Reset all call counts and side effects for each test
    mock_module.config.from_file.reset_mock()
    mock_module.config.validate_config.reset_mock()
    mock_module.vault.VaultsClient.reset_mock()
    mock_module.vault.SecretsClient.reset_mock()
    mock_module.vault.models.CreateSecretDetails.reset_mock()
    mock_module.vault.models.SecretContentDetails.reset_mock()
    mock_module.vault.models.ScheduleSecretDeletionDetails.reset_mock()
    mock_module.secrets.SecretsClient.reset_mock()

    # Reset return values
    mock_module.config.from_file.return_value = MagicMock()

    yield mock_module


class TestOCIVaultAdapterInit:
    """Tests for adapter initialization."""

    def test_init_success(self, config: ConnectionConfig):
        """Test successful adapter initialization."""
        adapter = OCIVaultAdapter(config)
        assert adapter.config == config
        assert adapter._connected is False

    def test_init_missing_sdk(self, config: ConnectionConfig):
        """Test initialization fails when OCI SDK not installed."""
        # Temporarily remove the mocked oci module
        original_oci = sys.modules.pop("oci", None)
        original_config = sys.modules.pop("oci.config", None)
        original_exceptions = sys.modules.pop("oci.exceptions", None)
        original_vault = sys.modules.pop("oci.vault", None)
        original_models = sys.modules.pop("oci.vault.models", None)
        original_secrets = sys.modules.pop("oci.secrets", None)

        try:
            # Need to reload the adapter module to trigger the ImportError
            import importlib
            import penguin_sal.adapters.oci_vault

            # This should raise AdapterNotInstalledError in __init__
            with pytest.raises(AdapterNotInstalledError) as exc_info:
                OCIVaultAdapter(config)
            assert "oci-vault" in str(exc_info.value)
            assert "oci" in str(exc_info.value)
        finally:
            # Restore mocked modules
            if original_oci is not None:
                sys.modules["oci"] = original_oci
            if original_config is not None:
                sys.modules["oci.config"] = original_config
            if original_exceptions is not None:
                sys.modules["oci.exceptions"] = original_exceptions
            if original_vault is not None:
                sys.modules["oci.vault"] = original_vault
            if original_models is not None:
                sys.modules["oci.vault.models"] = original_models
            if original_secrets is not None:
                sys.modules["oci.secrets"] = original_secrets


class TestOCIVaultAdapterConnection:
    """Tests for connection initialization and authentication."""

    def test_init_connection_success(self, config: ConnectionConfig, mock_oci):
        """Test successful connection initialization."""
        adapter = OCIVaultAdapter(config)
        adapter._init_connection()

        assert adapter._connected is True
        assert adapter._vaults_client is not None
        assert adapter._secrets_client is not None
        assert adapter._compartment_id == "ocid1.compartment.oc1..test"
        assert adapter._vault_id == "ocid1.vault.oc1..test"

    def test_init_connection_missing_compartment_id(self, mock_oci):
        """Test connection fails without compartment_id."""
        config = ConnectionConfig(
            scheme="oci-vault", host="us-ashburn-1", params={}
        )
        adapter = OCIVaultAdapter(config)
        with pytest.raises(ConnectionError) as exc_info:
            adapter._init_connection()
        assert "compartment_id" in str(exc_info.value)

    def test_init_connection_with_config_path(self, mock_oci):
        """Test connection with explicit config file path."""
        config = ConnectionConfig(
            scheme="oci-vault",
            host="us-ashburn-1",
            params={
                "compartment_id": "ocid1.compartment.oc1..test",
                "vault_id": "ocid1.vault.oc1..test",
                "config_path": "/custom/path/config",
                "profile": "custom",
            },
        )
        adapter = OCIVaultAdapter(config)
        adapter._init_connection()

        mock_oci.config.from_file.assert_called_once_with("/custom/path/config", "custom")

    def test_authenticate_success(self, config: ConnectionConfig, mock_oci):
        """Test successful authentication."""
        adapter = OCIVaultAdapter(config)
        adapter._init_connection()

        # Mock vault list response
        mock_vault = MagicMock()
        mock_vault.id = "ocid1.vault.oc1..test"
        mock_response = MagicMock()
        mock_response.data = [mock_vault]
        adapter._vaults_client.list_vaults.return_value = mock_response

        adapter.authenticate()
        adapter._vaults_client.list_vaults.assert_called_once()

    def test_authenticate_no_vaults(self, config: ConnectionConfig, mock_oci):
        """Test authentication fails when no vaults in compartment."""
        adapter = OCIVaultAdapter(config)
        adapter._init_connection()

        # Mock empty vault list
        mock_response = MagicMock()
        mock_response.data = []
        adapter._vaults_client.list_vaults.return_value = mock_response

        with pytest.raises(AuthenticationError) as exc_info:
            adapter.authenticate()
        assert "vaults" in str(exc_info.value).lower()

    def test_authenticate_401_error(self, config: ConnectionConfig, mock_oci):
        """Test authentication fails with 401 error."""
        adapter = OCIVaultAdapter(config)
        adapter._init_connection()

        # Mock 401 error
        error = mock_oci.exceptions.ServiceError()
        error.status = 401
        adapter._vaults_client.list_vaults.side_effect = error

        with pytest.raises(AuthenticationError):
            adapter.authenticate()

    def test_authenticate_403_error(self, config: ConnectionConfig, mock_oci):
        """Test authentication fails with 403 error (insufficient permissions)."""
        adapter = OCIVaultAdapter(config)
        adapter._init_connection()

        # Mock 403 error
        error = mock_oci.exceptions.ServiceError()
        error.status = 403
        adapter._vaults_client.list_vaults.side_effect = error

        with pytest.raises(AuthorizationError):
            adapter.authenticate()


class TestOCIVaultAdapterGet:
    """Tests for secret retrieval."""

    def test_get_success(self, config: ConnectionConfig, mock_oci):
        """Test successful secret retrieval."""
        adapter = OCIVaultAdapter(config)
        adapter._init_connection()

        # Mock secret response
        secret_value = "my-secret-value"
        encoded_value = base64.b64encode(secret_value.encode()).decode()

        mock_content = MagicMock()
        mock_content.content = encoded_value
        mock_content.version_number = 1

        mock_bundle = MagicMock()
        mock_bundle.id = "ocid1.secret.oc1..test"
        mock_bundle.secret_bundle_content = [mock_content]
        mock_bundle.time_created = datetime.now()

        mock_response = MagicMock()
        mock_response.data = mock_bundle

        adapter._secrets_client.get_secret_bundle_by_name.return_value = mock_response

        secret = adapter.get("my-secret")

        assert secret.key == "my-secret"
        assert secret.value == secret_value
        assert secret.version == 1
        assert secret.metadata["secret_bundle_id"] == "ocid1.secret.oc1..test"

    def test_get_dict_value(self, config: ConnectionConfig, mock_oci):
        """Test retrieving secret with dict value."""
        adapter = OCIVaultAdapter(config)
        adapter._init_connection()

        secret_dict = {"username": "admin", "password": "secret"}
        secret_value = json.dumps(secret_dict)
        encoded_value = base64.b64encode(secret_value.encode()).decode()

        mock_content = MagicMock()
        mock_content.content = encoded_value
        mock_content.version_number = 1

        mock_bundle = MagicMock()
        mock_bundle.secret_bundle_content = [mock_content]
        mock_bundle.time_created = datetime.now()

        mock_response = MagicMock()
        mock_response.data = mock_bundle

        adapter._secrets_client.get_secret_bundle_by_name.return_value = mock_response

        secret = adapter.get("my-secret")
        assert secret.value == secret_value

    def test_get_not_found(self, config: ConnectionConfig, mock_oci):
        """Test secret not found error."""
        adapter = OCIVaultAdapter(config)
        adapter._init_connection()

        # Mock 404 error
        error = mock_oci.exceptions.ServiceError()
        error.status = 404
        adapter._secrets_client.get_secret_bundle_by_name.side_effect = error

        with pytest.raises(SecretNotFoundError) as exc_info:
            adapter.get("nonexistent")
        assert exc_info.value.key == "nonexistent"
        assert "oci-vault" in exc_info.value.backend

    def test_get_backend_error(self, config: ConnectionConfig, mock_oci):
        """Test backend error during retrieval."""
        adapter = OCIVaultAdapter(config)
        adapter._init_connection()

        # Mock other error
        error = mock_oci.exceptions.ServiceError()
        error.status = 500
        adapter._secrets_client.get_secret_bundle_by_name.side_effect = error

        with pytest.raises(BackendError) as exc_info:
            adapter.get("my-secret")
        assert "oci-vault" in exc_info.value.backend


class TestOCIVaultAdapterSet:
    """Tests for secret creation/update."""

    def test_set_string_value(self, config: ConnectionConfig, mock_oci):
        """Test storing string secret."""
        adapter = OCIVaultAdapter(config)
        adapter._init_connection()

        # Mock create response
        mock_secret = MagicMock()
        mock_secret.id = "ocid1.secret.oc1..test"
        mock_secret.time_created = datetime.now()

        mock_response = MagicMock()
        mock_response.data = mock_secret

        adapter._vaults_client.create_secret.return_value = mock_response

        secret = adapter.set("my-secret", "my-value")

        assert secret.key == "my-secret"
        assert secret.value == "my-value"
        assert secret.version == 1
        adapter._vaults_client.create_secret.assert_called_once()

    def test_set_bytes_value(self, config: ConnectionConfig, mock_oci):
        """Test storing bytes secret."""
        adapter = OCIVaultAdapter(config)
        adapter._init_connection()

        mock_secret = MagicMock()
        mock_secret.time_created = datetime.now()
        mock_response = MagicMock()
        mock_response.data = mock_secret
        adapter._vaults_client.create_secret.return_value = mock_response

        secret = adapter.set("my-secret", b"my-bytes")

        assert secret.value == "my-bytes"
        adapter._vaults_client.create_secret.assert_called_once()

    def test_set_dict_value(self, config: ConnectionConfig, mock_oci):
        """Test storing dict secret."""
        adapter = OCIVaultAdapter(config)
        adapter._init_connection()

        mock_secret = MagicMock()
        mock_secret.time_created = datetime.now()
        mock_response = MagicMock()
        mock_response.data = mock_secret
        adapter._vaults_client.create_secret.return_value = mock_response

        test_dict = {"key": "value", "nested": {"inner": "data"}}
        secret = adapter.set("my-secret", test_dict)

        # Value should be JSON stringified
        assert isinstance(secret.value, str)
        parsed = json.loads(secret.value)
        assert parsed == test_dict

    def test_set_with_metadata(self, config: ConnectionConfig, mock_oci):
        """Test storing secret with metadata."""
        adapter = OCIVaultAdapter(config)
        adapter._init_connection()

        mock_secret = MagicMock()
        mock_secret.time_created = datetime.now()
        mock_response = MagicMock()
        mock_response.data = mock_secret
        adapter._vaults_client.create_secret.return_value = mock_response

        metadata = {"description": "test secret", "owner": "testuser"}
        secret = adapter.set("my-secret", "value", metadata=metadata)

        assert secret.key == "my-secret"
        adapter._vaults_client.create_secret.assert_called_once()

    def test_set_backend_error(self, config: ConnectionConfig, mock_oci):
        """Test error during secret creation."""
        adapter = OCIVaultAdapter(config)
        adapter._init_connection()

        error = mock_oci.exceptions.ServiceError()
        error.status = 500
        adapter._vaults_client.create_secret.side_effect = error

        with pytest.raises(BackendError):
            adapter.set("my-secret", "value")


class TestOCIVaultAdapterDelete:
    """Tests for secret deletion."""

    def test_delete_success(self, config: ConnectionConfig, mock_oci):
        """Test successful secret deletion."""
        adapter = OCIVaultAdapter(config)
        adapter._init_connection()

        # Mock get response for finding secret ID
        mock_bundle = MagicMock()
        mock_bundle.secret_id = "ocid1.secret.oc1..test"
        mock_response = MagicMock()
        mock_response.data = mock_bundle

        adapter._secrets_client.get_secret_bundle_by_name.return_value = mock_response
        adapter._vaults_client.schedule_secret_deletion.return_value = MagicMock()

        result = adapter.delete("my-secret")

        assert result is True
        adapter._secrets_client.get_secret_bundle_by_name.assert_called_once()
        adapter._vaults_client.schedule_secret_deletion.assert_called_once()

    def test_delete_not_found(self, config: ConnectionConfig, mock_oci):
        """Test deleting non-existent secret returns False."""
        adapter = OCIVaultAdapter(config)
        adapter._init_connection()

        error = mock_oci.exceptions.ServiceError()
        error.status = 404
        adapter._secrets_client.get_secret_bundle_by_name.side_effect = error

        result = adapter.delete("nonexistent")

        assert result is False

    def test_delete_backend_error(self, config: ConnectionConfig, mock_oci):
        """Test backend error during deletion."""
        adapter = OCIVaultAdapter(config)
        adapter._init_connection()

        # Get succeeds, but delete fails
        mock_bundle = MagicMock()
        mock_bundle.secret_id = "ocid1.secret.oc1..test"
        mock_response = MagicMock()
        mock_response.data = mock_bundle

        adapter._secrets_client.get_secret_bundle_by_name.return_value = mock_response

        error = mock_oci.exceptions.ServiceError()
        error.status = 500
        adapter._vaults_client.schedule_secret_deletion.side_effect = error

        with pytest.raises(BackendError):
            adapter.delete("my-secret")


class TestOCIVaultAdapterList:
    """Tests for secret listing."""

    def test_list_success(self, config: ConnectionConfig, mock_oci):
        """Test successful secret listing."""
        adapter = OCIVaultAdapter(config)
        adapter._init_connection()

        # Mock list response
        mock_secret1 = MagicMock()
        mock_secret1.secret_name = "secret-1"
        mock_secret2 = MagicMock()
        mock_secret2.secret_name = "secret-2"

        mock_response = MagicMock()
        mock_response.data = [mock_secret1, mock_secret2]
        mock_response.opc_next_page = None

        adapter._vaults_client.list_secrets.return_value = mock_response

        result = adapter.list()

        assert len(result.keys) == 2
        assert "secret-1" in result.keys
        assert "secret-2" in result.keys
        assert result.cursor is None

    def test_list_with_prefix(self, config: ConnectionConfig, mock_oci):
        """Test listing secrets with prefix filter."""
        adapter = OCIVaultAdapter(config)
        adapter._init_connection()

        # Mock list response
        mock_secret1 = MagicMock()
        mock_secret1.secret_name = "prod-secret-1"
        mock_secret2 = MagicMock()
        mock_secret2.secret_name = "prod-secret-2"
        mock_secret3 = MagicMock()
        mock_secret3.secret_name = "dev-secret-1"

        mock_response = MagicMock()
        mock_response.data = [mock_secret1, mock_secret2, mock_secret3]
        mock_response.opc_next_page = None

        adapter._vaults_client.list_secrets.return_value = mock_response

        result = adapter.list(prefix="prod-")

        assert len(result.keys) == 2
        assert "prod-secret-1" in result.keys
        assert "prod-secret-2" in result.keys

    def test_list_with_limit(self, config: ConnectionConfig, mock_oci):
        """Test listing secrets with limit."""
        adapter = OCIVaultAdapter(config)
        adapter._init_connection()

        secrets = [MagicMock(secret_name=f"secret-{i}") for i in range(5)]

        mock_response = MagicMock()
        mock_response.data = secrets
        mock_response.opc_next_page = None

        adapter._vaults_client.list_secrets.return_value = mock_response

        result = adapter.list(limit=3)

        assert len(result.keys) <= 3

    def test_list_backend_error(self, config: ConnectionConfig, mock_oci):
        """Test backend error during listing."""
        adapter = OCIVaultAdapter(config)
        adapter._init_connection()

        error = mock_oci.exceptions.ServiceError()
        error.status = 500
        adapter._vaults_client.list_secrets.side_effect = error

        with pytest.raises(BackendError):
            adapter.list()


class TestOCIVaultAdapterExists:
    """Tests for secret existence check."""

    def test_exists_true(self, config: ConnectionConfig, mock_oci):
        """Test checking if secret exists."""
        adapter = OCIVaultAdapter(config)
        adapter._init_connection()

        mock_bundle = MagicMock()
        mock_response = MagicMock()
        mock_response.data = mock_bundle

        adapter._secrets_client.get_secret_bundle_by_name.return_value = mock_response

        result = adapter.exists("my-secret")

        assert result is True

    def test_exists_false(self, config: ConnectionConfig, mock_oci):
        """Test checking if non-existent secret returns False."""
        adapter = OCIVaultAdapter(config)
        adapter._init_connection()

        error = mock_oci.exceptions.ServiceError()
        error.status = 404
        adapter._secrets_client.get_secret_bundle_by_name.side_effect = error

        result = adapter.exists("nonexistent")

        assert result is False

    def test_exists_other_error_returns_false(self, config: ConnectionConfig, mock_oci):
        """Test that other errors return False."""
        adapter = OCIVaultAdapter(config)
        adapter._init_connection()

        adapter._secrets_client.get_secret_bundle_by_name.side_effect = Exception("Network error")

        result = adapter.exists("my-secret")

        assert result is False


class TestOCIVaultAdapterHealthCheck:
    """Tests for health check."""

    def test_health_check_success(self, config: ConnectionConfig, mock_oci):
        """Test successful health check."""
        adapter = OCIVaultAdapter(config)
        adapter._init_connection()

        mock_response = MagicMock()
        adapter._vaults_client.list_vaults.return_value = mock_response

        result = adapter.health_check()

        assert result is True

    def test_health_check_failure(self, config: ConnectionConfig, mock_oci):
        """Test health check failure."""
        adapter = OCIVaultAdapter(config)
        adapter._init_connection()

        adapter._vaults_client.list_vaults.side_effect = Exception("Connection failed")

        result = adapter.health_check()

        assert result is False

    def test_health_check_initializes_connection(self, config: ConnectionConfig, mock_oci):
        """Test health check initializes connection if needed."""
        adapter = OCIVaultAdapter(config)
        assert adapter._connected is False

        mock_response = MagicMock()
        adapter._vaults_client = mock_oci.vault.VaultsClient()
        adapter._vaults_client.list_vaults.return_value = mock_response

        # Manually set connection state for this test
        adapter._connected = True
        adapter._compartment_id = "ocid1.compartment.oc1..test"

        result = adapter.health_check()

        assert result is True


class TestOCIVaultAdapterClose:
    """Tests for connection cleanup."""

    def test_close(self, config: ConnectionConfig, mock_oci):
        """Test closing adapter."""
        adapter = OCIVaultAdapter(config)
        adapter._init_connection()

        assert adapter._connected is True
        adapter.close()

        assert adapter._connected is False
        assert adapter._vaults_client is None
        assert adapter._secrets_client is None


class TestOCIVaultAdapterContextManager:
    """Tests for context manager support."""

    def test_context_manager(self, config: ConnectionConfig, mock_oci):
        """Test using adapter as context manager."""
        with OCIVaultAdapter(config) as adapter:
            adapter._init_connection()
            assert adapter._connected is True

        # Adapter should be closed after exiting context
        assert adapter._connected is False
