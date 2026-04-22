"""CyberArk Conjur secrets backend adapter."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

from penguin_sal.core.base_adapter import BaseAdapter
from penguin_sal.core.exceptions import (
    AdapterNotInstalledError,
    AuthenticationError,
    BackendError,
    ConnectionError,
    SecretNotFoundError,
)
from penguin_sal.core.types import ConnectionConfig, Secret, SecretList

try:
    from conjur import api as conjur_api
except ImportError:
    conjur_api = None  # type: ignore[assignment]


class CyberArkAdapter(BaseAdapter):
    """Adapter for CyberArk Conjur secrets management system.

    Conjur is an enterprise secrets vault that integrates with various
    authentication providers and deployment platforms.

    Example URI:
        conjur://https://my-conjur-host:8443?account=my-account

    Environment variables:
        CONJUR_AUTHN_LOGIN: Login identifier (username)
        CONJUR_AUTHN_API_KEY: API key for authentication
    """

    def __init__(self, config: ConnectionConfig) -> None:
        """Initialize CyberArk Conjur adapter.

        Args:
            config: Connection configuration with account in params.

        Raises:
            AdapterNotInstalledError: If conjur SDK is not installed.
        """
        super().__init__(config)
        if conjur_api is None:
            raise AdapterNotInstalledError("cyberark", "cyberark")

        self.client: Any = None
        self._init_connection()

    def _init_connection(self, **kwargs: Any) -> None:
        """Initialize Conjur client connection.

        Builds the Conjur URL from host and port and creates a client.

        Raises:
            ConnectionError: If unable to initialize the client.
        """
        try:
            # Build Conjur URL
            host = self.config.host
            port = self.config.port or 443
            url = f"https://{host}:{port}"

            # Get account from connection params
            account = self.config.params.get("account")
            if not account:
                raise ValueError("Account must be specified in connection params")

            # Create Conjur client
            self.client = conjur_api.ConjurClient(
                url=url,
                account=account,
            )
            self._connected = True

        except ValueError as e:
            raise ConnectionError(f"Failed to initialize Conjur client: {e}") from e
        except Exception as e:
            raise ConnectionError(f"Failed to initialize Conjur client: {e}") from e

    def authenticate(self) -> None:
        """Authenticate with Conjur using login credentials.

        Uses the configured username (login) and password (API key).

        Raises:
            AuthenticationError: If authentication fails.
            ConnectionError: If unable to connect.
        """
        try:
            if not self.client:
                raise ConnectionError("Client not initialized")

            login = self.config.username
            api_key = self.config.password

            if not login or not api_key:
                raise ValueError("Username (login) and password (API key) required")

            # Authenticate with Conjur
            self.client.login(login, api_key)
            self._connected = True

        except ConnectionError:
            raise
        except Exception as e:
            raise AuthenticationError(f"Failed to authenticate with Conjur: {e}") from e

    def get(self, key: str, version: int | None = None) -> Secret:
        """Retrieve a secret from Conjur.

        Args:
            key: Variable path (e.g., 'prod/db/password').
            version: Conjur doesn't support versioning; parameter ignored.

        Returns:
            Secret with value and metadata.

        Raises:
            SecretNotFoundError: If the variable does not exist.
            BackendError: If retrieval fails.
        """
        try:
            if not self.client:
                raise BackendError("Client not initialized", backend="cyberark")

            # Retrieve variable from Conjur
            # Conjur returns bytes, we decode to str
            value = self.client.get_secret(key)

            if value is None:
                raise SecretNotFoundError(key, backend="cyberark")

            # Decode if bytes
            if isinstance(value, bytes):
                value = value.decode("utf-8")

            return Secret(
                key=key,
                value=value,
                version=None,
                created_at=None,
                updated_at=None,
                metadata=None,
            )

        except SecretNotFoundError:
            raise
        except BackendError:
            raise
        except Exception as e:
            if "404" in str(e) or "not found" in str(e).lower():
                raise SecretNotFoundError(key, backend="cyberark") from e
            raise BackendError(
                f"Failed to retrieve secret '{key}'",
                backend="cyberark",
                original_error=e,
            ) from e

    def set(
        self,
        key: str,
        value: str | bytes | dict[str, Any],
        metadata: dict[str, Any] | None = None,
    ) -> Secret:
        """Create or update a secret in Conjur.

        Args:
            key: Variable path (e.g., 'prod/db/password').
            value: Secret value (strings, bytes, or dicts are serialized).
            metadata: Metadata ignored (Conjur doesn't store it).

        Returns:
            Secret reflecting the stored state.

        Raises:
            BackendError: If the operation fails.
        """
        try:
            if not self.client:
                raise BackendError("Client not initialized", backend="cyberark")

            # Convert value to string if needed
            if isinstance(value, dict):
                value_str = json.dumps(value)
            elif isinstance(value, bytes):
                value_str = value.decode("utf-8")
            else:
                value_str = str(value)

            # Set variable in Conjur
            self.client.set_secret(key, value_str)

            return Secret(
                key=key,
                value=value_str,
                version=None,
                created_at=datetime.now(UTC),
                updated_at=datetime.now(UTC),
                metadata=None,
            )

        except Exception as e:
            raise BackendError(
                f"Failed to set secret '{key}'",
                backend="cyberark",
                original_error=e,
            ) from e

    def delete(self, key: str) -> bool:
        """Delete a secret from Conjur.

        Note: Conjur's REST API does not provide a direct delete endpoint
        for variables. Deletion requires policy updates or special permissions.
        This implementation raises BackendError to indicate the limitation.

        Args:
            key: Variable path.

        Returns:
            False (deletion not supported).

        Raises:
            BackendError: Explaining that deletion is not supported.
        """
        raise BackendError(
            "Conjur does not support variable deletion via REST API. "
            "Variables must be deleted using policy updates.",
            backend="cyberark",
        )

    def list(self, prefix: str = "", limit: int | None = None) -> SecretList:
        """List secret keys in Conjur.

        Queries Conjur resources API for variables, optionally filtered by prefix.

        Args:
            prefix: Filter by key prefix.
            limit: Maximum keys to return.

        Returns:
            SecretList with matching keys.

        Raises:
            BackendError: If listing fails.
        """
        try:
            if not self.client:
                raise BackendError("Client not initialized", backend="cyberark")

            # List resources of kind "variable"
            resources = self.client.list_resources(kind="variable")

            # Extract keys and filter by prefix
            keys: list[str] = []
            for resource in resources:
                # Resource IDs are like "account:variable:path"
                resource_id = resource.get("id", "")
                if ":" in resource_id:
                    key = resource_id.split(":", 2)[-1]
                else:
                    key = resource_id

                if not prefix or key.startswith(prefix):
                    keys.append(key)

            # Apply limit if specified
            if limit:
                keys = keys[:limit]

            return SecretList(keys=keys, cursor=None)

        except Exception as e:
            raise BackendError(
                "Failed to list secrets",
                backend="cyberark",
                original_error=e,
            ) from e

    def exists(self, key: str) -> bool:
        """Check if a secret exists in Conjur.

        Args:
            key: Variable path.

        Returns:
            True if the variable exists, False otherwise.
        """
        try:
            if not self.client:
                return False

            # Attempt to get the secret; 404 means it doesn't exist
            self.client.get_secret(key)
            return True

        except Exception as e:
            if "404" in str(e) or "not found" in str(e).lower():
                return False
            # For other errors, we can't determine existence
            return False

    def health_check(self) -> bool:
        """Check if Conjur is healthy and reachable.

        Calls the Conjur health endpoint.

        Returns:
            True if Conjur is healthy, False otherwise.
        """
        try:
            if not self.client:
                return False

            # Call Conjur info endpoint as a health check
            self.client.info()
            return True

        except Exception:
            return False

    def close(self) -> None:
        """Close the Conjur client connection."""
        self.client = None
        self._connected = False
