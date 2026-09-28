"""Supplementary coverage tests for the AWS Secrets Manager adapter.

Targets branches the primary test_aws_sm_adapter.py suite doesn't reach:
the "not yet connected" lazy-init guard on every public method, the
region/credential kwargs path in _init_connection, and the generic
Exception -> BackendError/ConnectionError wrapping branches.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from penguin_aaa.secrets.adapters.aws_sm import AWSSecretsManagerAdapter
from penguin_aaa.secrets.core.exceptions import BackendError, ConnectionError
from penguin_aaa.secrets.core.types import ConnectionConfig


def _lazy_adapter() -> AWSSecretsManagerAdapter:
    """Adapter with _connected=False, whose _init_connection is stubbed to
    attach a MagicMock client and flip _connected to True."""
    config = ConnectionConfig(scheme="aws-sm", host="localhost")
    adapter = AWSSecretsManagerAdapter(config)

    def _fake_init(**kwargs: object) -> None:
        adapter._client = MagicMock()
        adapter._connected = True

    adapter._init_connection = _fake_init  # type: ignore[method-assign]
    return adapter


class TestLazyInitGuard:
    """Every public method must call _init_connection when not connected."""

    def test_authenticate_initializes_when_not_connected(self) -> None:
        adapter = _lazy_adapter()
        adapter._client = None
        adapter._init_connection()  # priming won't matter; call authenticate directly
        adapter._connected = False
        adapter.authenticate()
        assert adapter._connected is True

    def test_get_initializes_when_not_connected(self) -> None:
        adapter = _lazy_adapter()
        adapter._connected = False
        adapter.get("k")
        assert adapter._connected is True

    def test_set_initializes_when_not_connected(self) -> None:
        adapter = _lazy_adapter()
        adapter._connected = False
        adapter.set("k", "v")
        assert adapter._connected is True

    def test_delete_initializes_when_not_connected(self) -> None:
        adapter = _lazy_adapter()
        adapter._connected = False
        adapter.delete("k")
        assert adapter._connected is True

    def test_list_initializes_when_not_connected(self) -> None:
        adapter = _lazy_adapter()
        adapter._init_connection()
        adapter._client.get_paginator.return_value.paginate.return_value = []
        adapter._connected = False
        adapter.list()
        assert adapter._connected is True

    def test_exists_initializes_when_not_connected(self) -> None:
        adapter = _lazy_adapter()
        adapter._connected = False
        adapter.exists("k")
        assert adapter._connected is True


class TestInitConnectionKwargs:
    """Region and static-credential params get forwarded to boto3.client()."""

    def test_region_and_credentials_forwarded(self) -> None:
        config = ConnectionConfig(
            scheme="aws-sm",
            host="localhost",
            username="AKIA_TEST",
            password="secret-key",
            params={"region": "us-west-2"},
        )
        adapter = AWSSecretsManagerAdapter(config)

        fake_boto3 = MagicMock()
        with patch.dict("sys.modules", {"boto3": fake_boto3}):
            adapter._init_connection()

        _, kwargs = fake_boto3.client.call_args
        assert kwargs["region_name"] == "us-west-2"
        assert kwargs["aws_access_key_id"] == "AKIA_TEST"
        assert kwargs["aws_secret_access_key"] == "secret-key"

    def test_init_connection_wraps_generic_exception(self) -> None:
        config = ConnectionConfig(scheme="aws-sm", host="localhost")
        adapter = AWSSecretsManagerAdapter(config)

        fake_boto3 = MagicMock()
        fake_boto3.client.side_effect = RuntimeError("boom")
        with patch.dict("sys.modules", {"boto3": fake_boto3}):
            with pytest.raises(ConnectionError, match="Failed to initialize"):
                adapter._init_connection()


class TestGenericExceptionWrapping:
    """Non-botocore exceptions still get wrapped, never leak raw."""

    def test_authenticate_wraps_generic_exception(self) -> None:
        # Without botocore installed, _get_client_error() falls back to the
        # bare Exception type, so a ValueError is caught there rather than
        # by the trailing `except Exception` -- either way it must come out
        # as a ConnectionError, never leak raw.
        adapter = _lazy_adapter()
        adapter._init_connection()
        adapter._client.list_secrets.side_effect = ValueError("weird")
        with pytest.raises(ConnectionError):
            adapter.authenticate()

    def test_get_reraises_backend_error_unchanged(self) -> None:
        adapter = _lazy_adapter()
        adapter._init_connection()
        adapter._client.get_secret_value.side_effect = BackendError(
            "already wrapped", backend="aws-sm"
        )
        with pytest.raises(BackendError, match="already wrapped"):
            adapter.get("k")

    def test_set_reraises_backend_error_unchanged(self) -> None:
        adapter = _lazy_adapter()
        adapter._init_connection()
        adapter._client.put_secret_value.side_effect = BackendError(
            "already wrapped", backend="aws-sm"
        )
        with pytest.raises(BackendError, match="already wrapped"):
            adapter.set("k", "v")
