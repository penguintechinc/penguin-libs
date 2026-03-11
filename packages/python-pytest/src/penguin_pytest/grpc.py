"""gRPC mock fixtures and helpers for PenguinTech middleware tests."""

from __future__ import annotations

import sys
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock

import pytest


@pytest.fixture(autouse=False)
def mock_grpc_module(monkeypatch: pytest.MonkeyPatch) -> MagicMock:
    """Provide a mock ``grpc`` module for tests that import gRPC middleware.

    The real ``grpcio`` package is not required as a test dependency.  This
    fixture injects a ``MagicMock`` into ``sys.modules["grpc"]`` so that any
    module importing ``grpc`` during the test will receive the mock.

    Set ``autouse=True`` on a per-module basis by adding::

        pytestmark = pytest.mark.usefixtures("mock_grpc_module")

    Returns:
        The ``MagicMock`` grpc module so callers can configure return values.
    """
    mock_grpc: MagicMock = MagicMock()
    mock_grpc.StatusCode.UNAUTHENTICATED = "UNAUTHENTICATED"

    def mock_unary_unary_handler(
        handler: Any,
        request_deserializer: Any = None,
        response_serializer: Any = None,
    ) -> SimpleNamespace:
        return SimpleNamespace(
            handler=handler,
            request_deserializer=request_deserializer,
            response_serializer=response_serializer,
        )

    mock_grpc.unary_unary_rpc_method_handler = mock_unary_unary_handler
    monkeypatch.setitem(sys.modules, "grpc", mock_grpc)
    return mock_grpc


def grpc_handler_call_details(
    method: str,
    metadata: list[tuple[str, str | bytes]] | None = None,
) -> SimpleNamespace:
    """Create a mock ``HandlerCallDetails`` for gRPC interceptor tests.

    Args:
        method: The fully-qualified gRPC method name, e.g.
            ``"/my.Service/Method"``.
        metadata: List of ``(key, value)`` pairs representing invocation
            metadata (default: empty list).

    Returns:
        A :class:`~types.SimpleNamespace` with ``method`` and
        ``invocation_metadata`` attributes, matching the gRPC
        ``HandlerCallDetails`` interface.
    """
    return SimpleNamespace(
        method=method,
        invocation_metadata=metadata if metadata is not None else [],
    )
