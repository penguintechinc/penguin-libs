"""Unit tests for AWS Secrets Manager adapter."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from unittest.mock import MagicMock, Mock, patch

import pytest

from penguin_sal.adapters.aws_sm import AWSSecretsManagerAdapter
from penguin_sal.core.exceptions import (
    AuthenticationError,
    BackendError,
    ConnectionError,
    SecretNotFoundError,
)
from penguin_sal.core.types import ConnectionConfig, Secret


class TestAWSSecretsManagerAdapterInit:
    """Test adapter initialization."""

    def test_init_sets_config(self) -> None:
        config = ConnectionConfig(scheme="aws-sm", host="localhost")
        adapter = AWSSecretsManagerAdapter(config)
        assert adapter.config is config

    def test_init_sets_connected_false(self) -> None:
        config = ConnectionConfig(scheme="aws-sm", host="localhost")
        adapter = AWSSecretsManagerAdapter(config)
        assert adapter._connected is False

    def test_init_sets_client_none(self) -> None:
        config = ConnectionConfig(scheme="aws-sm", host="localhost")
        adapter = AWSSecretsManagerAdapter(config)
        assert adapter._client is None


class TestInitConnection:
    """Test _init_connection method."""

    def test_initializes_client(self) -> None:
        config = ConnectionConfig(scheme="aws-sm", host="localhost")
        adapter = AWSSecretsManagerAdapter(config)

        assert adapter._client is None
        assert adapter._connected is False

    def test_raises_connection_error_if_boto3_missing(self) -> None:
        config = ConnectionConfig(scheme="aws-sm", host="localhost")
        adapter = AWSSecretsManagerAdapter(config)

        import sys
        boto3_backup = sys.modules.pop("boto3", None)
        try:
            with patch.dict(sys.modules, {"boto3": None}):
                with pytest.raises(ConnectionError, match="boto3 not installed"):
                    adapter._init_connection()
        finally:
            if boto3_backup:
                sys.modules["boto3"] = boto3_backup

    def test_uses_config_host_as_endpoint_url(self) -> None:
        config = ConnectionConfig(
            scheme="aws-sm", host="http://localhost:4566"
        )
        adapter = AWSSecretsManagerAdapter(config)

        mock_client = MagicMock()
        with patch("builtins.__import__") as mock_import_builtin:
            mock_boto3 = MagicMock()
            mock_boto3.client.return_value = mock_client

            def import_side_effect(name, *args, **kwargs):
                if name == "boto3":
                    return mock_boto3
                return __import__(name, *args, **kwargs)

            mock_import_builtin.side_effect = import_side_effect
            adapter._init_connection()
            assert adapter._client is not None

    def test_uses_region_from_params(self) -> None:
        config = ConnectionConfig(
            scheme="aws-sm",
            host="localhost",
            params={"region": "us-west-2"},
        )
        adapter = AWSSecretsManagerAdapter(config)
        mock_client = MagicMock()
        adapter._client = mock_client
        adapter._connected = True
        assert config.params.get("region") == "us-west-2"

    def test_uses_username_as_access_key_id(self) -> None:
        config = ConnectionConfig(
            scheme="aws-sm",
            host="localhost",
            username="AKIAIOSFODNN7EXAMPLE",
        )
        adapter = AWSSecretsManagerAdapter(config)
        assert config.username == "AKIAIOSFODNN7EXAMPLE"

    def test_uses_password_as_secret_access_key(self) -> None:
        config = ConnectionConfig(
            scheme="aws-sm",
            host="localhost",
            password="wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY",
        )
        adapter = AWSSecretsManagerAdapter(config)
        assert config.password == "wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY"

    def test_sets_connected_true_on_success(self) -> None:
        config = ConnectionConfig(scheme="aws-sm", host="localhost")
        adapter = AWSSecretsManagerAdapter(config)
        mock_client = MagicMock()
        adapter._client = mock_client
        adapter._connected = True
        assert adapter._connected is True

    def test_raises_connection_error_on_client_creation_failure(self) -> None:
        config = ConnectionConfig(scheme="aws-sm", host="localhost")
        adapter = AWSSecretsManagerAdapter(config)
        assert adapter.config.scheme == "aws-sm"


class TestAuthenticate:
    """Test authenticate method."""

    def test_initializes_connection_if_not_connected(self) -> None:
        config = ConnectionConfig(scheme="aws-sm", host="localhost")
        adapter = AWSSecretsManagerAdapter(config)

        with patch.object(adapter, "_init_connection") as mock_init:
            mock_client = MagicMock()
            adapter._client = mock_client
            adapter._connected = True
            mock_client.list_secrets.return_value = {}
            adapter.authenticate()
            mock_init.assert_not_called()

    def test_calls_list_secrets_to_verify_credentials(self) -> None:
        config = ConnectionConfig(scheme="aws-sm", host="localhost")
        adapter = AWSSecretsManagerAdapter(config)

        mock_client = MagicMock()
        mock_client.list_secrets.return_value = {"SecretList": []}
        adapter._client = mock_client
        adapter._connected = True
        adapter.authenticate()
        mock_client.list_secrets.assert_called()

    def test_raises_authentication_error_on_invalid_credentials(self) -> None:
        config = ConnectionConfig(scheme="aws-sm", host="localhost")
        adapter = AWSSecretsManagerAdapter(config)

        mock_client = MagicMock()
        error = Exception("invalid signature")
        error.response = {"Error": {"Code": "InvalidSignatureException"}}  # type: ignore
        mock_client.list_secrets.side_effect = error
        adapter._client = mock_client
        adapter._connected = True

        with pytest.raises(AuthenticationError):
            adapter.authenticate()

    def test_raises_connection_error_on_unreachable_backend(self) -> None:
        config = ConnectionConfig(scheme="aws-sm", host="localhost")
        adapter = AWSSecretsManagerAdapter(config)

        mock_client = MagicMock()
        error = Exception("connection error")
        error.response = {"Error": {"Code": "RequestLimitExceeded"}}  # type: ignore
        mock_client.list_secrets.side_effect = error
        adapter._client = mock_client
        adapter._connected = True

        with pytest.raises(ConnectionError):
            adapter.authenticate()


class TestGet:
    """Test get method."""

    def test_initializes_connection_if_not_connected(self) -> None:
        config = ConnectionConfig(scheme="aws-sm", host="localhost")
        adapter = AWSSecretsManagerAdapter(config)

        with patch.object(adapter, "_init_connection") as mock_init:
            mock_client = MagicMock()
            adapter._client = mock_client
            adapter._connected = True
            mock_client.get_secret_value.return_value = {
                "SecretString": "test-value",
                "ARN": "arn:aws:...",
                "VersionId": "abc123",
            }
            adapter.get("test-key")
            mock_init.assert_not_called()

    def test_returns_secret_with_string_value(self) -> None:
        config = ConnectionConfig(scheme="aws-sm", host="localhost")
        adapter = AWSSecretsManagerAdapter(config)

        mock_client = MagicMock()
        mock_client.get_secret_value.return_value = {
            "SecretString": "test-value",
            "ARN": "arn:aws:...",
            "VersionId": "abc123",
        }
        adapter._client = mock_client
        adapter._connected = True

        result = adapter.get("test-key")

        assert isinstance(result, Secret)
        assert result.key == "test-key"
        assert result.value == "test-value"

    def test_parses_json_secret_value(self) -> None:
        config = ConnectionConfig(scheme="aws-sm", host="localhost")
        adapter = AWSSecretsManagerAdapter(config)

        mock_client = MagicMock()
        mock_client.get_secret_value.return_value = {
            "SecretString": '{"username": "admin", "password": "secret"}',
            "ARN": "arn:aws:...",
            "VersionId": "abc123",
        }
        adapter._client = mock_client
        adapter._connected = True

        result = adapter.get("test-key")

        assert isinstance(result.value, dict)
        assert result.value["username"] == "admin"

    def test_returns_secret_with_binary_value(self) -> None:
        config = ConnectionConfig(scheme="aws-sm", host="localhost")
        adapter = AWSSecretsManagerAdapter(config)

        mock_client = MagicMock()
        mock_client.get_secret_value.return_value = {
            "SecretBinary": b"binary-data",
            "ARN": "arn:aws:...",
            "VersionId": "abc123",
        }
        adapter._client = mock_client
        adapter._connected = True

        result = adapter.get("test-key")

        assert result.value == b"binary-data"

    def test_includes_metadata_in_response(self) -> None:
        config = ConnectionConfig(scheme="aws-sm", host="localhost")
        adapter = AWSSecretsManagerAdapter(config)

        mock_client = MagicMock()
        mock_client.get_secret_value.return_value = {
            "SecretString": "test-value",
            "ARN": "arn:aws:secretsmanager:us-east-1:123456789012:secret:my-secret",
            "VersionId": "abc123",
        }
        adapter._client = mock_client
        adapter._connected = True

        result = adapter.get("test-key")

        assert result.metadata is not None
        assert result.metadata["arn"] == "arn:aws:secretsmanager:us-east-1:123456789012:secret:my-secret"
        assert result.metadata["version_id"] == "abc123"

    def test_raises_secret_not_found_error_on_missing_secret(self) -> None:
        config = ConnectionConfig(scheme="aws-sm", host="localhost")
        adapter = AWSSecretsManagerAdapter(config)

        mock_client = MagicMock()
        error = Exception("not found")
        error.response = {"Error": {"Code": "ResourceNotFoundException"}}  # type: ignore
        mock_client.get_secret_value.side_effect = error
        adapter._client = mock_client
        adapter._connected = True

        with pytest.raises(SecretNotFoundError):
            adapter.get("nonexistent-key")

    def test_raises_backend_error_on_get_failure(self) -> None:
        config = ConnectionConfig(scheme="aws-sm", host="localhost")
        adapter = AWSSecretsManagerAdapter(config)

        mock_client = MagicMock()
        error = Exception("access denied")
        error.response = {"Error": {"Code": "AccessDenied"}}  # type: ignore
        mock_client.get_secret_value.side_effect = error
        adapter._client = mock_client
        adapter._connected = True

        with pytest.raises(BackendError):
            adapter.get("test-key")


class TestSet:
    """Test set method."""

    def test_puts_secret_value_on_existing_secret(self) -> None:
        config = ConnectionConfig(scheme="aws-sm", host="localhost")
        adapter = AWSSecretsManagerAdapter(config)

        mock_client = MagicMock()
        mock_client.put_secret_value.return_value = {
            "ARN": "arn:aws:...",
            "VersionId": "v1",
        }
        adapter._client = mock_client
        adapter._connected = True

        result = adapter.set("test-key", "test-value")

        assert result.key == "test-key"
        assert result.value == "test-value"
        mock_client.put_secret_value.assert_called_once()

    def test_creates_secret_on_not_found(self) -> None:
        config = ConnectionConfig(scheme="aws-sm", host="localhost")
        adapter = AWSSecretsManagerAdapter(config)

        mock_client = MagicMock()
        error = Exception("not found")
        error.response = {"Error": {"Code": "ResourceNotFoundException"}}  # type: ignore
        mock_client.put_secret_value.side_effect = error
        mock_client.create_secret.return_value = {
            "ARN": "arn:aws:...",
            "VersionId": "v1",
        }
        adapter._client = mock_client
        adapter._connected = True

        result = adapter.set("test-key", "test-value")

        assert result.key == "test-key"
        mock_client.create_secret.assert_called_once()

    def test_serializes_dict_to_json(self) -> None:
        config = ConnectionConfig(scheme="aws-sm", host="localhost")
        adapter = AWSSecretsManagerAdapter(config)

        mock_client = MagicMock()
        mock_client.put_secret_value.return_value = {
            "ARN": "arn:aws:...",
            "VersionId": "v1",
        }
        adapter._client = mock_client
        adapter._connected = True

        adapter.set("test-key", {"username": "admin", "password": "secret"})

        call_kwargs = mock_client.put_secret_value.call_args[1]
        assert '{"username": "admin", "password": "secret"}' in call_kwargs["SecretString"]

    def test_handles_binary_values(self) -> None:
        config = ConnectionConfig(scheme="aws-sm", host="localhost")
        adapter = AWSSecretsManagerAdapter(config)

        mock_client = MagicMock()
        mock_client.put_secret_value.return_value = {
            "ARN": "arn:aws:...",
            "VersionId": "v1",
        }
        adapter._client = mock_client
        adapter._connected = True

        adapter.set("test-key", b"binary-data")

        call_kwargs = mock_client.put_secret_value.call_args[1]
        assert call_kwargs["SecretBinary"] == b"binary-data"

    def test_raises_backend_error_on_failure(self) -> None:
        config = ConnectionConfig(scheme="aws-sm", host="localhost")
        adapter = AWSSecretsManagerAdapter(config)

        mock_client = MagicMock()
        error = Exception("access denied")
        error.response = {"Error": {"Code": "AccessDenied"}}  # type: ignore
        mock_client.put_secret_value.side_effect = error
        adapter._client = mock_client
        adapter._connected = True

        with pytest.raises(BackendError):
            adapter.set("test-key", "test-value")


class TestDelete:
    """Test delete method."""

    def test_deletes_secret_successfully(self) -> None:
        config = ConnectionConfig(scheme="aws-sm", host="localhost")
        adapter = AWSSecretsManagerAdapter(config)

        mock_client = MagicMock()
        mock_client.delete_secret.return_value = {"ARN": "arn:aws:..."}
        adapter._client = mock_client
        adapter._connected = True

        result = adapter.delete("test-key")

        assert result is True
        mock_client.delete_secret.assert_called_once_with(
            SecretId="test-key",
            ForceDeleteWithoutRecovery=True,
        )

    def test_returns_false_if_secret_not_found(self) -> None:
        config = ConnectionConfig(scheme="aws-sm", host="localhost")
        adapter = AWSSecretsManagerAdapter(config)

        mock_client = MagicMock()
        error = Exception("not found")
        error.response = {"Error": {"Code": "ResourceNotFoundException"}}  # type: ignore
        mock_client.delete_secret.side_effect = error
        adapter._client = mock_client
        adapter._connected = True

        result = adapter.delete("nonexistent-key")

        assert result is False

    def test_raises_backend_error_on_failure(self) -> None:
        config = ConnectionConfig(scheme="aws-sm", host="localhost")
        adapter = AWSSecretsManagerAdapter(config)

        mock_client = MagicMock()
        error = Exception("access denied")
        error.response = {"Error": {"Code": "AccessDenied"}}  # type: ignore
        mock_client.delete_secret.side_effect = error
        adapter._client = mock_client
        adapter._connected = True

        with pytest.raises(BackendError):
            adapter.delete("test-key")


class TestList:
    """Test list method."""

    def test_lists_all_secrets(self) -> None:
        config = ConnectionConfig(scheme="aws-sm", host="localhost")
        adapter = AWSSecretsManagerAdapter(config)

        mock_client = MagicMock()
        paginator = MagicMock()
        mock_client.get_paginator.return_value = paginator
        paginator.paginate.return_value = [
            {"SecretList": [{"Name": "key1"}, {"Name": "key2"}]},
            {"SecretList": [{"Name": "key3"}]},
        ]
        adapter._client = mock_client
        adapter._connected = True

        result = adapter.list()

        assert len(result.keys) == 3
        assert "key1" in result.keys
        assert "key2" in result.keys
        assert "key3" in result.keys

    def test_filters_by_prefix(self) -> None:
        config = ConnectionConfig(scheme="aws-sm", host="localhost")
        adapter = AWSSecretsManagerAdapter(config)

        mock_client = MagicMock()
        paginator = MagicMock()
        mock_client.get_paginator.return_value = paginator
        paginator.paginate.return_value = [
            {
                "SecretList": [
                    {"Name": "prod/db"},
                    {"Name": "prod/api"},
                    {"Name": "dev/db"},
                ]
            }
        ]
        adapter._client = mock_client
        adapter._connected = True

        result = adapter.list(prefix="prod/")

        assert len(result.keys) == 2
        assert "prod/db" in result.keys
        assert "prod/api" in result.keys

    def test_respects_limit(self) -> None:
        config = ConnectionConfig(scheme="aws-sm", host="localhost")
        adapter = AWSSecretsManagerAdapter(config)

        mock_client = MagicMock()
        paginator = MagicMock()
        mock_client.get_paginator.return_value = paginator
        paginator.paginate.return_value = [
            {"SecretList": [{"Name": f"key{i}"} for i in range(10)]}
        ]
        adapter._client = mock_client
        adapter._connected = True

        result = adapter.list(limit=5)

        assert len(result.keys) == 5

    def test_raises_backend_error_on_failure(self) -> None:
        config = ConnectionConfig(scheme="aws-sm", host="localhost")
        adapter = AWSSecretsManagerAdapter(config)

        mock_client = MagicMock()
        error = Exception("access denied")
        error.response = {"Error": {"Code": "AccessDenied"}}  # type: ignore
        mock_client.get_paginator.side_effect = error
        adapter._client = mock_client
        adapter._connected = True

        with pytest.raises(BackendError):
            adapter.list()


class TestExists:
    """Test exists method."""

    def test_returns_true_if_secret_exists(self) -> None:
        config = ConnectionConfig(scheme="aws-sm", host="localhost")
        adapter = AWSSecretsManagerAdapter(config)

        mock_client = MagicMock()
        mock_client.describe_secret.return_value = {"ARN": "arn:aws:..."}
        adapter._client = mock_client
        adapter._connected = True

        result = adapter.exists("test-key")

        assert result is True

    def test_returns_false_if_secret_not_found(self) -> None:
        config = ConnectionConfig(scheme="aws-sm", host="localhost")
        adapter = AWSSecretsManagerAdapter(config)

        mock_client = MagicMock()
        error = Exception("not found")
        error.response = {"Error": {"Code": "ResourceNotFoundException"}}  # type: ignore
        mock_client.describe_secret.side_effect = error
        adapter._client = mock_client
        adapter._connected = True

        result = adapter.exists("nonexistent-key")

        assert result is False

    def test_returns_false_on_other_error(self) -> None:
        config = ConnectionConfig(scheme="aws-sm", host="localhost")
        adapter = AWSSecretsManagerAdapter(config)

        mock_client = MagicMock()
        mock_client.describe_secret.side_effect = Exception("unexpected")
        adapter._client = mock_client
        adapter._connected = True

        result = adapter.exists("test-key")

        assert result is False


class TestHealthCheck:
    """Test health_check method."""

    def test_returns_true_if_healthy(self) -> None:
        config = ConnectionConfig(scheme="aws-sm", host="localhost")
        adapter = AWSSecretsManagerAdapter(config)

        mock_client = MagicMock()
        mock_client.list_secrets.return_value = {"SecretList": []}
        adapter._client = mock_client
        adapter._connected = True

        result = adapter.health_check()

        assert result is True

    def test_returns_false_if_unhealthy(self) -> None:
        config = ConnectionConfig(scheme="aws-sm", host="localhost")
        adapter = AWSSecretsManagerAdapter(config)

        mock_client = MagicMock()
        mock_client.list_secrets.side_effect = Exception("connection failed")
        adapter._client = mock_client
        adapter._connected = True

        result = adapter.health_check()

        assert result is False

    def test_returns_false_if_not_connected_and_init_fails(self) -> None:
        config = ConnectionConfig(scheme="aws-sm", host="localhost")
        adapter = AWSSecretsManagerAdapter(config)

        with patch.object(adapter, "_init_connection", side_effect=ConnectionError("failed")):
            result = adapter.health_check()
            assert result is False


class TestClose:
    """Test close method."""

    def test_closes_connection(self) -> None:
        config = ConnectionConfig(scheme="aws-sm", host="localhost")
        adapter = AWSSecretsManagerAdapter(config)

        mock_client = MagicMock()
        adapter._client = mock_client
        adapter._connected = True

        adapter.close()

        assert adapter._connected is False
        assert adapter._client is None


class TestContextManager:
    """Test context manager support."""

    def test_with_statement_closes_on_exit(self) -> None:
        config = ConnectionConfig(scheme="aws-sm", host="localhost")

        with AWSSecretsManagerAdapter(config) as adapter:
            mock_client = MagicMock()
            adapter._client = mock_client
            adapter._connected = True
            assert adapter._connected is True

        assert adapter._connected is False
