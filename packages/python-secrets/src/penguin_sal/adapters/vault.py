"""HashiCorp Vault adapter for penguin-sal secrets management."""

from __future__ import annotations

from datetime import datetime
from typing import Any

import hvac
from hvac.exceptions import InvalidPath, Unauthorized, VaultDown, VaultError

from penguin_sal.core.base_adapter import BaseAdapter
from penguin_sal.core.exceptions import (
    AuthenticationError,
    BackendError,
    ConnectionError,
    SecretNotFoundError,
)
from penguin_sal.core.types import ConnectionConfig, Secret, SecretList


class VaultAdapter(BaseAdapter):
    """HashiCorp Vault adapter for secrets management.

    Supports KV v1 and v2 engines, token auth, and AppRole auth.
    """

    def __init__(self, config: ConnectionConfig) -> None:
        """Initialize Vault adapter."""
        super().__init__(config)
        self.client: hvac.Client | None = None

    def _build_url(self) -> str:
        """Build Vault URL from config."""
        scheme = self.config.scheme or "https"
        host = self.config.host
        port = self.config.port or 8200
        return f"{scheme}://{host}:{port}"

    def _clean_path(self, path: str) -> str:
        """Clean path by stripping leading/trailing slashes."""
        return path.strip("/")

    def _init_connection(self, **kwargs: Any) -> None:
        """Initialize the Vault client."""
        try:
            url = self._build_url()
            self.client = hvac.Client(url=url, verify=kwargs.get("verify", True))
            self._connected = True
        except Exception as e:
            raise ConnectionError(f"Failed to initialize Vault client: {e}") from e

    def authenticate(self) -> None:
        """Authenticate with Vault using token or AppRole."""
        if not self.client:
            raise ConnectionError("Client not initialized")
        try:
            token = self.config.password or self.config.params.get("token")
            if token:
                self.client.token = token
                if not self.client.is_authenticated():
                    raise AuthenticationError("Token authentication failed")
            else:
                role_id = self.config.params.get("role_id")
                secret_id = self.config.params.get("secret_id")
                if not (role_id and secret_id):
                    raise AuthenticationError(
                        "No token or AppRole credentials provided"
                    )
                auth_data = self.client.auth.approle.login(
                    role_id=role_id, secret_id=secret_id
                )
                self.client.token = auth_data["auth"]["client_token"]
        except (Unauthorized, VaultError) as e:
            raise AuthenticationError(f"Vault authentication failed: {e}") from e

    def get(self, key: str, version: int | None = None) -> Secret:
        """Retrieve a secret from Vault."""
        if not self.client:
            raise ConnectionError("Client not initialized")
        try:
            kv_version = self.config.params.get("kv_version", "2")
            mount_point = self.config.params.get("mount_point", "secret")
            path = key.strip("/")
            if kv_version == "2":
                kwargs = {"path": path, "mount_point": mount_point}
                if version is not None:
                    kwargs["version"] = version
                response = self.client.secrets.kv.v2.read_secret_version(**kwargs)
                data, metadata = response["data"]["data"], response["data"]["metadata"]
                return Secret(
                    key=key,
                    value=data,
                    version=metadata.get("version"),
                    created_at=self._parse_timestamp(metadata.get("created_time")),
                    updated_at=self._parse_timestamp(metadata.get("updated_time")),
                    metadata=metadata,
                )
            else:
                response = self.client.secrets.kv.v1.read_secret_version(
                    path=path, mount_point=mount_point
                )
                return Secret(key=key, value=response["data"])
        except InvalidPath as e:
            raise SecretNotFoundError(key, backend="vault") from e
        except (Unauthorized, VaultError) as e:
            raise BackendError(f"Failed to read secret: {e}", backend="vault") from e

    def set(
        self,
        key: str,
        value: str | bytes | dict[str, Any],
        metadata: dict[str, Any] | None = None,
    ) -> Secret:
        """Store a secret in Vault."""
        if not self.client:
            raise ConnectionError("Client not initialized")
        try:
            kv_version = self.config.params.get("kv_version", "2")
            mount_point = self.config.params.get("mount_point", "secret")
            path = key.strip("/")
            secret_data = value if isinstance(value, dict) else {"value": value}
            if kv_version == "2":
                response = self.client.secrets.kv.v2.create_or_update_secret(
                    path=path, secret=secret_data, mount_point=mount_point
                )
                meta = response["data"]["metadata"]
                return Secret(
                    key=key,
                    value=secret_data,
                    version=meta.get("version"),
                    created_at=self._parse_timestamp(meta.get("created_time")),
                    updated_at=self._parse_timestamp(meta.get("updated_time")),
                    metadata=meta,
                )
            else:
                self.client.secrets.kv.v1.create_or_update_secret(
                    path=path, secret=secret_data, mount_point=mount_point
                )
                return Secret(key=key, value=secret_data, metadata=metadata or {})
        except (Unauthorized, VaultError) as e:
            raise BackendError(f"Failed to write secret: {e}", backend="vault") from e

    def delete(self, key: str) -> bool:
        """Delete a secret from Vault."""
        if not self.client:
            raise ConnectionError("Client not initialized")
        try:
            kv_version = self.config.params.get("kv_version", "2")
            mount_point = self.config.params.get("mount_point", "secret")
            path = key.strip("/")
            if kv_version == "2":
                self.client.secrets.kv.v2.delete_metadata_and_all_versions(
                    path=path, mount_point=mount_point
                )
            else:
                self.client.secrets.kv.v1.delete_secret_version(
                    path=path, mount_point=mount_point
                )
            return True
        except InvalidPath:
            return False
        except (Unauthorized, VaultError) as e:
            raise BackendError(f"Failed to delete secret: {e}", backend="vault") from e

    def list(self, prefix: str = "", limit: int | None = None) -> SecretList:
        """List secrets in Vault."""
        if not self.client:
            raise ConnectionError("Client not initialized")
        try:
            mount_point = self.config.params.get("mount_point", "secret")
            path = prefix.strip("/") if prefix else ""
            kv_version = self.config.params.get("kv_version", "2")
            list_method = (
                self.client.secrets.kv.v2.list_secrets
                if kv_version == "2"
                else self.client.secrets.kv.v1.list_secrets
            )
            response = list_method(path=path, mount_point=mount_point)
            keys = response.get("data", {}).get("keys", [])
            return SecretList(keys=keys[:limit] if limit else keys)
        except InvalidPath:
            return SecretList(keys=[])
        except (Unauthorized, VaultError) as e:
            raise BackendError(f"Failed to list secrets: {e}", backend="vault") from e

    def exists(self, key: str) -> bool:
        """Check if a secret exists in Vault."""
        if not self.client:
            return False
        try:
            self.get(key)
            return True
        except (SecretNotFoundError, Exception):
            return False

    def health_check(self) -> bool:
        """Check Vault health and readiness."""
        if not self.client:
            return False
        try:
            return (
                self.client.sys.is_initialized()
                and not self.client.sys.is_sealed()
            )
        except (VaultDown, VaultError, Exception):
            return False

    def close(self) -> None:
        """Close the Vault client connection."""
        if self.client:
            self.client.close()
            self.client = None
            self._connected = False

    @staticmethod
    def _parse_timestamp(timestamp_str: str | None) -> datetime | None:
        """Parse ISO 8601 timestamp from Vault."""
        if not timestamp_str:
            return None
        try:
            return datetime.fromisoformat(timestamp_str.replace("Z", "+00:00"))
        except (ValueError, AttributeError):
            return None
