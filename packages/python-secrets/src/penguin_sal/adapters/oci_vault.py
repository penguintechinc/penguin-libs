"""OCI Vault secrets adapter for penguin-sal."""

from __future__ import annotations

import base64
import logging
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

logger = logging.getLogger(__name__)


class OCIVaultAdapter(BaseAdapter):
    """OCI Vault Secrets adapter.

    Manages secrets in Oracle Cloud Infrastructure (OCI) Vault service.
    Requires OCI SDK (oci) to be installed.

    Configuration:
        - scheme: "oci-vault"
        - host: OCI region (e.g., "us-ashburn-1")
        - params["compartment_id"]: Required OCID of the compartment
        - params["vault_id"]: Optional OCID of the vault (defaults to first vault)
        - params["config_path"]: Optional path to OCI config file (~/.oci/config)
        - params["profile"]: Optional OCI config profile name
    """

    def __init__(self, config: ConnectionConfig) -> None:
        """Initialize OCI Vault adapter.

        Args:
            config: Connection configuration.

        Raises:
            AdapterNotInstalledError: If OCI SDK is not installed.
        """
        try:
            import oci  # noqa: F401
        except ImportError as e:
            from penguin_sal.core.exceptions import AdapterNotInstalledError

            raise AdapterNotInstalledError("oci-vault", "oci") from e

        super().__init__(config)
        self._vaults_client: Any = None
        self._secrets_client: Any = None
        self._vault_id: str | None = None
        self._compartment_id: str | None = None

    def _init_connection(self, **kwargs: Any) -> None:
        """Initialize OCI clients.

        Raises:
            ConnectionError: If OCI configuration is invalid or unreachable.
        """
        try:
            import oci

            # Extract configuration parameters
            self._compartment_id = self.config.params.get("compartment_id")
            if not self._compartment_id:
                raise ValueError("compartment_id is required in config params")

            self._vault_id = self.config.params.get("vault_id")

            # Build OCI config
            config_path = self.config.params.get("config_path")
            profile = self.config.params.get("profile", "DEFAULT")

            if config_path:
                oci_config = oci.config.from_file(config_path, profile)
            else:
                # Use default OCI config from ~/.oci/config
                oci_config = oci.config.from_file()

            # Validate config
            oci.config.validate_config(oci_config)

            # Initialize clients
            self._vaults_client = oci.vault.VaultsClient(oci_config)
            self._secrets_client = oci.secrets.SecretsClient(oci_config)

            self._connected = True
            logger.debug(f"OCI Vault adapter connected to region: {self.config.host}")

        except (ImportError, ValueError, TypeError, oci.exceptions.ConfigFileNotFound) as e:
            msg = f"Failed to initialize OCI connection: {e}"
            logger.error(msg)
            raise ConnectionError(msg) from e
        except Exception as e:
            msg = f"OCI connection error: {e}"
            logger.error(msg)
            raise ConnectionError(msg) from e

    def authenticate(self) -> None:
        """Authenticate with OCI Vault.

        Verifies connectivity by listing vaults in the compartment.

        Raises:
            ConnectionError: If OCI is unreachable.
            AuthenticationError: If authentication fails.
        """
        try:
            if not self._connected:
                self._init_connection()

            import oci

            # Verify by listing vaults in compartment
            response = self._vaults_client.list_vaults(
                compartment_id=self._compartment_id, limit=1
            )

            if response.data:
                if not self._vault_id:
                    self._vault_id = response.data[0].id
                logger.debug(f"OCI authentication successful, vault: {self._vault_id}")
            else:
                raise AuthenticationError("No vaults found in compartment")

        except oci.exceptions.ServiceError as e:
            if e.status == 401:
                msg = "OCI authentication failed: invalid credentials"
                logger.error(msg)
                raise AuthenticationError(msg) from e
            elif e.status == 403:
                msg = "OCI authentication failed: insufficient permissions"
                logger.error(msg)
                raise AuthorizationError(msg) from e
            msg = f"OCI authentication error: {e}"
            logger.error(msg)
            raise AuthenticationError(msg) from e
        except ConnectionError:
            raise
        except Exception as e:
            msg = f"OCI authentication failed: {e}"
            logger.error(msg)
            raise AuthenticationError(msg) from e

    def get(self, key: str, version: int | None = None) -> Secret:
        """Retrieve a secret from OCI Vault.

        Args:
            key: Secret name or OCID.
            version: Optional version number (ignored for OCI Vault).

        Returns:
            Secret object with decrypted value.

        Raises:
            SecretNotFoundError: If secret does not exist.
            BackendError: If retrieval fails.
        """
        if not self._connected:
            self._init_connection()

        try:
            import oci

            # Try to get secret bundle by name first
            try:
                bundle = self._secrets_client.get_secret_bundle_by_name(
                    secret_name=key, vault_id=self._vault_id
                )
            except oci.exceptions.ServiceError as e:
                if e.status == 404:
                    raise SecretNotFoundError(key, "oci-vault") from e
                raise

            # Extract and decode secret content
            secret_bundle = bundle.data
            secret_version = secret_bundle.secret_bundle_content[0]

            if hasattr(secret_version, "content"):
                content = secret_version.content
                if isinstance(content, str):
                    # Decode base64 content
                    try:
                        value = base64.b64decode(content).decode("utf-8")
                    except Exception:
                        value = content
                else:
                    value = content
            else:
                value = ""

            # Extract metadata
            created_at = secret_bundle.time_created
            updated_at = secret_bundle.time_created

            return Secret(
                key=key,
                value=value,
                version=secret_version.version_number,
                created_at=created_at,
                updated_at=updated_at,
                metadata={"secret_bundle_id": secret_bundle.id},
            )

        except SecretNotFoundError:
            raise
        except oci.exceptions.ServiceError as e:
            msg = f"Failed to retrieve secret {key}: {e}"
            logger.error(msg)
            raise BackendError(msg, "oci-vault", e) from e
        except Exception as e:
            msg = f"Failed to retrieve secret {key}: {e}"
            logger.error(msg)
            raise BackendError(msg, "oci-vault", e) from e

    def set(
        self,
        key: str,
        value: str | bytes | dict[str, Any],
        metadata: dict[str, Any] | None = None,
    ) -> Secret:
        """Create or update a secret in OCI Vault.

        Args:
            key: Secret name.
            value: Secret value (string, bytes, or dict).
            metadata: Optional metadata (ignored for OCI).

        Returns:
            Secret object reflecting stored state.

        Raises:
            BackendError: If storage fails.
        """
        if not self._connected:
            self._init_connection()

        try:
            import oci

            # Convert value to string
            if isinstance(value, dict):
                import json

                value_str = json.dumps(value)
            elif isinstance(value, bytes):
                value_str = value.decode("utf-8")
            else:
                value_str = value

            # Encode to base64
            encoded_value = base64.b64encode(value_str.encode("utf-8")).decode("utf-8")

            # Create secret
            secret_details = oci.vault.models.CreateSecretDetails(
                compartment_id=self._compartment_id,
                secret_name=key,
                vault_id=self._vault_id,
                key_id=None,  # Use vault default key
                secret_content=oci.vault.models.SecretContentDetails(
                    content_type="BASE64", content=encoded_value
                ),
            )

            response = self._vaults_client.create_secret(secret_details)
            secret = response.data

            return Secret(
                key=key,
                value=value_str,
                version=1,
                created_at=secret.time_created,
                updated_at=secret.time_created,
                metadata={"secret_id": secret.id},
            )

        except oci.exceptions.ServiceError as e:
            msg = f"Failed to store secret {key}: {e}"
            logger.error(msg)
            raise BackendError(msg, "oci-vault", e) from e
        except Exception as e:
            msg = f"Failed to store secret {key}: {e}"
            logger.error(msg)
            raise BackendError(msg, "oci-vault", e) from e

    def delete(self, key: str) -> bool:
        """Delete a secret from OCI Vault.

        Args:
            key: Secret name or OCID.

        Returns:
            True if deleted, False if not found.

        Raises:
            BackendError: If deletion fails.
        """
        if not self._connected:
            self._init_connection()

        try:
            import oci

            # Get secret to find its OCID
            try:
                bundle = self._secrets_client.get_secret_bundle_by_name(
                    secret_name=key, vault_id=self._vault_id
                )
                secret_id = bundle.data.secret_id
            except oci.exceptions.ServiceError as e:
                if e.status == 404:
                    return False
                raise

            # Schedule deletion
            self._vaults_client.schedule_secret_deletion(
                secret_id=secret_id,
                schedule_secret_deletion_details=oci.vault.models.ScheduleSecretDeletionDetails(
                    time_of_deletion=None  # Immediate deletion
                ),
            )

            logger.debug(f"Secret {key} scheduled for deletion")
            return True

        except oci.exceptions.ServiceError as e:
            if e.status == 404:
                return False
            msg = f"Failed to delete secret {key}: {e}"
            logger.error(msg)
            raise BackendError(msg, "oci-vault", e) from e
        except Exception as e:
            msg = f"Failed to delete secret {key}: {e}"
            logger.error(msg)
            raise BackendError(msg, "oci-vault", e) from e

    def list(self, prefix: str = "", limit: int | None = None) -> SecretList:
        """List secrets in OCI Vault.

        Args:
            prefix: Filter by secret name prefix.
            limit: Maximum number of secrets to return.

        Returns:
            SecretList with matching keys.

        Raises:
            BackendError: If listing fails.
        """
        if not self._connected:
            self._init_connection()

        try:
            import oci

            # List all secrets in vault
            secrets = []
            cursor = None
            remaining_limit = limit

            while True:
                if remaining_limit is not None and remaining_limit <= 0:
                    break

                page_size = 100
                if remaining_limit is not None:
                    page_size = min(100, remaining_limit)

                response = self._vaults_client.list_secrets(
                    compartment_id=self._compartment_id,
                    vault_id=self._vault_id,
                    limit=page_size,
                    page=cursor,
                )

                for secret in response.data:
                    if prefix and not secret.secret_name.startswith(prefix):
                        continue
                    secrets.append(secret.secret_name)
                    if remaining_limit is not None:
                        remaining_limit -= 1
                        if remaining_limit <= 0:
                            break

                # Check for more pages
                cursor = response.opc_next_page
                if not cursor:
                    break

            return SecretList(keys=secrets, cursor=cursor)

        except oci.exceptions.ServiceError as e:
            msg = f"Failed to list secrets: {e}"
            logger.error(msg)
            raise BackendError(msg, "oci-vault", e) from e
        except Exception as e:
            msg = f"Failed to list secrets: {e}"
            logger.error(msg)
            raise BackendError(msg, "oci-vault", e) from e

    def exists(self, key: str) -> bool:
        """Check if a secret exists in OCI Vault.

        Args:
            key: Secret name.

        Returns:
            True if secret exists.
        """
        if not self._connected:
            self._init_connection()

        try:
            import oci

            try:
                self._secrets_client.get_secret_bundle_by_name(
                    secret_name=key, vault_id=self._vault_id
                )
                return True
            except oci.exceptions.ServiceError as e:
                if e.status == 404:
                    return False
                raise

        except Exception:
            return False

    def health_check(self) -> bool:
        """Check OCI Vault health.

        Returns:
            True if OCI Vault is reachable.
        """
        if not self._connected:
            try:
                self._init_connection()
            except Exception:
                return False

        try:

            # Simple health check: list vaults
            self._vaults_client.list_vaults(
                compartment_id=self._compartment_id, limit=1
            )
            return True
        except Exception:
            return False

    def close(self) -> None:
        """Close OCI clients and release resources."""
        self._vaults_client = None
        self._secrets_client = None
        self._connected = False
        logger.debug("OCI Vault adapter closed")
