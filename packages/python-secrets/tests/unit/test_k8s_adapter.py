"""Tests for Kubernetes Secrets adapter."""

from __future__ import annotations

import sys
from datetime import datetime
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from penguin_sal.adapters.k8s_secrets import KubernetesSecretsAdapter
from penguin_sal.core.exceptions import (
    AuthenticationError,
    BackendError,
    ConnectionError,
    SecretNotFoundError,
)
from penguin_sal.core.types import ConnectionConfig, Secret, SecretList


@pytest.fixture
def mock_k8s_module() -> Any:
    """Provide mocked kubernetes module for entire test session."""
    mock_config = MagicMock()
    mock_client = MagicMock()

    class ConfigException(Exception):
        pass

    mock_config.config_exception.ConfigException = ConfigException

    mocks = {
        "kubernetes": MagicMock(config=mock_config, client=mock_client),
        "kubernetes.config": mock_config,
        "kubernetes.client": mock_client,
    }

    with patch.dict(sys.modules, mocks):
        yield mocks


@pytest.fixture
def k8s_config() -> ConnectionConfig:
    """Create a Kubernetes ConnectionConfig."""
    return ConnectionConfig(
        scheme="k8s",
        host="kubernetes.default.svc",
        params={"namespace": "default"},
    )


class TestKubernetesSecretsAdapterInit:
    """Test adapter initialization."""

    def test_init_stores_config_and_namespace(self, k8s_config: ConnectionConfig) -> None:
        adapter = KubernetesSecretsAdapter(k8s_config)
        assert adapter.config is k8s_config
        assert adapter._namespace == "default"
        assert adapter._connected is False

    def test_init_uses_custom_namespace(self) -> None:
        config = ConnectionConfig(
            scheme="k8s",
            host="localhost",
            params={"namespace": "custom-ns"},
        )
        adapter = KubernetesSecretsAdapter(config)
        assert adapter._namespace == "custom-ns"

    def test_init_defaults_namespace(self) -> None:
        config = ConnectionConfig(scheme="k8s", host="localhost")
        adapter = KubernetesSecretsAdapter(config)
        assert adapter._namespace == "default"


class TestInitConnection:
    """Test Kubernetes API client initialization."""

    def test_init_connection_with_kubeconfig_file(
        self, mock_k8s_module: Any, k8s_config: ConnectionConfig
    ) -> None:
        mock_load = MagicMock()
        mock_api = MagicMock()
        sys.modules["kubernetes"].config.load_kube_config = mock_load
        sys.modules["kubernetes"].client.CoreV1Api = lambda: mock_api

        config = ConnectionConfig(
            scheme="k8s",
            host="localhost",
            params={"kubeconfig": "/path/to/config"},
        )
        adapter = KubernetesSecretsAdapter(config)
        adapter._init_connection()

        mock_load.assert_called_once_with(config_file="/path/to/config")
        assert adapter._connected is True
        assert adapter._api_client is mock_api

    def test_init_connection_in_cluster(
        self, mock_k8s_module: Any, k8s_config: ConnectionConfig
    ) -> None:
        mock_in_cluster = MagicMock()
        mock_api = MagicMock()
        sys.modules["kubernetes"].config.load_incluster_config = mock_in_cluster
        sys.modules["kubernetes"].client.CoreV1Api = lambda: mock_api

        adapter = KubernetesSecretsAdapter(k8s_config)
        adapter._init_connection()

        mock_in_cluster.assert_called_once()
        assert adapter._connected is True

    def test_init_connection_fallback_to_default_kubeconfig(
        self, mock_k8s_module: Any, k8s_config: ConnectionConfig
    ) -> None:
        # Create a proper ConfigException for the fallback test
        config_exc = sys.modules["kubernetes"].config.config_exception.ConfigException(
            "Not in cluster"
        )
        mock_in_cluster = MagicMock(side_effect=config_exc)
        mock_load = MagicMock()
        mock_api = MagicMock()
        sys.modules["kubernetes"].config.load_incluster_config = mock_in_cluster
        sys.modules["kubernetes"].config.load_kube_config = mock_load
        sys.modules["kubernetes"].client.CoreV1Api = lambda: mock_api

        adapter = KubernetesSecretsAdapter(k8s_config)
        adapter._init_connection()

        mock_load.assert_called_once()
        assert adapter._connected is True

    def test_init_connection_raises_import_error(
        self, k8s_config: ConnectionConfig
    ) -> None:
        with patch.dict(sys.modules, {"kubernetes": None}):
            adapter = KubernetesSecretsAdapter(k8s_config)
            with pytest.raises(
                ConnectionError, match="kubernetes client not installed"
            ):
                adapter._init_connection()


class TestAuthenticate:
    """Test authentication."""

    def test_authenticate_success(
        self, mock_k8s_module: Any, k8s_config: ConnectionConfig
    ) -> None:
        mock_api = MagicMock()
        mock_api.list_namespace.return_value = MagicMock()
        sys.modules["kubernetes"].config.load_incluster_config = MagicMock()
        sys.modules["kubernetes"].client.CoreV1Api = lambda: mock_api

        adapter = KubernetesSecretsAdapter(k8s_config)
        adapter.authenticate()

        mock_api.list_namespace.assert_called_once()

    def test_authenticate_raises_authentication_error(
        self, mock_k8s_module: Any, k8s_config: ConnectionConfig
    ) -> None:
        mock_api = MagicMock()
        api_err = Exception("Unauthorized")
        api_err.status = 401  # type: ignore[attr-defined]
        mock_api.list_namespace.side_effect = api_err
        sys.modules["kubernetes"].config.load_incluster_config = MagicMock()
        sys.modules["kubernetes"].client.CoreV1Api = lambda: mock_api

        adapter = KubernetesSecretsAdapter(k8s_config)
        with pytest.raises(AuthenticationError):
            adapter.authenticate()


class TestGet:
    """Test retrieving secrets."""

    def test_get_single_value_secret(
        self, mock_k8s_module: Any, k8s_config: ConnectionConfig
    ) -> None:
        import base64

        mock_api = MagicMock()
        k8s_secret = MagicMock()
        k8s_secret.data = {"password": base64.b64encode(b"secret123").decode()}
        k8s_secret.metadata = MagicMock()
        k8s_secret.metadata.resource_version = "1000"
        k8s_secret.metadata.creation_timestamp = datetime(2025, 1, 1)
        k8s_secret.metadata.managed_fields = [MagicMock(time=datetime(2025, 1, 2))]
        mock_api.read_namespaced_secret.return_value = k8s_secret

        sys.modules["kubernetes"].config.load_incluster_config = MagicMock()
        sys.modules["kubernetes"].client.CoreV1Api = lambda: mock_api

        adapter = KubernetesSecretsAdapter(k8s_config)
        adapter._init_connection()
        secret = adapter.get("my-secret")

        assert secret.key == "my-secret"
        assert secret.value == "secret123"
        assert secret.version == 1000

    def test_get_dict_secret(
        self, mock_k8s_module: Any, k8s_config: ConnectionConfig
    ) -> None:
        import base64

        mock_api = MagicMock()
        k8s_secret = MagicMock()
        k8s_secret.data = {
            "username": base64.b64encode(b"admin").decode(),
            "password": base64.b64encode(b"pass123").decode(),
        }
        k8s_secret.metadata = MagicMock()
        k8s_secret.metadata.resource_version = "1000"
        k8s_secret.metadata.creation_timestamp = datetime(2025, 1, 1)
        k8s_secret.metadata.managed_fields = [MagicMock(time=datetime(2025, 1, 2))]
        mock_api.read_namespaced_secret.return_value = k8s_secret

        sys.modules["kubernetes"].config.load_incluster_config = MagicMock()
        sys.modules["kubernetes"].client.CoreV1Api = lambda: mock_api

        adapter = KubernetesSecretsAdapter(k8s_config)
        adapter._init_connection()
        secret = adapter.get("my-secret")

        assert secret.key == "my-secret"
        assert isinstance(secret.value, dict)
        assert secret.value == {"username": "admin", "password": "pass123"}

    def test_get_with_metadata_labels(
        self, mock_k8s_module: Any, k8s_config: ConnectionConfig
    ) -> None:
        import base64

        mock_api = MagicMock()
        k8s_secret = MagicMock()
        k8s_secret.data = {"data": base64.b64encode(b"secret").decode()}
        k8s_secret.metadata = MagicMock()
        k8s_secret.metadata.resource_version = "1000"
        k8s_secret.metadata.creation_timestamp = datetime(2025, 1, 1)
        k8s_secret.metadata.managed_fields = [MagicMock(time=datetime(2025, 1, 2))]
        k8s_secret.metadata.labels = {"env": "prod", "owner": "app"}
        mock_api.read_namespaced_secret.return_value = k8s_secret

        sys.modules["kubernetes"].config.load_incluster_config = MagicMock()
        sys.modules["kubernetes"].client.CoreV1Api = lambda: mock_api

        adapter = KubernetesSecretsAdapter(k8s_config)
        adapter._init_connection()
        secret = adapter.get("my-secret")

        assert secret.metadata == {"env": "prod", "owner": "app"}

    def test_get_not_found(
        self, mock_k8s_module: Any, k8s_config: ConnectionConfig
    ) -> None:
        mock_api = MagicMock()
        api_err = Exception("Not found")
        api_err.status = 404  # type: ignore[attr-defined]
        mock_api.read_namespaced_secret.side_effect = api_err

        sys.modules["kubernetes"].config.load_incluster_config = MagicMock()
        sys.modules["kubernetes"].client.CoreV1Api = lambda: mock_api

        adapter = KubernetesSecretsAdapter(k8s_config)
        adapter._init_connection()
        with pytest.raises(SecretNotFoundError, match="my-secret"):
            adapter.get("my-secret")


class TestSet:
    """Test creating/updating secrets."""

    def test_set_string_value_create(
        self, mock_k8s_module: Any, k8s_config: ConnectionConfig
    ) -> None:
        mock_api = MagicMock()
        api_err = MagicMock()
        api_err.status = 404
        mock_api.read_namespaced_secret.side_effect = api_err
        mock_result = MagicMock()
        mock_result.metadata = MagicMock()
        mock_result.metadata.resource_version = "1001"
        mock_result.metadata.creation_timestamp = datetime(2025, 1, 1)
        mock_api.create_namespaced_secret.return_value = mock_result

        sys.modules["kubernetes"].config.load_incluster_config = MagicMock()
        sys.modules["kubernetes"].client.CoreV1Api = lambda: mock_api
        sys.modules["kubernetes"].client.V1Secret = MagicMock
        sys.modules["kubernetes"].client.V1ObjectMeta = MagicMock

        adapter = KubernetesSecretsAdapter(k8s_config)
        secret = adapter.set("my-secret", "my-value")

        assert secret.key == "my-secret"
        assert secret.value == "my-value"

    def test_set_dict_value_patch(
        self, mock_k8s_module: Any, k8s_config: ConnectionConfig
    ) -> None:
        mock_api = MagicMock()
        mock_api.read_namespaced_secret.return_value = MagicMock()
        mock_result = MagicMock()
        mock_result.metadata = MagicMock()
        mock_result.metadata.resource_version = "1001"
        mock_result.metadata.creation_timestamp = datetime(2025, 1, 1)
        mock_api.patch_namespaced_secret.return_value = mock_result

        sys.modules["kubernetes"].config.load_incluster_config = MagicMock()
        sys.modules["kubernetes"].client.CoreV1Api = lambda: mock_api
        sys.modules["kubernetes"].client.V1Secret = MagicMock
        sys.modules["kubernetes"].client.V1ObjectMeta = MagicMock

        adapter = KubernetesSecretsAdapter(k8s_config)
        secret = adapter.set(
            "my-secret",
            {"username": "admin", "password": "pass123"},
        )

        assert secret.key == "my-secret"


class TestDelete:
    """Test deleting secrets."""

    def test_delete_success(
        self, mock_k8s_module: Any, k8s_config: ConnectionConfig
    ) -> None:
        mock_api = MagicMock()
        mock_api.delete_namespaced_secret.return_value = MagicMock()

        sys.modules["kubernetes"].config.load_incluster_config = MagicMock()
        sys.modules["kubernetes"].client.CoreV1Api = lambda: mock_api

        adapter = KubernetesSecretsAdapter(k8s_config)
        result = adapter.delete("my-secret")

        assert result is True
        mock_api.delete_namespaced_secret.assert_called_once_with(
            "my-secret", "default"
        )

    def test_delete_not_found(
        self, mock_k8s_module: Any, k8s_config: ConnectionConfig
    ) -> None:
        mock_api = MagicMock()
        api_err = Exception("Not found")
        api_err.status = 404  # type: ignore[attr-defined]
        mock_api.delete_namespaced_secret.side_effect = api_err

        sys.modules["kubernetes"].config.load_incluster_config = MagicMock()
        sys.modules["kubernetes"].client.CoreV1Api = lambda: mock_api

        adapter = KubernetesSecretsAdapter(k8s_config)
        result = adapter.delete("my-secret")

        assert result is False


class TestList:
    """Test listing secrets."""

    def test_list_all_secrets(
        self, mock_k8s_module: Any, k8s_config: ConnectionConfig
    ) -> None:
        mock_api = MagicMock()
        item1 = MagicMock()
        item1.metadata = MagicMock()
        item1.metadata.name = "secret1"
        item2 = MagicMock()
        item2.metadata = MagicMock()
        item2.metadata.name = "secret2"

        secret_list = MagicMock()
        secret_list.items = [item1, item2]
        mock_api.list_namespaced_secret.return_value = secret_list

        sys.modules["kubernetes"].config.load_incluster_config = MagicMock()
        sys.modules["kubernetes"].client.CoreV1Api = lambda: mock_api

        adapter = KubernetesSecretsAdapter(k8s_config)
        result = adapter.list()

        assert isinstance(result, SecretList)
        assert result.keys == ["secret1", "secret2"]

    def test_list_with_prefix(
        self, mock_k8s_module: Any, k8s_config: ConnectionConfig
    ) -> None:
        mock_api = MagicMock()
        item1 = MagicMock()
        item1.metadata = MagicMock()
        item1.metadata.name = "app-secret"
        item2 = MagicMock()
        item2.metadata = MagicMock()
        item2.metadata.name = "db-secret"

        secret_list = MagicMock()
        secret_list.items = [item1, item2]
        mock_api.list_namespaced_secret.return_value = secret_list

        sys.modules["kubernetes"].config.load_incluster_config = MagicMock()
        sys.modules["kubernetes"].client.CoreV1Api = lambda: mock_api

        adapter = KubernetesSecretsAdapter(k8s_config)
        result = adapter.list(prefix="app-")

        assert result.keys == ["app-secret"]

    def test_list_with_limit(
        self, mock_k8s_module: Any, k8s_config: ConnectionConfig
    ) -> None:
        mock_api = MagicMock()
        items = [MagicMock(metadata=MagicMock(name=f"secret{i}")) for i in range(5)]
        secret_list = MagicMock()
        secret_list.items = items
        mock_api.list_namespaced_secret.return_value = secret_list

        sys.modules["kubernetes"].config.load_incluster_config = MagicMock()
        sys.modules["kubernetes"].client.CoreV1Api = lambda: mock_api

        adapter = KubernetesSecretsAdapter(k8s_config)
        result = adapter.list(limit=3)

        assert len(result.keys) == 3


class TestExists:
    """Test checking if secret exists."""

    def test_exists_true(
        self, mock_k8s_module: Any, k8s_config: ConnectionConfig
    ) -> None:
        mock_api = MagicMock()
        mock_api.read_namespaced_secret.return_value = MagicMock()

        sys.modules["kubernetes"].config.load_incluster_config = MagicMock()
        sys.modules["kubernetes"].client.CoreV1Api = lambda: mock_api

        adapter = KubernetesSecretsAdapter(k8s_config)
        result = adapter.exists("my-secret")

        assert result is True

    def test_exists_false(
        self, mock_k8s_module: Any, k8s_config: ConnectionConfig
    ) -> None:
        mock_api = MagicMock()
        api_err = Exception("Not found")
        api_err.status = 404  # type: ignore[attr-defined]
        mock_api.read_namespaced_secret.side_effect = api_err

        sys.modules["kubernetes"].config.load_incluster_config = MagicMock()
        sys.modules["kubernetes"].client.CoreV1Api = lambda: mock_api

        adapter = KubernetesSecretsAdapter(k8s_config)
        result = adapter.exists("my-secret")

        assert result is False


class TestHealthCheck:
    """Test health check."""

    def test_health_check_success(
        self, mock_k8s_module: Any, k8s_config: ConnectionConfig
    ) -> None:
        mock_api = MagicMock()
        mock_api.list_namespace.return_value = MagicMock()

        sys.modules["kubernetes"].config.load_incluster_config = MagicMock()
        sys.modules["kubernetes"].client.CoreV1Api = lambda: mock_api

        adapter = KubernetesSecretsAdapter(k8s_config)
        result = adapter.health_check()

        assert result is True

    def test_health_check_failure(
        self, mock_k8s_module: Any, k8s_config: ConnectionConfig
    ) -> None:
        mock_api = MagicMock()
        mock_api.list_namespace.side_effect = Exception("Connection failed")

        sys.modules["kubernetes"].config.load_incluster_config = MagicMock()
        sys.modules["kubernetes"].client.CoreV1Api = lambda: mock_api

        adapter = KubernetesSecretsAdapter(k8s_config)
        result = adapter.health_check()

        assert result is False


class TestClose:
    """Test closing the adapter."""

    def test_close(self, mock_k8s_module: Any, k8s_config: ConnectionConfig) -> None:
        sys.modules["kubernetes"].config.load_incluster_config = MagicMock()
        sys.modules["kubernetes"].client.CoreV1Api = lambda: MagicMock()

        adapter = KubernetesSecretsAdapter(k8s_config)
        adapter._init_connection()
        assert adapter._connected is True

        adapter.close()
        assert adapter._connected is False
        assert adapter._api_client is None


class TestContextManager:
    """Test context manager support."""

    def test_with_statement(
        self, mock_k8s_module: Any, k8s_config: ConnectionConfig
    ) -> None:
        sys.modules["kubernetes"].config.load_incluster_config = MagicMock()
        sys.modules["kubernetes"].client.CoreV1Api = lambda: MagicMock()

        with KubernetesSecretsAdapter(k8s_config) as adapter:
            assert isinstance(adapter, KubernetesSecretsAdapter)
