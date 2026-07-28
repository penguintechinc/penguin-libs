"""GCP Secret Manager adapter for penguin-sal."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

from penguin_sal.core.base_adapter import BaseAdapter
from penguin_sal.core.exceptions import (
    AuthenticationError,
    AuthorizationError,
    BackendError,
    ConnectionError,
    SecretNotFoundError,
)
from penguin_sal.core.types import ConnectionConfig, Secret, SecretList


class GCPSecretManagerAdapter(BaseAdapter):
    """Adapter for Google Cloud Secret Manager.

    Requires:
        - google-cloud-secret-manager
        - GCP credentials (via GOOGLE_APPLICATION_CREDENTIALS env var or ADC)

    URI scheme: gcp-sm://host/path?project=PROJECT_ID
    Example: gcp-sm://secretmanager.googleapis.com?project=my-gcp-project
    """

    def __init__(self, config: ConnectionConfig) -> None:
        """Initialize GCP Secret Manager adapter.

        Args:
            config: Connection configuration with params['project'] required.

        Raises:
            ValueError: If project ID is missing from params.
        """
        super().__init__(config)
        if "project" not in config.params:
            raise ValueError("GCP project ID is required in URI params (project=...)")
        self._project = f"projects/{config.params['project']}"
        self._client: Any = None

    def _init_connection(self, **kwargs: Any) -> None:
        """Initialize the GCP Secret Manager client.

        Args:
            **kwargs: Additional arguments (unused, for compatibility).

        Raises:
            ConnectionError: If client initialization fails.
        """
        try:
            from google.cloud import secretmanager

            self._client = secretmanager.SecretManagerServiceClient()
            self._connected = True
        except ImportError as e:
            raise ConnectionError(
                "google-cloud-secret-manager is required. "
                "Install with: pip install penguin-sal[gcp]"
            ) from e
        except Exception as e:
            raise ConnectionError(f"Failed to initialize GCP Secret Manager client: {e}") from e

    def authenticate(self) -> None:
        """Authenticate with GCP Secret Manager.

        Verifies credentials by listing secrets with page_size=1.

        Raises:
            AuthenticationError: If credentials are invalid.
            AuthorizationError: If lacking permissions.
            ConnectionError: If the backend is unreachable.
        """
        if not self._connected:
            self._init_connection()

        try:
            from google.api_core.exceptions import PermissionDenied, Unauthenticated

            # Verify authentication by listing secrets
            self._client.list_secrets(request={"parent": self._project, "page_size": 1})
        except Unauthenticated as e:
            raise AuthenticationError(f"GCP authentication failed: {e}") from e
        except PermissionDenied as e:
            raise AuthorizationError(
                f"Insufficient GCP permissions for project {self._project}: {e}"
            ) from e
        except Exception as e:
            raise ConnectionError(f"GCP connection failed: {e}") from e

    def get(self, key: str, version: int | None = None) -> Secret:
        """Retrieve a secret from GCP Secret Manager.

        Args:
            key: The secret name (key).
            version: Optional specific version number (default: "latest").

        Returns:
            Secret object with value, version, and timestamps.

        Raises:
            SecretNotFoundError: If the secret does not exist.
            BackendError: If retrieval fails.
        """
        if not self._connected:
            self._init_connection()

        try:
            from google.api_core.exceptions import NotFound, PermissionDenied

            version_str = str(version) if version is not None else "latest"
            secret_version_name = f"{self._project}/secrets/{key}/versions/{version_str}"

            response = self._client.access_secret_version(
                request={"name": secret_version_name}
            )

            # Parse payload
            value: str | bytes | dict[str, Any]
            if response.payload.data:
                raw_value = response.payload.data
                try:
                    value = json.loads(raw_value.decode("utf-8"))
                except (json.JSONDecodeError, UnicodeDecodeError):
                    value = raw_value

            # Extract version number from name
            version_num = int(response.name.split("/versions/")[-1])

            # Build metadata
            metadata: dict[str, Any] = {}
            if hasattr(response, "create_time") and response.create_time:
                metadata["created_at"] = response.create_time.isoformat()

            return Secret(
                key=key,
                value=value,
                version=version_num,
                created_at=response.create_time.astimezone(UTC) if response.create_time else None,
                metadata=metadata,
            )
        except NotFound:
            raise SecretNotFoundError(key, backend="gcp-sm")
        except PermissionDenied as e:
            raise AuthorizationError(f"Permission denied accessing secret {key}: {e}") from e
        except Exception as e:
            raise BackendError(
                f"Failed to retrieve secret {key}",
                backend="gcp-sm",
                original_error=e,
            ) from e

    def set(
        self,
        key: str,
        value: str | bytes | dict[str, Any],
        metadata: dict[str, Any] | None = None,
    ) -> Secret:
        """Create or update a secret in GCP Secret Manager.

        Args:
            key: The secret name.
            value: The secret value (str, bytes, or dict).
            metadata: Optional metadata (stored as labels).

        Returns:
            Secret object reflecting the stored state.

        Raises:
            BackendError: If creation/update fails.
        """
        if not self._connected:
            self._init_connection()

        try:
            from google.api_core.exceptions import AlreadyExists, PermissionDenied

            # Encode payload
            if isinstance(value, dict):
                payload = json.dumps(value).encode("utf-8")
            elif isinstance(value, bytes):
                payload = value
            else:
                payload = str(value).encode("utf-8")

            # Check if secret exists
            secret_name = f"{self._project}/secrets/{key}"
            secret_exists = False
            try:
                self._client.get_secret(request={"name": secret_name})
                secret_exists = True
            except Exception:
                pass

            # Create secret if it doesn't exist
            if not secret_exists:
                try:
                    self._client.create_secret(
                        request={
                            "parent": self._project,
                            "secret_id": key,
                            "secret": {"labels": metadata or {}},
                        }
                    )
                except AlreadyExists:
                    pass

            # Add or update secret version
            response = self._client.add_secret_version(
                request={"parent": secret_name, "payload": {"data": payload}}
            )

            # Extract version number
            version_num = int(response.name.split("/versions/")[-1])

            return Secret(
                key=key,
                value=value,
                version=version_num,
                created_at=datetime.now(UTC),
                metadata=metadata or {},
            )
        except PermissionDenied as e:
            raise AuthorizationError(f"Permission denied updating secret {key}: {e}") from e
        except Exception as e:
            raise BackendError(
                f"Failed to update secret {key}",
                backend="gcp-sm",
                original_error=e,
            ) from e

    def delete(self, key: str) -> bool:
        """Delete a secret from GCP Secret Manager.

        Args:
            key: The secret name.

        Returns:
            True if deleted, False if not found.

        Raises:
            BackendError: If deletion fails.
        """
        if not self._connected:
            self._init_connection()

        try:
            from google.api_core.exceptions import NotFound, PermissionDenied

            secret_name = f"{self._project}/secrets/{key}"
            self._client.delete_secret(request={"name": secret_name})
            return True
        except NotFound:
            return False
        except PermissionDenied as e:
            raise AuthorizationError(f"Permission denied deleting secret {key}: {e}") from e
        except Exception as e:
            raise BackendError(
                f"Failed to delete secret {key}",
                backend="gcp-sm",
                original_error=e,
            ) from e

    def list(self, prefix: str = "", limit: int | None = None) -> SecretList:
        """List secret names in GCP Secret Manager.

        Args:
            prefix: Filter secrets by name prefix.
            limit: Maximum number of secrets to return.

        Returns:
            SecretList with matching secret names.

        Raises:
            BackendError: If listing fails.
        """
        if not self._connected:
            self._init_connection()

        try:
            from google.api_core.exceptions import PermissionDenied

            page_size = limit if limit and limit > 0 else 100
            request = {"parent": self._project, "page_size": page_size}

            # Use filter for prefix if provided
            if prefix:
                # GCP Secret Manager filter syntax: name:prefix
                request["filter"] = f"name:{prefix}*"

            secrets = self._client.list_secrets(request=request)

            keys: list[str] = []
            cursor: str | None = None

            for i, secret in enumerate(secrets):
                if limit and i >= limit:
                    break
                # Extract secret name from resource name (projects/{proj}/secrets/{name})
                secret_name = secret.name.split("/secrets/")[-1]
                if not prefix or secret_name.startswith(prefix):
                    keys.append(secret_name)

            return SecretList(keys=keys, cursor=cursor)
        except PermissionDenied as e:
            raise AuthorizationError(f"Permission denied listing secrets: {e}") from e
        except Exception as e:
            raise BackendError("Failed to list secrets", backend="gcp-sm", original_error=e) from e

    def exists(self, key: str) -> bool:
        """Check if a secret exists in GCP Secret Manager.

        Args:
            key: The secret name.

        Returns:
            True if the secret exists, False otherwise.
        """
        if not self._connected:
            self._init_connection()

        try:
            from google.api_core.exceptions import NotFound

            secret_name = f"{self._project}/secrets/{key}"
            self._client.get_secret(request={"name": secret_name})
            return True
        except NotFound:
            return False
        except Exception:
            # On other errors, assume doesn't exist rather than crashing
            return False

    def health_check(self) -> bool:
        """Check if GCP Secret Manager is reachable and healthy.

        Returns:
            True if healthy, False otherwise.
        """
        if not self._connected:
            try:
                self._init_connection()
            except Exception:
                return False

        try:
            from google.api_core.exceptions import PermissionDenied, Unauthenticated

            # Try listing with page_size=1
            self._client.list_secrets(request={"parent": self._project, "page_size": 1})
            return True
        except (Unauthenticated, PermissionDenied):
            # Auth errors still mean the service is reachable
            return True
        except Exception:
            return False

    def close(self) -> None:
        """Close the GCP Secret Manager client connection."""
        if self._client:
            try:
                self._client.transport.close()
            except Exception:
                pass
        self._connected = False
