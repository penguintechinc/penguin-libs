"""Passbolt password manager adapter for penguin-sal."""

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


class PassboltAdapter(BaseAdapter):
    """Passbolt password manager secrets adapter.

    Provides CRUD operations for password resources in Passbolt using GPG encryption.
    Config params: private_key_path (file path), private_key (content),
    fingerprint (GPG fingerprint, optional).
    """

    def __init__(self, config: ConnectionConfig) -> None:
        super().__init__(config)
        self._client: Any = None

    def _init_connection(self, **kwargs: Any) -> None:
        """Initialize Passbolt API client. Raises ConnectionError on failure."""
        try:
            from passbolt_python_api import PassboltAPI
        except ImportError as e:
            raise ImportError(
                "passbolt-python-api required. Install: pip install penguin-sal[passbolt]"
            ) from e

        try:
            scheme = "https" if "://" not in self.config.host else ""
            url = f"{scheme}{self.config.host}" if scheme else self.config.host
            self._client = PassboltAPI(
                url=url,
                username=self.config.username,
                private_key_path=self.config.params.get("private_key_path"),
                private_key=self.config.params.get("private_key"),
                server_public_key_path=None,
                fingerprint=self.config.params.get("fingerprint"),
            )
            self._connected = True
        except Exception as e:
            raise ConnectionError(f"Failed to initialize Passbolt client: {e}") from e

    def authenticate(self) -> None:
        """Authenticate with Passbolt. Raises AuthenticationError on failure."""
        if not self._client:
            self._init_connection()
        try:
            self._client.login()
        except Exception as e:
            raise AuthenticationError(f"Passbolt authentication failed: {e}") from e

    def get(self, key: str, version: int | None = None) -> Secret:
        """Retrieve secret by resource name. Raises SecretNotFoundError if not found."""
        if not self._client:
            self._init_connection()

        try:
            resources = self._client.get_resources()
            resource = next(
                (res for res in resources if res.get("name") == key), None
            )
            if not resource:
                raise SecretNotFoundError(key, backend="passbolt")

            resource_id = resource.get("id")
            secret = self._client.get_secret(resource_id)
            password_value = secret.get("password", "")

            def parse_timestamp(ts: str | None) -> datetime | None:
                if not ts:
                    return None
                try:
                    return datetime.fromisoformat(ts.replace("Z", "+00:00"))
                except (ValueError, AttributeError):
                    return None

            return Secret(
                key=key,
                value=password_value,
                version=1,
                created_at=parse_timestamp(resource.get("created")),
                updated_at=parse_timestamp(resource.get("modified")),
            )
        except SecretNotFoundError:
            raise
        except Exception as e:
            raise BackendError(
                f"Failed to retrieve secret {key}",
                backend="passbolt",
                original_error=e,
            ) from e

    def set(
        self,
        key: str,
        value: str | bytes | dict[str, Any],
        metadata: dict[str, Any] | None = None,
    ) -> Secret:
        """Create or update a resource. Raises BackendError on failure."""
        if not self._client:
            self._init_connection()

        if isinstance(value, bytes):
            value = value.decode("utf-8")
        elif isinstance(value, dict):
            value = str(value)

        try:
            resources = self._client.get_resources()
            existing = next(
                (res for res in resources if res.get("name") == key), None
            )

            if existing:
                self._client.update_secret(existing.get("id"), value)
                return Secret(key=key, value=value, version=1)

            meta = metadata or {}
            self._client.create_resource(
                {
                    "name": key,
                    "password": value,
                    "username": meta.get("username"),
                    "uri": meta.get("uri"),
                    "description": meta.get("description"),
                }
            )
            return Secret(key=key, value=value, version=1, metadata=metadata)
        except Exception as e:
            raise BackendError(
                f"Failed to set secret {key}",
                backend="passbolt",
                original_error=e,
            ) from e

    def delete(self, key: str) -> bool:
        """Delete a resource. Returns True if deleted, False if not found."""
        if not self._client:
            self._init_connection()

        try:
            resources = self._client.get_resources()
            resource = next(
                (res for res in resources if res.get("name") == key), None
            )
            if resource:
                self._client.delete_resource(resource.get("id"))
                return True
            return False
        except Exception as e:
            raise BackendError(
                f"Failed to delete secret {key}",
                backend="passbolt",
                original_error=e,
            ) from e

    def list(self, prefix: str = "", limit: int | None = None) -> SecretList:
        """List resources, optionally filtered by prefix."""
        if not self._client:
            self._init_connection()

        try:
            resources = self._client.get_resources()
            keys = []
            for res in resources:
                name = res.get("name", "")
                if name.startswith(prefix):
                    keys.append(name)
                    if limit and len(keys) >= limit:
                        break
            return SecretList(keys=keys)
        except Exception as e:
            raise BackendError(
                "Failed to list secrets",
                backend="passbolt",
                original_error=e,
            ) from e

    def exists(self, key: str) -> bool:
        """Check if resource exists. Returns False on error."""
        if not self._client:
            self._init_connection()
        try:
            return any(res.get("name") == key for res in self._client.get_resources())
        except Exception:
            return False

    def health_check(self) -> bool:
        """Check server health. Returns False on error."""
        if not self._client:
            try:
                self._init_connection()
            except (ConnectionError, Exception):
                return False
        try:
            self._client.get_server()
            return True
        except Exception:
            return False

    def close(self) -> None:
        """Close Passbolt session."""
        if self._client:
            try:
                self._client.logout()
            except Exception:
                pass
        self._connected = False
        self._client = None
