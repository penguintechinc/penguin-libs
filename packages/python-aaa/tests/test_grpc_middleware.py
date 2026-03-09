"""Tests for penguin_aaa.middleware.grpc — gRPC OIDC auth interceptor."""

import sys
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest


# grpc is not installed, so we need to mock it before importing the module
@pytest.fixture(autouse=True)
def _mock_grpc(monkeypatch):
    """Provide a mock grpc module for all tests in this module."""
    mock_grpc = MagicMock()
    mock_grpc.StatusCode.UNAUTHENTICATED = "UNAUTHENTICATED"

    def mock_unary_unary_handler(handler, request_deserializer=None, response_serializer=None):
        return SimpleNamespace(
            handler=handler,
            request_deserializer=request_deserializer,
            response_serializer=response_serializer,
        )

    mock_grpc.unary_unary_rpc_method_handler = mock_unary_unary_handler
    monkeypatch.setitem(sys.modules, "grpc", mock_grpc)


def _make_handler_call_details(method, metadata=None):
    """Create a mock HandlerCallDetails."""
    if metadata is None:
        metadata = []
    return SimpleNamespace(method=method, invocation_metadata=metadata)


def _import_interceptor():
    """Import OIDCAuthInterceptor after grpc mock is in place."""
    # Force re-import to pick up the mock
    mod_name = "penguin_aaa.middleware.grpc"
    if mod_name in sys.modules:
        del sys.modules[mod_name]
    from penguin_aaa.middleware.grpc import OIDCAuthInterceptor

    return OIDCAuthInterceptor


class TestOIDCAuthInterceptor:
    def test_public_method_bypasses_auth(self):
        cls = _import_interceptor()
        rp = MagicMock()
        interceptor = cls(rp, public_methods={"/grpc.health.v1.Health/Check"})
        details = _make_handler_call_details("/grpc.health.v1.Health/Check")
        continuation = MagicMock(return_value="handler")

        result = interceptor.intercept_service(continuation, details)

        assert result == "handler"
        continuation.assert_called_once_with(details)
        rp.verify_token_sync.assert_not_called()

    def test_missing_auth_header_returns_unauthenticated(self):
        cls = _import_interceptor()
        rp = MagicMock()
        interceptor = cls(rp)
        details = _make_handler_call_details("/my.Service/Method", metadata=[])
        continuation = MagicMock()

        result = interceptor.intercept_service(continuation, details)

        continuation.assert_not_called()
        # result should be an abort handler
        assert hasattr(result, "handler")

    def test_non_bearer_token_returns_unauthenticated(self):
        cls = _import_interceptor()
        rp = MagicMock()
        interceptor = cls(rp)
        details = _make_handler_call_details(
            "/my.Service/Method",
            metadata=[("authorization", "Basic dXNlcjpwYXNz")],
        )
        continuation = MagicMock()

        result = interceptor.intercept_service(continuation, details)

        continuation.assert_not_called()
        assert hasattr(result, "handler")

    def test_valid_bearer_token_passes_through(self):
        cls = _import_interceptor()
        rp = MagicMock()
        rp.verify_token_sync.return_value = {"sub": "user123"}
        interceptor = cls(rp)
        details = _make_handler_call_details(
            "/my.Service/Method",
            metadata=[("authorization", "Bearer valid-token-here")],
        )
        continuation = MagicMock(return_value="handler")

        result = interceptor.intercept_service(continuation, details)

        assert result == "handler"
        rp.verify_token_sync.assert_called_once_with("valid-token-here")
        continuation.assert_called_once_with(details)

    def test_invalid_token_returns_unauthenticated(self):
        cls = _import_interceptor()
        rp = MagicMock()
        rp.verify_token_sync.side_effect = Exception("token expired")
        interceptor = cls(rp)
        details = _make_handler_call_details(
            "/my.Service/Method",
            metadata=[("authorization", "Bearer bad-token")],
        )
        continuation = MagicMock()

        result = interceptor.intercept_service(continuation, details)

        continuation.assert_not_called()
        assert hasattr(result, "handler")

    def test_abort_handler_calls_context_abort(self):
        cls = _import_interceptor()
        rp = MagicMock()
        interceptor = cls(rp)
        details = _make_handler_call_details("/my.Service/Method", metadata=[])
        continuation = MagicMock()

        result = interceptor.intercept_service(continuation, details)

        # Call the abort handler and verify it calls context.abort
        context = MagicMock()
        result.handler("request", context)
        context.abort.assert_called_once()

    def test_bytes_auth_header_decoded(self):
        cls = _import_interceptor()
        rp = MagicMock()
        rp.verify_token_sync.return_value = {"sub": "user123"}
        interceptor = cls(rp)
        details = _make_handler_call_details(
            "/my.Service/Method",
            metadata=[("authorization", b"Bearer bytes-token")],
        )
        continuation = MagicMock(return_value="handler")

        result = interceptor.intercept_service(continuation, details)

        assert result == "handler"
        rp.verify_token_sync.assert_called_once_with("bytes-token")

    def test_default_public_methods_empty(self):
        cls = _import_interceptor()
        rp = MagicMock()
        interceptor = cls(rp)
        assert interceptor._public_methods == set()
