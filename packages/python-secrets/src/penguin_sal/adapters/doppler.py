"""Doppler secrets adapter for penguin-sal."""

from __future__ import annotations

from typing import Any

from penguin_sal.core.base_adapter import BaseAdapter
from penguin_sal.core.exceptions import (
    AuthenticationError,
    BackendError,
    ConnectionError,
    SecretNotFoundError,
)
from penguin_sal.core.types import ConnectionConfig, Secret, SecretList


class DopplerAdapter(BaseAdapter):
    """Adapter for Doppler secrets management platform.

    Configuration parameters:
    - config.password: Doppler service token (or use params["token"])
    - config.params["token"]: Alternative location for Doppler service token
    - config.params["project"]: Doppler project name (required)
    - config.params.get("config", "dev"): Doppler config/environment name
    """

    def __init__(self, config: ConnectionConfig) -> None:
        super().__init__(config)
        self._client: Any = None
        self._project: str | None = None
        self._config_name: str | None = None

    def _init_connection(self, **kwargs: Any) -> None:
        """Initialize the Doppler SDK client.

        Raises:
            ImportError: If dopplersdk is not installed.
        """
        try:
            import dopplersdk
        except ImportError as e:
            raise ImportError(
                "dopplersdk is required for DopplerAdapter. "
                "Install with: pip install penguin-sal[doppler]"
            ) from e

        # Get token from password or params
        token = self.config.password or self.config.params.get("token")
        if not token:
            raise ValueError(
                "Doppler service token required in config.password or "
                "config.params['token']"
            )

        # Get project and config name
        project = self.config.params.get("project")
        if not project:
            raise ValueError("Doppler project required in config.params['project']")

        self._project = project
        self._config_name = self.config.params.get("config", "dev")

        # Create client
        self._client = dopplersdk.Doppler(token=token)
        self._connected = True

    def authenticate(self) -> None:
        """Authenticate by listing secrets.

        Raises:
            ConnectionError: If unable to connect.
            AuthenticationError: If authentication fails.
            BackendError: If the backend request fails.
        """
        if not self._connected or not self._client:
            raise ConnectionError("Doppler connection not initialized")

        try:
            # Verify access by listing secrets
            self._client.secrets.list(
                project=self._project, config=self._config_name
            )
        except Exception as e:
            if "invalid" in str(e).lower() or "unauthorized" in str(e).lower():
                raise AuthenticationError(
                    f"Failed to authenticate with Doppler: {e}"
                ) from e
            raise BackendError(
                f"Failed to authenticate with Doppler: {e}",
                backend="doppler",
                original_error=e,
            ) from e

    def get(self, key: str, version: int | None = None) -> Secret:
        """Retrieve a secret by key.

        Args:
            key: The secret name.
            version: Ignored (Doppler doesn't support versioning via SDK).

        Returns:
            Secret object with value.

        Raises:
            ConnectionError: If not connected.
            SecretNotFoundError: If the secret does not exist.
            BackendError: If the backend request fails.
        """
        if not self._connected or not self._client:
            raise ConnectionError("Doppler connection not initialized")

        try:
            response = self._client.secrets.get(
                project=self._project,
                config=self._config_name,
                name=key,
            )

            # Extract value from response
            if not response or "secret" not in response:
                raise SecretNotFoundError(key, backend="doppler")

            secret_obj = response["secret"]
            value = secret_obj.get("raw", "")

            return Secret(
                key=key,
                value=value,
                version=None,
                created_at=None,
                updated_at=None,
                metadata={"doppler_name": secret_obj.get("name", key)},
            )

        except SecretNotFoundError:
            raise
        except Exception as e:
            if "not found" in str(e).lower() or "404" in str(e):
                raise SecretNotFoundError(key, backend="doppler") from e
            raise BackendError(
                f"Failed to get secret '{key}': {e}",
                backend="doppler",
                original_error=e,
            ) from e

    def set(
        self,
        key: str,
        value: str | bytes | dict[str, Any],
        metadata: dict[str, Any] | None = None,
    ) -> Secret:
        """Create or update a secret.

        Args:
            key: The secret name.
            value: The secret value.
            metadata: Optional metadata (not stored in Doppler).

        Returns:
            Secret object reflecting the stored state.

        Raises:
            ConnectionError: If not connected.
            BackendError: If the backend request fails.
        """
        if not self._connected or not self._client:
            raise ConnectionError("Doppler connection not initialized")

        # Convert bytes to string
        if isinstance(value, bytes):
            value_str = value.decode("utf-8")
        elif isinstance(value, dict):
            import json

            value_str = json.dumps(value)
        else:
            value_str = value

        try:
            self._client.secrets.update(
                project=self._project,
                config=self._config_name,
                name=key,
                value=value_str,
            )

            # Return updated secret
            return Secret(
                key=key,
                value=value_str,
                version=None,
                created_at=None,
                updated_at=None,
                metadata=metadata or {},
            )

        except Exception as e:
            raise BackendError(
                f"Failed to set secret '{key}': {e}",
                backend="doppler",
                original_error=e,
            ) from e

    def delete(self, key: str) -> bool:
        """Delete a secret.

        Doppler SDK doesn't support individual secret deletion directly.
        This implementation sets the secret to an empty string.

        Args:
            key: The secret name.

        Returns:
            True if deleted (or set to empty).

        Raises:
            ConnectionError: If not connected.
            BackendError: If the backend request fails.
        """
        if not self._connected or not self._client:
            raise ConnectionError("Doppler connection not initialized")

        try:
            # Doppler doesn't support deletion via SDK, so set to empty string
            self._client.secrets.update(
                project=self._project,
                config=self._config_name,
                name=key,
                value="",
            )
            return True

        except Exception as e:
            raise BackendError(
                f"Failed to delete secret '{key}': {e}",
                backend="doppler",
                original_error=e,
            ) from e

    def list(self, prefix: str = "", limit: int | None = None) -> SecretList:
        """List secret names, optionally filtered by prefix.

        Args:
            prefix: Filter keys by prefix.
            limit: Maximum number of keys to return.

        Returns:
            SecretList with matching keys.

        Raises:
            ConnectionError: If not connected.
            BackendError: If the backend request fails.
        """
        if not self._connected or not self._client:
            raise ConnectionError("Doppler connection not initialized")

        try:
            response = self._client.secrets.list(
                project=self._project, config=self._config_name
            )

            # Extract secret names
            secrets = response.get("secrets", {})
            keys = list(secrets.keys())

            # Filter by prefix
            if prefix:
                keys = [k for k in keys if k.startswith(prefix)]

            # Apply limit
            if limit:
                keys = keys[:limit]

            return SecretList(keys=keys, cursor=None)

        except Exception as e:
            raise BackendError(
                f"Failed to list secrets: {e}",
                backend="doppler",
                original_error=e,
            ) from e

    def exists(self, key: str) -> bool:
        """Check if a secret exists.

        Args:
            key: The secret name.

        Returns:
            True if the secret exists.

        Raises:
            ConnectionError: If not connected.
            BackendError: If the backend request fails.
        """
        if not self._connected or not self._client:
            raise ConnectionError("Doppler connection not initialized")

        try:
            response = self._client.secrets.list(
                project=self._project, config=self._config_name
            )

            secrets = response.get("secrets", {})
            return key in secrets

        except Exception as e:
            raise BackendError(
                f"Failed to check secret existence: {e}",
                backend="doppler",
                original_error=e,
            ) from e

    def health_check(self) -> bool:
        """Check if Doppler is reachable.

        Args:
            None

        Returns:
            True if Doppler is healthy.
        """
        if not self._connected or not self._client:
            return False

        try:
            # Try to list projects as a health check
            self._client.secrets.list(
                project=self._project, config=self._config_name
            )
            return True

        except Exception:
            return False

    def close(self) -> None:
        """Close the connection and clean up resources."""
        self._client = None
        self._connected = False
