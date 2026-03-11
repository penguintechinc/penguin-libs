"""Tests for penguin_pytest.grpc helpers."""

from __future__ import annotations

import sys
from unittest.mock import MagicMock

from penguin_pytest.grpc import grpc_handler_call_details


def test_grpc_handler_call_details_defaults() -> None:
    details = grpc_handler_call_details("/my.Service/Method")
    assert details.method == "/my.Service/Method"
    assert details.invocation_metadata == []


def test_grpc_handler_call_details_with_metadata() -> None:
    meta = [("authorization", "Bearer tok")]
    details = grpc_handler_call_details("/svc/method", metadata=meta)
    assert details.invocation_metadata == meta


def test_mock_grpc_module_injects_into_sys_modules(mock_grpc_module: MagicMock) -> None:
    assert "grpc" in sys.modules
    assert sys.modules["grpc"] is mock_grpc_module


def test_mock_grpc_module_has_unauthenticated_status(mock_grpc_module: MagicMock) -> None:
    assert mock_grpc_module.StatusCode.UNAUTHENTICATED == "UNAUTHENTICATED"


def test_mock_grpc_module_unary_handler(mock_grpc_module: MagicMock) -> None:
    handler = lambda req, ctx: "response"  # noqa: E731
    result = mock_grpc_module.unary_unary_rpc_method_handler(handler)
    assert result.handler is handler
