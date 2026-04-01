"""1Password Connect backend adapter for penguin-sal."""

from __future__ import annotations

from datetime import datetime
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
    from onepasswordconnectsdk.client import Client
    from onepasswordconnectsdk.client import new_client_from_environment as sdk_new_client
except ImportError as e:
    raise AdapterNotInstalledError("onepassword", "onepassword") from e


class OnePasswordAdapter(BaseAdapter):
    """1Password Connect secrets backend adapter.

    Connects to a 1Password Connect server to retrieve and manage secrets.
    Requires OP_CONNECT_HOST, OP_CONNECT_TOKEN environment variables or
    explicit config with token and vault ID.
    """

    def __init__(self, config: ConnectionConfig) -> None:
        super().__init__(config)
        self._client: Client | None = None
        self._vault_id: str | None = None

    def _init_connection(self, **kwargs: Any) -> None:
        """Initialize 1Password Connect client."""
        try:
            # Try environment-based initialization first
            self._client = sdk_new_client()
        except Exception:
            # Fall back to explicit configuration
            token = self.config.password or self.config.params.get("token")
            if not token:
                raise ConnectionError(
                    "1Password Connect token required: set config.password or "
                    "config.params['token']"
                )

            # Build URL from host and port
            scheme = self.config.scheme or "https"
            port = f":{self.config.port}" if self.config.port else ""
            url = f"{scheme}://{self.config.host}{port}"

            self._client = Client(url=url, token=token)

        # Extract vault ID from config
        self._vault_id = (
            self.config.params.get("vault_id")
            or self.config.params.get("vault")
        )
        if not self._vault_id:
            raise ConnectionError(
                "1Password vault ID required: set config.params['vault_id'] or "
                "config.params['vault']"
            )

        self._connected = True

    def authenticate(self) -> None:
        """Verify authentication by listing vaults."""
        if not self._client:
            raise ConnectionError("Not connected to 1Password")

        try:
            self._client.vaults.list()
        except Exception as e:
            raise AuthenticationError(
                f"Failed to authenticate with 1Password: {e}"
            ) from e

    def get(self, key: str, version: int | None = None) -> Secret:
        """Retrieve a secret by title/key.

        Args:
            key: The item title to retrieve.
            version: Ignored (1Password doesn't use versions for items).

        Returns:
            Secret with the item's password field value.

        Raises:
            SecretNotFoundError: If no item with that title exists.
            BackendError: If the backend request fails.
        """
        if not self._client or not self._vault_id:
            raise ConnectionError("Not connected to 1Password")

        try:
            items = self._client.items.list(self._vault_id)
            for item in items:
                if item.title == key:
                    # Extract password from password field
                    password = None
                    if item.password:
                        password = item.password
                    else:
                        # Try to extract from first field
                        for field in (item.fields or []):
                            if field.type == "password":
                                password = field.value
                                break

                    if password is None:
                        password = ""

                    return Secret(
                        key=key,
                        value=password,
                        version=None,
                        created_at=item.created_at,
                        updated_at=item.updated_at,
                    )

            raise SecretNotFoundError(key, backend="onepassword")
        except SecretNotFoundError:
            raise
        except Exception as e:
            raise BackendError(
                f"Failed to retrieve secret '{key}'",
                backend="onepassword",
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
            key: The item title.
            value: The secret value (converted to string).
            metadata: Optional metadata (stored as item details).

        Returns:
            Secret reflecting the stored state.

        Raises:
            BackendError: If the backend request fails.
        """
        if not self._client or not self._vault_id:
            raise ConnectionError("Not connected to 1Password")

        try:
            # Convert value to string if needed
            secret_value = value if isinstance(value, str) else str(value)

            # Check if item exists
            items = self._client.items.list(self._vault_id)
            existing_item = None
            for item in items:
                if item.title == key:
                    existing_item = item
                    break

            if existing_item:
                # Update existing item's password
                existing_item.password = secret_value
                self._client.items.update(self._vault_id, existing_item)
                return Secret(
                    key=key,
                    value=secret_value,
                    updated_at=datetime.now(),
                )
            else:
                # Create new item with password
                from onepasswordconnectsdk.models.item import Item, ItemPassword

                new_item = Item(
                    title=key,
                    password=ItemPassword(value=secret_value),
                )
                self._client.items.create(self._vault_id, new_item)
                return Secret(
                    key=key,
                    value=secret_value,
                    created_at=datetime.now(),
                    updated_at=datetime.now(),
                )
        except Exception as e:
            raise BackendError(
                f"Failed to store secret '{key}'",
                backend="onepassword",
                original_error=e,
            ) from e

    def delete(self, key: str) -> bool:
        """Delete a secret by title.

        Args:
            key: The item title to delete.

        Returns:
            True if deleted, False if not found.

        Raises:
            BackendError: If the backend request fails.
        """
        if not self._client or not self._vault_id:
            raise ConnectionError("Not connected to 1Password")

        try:
            items = self._client.items.list(self._vault_id)
            for item in items:
                if item.title == key:
                    self._client.items.delete(self._vault_id, item.id)
                    return True

            return False
        except Exception as e:
            raise BackendError(
                f"Failed to delete secret '{key}'",
                backend="onepassword",
                original_error=e,
            ) from e

    def list(self, prefix: str = "", limit: int | None = None) -> SecretList:
        """List secret keys in the vault.

        Args:
            prefix: Filter keys by prefix (title starts with).
            limit: Maximum number of keys to return.

        Returns:
            SecretList with matching item titles.

        Raises:
            BackendError: If the backend request fails.
        """
        if not self._client or not self._vault_id:
            raise ConnectionError("Not connected to 1Password")

        try:
            items = self._client.items.list(self._vault_id)
            keys = []

            for item in items:
                if prefix and not item.title.startswith(prefix):
                    continue

                keys.append(item.title)

                if limit and len(keys) >= limit:
                    break

            return SecretList(keys=keys)
        except Exception as e:
            raise BackendError(
                "Failed to list secrets",
                backend="onepassword",
                original_error=e,
            ) from e

    def exists(self, key: str) -> bool:
        """Check if a secret exists.

        Args:
            key: The item title to check.

        Returns:
            True if the item exists in the vault.
        """
        if not self._client or not self._vault_id:
            return False

        try:
            items = self._client.items.list(self._vault_id)
            return any(item.title == key for item in items)
        except Exception:
            return False

    def health_check(self) -> bool:
        """Check if 1Password is healthy and reachable.

        Returns:
            True if the backend is accessible.
        """
        if not self._client:
            return False

        try:
            self._client.vaults.list()
            return True
        except Exception:
            return False

    def close(self) -> None:
        """Close the 1Password connection."""
        self._client = None
        self._vault_id = None
        self._connected = False
