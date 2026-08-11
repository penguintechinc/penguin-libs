"""Kubernetes Secrets adapter for penguin-sal."""

from __future__ import annotations

import base64
from datetime import UTC, datetime
from typing import Any

from penguin_sal.core.base_adapter import BaseAdapter
from penguin_sal.core.exceptions import (
    AuthenticationError,
    BackendError,
    ConnectionError,
    SecretNotFoundError,
)
from penguin_sal.core.types import ConnectionConfig, Secret, SecretList


class KubernetesSecretsAdapter(BaseAdapter):
    """Adapter for Kubernetes Secrets backend.

    Manages secrets stored as Kubernetes Secret objects in a specific
    namespace. Supports reading kubeconfig from file or using in-cluster
    authentication. Custom metadata is stored as Secret labels.
    """

    def __init__(self, config: ConnectionConfig) -> None:
        """Initialize the Kubernetes Secrets adapter.

        Args:
            config: ConnectionConfig with optional params:
                - kubeconfig: Path to kubeconfig file (uses in-cluster if not set)
                - namespace: K8s namespace to store secrets (default: "default")
        """
        super().__init__(config)
        self._api_client: Any = None
        self._namespace: str = config.params.get("namespace", "default")

    def _init_connection(self, **kwargs: Any) -> None:
        """Initialize the Kubernetes API client connection.

        Tries kubeconfig from params, then in-cluster config, then default
        kubeconfig location. Imports kubernetes dynamically to support
        optional dependency.

        Raises:
            ConnectionError: If unable to load any kubeconfig or in-cluster config.
        """
        try:
            from kubernetes import client
            from kubernetes import config as k8s_config
        except ImportError as e:
            raise ConnectionError(
                "kubernetes client not installed. "
                "Install with: pip install penguin-sal[k8s]"
            ) from e

        kubeconfig_path = self.config.params.get("kubeconfig")

        try:
            if kubeconfig_path:
                k8s_config.load_kube_config(config_file=kubeconfig_path)
            else:
                # Try in-cluster first, then fall back to default kubeconfig
                try:
                    k8s_config.load_incluster_config()
                except k8s_config.config_exception.ConfigException:
                    k8s_config.load_kube_config()
        except Exception as e:
            raise ConnectionError(
                f"Failed to load Kubernetes configuration: {e}"
            ) from e

        self._api_client = client.CoreV1Api()
        self._connected = True

    def authenticate(self) -> None:
        """Authenticate with Kubernetes by listing namespaces.

        Verifies the API client can communicate with the cluster.

        Raises:
            AuthenticationError: If unable to list namespaces.
            ConnectionError: If the cluster is unreachable.
        """
        if not self._connected or not self._api_client:
            self._init_connection()

        try:
            self._api_client.list_namespace()
        except Exception as e:
            self._raise_for_api_exception(e, "Failed to authenticate")

    def get(self, key: str, version: int | None = None) -> Secret:
        """Retrieve a Kubernetes Secret by name.

        Args:
            key: The secret name.
            version: Ignored (K8s uses resourceVersion, not semantic versions).

        Returns:
            Secret with decoded data. If the K8s secret has multiple keys,
            returns dict of all keys. If single key, returns that value.

        Raises:
            SecretNotFoundError: If the secret does not exist.
            BackendError: If the API call fails.
        """
        try:
            k8s_secret = self._api_client.read_namespaced_secret(
                key, self._namespace
            )
        except Exception as e:
            self._raise_for_api_exception(
                e, f"Failed to retrieve secret '{key}'", key
            )

        # Decode base64 data
        decoded_data: dict[str, Any] = {}
        if k8s_secret.data:
            for k, v in k8s_secret.data.items():
                try:
                    decoded_data[k] = base64.b64decode(v).decode("utf-8")
                except (ValueError, UnicodeDecodeError):
                    decoded_data[k] = v

        # If single key, return value directly; otherwise return dict
        if len(decoded_data) == 1:
            value = list(decoded_data.values())[0]
        else:
            value = decoded_data

        # Extract metadata from labels
        metadata = {}
        if k8s_secret.metadata and k8s_secret.metadata.labels:
            metadata = dict(k8s_secret.metadata.labels)

        return Secret(
            key=key,
            value=value,
            version=int(k8s_secret.metadata.resource_version or 0)
            if k8s_secret.metadata
            else None,
            created_at=k8s_secret.metadata.creation_timestamp
            if k8s_secret.metadata
            else None,
            updated_at=k8s_secret.metadata.managed_fields[-1].time
            if k8s_secret.metadata and k8s_secret.metadata.managed_fields
            else None,
            metadata=metadata if metadata else None,
        )

    def set(
        self,
        key: str,
        value: str | bytes | dict[str, Any],
        metadata: dict[str, Any] | None = None,
    ) -> Secret:
        """Create or update a Kubernetes Secret.

        Args:
            key: The secret name.
            value: String, bytes, or dict of key-value pairs.
            metadata: Dict stored as Secret labels.

        Returns:
            Secret reflecting the stored state.

        Raises:
            BackendError: If the API call fails.
        """
        try:
            from kubernetes import client
        except ImportError as e:
            raise BackendError("kubernetes not installed", backend="k8s") from e

        if not self._connected or not self._api_client:
            self._init_connection()

        # Prepare data dict
        if isinstance(value, dict):
            data_dict = {k: str(v) for k, v in value.items()}
        elif isinstance(value, bytes):
            data_dict = {"data": value.decode("utf-8")}
        else:
            data_dict = {"data": value}

        # Encode data as base64
        encoded_data = {
            k: base64.b64encode(v.encode("utf-8")).decode("utf-8")
            if isinstance(v, str)
            else base64.b64encode(v).decode("utf-8")
            for k, v in data_dict.items()
        }

        # Build labels from metadata
        labels = dict(metadata) if metadata else {}

        k8s_secret = client.V1Secret(
            api_version="v1",
            kind="Secret",
            metadata=client.V1ObjectMeta(
                name=key, namespace=self._namespace, labels=labels or None
            ),
            data=encoded_data,
        )

        try:
            # Try to get existing secret
            self._api_client.read_namespaced_secret(key, self._namespace)
            # Update if exists
            result = self._api_client.patch_namespaced_secret(
                key, self._namespace, k8s_secret
            )
        except Exception as e:
            # Check if it's 404 (not found)
            if hasattr(e, "status") and e.status == 404:  # type: ignore[attr-defined]
                # Create if doesn't exist
                try:
                    result = self._api_client.create_namespaced_secret(
                        self._namespace, k8s_secret
                    )
                except Exception as create_err:
                    self._raise_for_api_exception(
                        create_err, f"Failed to create secret '{key}'"
                    )
            else:
                self._raise_for_api_exception(
                    e, f"Failed to set secret '{key}'"
                )

        return Secret(
            key=key,
            value=value,
            version=int(result.metadata.resource_version or 0)
            if result.metadata
            else None,
            created_at=result.metadata.creation_timestamp
            if result.metadata
            else None,
            updated_at=datetime.now(UTC),
            metadata=labels if labels else None,
        )

    def delete(self, key: str) -> bool:
        """Delete a Kubernetes Secret.

        Args:
            key: The secret name.

        Returns:
            True if deleted, False if not found.

        Raises:
            BackendError: If the API call fails (except 404).
        """
        if not self._connected or not self._api_client:
            self._init_connection()

        try:
            self._api_client.delete_namespaced_secret(key, self._namespace)
            return True
        except Exception as e:
            if hasattr(e, "status") and e.status == 404:  # type: ignore[attr-defined]
                return False
            self._raise_for_api_exception(
                e, f"Failed to delete secret '{key}'"
            )

    def list(self, prefix: str = "", limit: int | None = None) -> SecretList:
        """List Kubernetes Secrets in the namespace.

        Args:
            prefix: Filter by secret name prefix.
            limit: Maximum number of secrets to return.

        Returns:
            SecretList with matching secret names.

        Raises:
            BackendError: If the API call fails.
        """
        if not self._connected or not self._api_client:
            self._init_connection()

        try:
            secrets = self._api_client.list_namespaced_secret(self._namespace)
        except Exception as e:
            self._raise_for_api_exception(e, "Failed to list secrets")

        keys = [
            item.metadata.name
            for item in (secrets.items or [])
            if item.metadata and item.metadata.name
            and (not prefix or item.metadata.name.startswith(prefix))
        ]

        if limit:
            keys = keys[:limit]

        return SecretList(keys=keys, cursor=None)

    def exists(self, key: str) -> bool:
        """Check if a Kubernetes Secret exists.

        Args:
            key: The secret name.

        Returns:
            True if the secret exists.
        """
        if not self._connected or not self._api_client:
            self._init_connection()

        try:
            self._api_client.read_namespaced_secret(key, self._namespace)
            return True
        except Exception as e:
            if hasattr(e, "status") and e.status == 404:  # type: ignore[attr-defined]
                return False
            # Ignore other errors and return False
            return False

    def health_check(self) -> bool:
        """Check Kubernetes cluster health by listing namespaces.

        Returns:
            True if the cluster is reachable and responsive.
        """
        if not self._api_client:
            try:
                self._init_connection()
            except (ConnectionError, AuthenticationError):
                return False

        try:
            self._api_client.list_namespace()
            return True
        except Exception:
            return False

    def close(self) -> None:
        """Close the API client connection."""
        self._api_client = None
        self._connected = False

    def _raise_for_api_exception(
        self,
        exc: Exception,
        message: str,
        secret_key: str | None = None,
    ) -> None:
        """Raise appropriate penguin-sal exception for Kubernetes API error.

        Args:
            exc: The original exception from kubernetes client.
            message: Error message to include.
            secret_key: Secret key if applicable (for SecretNotFoundError).

        Raises:
            SecretNotFoundError: If status 404.
            AuthenticationError: If status 401.
            BackendError: For all other errors.
        """
        if hasattr(exc, "status"):
            status = exc.status  # type: ignore[attr-defined]
            if status == 404:
                if secret_key:
                    raise SecretNotFoundError(secret_key, backend="k8s")
                raise SecretNotFoundError("unknown", backend="k8s")
            if status == 401:
                raise AuthenticationError(message)

        raise BackendError(message, backend="k8s", original_error=exc)
