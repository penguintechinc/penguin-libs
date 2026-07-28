"""AWS Secrets Manager adapter for penguin-sal."""

from __future__ import annotations

import json
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


class AWSSecretsManagerAdapter(BaseAdapter):
    """AWS Secrets Manager adapter using boto3."""

    def __init__(self, config: ConnectionConfig) -> None:
        super().__init__(config)
        self._client: Any = None

    def _init_connection(self, **kwargs: Any) -> None:
        """Initialize boto3 Secrets Manager client."""
        try:
            import boto3
        except ImportError as e:
            raise ConnectionError(
                "boto3 not installed. Install with: pip install penguin-sal[aws]"
            ) from e

        try:
            client_kwargs: dict[str, Any] = {
                "service_name": "secretsmanager",
            }

            if self.config.host:
                client_kwargs["endpoint_url"] = self.config.host

            region = self.config.params.get("region")
            if region:
                client_kwargs["region_name"] = region

            if self.config.username:
                client_kwargs["aws_access_key_id"] = self.config.username
            if self.config.password:
                client_kwargs["aws_secret_access_key"] = self.config.password

            client_kwargs.update(kwargs)
            self._client = boto3.client(**client_kwargs)
            self._connected = True
        except Exception as e:
            raise ConnectionError(f"Failed to initialize AWS Secrets Manager: {e}") from e

    def authenticate(self) -> None:
        """Verify credentials work by listing secrets."""
        if not self._connected:
            self._init_connection()

        try:
            self._client.list_secrets(MaxResults=1)
        except self._get_client_error() as e:
            error_code = getattr(e, "response", {}).get("Error", {}).get("Code", "")  # type: ignore[union-attr]
            if error_code in ("InvalidSignatureException", "UnrecognizedClientException"):
                raise AuthenticationError(
                    f"Invalid AWS credentials: {e}"
                ) from e
            raise ConnectionError(f"AWS Secrets Manager unreachable: {e}") from e
        except Exception as e:
            raise ConnectionError(f"Authentication check failed: {e}") from e

    def get(self, key: str, version: int | None = None) -> Secret:
        """Retrieve a secret."""
        if not self._connected:
            self._init_connection()

        try:
            kwargs: dict[str, Any] = {"SecretId": key}
            if version is not None:
                kwargs["VersionId"] = str(version)

            response = self._client.get_secret_value(**kwargs)

            value: str | bytes | dict[str, Any]
            if "SecretString" in response:
                try:
                    value = json.loads(response["SecretString"])
                except (json.JSONDecodeError, TypeError):
                    value = response["SecretString"]
            else:
                value = response.get("SecretBinary", b"")

            created_at = response.get("CreatedDate")
            if created_at and not isinstance(created_at, datetime):
                created_at = None

            return Secret(
                key=key,
                value=value,
                version=int(response.get("VersionId", version or 0)) if version else None,
                created_at=created_at,
                metadata={
                    "arn": response.get("ARN"),
                    "version_id": response.get("VersionId"),
                },
            )
        except self._get_client_error() as e:
            error_code = getattr(e, "response", {}).get("Error", {}).get("Code", "")  # type: ignore[union-attr]
            if error_code == "ResourceNotFoundException":
                raise SecretNotFoundError(key, backend="aws-sm") from e
            raise BackendError(
                f"Failed to get secret {key}: {e}",
                backend="aws-sm",
                original_error=e,
            ) from e
        except BackendError:
            raise
        except Exception as e:
            raise BackendError(
                f"Unexpected error retrieving secret {key}: {e}",
                backend="aws-sm",
                original_error=e,
            ) from e

    def set(
        self,
        key: str,
        value: str | bytes | dict[str, Any],
        metadata: dict[str, Any] | None = None,
    ) -> Secret:
        """Create or update a secret."""
        if not self._connected:
            self._init_connection()

        secret_value = self._serialize_value(value)

        try:
            response = self._client.put_secret_value(
                SecretId=key,
                SecretString=secret_value if isinstance(secret_value, str) else None,
                SecretBinary=secret_value if isinstance(secret_value, bytes) else None,
            )
            return Secret(
                key=key,
                value=value,
                version=None,
                metadata={
                    "arn": response.get("ARN"),
                    "version_id": response.get("VersionId"),
                },
            )
        except self._get_client_error() as e:
            error_code = getattr(e, "response", {}).get("Error", {}).get("Code", "")  # type: ignore[union-attr]
            if error_code == "ResourceNotFoundException":
                try:
                    response = self._client.create_secret(
                        Name=key,
                        SecretString=secret_value if isinstance(secret_value, str) else None,
                        SecretBinary=secret_value if isinstance(secret_value, bytes) else None,
                        Description=metadata.get("description", "")
                        if metadata else "",
                    )
                    return Secret(
                        key=key,
                        value=value,
                        metadata={
                            "arn": response.get("ARN"),
                            "version_id": response.get("VersionId"),
                        },
                    )
                except self._get_client_error() as create_error:
                    raise BackendError(
                        f"Failed to create secret {key}: {create_error}",
                        backend="aws-sm",
                        original_error=create_error,
                    ) from create_error
            raise BackendError(
                f"Failed to set secret {key}: {e}",
                backend="aws-sm",
                original_error=e,
            ) from e
        except BackendError:
            raise
        except Exception as e:
            raise BackendError(
                f"Unexpected error setting secret {key}: {e}",
                backend="aws-sm",
                original_error=e,
            ) from e

    def delete(self, key: str) -> bool:
        """Delete a secret."""
        if not self._connected:
            self._init_connection()

        try:
            self._client.delete_secret(
                SecretId=key,
                ForceDeleteWithoutRecovery=True,
            )
            return True
        except self._get_client_error() as e:
            error_code = getattr(e, "response", {}).get("Error", {}).get("Code", "")  # type: ignore[union-attr]
            if error_code == "ResourceNotFoundException":
                return False
            raise BackendError(
                f"Failed to delete secret {key}: {e}",
                backend="aws-sm",
                original_error=e,
            ) from e
        except Exception as e:
            raise BackendError(
                f"Unexpected error deleting secret {key}: {e}",
                backend="aws-sm",
                original_error=e,
            ) from e

    def list(self, prefix: str = "", limit: int | None = None) -> SecretList:
        """List secret keys."""
        if not self._connected:
            self._init_connection()

        try:
            paginator = self._client.get_paginator("list_secrets")
            keys: list[str] = []
            cursor: str | None = None

            for page in paginator.paginate():
                for secret in page.get("SecretList", []):
                    name = secret.get("Name", "")
                    if prefix and not name.startswith(prefix):
                        continue
                    keys.append(name)
                    if limit and len(keys) >= limit:
                        break

                if limit and len(keys) >= limit:
                    break

            return SecretList(keys=keys[:limit] if limit else keys, cursor=cursor)
        except self._get_client_error() as e:
            raise BackendError(
                f"Failed to list secrets: {e}",
                backend="aws-sm",
                original_error=e,
            ) from e
        except Exception as e:
            raise BackendError(
                f"Unexpected error listing secrets: {e}",
                backend="aws-sm",
                original_error=e,
            ) from e

    def exists(self, key: str) -> bool:
        """Check if a secret exists."""
        if not self._connected:
            self._init_connection()

        try:
            self._client.describe_secret(SecretId=key)
            return True
        except Exception as e:
            if hasattr(e, "response"):
                error_code = e.response.get("Error", {}).get("Code", "")
                if error_code == "ResourceNotFoundException":
                    return False
            return False

    def health_check(self) -> bool:
        """Check if the backend is healthy."""
        if not self._connected:
            try:
                self._init_connection()
            except ConnectionError:
                return False

        try:
            self._client.list_secrets(MaxResults=1)
            return True
        except Exception:
            return False

    def close(self) -> None:
        """Close the connection and release resources."""
        self._client = None
        self._connected = False

    def _serialize_value(self, value: str | bytes | dict[str, Any]) -> str | bytes:
        """Serialize a value for storage."""
        if isinstance(value, dict):
            return json.dumps(value)
        return value

    def _get_client_error(self) -> type[BaseException]:
        """Get the botocore ClientError exception type."""
        try:
            import botocore.exceptions  # type: ignore[import-not-found]
            return botocore.exceptions.ClientError  # type: ignore[attr-defined,return-value]
        except ImportError:
            return Exception  # type: ignore[return-value]
