"""Azure Key Vault adapter for penguin-sal secrets management."""

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


class AzureKeyVaultAdapter(BaseAdapter):
    """Azure Key Vault adapter for secrets storage and retrieval.

    Supports both DefaultAzureCredential (managed identity) and
    ClientSecretCredential (service principal) authentication methods.
    """

    def __init__(self, config: ConnectionConfig) -> None:
        """Initialize Azure Key Vault adapter.

        Args:
            config: Connection configuration with Azure Key Vault details.
        """
        super().__init__(config)
        self._client: Any = None
        self._resource_not_found_error: type[Exception] = Exception
        self._init_connection()

    def _init_connection(self, **kwargs: Any) -> None:
        """Initialize the Azure Key Vault client.

        Supports two credential types:
        - DefaultAzureCredential: For managed identity and environment auth
        - ClientSecretCredential: For service principal auth

        Raises:
            ConnectionError: If client initialization fails.
            BackendError: If required imports are missing.
        """
        try:
            from azure.core.exceptions import ResourceNotFoundError
            from azure.identity import (
                ClientSecretCredential,
                DefaultAzureCredential,
            )
            from azure.keyvault.secrets import SecretClient

            self._resource_not_found_error = ResourceNotFoundError
        except ImportError as e:
            raise BackendError(
                "Azure SDK not installed. Install with: pip install penguin-sal[azure]",
                backend="azure-kv",
                original_error=e,
            ) from e

        try:
            # Determine vault URL
            vault_url = self.config.params.get("vault_url")
            if not vault_url:
                vault_url = f"https://{self.config.host}"
            if not vault_url.startswith("https://"):
                vault_url = f"https://{vault_url}"

            # Choose credential type based on config
            if (
                self.config.username
                and self.config.password
                and "tenant_id" in self.config.params
            ):
                # Service principal authentication
                credential = ClientSecretCredential(
                    tenant_id=self.config.params["tenant_id"],
                    client_id=self.config.username,
                    client_secret=self.config.password,
                )
            else:
                # Managed identity or environment auth
                credential = DefaultAzureCredential()

            self._client = SecretClient(vault_url=vault_url, credential=credential)
            self._connected = True
        except Exception as e:
            raise ConnectionError(
                f"Failed to initialize Azure Key Vault client: {e}"
            ) from e

    def authenticate(self) -> None:
        """Verify authentication with Azure Key Vault.

        Performs a minimal list operation to verify credentials are valid.

        Raises:
            AuthenticationError: If authentication fails.
            ConnectionError: If the vault is unreachable.
        """
        if not self._client:
            raise ConnectionError("Client not initialized")

        try:
            # List with max_page_size=1 to verify auth without heavy I/O
            list(self._client.list_properties_of_secrets(max_page_size=1))
        except Exception as e:
            error_msg = str(e).lower()
            if "authentication" in error_msg or "unauthorized" in error_msg:
                raise AuthenticationError(f"Azure Key Vault authentication failed: {e}") from e
            raise ConnectionError(f"Azure Key Vault unreachable: {e}") from e

    def get(self, key: str, version: int | None = None) -> Secret:
        """Retrieve a secret from Azure Key Vault.

        Args:
            key: The secret name.
            version: Optional specific version (Azure uses version UUID strings).

        Returns:
            Secret object with value and metadata.

        Raises:
            SecretNotFoundError: If the secret does not exist.
            BackendError: If the operation fails.
        """
        if not self._client:
            raise BackendError("Client not initialized", backend="azure-kv")

        try:
            secret = self._client.get_secret(key, version=version)
            return Secret(
                key=key,
                value=secret.value,
                version=secret.version,
                created_at=secret.properties.created_on,
                updated_at=secret.properties.updated_on,
                metadata=secret.properties.tags or {},
            )
        except self._resource_not_found_error as e:
            raise SecretNotFoundError(key, backend="azure-kv") from e
        except Exception as e:
            raise BackendError(
                f"Failed to retrieve secret '{key}': {e}",
                backend="azure-kv",
                original_error=e,
            ) from e

    def set(
        self,
        key: str,
        value: str | bytes | dict[str, Any],
        metadata: dict[str, Any] | None = None,
    ) -> Secret:
        """Create or update a secret in Azure Key Vault.

        Args:
            key: The secret name.
            value: The secret value (will be converted to string).
            metadata: Optional metadata to attach as tags.

        Returns:
            Secret object reflecting the stored state.

        Raises:
            BackendError: If the operation fails.
        """
        if not self._client:
            raise BackendError("Client not initialized", backend="azure-kv")

        try:
            # Convert value to string
            if isinstance(value, bytes):
                str_value = value.decode("utf-8")
            elif isinstance(value, dict):
                import json
                str_value = json.dumps(value)
            else:
                str_value = str(value)

            # Set secret with metadata as tags
            secret_properties = self._client.set_secret(
                key, str_value, tags=metadata or {}
            )

            return Secret(
                key=key,
                value=str_value,
                version=secret_properties.version,
                created_at=secret_properties.properties.created_on,
                updated_at=secret_properties.properties.updated_on,
                metadata=secret_properties.properties.tags or {},
            )
        except Exception as e:
            raise BackendError(
                f"Failed to set secret '{key}': {e}",
                backend="azure-kv",
                original_error=e,
            ) from e

    def delete(self, key: str) -> bool:
        """Delete a secret from Azure Key Vault.

        Azure Key Vault uses soft-delete by default. This operation
        begins deletion and then purges the secret.

        Args:
            key: The secret name.

        Returns:
            True if the secret was deleted, False if it didn't exist.

        Raises:
            BackendError: If the operation fails.
        """
        if not self._client:
            raise BackendError("Client not initialized", backend="azure-kv")

        try:
            # Begin deletion (soft delete)
            self._client.begin_delete_secret(key)
            # Purge to permanently remove
            self._client.purge_deleted_secret(key)
            return True
        except self._resource_not_found_error:
            return False
        except Exception as e:
            raise BackendError(
                f"Failed to delete secret '{key}': {e}",
                backend="azure-kv",
                original_error=e,
            ) from e

    def list(self, prefix: str = "", limit: int | None = None) -> SecretList:
        """List secret names in Azure Key Vault.

        Args:
            prefix: Filter by secret name prefix (substring match).
            limit: Maximum number of secrets to return.

        Returns:
            SecretList with matching secret names.

        Raises:
            BackendError: If the operation fails.
        """
        if not self._client:
            raise BackendError("Client not initialized", backend="azure-kv")

        try:
            secrets: list[str] = []
            count = 0

            for secret_properties in self._client.list_properties_of_secrets():
                name = secret_properties.name
                if not name:
                    continue

                # Apply prefix filter if provided
                if prefix and not name.startswith(prefix):
                    continue

                secrets.append(name)
                count += 1

                # Apply limit if provided
                if limit and count >= limit:
                    break

            return SecretList(keys=secrets, cursor=None)
        except Exception as e:
            raise BackendError(
                f"Failed to list secrets: {e}",
                backend="azure-kv",
                original_error=e,
            ) from e

    def exists(self, key: str) -> bool:
        """Check if a secret exists in Azure Key Vault.

        Args:
            key: The secret name.

        Returns:
            True if the secret exists, False otherwise.
        """
        if not self._client:
            return False

        try:
            self._client.get_secret(key)
            return True
        except self._resource_not_found_error:
            return False
        except Exception:
            return False

    def health_check(self) -> bool:
        """Check if Azure Key Vault is healthy and reachable.

        Performs a minimal list operation to verify connectivity.

        Returns:
            True if the vault is healthy, False otherwise.
        """
        if not self._client:
            return False

        try:
            # List with max_page_size=1 to verify connectivity
            list(self._client.list_properties_of_secrets(max_page_size=1))
            return True
        except Exception:
            return False

    def close(self) -> None:
        """Close the Azure Key Vault client connection.

        Releases the client and resets the connected flag.
        """
        if self._client:
            try:
                self._client.close()
            except Exception:
                pass
        self._client = None
        self._connected = False
