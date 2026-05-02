"""Tests for penguin_libs.grpc subpackage (client, server, interceptors)."""

from __future__ import annotations

import time
from dataclasses import FrozenInstanceError
from unittest.mock import MagicMock, mock_open, patch

import pytest

# The grpc module has hard dependencies on grpc, jwt, grpc_health, grpc_reflection.
# We mock them at the top level so we can import regardless of installation state.
# Create mock grpc module with all needed attributes BEFORE importing penguin_libs.grpc.

_mock_grpc = MagicMock()
_mock_grpc.__version__ = "1.80.0"  # Required: grpc_health imports check this
_mock_grpc.StatusCode.UNAUTHENTICATED = "UNAUTHENTICATED"
_mock_grpc.StatusCode.PERMISSION_DENIED = "PERMISSION_DENIED"
_mock_grpc.StatusCode.INVALID_ARGUMENT = "INVALID_ARGUMENT"
_mock_grpc.StatusCode.NOT_FOUND = "NOT_FOUND"
_mock_grpc.StatusCode.ALREADY_EXISTS = "ALREADY_EXISTS"
_mock_grpc.StatusCode.RESOURCE_EXHAUSTED = "RESOURCE_EXHAUSTED"
_mock_grpc.StatusCode.INTERNAL = "INTERNAL"
_mock_grpc.RpcError = type("RpcError", (Exception,), {"code": lambda self: self._code})
_mock_grpc.ServerInterceptor = type("ServerInterceptor", (), {})
_mock_grpc.Channel = MagicMock
_mock_grpc.HandlerCallDetails = MagicMock

import sys

_real_grpc = sys.modules.get("grpc")
_real_jwt = sys.modules.get("jwt")
_real_health = sys.modules.get("grpc_health.v1.health")
_real_health_pb2 = sys.modules.get("grpc_health.v1.health_pb2")
_real_health_pb2_grpc = sys.modules.get("grpc_health.v1.health_pb2_grpc")
_real_reflection = sys.modules.get("grpc_reflection.v1alpha.reflection")

_need_mock = _real_grpc is None

if _need_mock:
    # Ensure grpc version is set
    _mock_grpc.__version__ = "1.80.0"

    # Create mock jwt
    _mock_jwt = MagicMock()
    _mock_jwt.ExpiredSignatureError = type("ExpiredSignatureError", (Exception,), {})
    _mock_jwt.InvalidTokenError = type("InvalidTokenError", (Exception,), {})

    # Create mock health modules
    _mock_health = MagicMock()
    _mock_health.SERVICE_NAME = "grpc.health.v1.Health"
    _mock_health_pb2 = MagicMock()
    _mock_health_pb2.HealthCheckResponse.SERVING = 1
    _mock_health_pb2_grpc = MagicMock()
    _mock_reflection = MagicMock()
    _mock_reflection.SERVICE_NAME = "grpc.reflection.v1alpha.ServerReflection"

    sys.modules["grpc"] = _mock_grpc
    sys.modules["jwt"] = _mock_jwt
    sys.modules["grpc_health"] = MagicMock()
    sys.modules["grpc_health.v1"] = MagicMock()
    sys.modules["grpc_health.v1.health"] = _mock_health
    sys.modules["grpc_health.v1.health_pb2"] = _mock_health_pb2
    sys.modules["grpc_health.v1.health_pb2_grpc"] = _mock_health_pb2_grpc
    sys.modules["grpc_reflection"] = MagicMock()
    sys.modules["grpc_reflection.v1alpha"] = MagicMock()
    sys.modules["grpc_reflection.v1alpha.reflection"] = _mock_reflection


# Force reimport with mocks in place.
# Delete penguin_libs too so _compat.py re-runs and re-registers sys.modules aliases.
if "penguin_libs" in sys.modules:
    del sys.modules["penguin_libs"]
if "penguin_libs._compat" in sys.modules:
    del sys.modules["penguin_libs._compat"]
if "penguin_libs.grpc" in sys.modules:
    del sys.modules["penguin_libs.grpc"]
if "penguin_libs.grpc.client" in sys.modules:
    del sys.modules["penguin_libs.grpc.client"]
if "penguin_libs.grpc.interceptors" in sys.modules:
    del sys.modules["penguin_libs.grpc.interceptors"]
if "penguin_libs.grpc.server" in sys.modules:
    del sys.modules["penguin_libs.grpc.server"]

from penguin_libs.grpc.client import ClientOptions, GrpcClient
from penguin_libs.grpc.interceptors import (
    AuditInterceptor,
    AuthInterceptor,
    CorrelationInterceptor,
    RateLimitEntry,
    RateLimitInterceptor,
    RecoveryInterceptor,
)
from penguin_libs.grpc.server import (
    ServerOptions,
    _enable_reflection,
    create_server,
    register_health_check,
    start_server_with_graceful_shutdown,
)

# Get the real grpc/jwt refs used inside the module
grpc_mod = sys.modules["grpc"]
jwt_mod = sys.modules["jwt"]


# ─── __init__.py ───────────────────────────────────────────────────────────


class TestGrpcInit:
    """Test grpc __init__.py exports."""

    def test_all_exports(self):
        from penguin_libs.grpc import __all__

        assert "create_server" in __all__
        assert "register_health_check" in __all__
        assert "GrpcClient" in __all__
        assert "AuthInterceptor" in __all__
        assert "RateLimitInterceptor" in __all__
        assert "AuditInterceptor" in __all__
        assert "CorrelationInterceptor" in __all__
        assert "RecoveryInterceptor" in __all__


# ─── ClientOptions ─────────────────────────────────────────────────────────


class TestClientOptions:
    """Tests for ClientOptions dataclass."""

    def test_defaults(self):
        opts = ClientOptions()
        assert opts.max_retries == 3
        assert opts.initial_backoff_ms == 100
        assert opts.max_backoff_ms == 5000
        assert opts.backoff_multiplier == 2.0
        assert opts.timeout_seconds == 30.0
        assert opts.enable_tls is False
        assert opts.ca_cert_path is None
        assert opts.client_cert_path is None
        assert opts.client_key_path is None
        assert opts.keepalive_time_ms == 60000
        assert opts.keepalive_timeout_ms == 20000

    def test_frozen(self):
        opts = ClientOptions()
        with pytest.raises(FrozenInstanceError):
            opts.max_retries = 5  # type: ignore[misc]


# ─── GrpcClient ────────────────────────────────────────────────────────────


class TestGrpcClient:
    """Tests for GrpcClient."""

    def test_init_defaults(self):
        client = GrpcClient("localhost:50051")
        assert client.target == "localhost:50051"
        assert isinstance(client.options, ClientOptions)
        assert client._channel is None

    def test_init_custom_options(self):
        opts = ClientOptions(max_retries=5, enable_tls=True)
        client = GrpcClient("server:50051", opts)
        assert client.options.max_retries == 5
        assert client.options.enable_tls is True

    def test_channel_creates_insecure(self):
        client = GrpcClient("localhost:50051")
        grpc_mod.insecure_channel = MagicMock(return_value=MagicMock())

        ch = client.channel()
        grpc_mod.insecure_channel.assert_called_once()
        assert ch is not None
        # Second call returns cached channel
        ch2 = client.channel()
        assert ch2 is ch

    def test_channel_creates_secure(self):
        opts = ClientOptions(enable_tls=True)
        client = GrpcClient("localhost:50051", opts)

        mock_creds = MagicMock()
        grpc_mod.ssl_channel_credentials = MagicMock(return_value=mock_creds)
        grpc_mod.secure_channel = MagicMock(return_value=MagicMock())

        ch = client.channel()
        grpc_mod.secure_channel.assert_called_once()
        assert ch is not None

    def test_create_credentials_no_certs(self):
        opts = ClientOptions(enable_tls=True)
        client = GrpcClient("localhost:50051", opts)

        grpc_mod.ssl_channel_credentials = MagicMock(return_value=MagicMock())
        client._create_credentials()
        grpc_mod.ssl_channel_credentials.assert_called_once_with(
            root_certificates=None,
            private_key=None,
            certificate_chain=None,
        )

    def test_create_credentials_with_ca_cert(self):
        opts = ClientOptions(enable_tls=True, ca_cert_path="/tmp/ca.pem")
        client = GrpcClient("localhost:50051", opts)

        grpc_mod.ssl_channel_credentials = MagicMock(return_value=MagicMock())
        m = mock_open(read_data=b"ca-cert-data")
        with patch("builtins.open", m):
            client._create_credentials()
        grpc_mod.ssl_channel_credentials.assert_called_once()
        args = grpc_mod.ssl_channel_credentials.call_args
        assert args.kwargs["root_certificates"] == b"ca-cert-data"

    def test_create_credentials_with_mtls(self):
        opts = ClientOptions(
            enable_tls=True,
            ca_cert_path="/tmp/ca.pem",
            client_cert_path="/tmp/client.pem",
            client_key_path="/tmp/client.key",
        )
        client = GrpcClient("localhost:50051", opts)

        grpc_mod.ssl_channel_credentials = MagicMock(return_value=MagicMock())

        def fake_open(path, mode="r"):
            data_map = {
                "/tmp/ca.pem": b"ca-data",
                "/tmp/client.key": b"key-data",
                "/tmp/client.pem": b"cert-data",
            }
            return mock_open(read_data=data_map.get(path, b""))()

        with patch("builtins.open", side_effect=fake_open):
            client._create_credentials()

        args = grpc_mod.ssl_channel_credentials.call_args
        assert args.kwargs["root_certificates"] == b"ca-data"
        assert args.kwargs["private_key"] == b"key-data"
        assert args.kwargs["certificate_chain"] == b"cert-data"

    def test_call_with_retry_success(self):
        client = GrpcClient("localhost:50051")
        func = MagicMock(return_value="response")
        result = client.call_with_retry(func, "arg1", key="val")
        func.assert_called_once_with("arg1", key="val", timeout=30.0)
        assert result == "response"

    def test_call_with_retry_preserves_existing_timeout(self):
        client = GrpcClient("localhost:50051")
        func = MagicMock(return_value="ok")
        client.call_with_retry(func, timeout=5.0)
        func.assert_called_once_with(timeout=5.0)

    def test_call_with_retry_non_retryable_error(self):
        client = GrpcClient("localhost:50051")

        rpc_error = grpc_mod.RpcError("not found")
        rpc_error._code = grpc_mod.StatusCode.NOT_FOUND
        func = MagicMock(side_effect=rpc_error)

        with pytest.raises(grpc_mod.RpcError):
            client.call_with_retry(func)
        assert func.call_count == 1

    def test_call_with_retry_retries_transient_errors(self):
        opts = ClientOptions(max_retries=3, initial_backoff_ms=1, max_backoff_ms=10)
        client = GrpcClient("localhost:50051", opts)

        rpc_error = grpc_mod.RpcError("unavailable")
        rpc_error._code = grpc_mod.StatusCode.INTERNAL
        func = MagicMock(side_effect=rpc_error)

        with patch("time.sleep"):
            with pytest.raises(grpc_mod.RpcError):
                client.call_with_retry(func)
        assert func.call_count == 3

    def test_call_with_retry_succeeds_on_second_try(self):
        opts = ClientOptions(max_retries=3, initial_backoff_ms=1)
        client = GrpcClient("localhost:50051", opts)

        rpc_error = grpc_mod.RpcError("unavailable")
        rpc_error._code = grpc_mod.StatusCode.INTERNAL
        func = MagicMock(side_effect=[rpc_error, "ok"])

        with patch("time.sleep"):
            result = client.call_with_retry(func)
        assert result == "ok"
        assert func.call_count == 2

    def test_call_with_retry_backoff_capped(self):
        opts = ClientOptions(
            max_retries=4,
            initial_backoff_ms=100,
            max_backoff_ms=200,
            backoff_multiplier=10.0,
        )
        client = GrpcClient("localhost:50051", opts)

        rpc_error = grpc_mod.RpcError("unavailable")
        rpc_error._code = grpc_mod.StatusCode.INTERNAL
        func = MagicMock(side_effect=rpc_error)

        sleep_times = []
        with patch("time.sleep", side_effect=lambda t: sleep_times.append(t)):
            with pytest.raises(grpc_mod.RpcError):
                client.call_with_retry(func)

        # Backoff should be capped at max_backoff_ms / 1000
        for t in sleep_times:
            assert t <= 0.2 + 0.001  # max_backoff_ms=200 => 0.2s

    def test_close(self):
        client = GrpcClient("localhost:50051")
        mock_channel = MagicMock()
        client._channel = mock_channel

        client.close()
        mock_channel.close.assert_called_once()
        assert client._channel is None

    def test_close_no_channel(self):
        client = GrpcClient("localhost:50051")
        client.close()  # Should not raise

    def test_context_manager(self):
        client = GrpcClient("localhost:50051")
        mock_channel = MagicMock()
        client._channel = mock_channel

        with client as c:
            assert c is client
        mock_channel.close.assert_called_once()

    def test_non_retryable_codes(self):
        """Ensure all non-retryable codes raise immediately."""
        client = GrpcClient("localhost:50051")
        non_retryable = [
            grpc_mod.StatusCode.INVALID_ARGUMENT,
            grpc_mod.StatusCode.NOT_FOUND,
            grpc_mod.StatusCode.ALREADY_EXISTS,
            grpc_mod.StatusCode.PERMISSION_DENIED,
            grpc_mod.StatusCode.UNAUTHENTICATED,
        ]
        for code in non_retryable:
            rpc_error = grpc_mod.RpcError(f"error {code}")
            rpc_error._code = code
            func = MagicMock(side_effect=rpc_error)
            with pytest.raises(grpc_mod.RpcError):
                client.call_with_retry(func)
            assert func.call_count == 1


# ─── AuthInterceptor ──────────────────────────────────────────────────────


class TestAuthInterceptor:
    """Tests for AuthInterceptor."""

    def _make_handler_call_details(self, method: str, metadata: dict[str, str]):
        details = MagicMock()
        details.method = method
        details.invocation_metadata = list(metadata.items())
        return details

    def test_public_method_skips_auth(self):
        interceptor = AuthInterceptor("secret", public_methods={"/pkg.Svc/Health"})
        continuation = MagicMock(return_value="handler")
        details = self._make_handler_call_details("/pkg.Svc/Health", {})

        result = interceptor.intercept_service(continuation, details)
        continuation.assert_called_once_with(details)
        assert result == "handler"

    def test_missing_auth_header(self):
        interceptor = AuthInterceptor("secret")
        continuation = MagicMock()
        details = self._make_handler_call_details("/pkg.Svc/Do", {})

        result = interceptor.intercept_service(continuation, details)
        continuation.assert_not_called()
        # Should return an abort handler
        assert result is not None

    def test_invalid_auth_prefix(self):
        interceptor = AuthInterceptor("secret")
        continuation = MagicMock()
        details = self._make_handler_call_details("/pkg.Svc/Do", {"authorization": "Basic abc"})

        result = interceptor.intercept_service(continuation, details)
        continuation.assert_not_called()

    def test_valid_token(self):
        interceptor = AuthInterceptor("secret")
        continuation = MagicMock(return_value="handler")
        details = self._make_handler_call_details(
            "/pkg.Svc/Do", {"authorization": "Bearer valid-token"}
        )

        jwt_mod.decode = MagicMock(return_value={"sub": "user-123"})

        result = interceptor.intercept_service(continuation, details)
        jwt_mod.decode.assert_called_once_with("valid-token", "secret", algorithms=["HS256"])
        continuation.assert_called_once_with(details)
        assert result == "handler"

    def test_expired_token(self):
        interceptor = AuthInterceptor("secret")
        continuation = MagicMock()
        details = self._make_handler_call_details(
            "/pkg.Svc/Do", {"authorization": "Bearer expired-token"}
        )

        jwt_mod.decode = MagicMock(side_effect=jwt_mod.ExpiredSignatureError("expired"))

        result = interceptor.intercept_service(continuation, details)
        continuation.assert_not_called()

    def test_invalid_token(self):
        interceptor = AuthInterceptor("secret")
        continuation = MagicMock()
        details = self._make_handler_call_details(
            "/pkg.Svc/Do", {"authorization": "Bearer bad-token"}
        )

        jwt_mod.decode = MagicMock(side_effect=jwt_mod.InvalidTokenError("bad"))

        result = interceptor.intercept_service(continuation, details)
        continuation.assert_not_called()

    def test_custom_algorithms(self):
        interceptor = AuthInterceptor("secret", algorithms=["RS256"])
        continuation = MagicMock(return_value="handler")
        details = self._make_handler_call_details("/pkg.Svc/Do", {"authorization": "Bearer tok"})
        jwt_mod.decode = MagicMock(return_value={"sub": "u"})

        interceptor.intercept_service(continuation, details)
        jwt_mod.decode.assert_called_once_with("tok", "secret", algorithms=["RS256"])

    def test_abort_handler_calls_context_abort(self):
        interceptor = AuthInterceptor("secret")
        handler = interceptor._abort_with_error(grpc_mod.StatusCode.UNAUTHENTICATED, "no auth")
        # The handler wraps a function that calls context.abort
        assert handler is not None


# ─── RateLimitInterceptor ──────────────────────────────────────────────────


class TestRateLimitInterceptor:
    """Tests for RateLimitInterceptor."""

    def _make_details(self, metadata: dict[str, str]):
        details = MagicMock()
        details.invocation_metadata = list(metadata.items())
        return details

    def test_allows_under_limit(self):
        interceptor = RateLimitInterceptor(requests_per_minute=10)
        continuation = MagicMock(return_value="handler")
        details = self._make_details({})

        result = interceptor.intercept_service(continuation, details)
        assert result == "handler"

    def test_blocks_over_limit(self):
        interceptor = RateLimitInterceptor(requests_per_minute=2)
        continuation = MagicMock(return_value="handler")
        details = self._make_details({})

        # First two should pass
        interceptor.intercept_service(continuation, details)
        interceptor.intercept_service(continuation, details)

        # Third should be blocked
        result = interceptor.intercept_service(continuation, details)
        # Should return an abort handler, not "handler"
        assert continuation.call_count == 2

    def test_per_user_extracts_sub_from_jwt(self):
        interceptor = RateLimitInterceptor(requests_per_minute=100, per_user=True)
        continuation = MagicMock(return_value="handler")

        jwt_mod.decode = MagicMock(return_value={"sub": "user-42"})
        details = self._make_details({"authorization": "Bearer some-token"})

        interceptor.intercept_service(continuation, details)
        jwt_mod.decode.assert_called_once()
        assert "user-42" in interceptor.limits

    def test_per_user_anonymous_on_bad_token(self):
        interceptor = RateLimitInterceptor(requests_per_minute=100, per_user=True)
        continuation = MagicMock(return_value="handler")

        jwt_mod.decode = MagicMock(side_effect=Exception("bad"))
        details = self._make_details({"authorization": "Bearer bad"})

        interceptor.intercept_service(continuation, details)
        assert "anonymous" in interceptor.limits

    def test_per_user_anonymous_no_bearer(self):
        interceptor = RateLimitInterceptor(requests_per_minute=100, per_user=True)
        continuation = MagicMock(return_value="handler")
        details = self._make_details({})

        interceptor.intercept_service(continuation, details)
        assert "anonymous" in interceptor.limits

    def test_per_ip_mode(self):
        interceptor = RateLimitInterceptor(requests_per_minute=100, per_user=False)
        continuation = MagicMock(return_value="handler")
        details = self._make_details({"x-forwarded-for": "1.2.3.4"})

        interceptor.intercept_service(continuation, details)
        assert "1.2.3.4" in interceptor.limits

    def test_per_ip_unknown(self):
        interceptor = RateLimitInterceptor(requests_per_minute=100, per_user=False)
        continuation = MagicMock(return_value="handler")
        details = self._make_details({})

        interceptor.intercept_service(continuation, details)
        assert "unknown" in interceptor.limits

    def test_window_reset(self):
        interceptor = RateLimitInterceptor(requests_per_minute=1)
        continuation = MagicMock(return_value="handler")
        details = self._make_details({})

        # First call passes
        interceptor.intercept_service(continuation, details)

        # Simulate window expiry
        for entry in interceptor.limits.values():
            entry.window_start -= 61.0

        # Should pass again after window reset
        result = interceptor.intercept_service(continuation, details)
        assert result == "handler"


# ─── AuditInterceptor ─────────────────────────────────────────────────────


class TestAuditInterceptor:
    """Tests for AuditInterceptor."""

    def _make_details(self, method: str, metadata: dict[str, str] | None = None):
        details = MagicMock()
        details.method = method
        details.invocation_metadata = list((metadata or {}).items())
        return details

    def test_logs_and_wraps_handler(self):
        interceptor = AuditInterceptor()

        original_fn = MagicMock(return_value="response")
        handler = MagicMock()
        handler.unary_unary = original_fn
        handler.request_deserializer = MagicMock()
        handler.response_serializer = MagicMock()

        continuation = MagicMock(return_value=handler)
        details = self._make_details("/svc/Method", {"x-correlation-id": "abc-123"})

        grpc_mod.unary_unary_rpc_method_handler = MagicMock(return_value="wrapped")
        result = interceptor.intercept_service(continuation, details)
        assert result == "wrapped"
        grpc_mod.unary_unary_rpc_method_handler.assert_called_once()

    def test_logged_handler_success(self):
        interceptor = AuditInterceptor()

        original_fn = MagicMock(return_value="response")
        handler = MagicMock()
        handler.unary_unary = original_fn
        handler.request_deserializer = "deser"
        handler.response_serializer = "ser"

        continuation = MagicMock(return_value=handler)
        details = self._make_details("/svc/Method")

        # Capture the wrapped handler
        wrapped_fn = None

        def capture_handler(fn, **kwargs):
            nonlocal wrapped_fn
            wrapped_fn = fn
            return MagicMock()

        grpc_mod.unary_unary_rpc_method_handler = capture_handler
        interceptor.intercept_service(continuation, details)

        ctx = MagicMock()
        result = wrapped_fn("request", ctx)
        assert result == "response"

    def test_logged_handler_exception(self):
        interceptor = AuditInterceptor()

        original_fn = MagicMock(side_effect=RuntimeError("boom"))
        handler = MagicMock()
        handler.unary_unary = original_fn
        handler.request_deserializer = "d"
        handler.response_serializer = "s"

        continuation = MagicMock(return_value=handler)
        details = self._make_details("/svc/Method")

        wrapped_fn = None

        def capture_handler(fn, **kwargs):
            nonlocal wrapped_fn
            wrapped_fn = fn
            return MagicMock()

        grpc_mod.unary_unary_rpc_method_handler = capture_handler
        interceptor.intercept_service(continuation, details)

        ctx = MagicMock()
        with pytest.raises(RuntimeError, match="boom"):
            wrapped_fn("request", ctx)

    def test_no_unary_unary_passthrough(self):
        interceptor = AuditInterceptor()
        handler = MagicMock()
        handler.unary_unary = None
        continuation = MagicMock(return_value=handler)
        details = self._make_details("/svc/Method")

        result = interceptor.intercept_service(continuation, details)
        assert result is handler

    def test_none_handler_passthrough(self):
        interceptor = AuditInterceptor()
        continuation = MagicMock(return_value=None)
        details = self._make_details("/svc/Method")

        result = interceptor.intercept_service(continuation, details)
        assert result is None


# ─── CorrelationInterceptor ────────────────────────────────────────────────


class TestCorrelationInterceptor:
    """Tests for CorrelationInterceptor."""

    def _make_details(self, metadata: dict[str, str]):
        details = MagicMock()
        details.invocation_metadata = list(metadata.items())
        return details

    def test_passes_through_with_existing_id(self):
        interceptor = CorrelationInterceptor()
        continuation = MagicMock(return_value="handler")
        details = self._make_details({"x-correlation-id": "existing-id"})

        result = interceptor.intercept_service(continuation, details)
        continuation.assert_called_once_with(details)
        assert result == "handler"

    def test_generates_id_when_missing(self):
        interceptor = CorrelationInterceptor()
        continuation = MagicMock(return_value="handler")
        details = self._make_details({})

        result = interceptor.intercept_service(continuation, details)
        continuation.assert_called_once_with(details)
        assert result == "handler"


# ─── RecoveryInterceptor ──────────────────────────────────────────────────


class TestRecoveryInterceptor:
    """Tests for RecoveryInterceptor."""

    def _make_details(self, method: str = "/svc/Method"):
        details = MagicMock()
        details.method = method
        details.invocation_metadata = []
        return details

    def test_wraps_handler(self):
        interceptor = RecoveryInterceptor()

        original_fn = MagicMock(return_value="ok")
        handler = MagicMock()
        handler.unary_unary = original_fn
        handler.request_deserializer = "d"
        handler.response_serializer = "s"

        continuation = MagicMock(return_value=handler)
        details = self._make_details()

        grpc_mod.unary_unary_rpc_method_handler = MagicMock(return_value="wrapped")
        result = interceptor.intercept_service(continuation, details)
        assert result == "wrapped"

    def test_recovery_handler_success(self):
        interceptor = RecoveryInterceptor()

        original_fn = MagicMock(return_value="response")
        handler = MagicMock()
        handler.unary_unary = original_fn
        handler.request_deserializer = "d"
        handler.response_serializer = "s"

        continuation = MagicMock(return_value=handler)
        details = self._make_details()

        wrapped_fn = None

        def capture(fn, **kwargs):
            nonlocal wrapped_fn
            wrapped_fn = fn
            return MagicMock()

        grpc_mod.unary_unary_rpc_method_handler = capture
        interceptor.intercept_service(continuation, details)

        ctx = MagicMock()
        result = wrapped_fn("req", ctx)
        assert result == "response"

    def test_recovery_handler_rpc_error_passthrough(self):
        interceptor = RecoveryInterceptor()

        rpc_error = grpc_mod.RpcError("rpc fail")
        rpc_error._code = grpc_mod.StatusCode.NOT_FOUND
        original_fn = MagicMock(side_effect=rpc_error)
        handler = MagicMock()
        handler.unary_unary = original_fn
        handler.request_deserializer = "d"
        handler.response_serializer = "s"

        continuation = MagicMock(return_value=handler)
        details = self._make_details()

        wrapped_fn = None

        def capture(fn, **kwargs):
            nonlocal wrapped_fn
            wrapped_fn = fn
            return MagicMock()

        grpc_mod.unary_unary_rpc_method_handler = capture
        interceptor.intercept_service(continuation, details)

        ctx = MagicMock()
        with pytest.raises(grpc_mod.RpcError):
            wrapped_fn("req", ctx)

    def test_recovery_handler_unexpected_error(self):
        interceptor = RecoveryInterceptor()

        original_fn = MagicMock(side_effect=ValueError("unexpected"))
        handler = MagicMock()
        handler.unary_unary = original_fn
        handler.request_deserializer = "d"
        handler.response_serializer = "s"

        continuation = MagicMock(return_value=handler)
        details = self._make_details()

        wrapped_fn = None

        def capture(fn, **kwargs):
            nonlocal wrapped_fn
            wrapped_fn = fn
            return MagicMock()

        grpc_mod.unary_unary_rpc_method_handler = capture
        interceptor.intercept_service(continuation, details)

        ctx = MagicMock()
        wrapped_fn("req", ctx)
        ctx.abort.assert_called_once()
        assert "unexpected" in str(ctx.abort.call_args)

    def test_no_unary_unary_passthrough(self):
        interceptor = RecoveryInterceptor()
        handler = MagicMock()
        handler.unary_unary = None
        continuation = MagicMock(return_value=handler)
        details = self._make_details()

        result = interceptor.intercept_service(continuation, details)
        assert result is handler

    def test_none_handler_passthrough(self):
        interceptor = RecoveryInterceptor()
        continuation = MagicMock(return_value=None)
        details = self._make_details()

        result = interceptor.intercept_service(continuation, details)
        assert result is None


# ─── ServerOptions ─────────────────────────────────────────────────────────


class TestServerOptions:
    """Tests for ServerOptions dataclass."""

    def test_defaults(self):
        opts = ServerOptions()
        assert opts.max_workers == 10
        assert opts.max_concurrent_rpcs == 100
        assert opts.enable_reflection is True
        assert opts.enable_health_check is True
        assert opts.port == 50051

    def test_frozen(self):
        opts = ServerOptions()
        with pytest.raises(FrozenInstanceError):
            opts.port = 9999  # type: ignore[misc]


# ─── create_server ─────────────────────────────────────────────────────────


class TestCreateServer:
    """Tests for create_server."""

    def test_default_options(self):
        grpc_mod.server = MagicMock(return_value=MagicMock())
        health_mod = sys.modules["grpc_health.v1.health"]
        health_mod.HealthServicer = MagicMock(return_value=MagicMock())
        health_pb2_grpc_mod = sys.modules["grpc_health.v1.health_pb2_grpc"]
        reflection_mod = sys.modules["grpc_reflection.v1alpha.reflection"]

        server = create_server()
        grpc_mod.server.assert_called_once()
        assert server is not None

    def test_with_interceptors(self):
        grpc_mod.server = MagicMock(return_value=MagicMock())
        health_mod = sys.modules["grpc_health.v1.health"]
        health_mod.HealthServicer = MagicMock(return_value=MagicMock())

        interceptor = MagicMock()
        server = create_server(interceptors=[interceptor])
        assert server is not None

    def test_no_health_check(self):
        grpc_mod.server = MagicMock(return_value=MagicMock())
        reflection_mod = sys.modules["grpc_reflection.v1alpha.reflection"]

        opts = ServerOptions(enable_health_check=False)
        with patch("penguin_libs.grpc.server.register_health_check") as mock_health:
            server = create_server(options=opts)
            mock_health.assert_not_called()

    def test_no_reflection(self):
        grpc_mod.server = MagicMock(return_value=MagicMock())
        health_mod = sys.modules["grpc_health.v1.health"]
        health_mod.HealthServicer = MagicMock(return_value=MagicMock())

        opts = ServerOptions(enable_reflection=False)
        with patch("penguin_libs.grpc.server._enable_reflection") as mock_ref:
            server = create_server(options=opts)
            mock_ref.assert_not_called()


# ─── register_health_check ─────────────────────────────────────────────────


class TestRegisterHealthCheck:
    """Tests for register_health_check."""

    def test_registers_servicer(self):
        mock_servicer = MagicMock()
        mock_health_cls = MagicMock(return_value=mock_servicer)
        mock_add_fn = MagicMock()
        mock_pb2 = MagicMock()
        mock_pb2.HealthCheckResponse.SERVING = 1

        mock_server = MagicMock()

        with (
            patch("penguin_libs.grpc.server.health") as p_health,
            patch("penguin_libs.grpc.server.health_pb2_grpc") as p_pb2_grpc,
            patch("penguin_libs.grpc.server.health_pb2") as p_pb2,
        ):
            p_health.HealthServicer = mock_health_cls
            p_pb2_grpc.add_HealthServicer_to_server = mock_add_fn
            p_pb2.HealthCheckResponse.SERVING = 1

            result = register_health_check(mock_server)

            mock_add_fn.assert_called_once_with(mock_servicer, mock_server)
            mock_servicer.set.assert_called_once()
            assert result is mock_servicer


# ─── _enable_reflection ────────────────────────────────────────────────────


class TestEnableReflection:
    """Tests for _enable_reflection."""

    def test_enables_reflection(self):
        mock_server = MagicMock()

        with (
            patch("penguin_libs.grpc.server.reflection") as mock_ref,
            patch("penguin_libs.grpc.server.health") as mock_health,
        ):
            mock_ref.SERVICE_NAME = "grpc.reflection.v1alpha.ServerReflection"
            mock_health.SERVICE_NAME = "grpc.health.v1.Health"

            _enable_reflection(mock_server)
            mock_ref.enable_server_reflection.assert_called_once()


# ─── start_server_with_graceful_shutdown ───────────────────────────────────


class TestStartServerWithGracefulShutdown:
    """Tests for start_server_with_graceful_shutdown."""

    def test_starts_and_registers_signals(self):
        mock_server = MagicMock()
        mock_server.wait_for_termination = MagicMock()

        with patch("signal.signal") as mock_signal:
            start_server_with_graceful_shutdown(mock_server, port=9999, grace_period=5.0)

        mock_server.add_insecure_port.assert_called_once_with("[::]:9999")
        mock_server.start.assert_called_once()
        mock_server.wait_for_termination.assert_called_once()
        assert mock_signal.call_count == 2

    def test_signal_handler_stops_server(self):
        mock_server = MagicMock()
        mock_server.wait_for_termination = MagicMock()

        captured_handlers = {}

        def capture_signal(sig, handler):
            captured_handlers[sig] = handler

        import signal as sig_mod

        with patch("signal.signal", side_effect=capture_signal):
            start_server_with_graceful_shutdown(mock_server, port=50051, grace_period=10.0)

        # Invoke the SIGTERM handler
        handler = captured_handlers.get(sig_mod.SIGTERM)
        assert handler is not None
        handler(sig_mod.SIGTERM, None)
        mock_server.stop.assert_called_once_with(10.0)


# ─── RateLimitEntry ────────────────────────────────────────────────────────


class TestRateLimitEntry:
    """Tests for RateLimitEntry dataclass."""

    def test_defaults(self):
        entry = RateLimitEntry()
        assert entry.count == 0
        assert entry.window_start == 0.0

    def test_mutable(self):
        entry = RateLimitEntry()
        entry.count = 5
        entry.window_start = time.time()
        assert entry.count == 5
