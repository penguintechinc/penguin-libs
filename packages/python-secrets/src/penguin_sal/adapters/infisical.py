"""Infisical secrets backend adapter."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from penguin_sal.core.base_adapter import BaseAdapter
from penguin_sal.core.exceptions import (
    AuthenticationError,
    BackendError,
    ConnectionError,
    SecretNotFoundError,
)
from penguin_sal.core.types import ConnectionConfig, Secret, SecretList


class InfisicalAdapter(BaseAdapter):
    """Adapter for Infisical secrets management platform.

    Requires: infisicalsdk

    Configuration:
        - scheme: "infisical"
        - host: Infisical instance hostname
        - port: Infisical instance port (optional, default 443)
        - password: API token or universal auth password
        - params:
            - project_id: Required. Infisical project ID
            - environment: Optional. Environment name (default: "dev")
            - token: Alternative to password for API token auth
    """

    def __init__(self, config: ConnectionConfig) -> None:
        super().__init__(config)
        self._client: Any = None

    def _init_connection(self, **kwargs: Any) -> None:
        """Initialize the Infisical client connection."""
        try:
            from infisicalsdk import InfisicalClient
        except ImportError as e:
            from penguin_sal.core.exceptions import AdapterNotInstalledError

            raise AdapterNotInstalledError("infisical", "infisical") from e

        # Build site URL from host and port
        scheme = "https"
        port_suffix = (
            "" if not self.config.port or self.config.port == 443
            else f":{self.config.port}"
        )
        site_url = f"{scheme}://{self.config.host}{port_suffix}"

        try:
            self._client = InfisicalClient(site_url=site_url)
            self._connected = True
        except Exception as e:
            raise ConnectionError(
                f"Failed to initialize Infisical client for {site_url}"
            ) from e

    def authenticate(self) -> None:
        """Authenticate with Infisical using token or universal auth.

        Raises:
            AuthenticationError: If authentication fails.
            ConnectionError: If the backend is unreachable.
        """
        if self._client is None:
            self._init_connection()

        if not self._client:
            raise ConnectionError("Infisical client not initialized")

        try:
            # Prefer token from params, then from password
            token = self.config.params.get("token") or self.config.password

            if not token:
                raise AuthenticationError(
                    "No authentication token provided. "
                    "Set config.password or config.params['token']"
                )

            # Authenticate the client
            self._client.auth(token=token)
        except Exception as e:
            if isinstance(e, AuthenticationError):
                raise
            raise AuthenticationError(f"Infisical authentication failed: {e}") from e

    def get(self, key: str, version: int | None = None) -> Secret:
        """Retrieve a secret by key name.

        Args:
            key: The secret key name.
            version: Ignored for Infisical (not supported by SDK).

        Returns:
            Secret object with the value from Infisical.

        Raises:
            SecretNotFoundError: If the secret does not exist.
            BackendError: If the backend request fails.
        """
        if self._client is None:
            self._init_connection()
            self.authenticate()

        project_id = self.config.params.get("project_id")
        environment = self.config.params.get("environment", "dev")

        if not project_id:
            raise BackendError(
                "project_id is required in config.params",
                backend="infisical",
            )

        try:
            secret = self._client.getSecret(
                secretName=key,
                projectId=project_id,
                environment=environment,
            )

            if not secret:
                raise SecretNotFoundError(key, backend="infisical")

            # Infisical returns a dict; extract value
            value = secret.get("secretValue", "")

            return Secret(
                key=key,
                value=value,
                version=version,
                created_at=self._parse_timestamp(secret.get("createdAt")),
                updated_at=self._parse_timestamp(secret.get("updatedAt")),
            )
        except SecretNotFoundError:
            raise
        except Exception as e:
            raise BackendError(
                f"Failed to get secret '{key}': {e}",
                backend="infisical",
                original_error=e,
            ) from e

    def set(
        self,
        key: str,
        value: str | bytes | dict[str, Any],
        metadata: dict[str, Any] | None = None,
    ) -> Secret:
        """Create or update a secret in Infisical.

        Args:
            key: The secret key name.
            value: The secret value.
            metadata: Ignored for Infisical.

        Returns:
            Secret object reflecting the stored state.

        Raises:
            BackendError: If the backend request fails.
        """
        if self._client is None:
            self._init_connection()
            self.authenticate()

        project_id = self.config.params.get("project_id")
        environment = self.config.params.get("environment", "dev")

        if not project_id:
            raise BackendError(
                "project_id is required in config.params",
                backend="infisical",
            )

        # Convert value to string if needed
        if isinstance(value, bytes):
            str_value = value.decode("utf-8")
        elif isinstance(value, dict):
            import json

            str_value = json.dumps(value)
        else:
            str_value = str(value)

        try:
            result = self._client.createSecret(
                secretName=key,
                secretValue=str_value,
                projectId=project_id,
                environment=environment,
            )

            return Secret(
                key=key,
                value=str_value,
                metadata=metadata,
                created_at=self._parse_timestamp(result.get("createdAt")),
                updated_at=self._parse_timestamp(result.get("updatedAt")),
            )
        except Exception as e:
            raise BackendError(
                f"Failed to set secret '{key}': {e}",
                backend="infisical",
                original_error=e,
            ) from e

    def delete(self, key: str) -> bool:
        """Delete a secret from Infisical.

        Args:
            key: The secret key name.

        Returns:
            True if deleted, False if not found.

        Raises:
            BackendError: If the backend request fails.
        """
        if self._client is None:
            self._init_connection()
            self.authenticate()

        project_id = self.config.params.get("project_id")
        environment = self.config.params.get("environment", "dev")

        if not project_id:
            raise BackendError(
                "project_id is required in config.params",
                backend="infisical",
            )

        try:
            # First check if secret exists
            if not self.exists(key):
                return False

            self._client.deleteSecret(
                secretName=key,
                projectId=project_id,
                environment=environment,
            )
            return True
        except Exception as e:
            raise BackendError(
                f"Failed to delete secret '{key}': {e}",
                backend="infisical",
                original_error=e,
            ) from e

    def list(self, prefix: str = "", limit: int | None = None) -> SecretList:
        """List secret keys in the project/environment.

        Args:
            prefix: Filter keys by prefix.
            limit: Maximum number of keys to return.

        Returns:
            SecretList with matching keys.

        Raises:
            BackendError: If the backend request fails.
        """
        if self._client is None:
            self._init_connection()
            self.authenticate()

        project_id = self.config.params.get("project_id")
        environment = self.config.params.get("environment", "dev")

        if not project_id:
            raise BackendError(
                "project_id is required in config.params",
                backend="infisical",
            )

        try:
            secrets = self._client.listSecrets(
                projectId=project_id,
                environment=environment,
            )

            # Extract secret names and apply prefix filter
            all_keys = [s.get("secretName", "") for s in (secrets or [])]
            filtered_keys = [k for k in all_keys if k.startswith(prefix)]

            # Apply limit if specified
            if limit:
                filtered_keys = filtered_keys[:limit]

            return SecretList(keys=filtered_keys)
        except Exception as e:
            raise BackendError(
                f"Failed to list secrets: {e}",
                backend="infisical",
                original_error=e,
            ) from e

    def exists(self, key: str) -> bool:
        """Check if a secret exists.

        Args:
            key: The secret key name.

        Returns:
            True if the secret exists.
        """
        try:
            self.get(key)
            return True
        except SecretNotFoundError:
            return False

    def health_check(self) -> bool:
        """Check if Infisical backend is healthy.

        Returns:
            True if the backend is reachable and responsive.
        """
        try:
            if self._client is None:
                self._init_connection()
                self.authenticate()

            # Try a simple list operation as health check
            project_id = self.config.params.get("project_id")
            if not project_id:
                return False

            self._client.listSecrets(
                projectId=project_id,
                environment=self.config.params.get("environment", "dev"),
            )
            return True
        except Exception:
            return False

    def close(self) -> None:
        """Close the backend connection and release resources."""
        if self._client is not None:
            self._client = None
        self._connected = False

    @staticmethod
    def _parse_timestamp(ts: str | None) -> datetime | None:
        """Parse ISO 8601 timestamp string to datetime.

        Args:
            ts: ISO 8601 timestamp string.

        Returns:
            datetime object or None if ts is None.
        """
        if not ts:
            return None
        try:
            # Handle ISO format with or without timezone
            if ts.endswith("Z"):
                ts = ts[:-1] + "+00:00"
            return datetime.fromisoformat(ts)
        except (ValueError, AttributeError):
            return None
