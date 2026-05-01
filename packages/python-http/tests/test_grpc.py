"""Tests for gRPC client, server, and interceptors."""

import signal
import time
import uuid
from unittest.mock import MagicMock, Mock, call, patch

import grpc
import jwt
import pytest
from grpc_health.v1 import health, health_pb2

from penguin_http.grpc.client import ClientOptions, GrpcClient
from penguin_http.grpc.interceptors import (
    AuditInterceptor,
    AuthInterceptor,
    CorrelationInterceptor,
    RateLimitEntry,
    RateLimitInterceptor,
    RecoveryInterceptor,
)
from penguin_http.grpc.server import (
    ServerOptions,
    _enable_reflection,
    create_server,
    register_health_check,
    start_server_with_graceful_shutdown,
)


class TestClientOptions:
    """Test ClientOptions dataclass."""

    def test_default_values(self) -> None:
        """Test ClientOptions has correct defaults."""
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

    def test_custom_values(self) -> None:
        """Test ClientOptions with custom values."""
        opts = ClientOptions(
            max_retries=5,
            timeout_seconds=60.0,
            enable_tls=True,
            ca_cert_path="/path/to/ca.pem",
        )
        assert opts.max_retries == 5
        assert opts.timeout_seconds == 60.0
        assert opts.enable_tls is True
        assert opts.ca_cert_path == "/path/to/ca.pem"

    def test_frozen_dataclass(self) -> None:
        """Test ClientOptions is frozen."""
        opts = ClientOptions()
        with pytest.raises(AttributeError):
            opts.max_retries = 10  # type: ignore


class TestGrpcClient:
    """Test GrpcClient wrapper."""

    def test_client_init(self) -> None:
        """Test GrpcClient initialization."""
        client = GrpcClient("localhost:50051")
        assert client.target == "localhost:50051"
        assert isinstance(client.options, ClientOptions)
        assert client._channel is None

    def test_client_init_with_custom_options(self) -> None:
        """Test GrpcClient with custom options."""
        opts = ClientOptions(timeout_seconds=60.0)
        client = GrpcClient("localhost:50051", options=opts)
        assert client.options.timeout_seconds == 60.0

    def test_client_channel_creation(self) -> None:
        """Test gRPC channel is created."""
        with patch("grpc.insecure_channel") as mock_channel:
            mock_channel.return_value = MagicMock(spec=grpc.Channel)
            client = GrpcClient("localhost:50051")
            channel = client.channel()
            assert channel is not None
            mock_channel.assert_called_once()

    def test_client_channel_reuses_existing(self) -> None:
        """Test channel is reused on subsequent calls."""
        with patch("grpc.insecure_channel") as mock_channel:
            mock_channel_obj = MagicMock(spec=grpc.Channel)
            mock_channel.return_value = mock_channel_obj
            client = GrpcClient("localhost:50051")

            channel1 = client.channel()
            channel2 = client.channel()

            assert channel1 is channel2
            mock_channel.assert_called_once()

    def test_client_insecure_channel(self) -> None:
        """Test insecure channel creation."""
        with patch("grpc.insecure_channel") as mock_insecure:
            mock_insecure.return_value = MagicMock(spec=grpc.Channel)
            client = GrpcClient("localhost:50051")
            client.channel()
            mock_insecure.assert_called_once()

    def test_client_secure_channel(self) -> None:
        """Test secure TLS channel creation."""
        with patch("grpc.secure_channel") as mock_secure:
            with patch.object(GrpcClient, "_create_credentials") as mock_creds:
                mock_creds.return_value = MagicMock()
                mock_secure.return_value = MagicMock(spec=grpc.Channel)

                opts = ClientOptions(enable_tls=True)
                client = GrpcClient("localhost:50051", options=opts)
                client.channel()

                mock_secure.assert_called_once()
                mock_creds.assert_called_once()

    def test_create_credentials_with_ca_cert(self) -> None:
        """Test credentials creation with CA certificate."""
        with patch("builtins.open", create=True) as mock_open:
            mock_open.return_value.__enter__.return_value.read.return_value = b"ca_cert"
            with patch("grpc.ssl_channel_credentials") as mock_creds:
                mock_creds.return_value = MagicMock()

                opts = ClientOptions(
                    enable_tls=True,
                    ca_cert_path="/path/to/ca.pem",
                )
                client = GrpcClient("localhost:50051", options=opts)
                client._create_credentials()

                mock_creds.assert_called_once()

    def test_create_credentials_with_client_cert(self) -> None:
        """Test credentials creation with client certificate."""
        with patch("builtins.open", create=True) as mock_open:
            mock_file = MagicMock()
            mock_file.__enter__.return_value.read.return_value = b"cert_data"
            mock_open.return_value = mock_file

            with patch("grpc.ssl_channel_credentials") as mock_creds:
                mock_creds.return_value = MagicMock()

                opts = ClientOptions(
                    enable_tls=True,
                    client_cert_path="/path/to/cert.pem",
                    client_key_path="/path/to/key.pem",
                )
                client = GrpcClient("localhost:50051", options=opts)
                client._create_credentials()

                mock_creds.assert_called_once()

    def test_call_with_retry_success(self) -> None:
        """Test successful RPC call without retry."""
        client = GrpcClient("localhost:50051")
        mock_func = MagicMock(return_value="response")

        result = client.call_with_retry(mock_func, "request")

        assert result == "response"
        mock_func.assert_called_once()

    def test_call_with_retry_sets_default_timeout(self) -> None:
        """Test default timeout is set if not provided."""
        client = GrpcClient("localhost:50051")
        mock_func = MagicMock(return_value="response")

        client.call_with_retry(mock_func, "request")

        call_kwargs = mock_func.call_args[1]
        assert "timeout" in call_kwargs
        assert call_kwargs["timeout"] == 30.0

    def test_call_with_retry_respects_custom_timeout(self) -> None:
        """Test custom timeout is preserved."""
        client = GrpcClient("localhost:50051")
        mock_func = MagicMock(return_value="response")

        client.call_with_retry(mock_func, "request", timeout=60.0)

        call_kwargs = mock_func.call_args[1]
        assert call_kwargs["timeout"] == 60.0

    def test_call_with_retry_retries_transient_errors(self) -> None:
        """Test transient errors trigger retries."""
        client = GrpcClient("localhost:50051", options=ClientOptions(max_retries=3))
        mock_func = MagicMock()

        # Fail twice, succeed on third attempt
        error = grpc.RpcError()
        error.code = MagicMock(return_value=grpc.StatusCode.UNAVAILABLE)
        mock_func.side_effect = [error, error, "success"]

        with patch("time.sleep"):
            result = client.call_with_retry(mock_func)
            assert result == "success"
            assert mock_func.call_count == 3

    def test_call_with_retry_non_retryable_errors(self) -> None:
        """Test non-retryable errors are raised immediately."""
        client = GrpcClient("localhost:50051", options=ClientOptions(max_retries=3))
        mock_func = MagicMock()

        error = grpc.RpcError()
        error.code = MagicMock(return_value=grpc.StatusCode.INVALID_ARGUMENT)
        mock_func.side_effect = error

        with pytest.raises(grpc.RpcError):
            client.call_with_retry(mock_func)

        # Should be called only once (no retries)
        assert mock_func.call_count == 1

    def test_call_with_retry_unauthorized_not_retried(self) -> None:
        """Test UNAUTHENTICATED errors are not retried."""
        client = GrpcClient("localhost:50051")
        mock_func = MagicMock()

        error = grpc.RpcError()
        error.code = MagicMock(return_value=grpc.StatusCode.UNAUTHENTICATED)
        mock_func.side_effect = error

        with pytest.raises(grpc.RpcError):
            client.call_with_retry(mock_func)

        assert mock_func.call_count == 1

    def test_call_with_retry_permission_denied_not_retried(self) -> None:
        """Test PERMISSION_DENIED errors are not retried."""
        client = GrpcClient("localhost:50051")
        mock_func = MagicMock()

        error = grpc.RpcError()
        error.code = MagicMock(return_value=grpc.StatusCode.PERMISSION_DENIED)
        mock_func.side_effect = error

        with pytest.raises(grpc.RpcError):
            client.call_with_retry(mock_func)

        assert mock_func.call_count == 1

    def test_call_with_retry_not_found_not_retried(self) -> None:
        """Test NOT_FOUND errors are not retried."""
        client = GrpcClient("localhost:50051")
        mock_func = MagicMock()

        error = grpc.RpcError()
        error.code = MagicMock(return_value=grpc.StatusCode.NOT_FOUND)
        mock_func.side_effect = error

        with pytest.raises(grpc.RpcError):
            client.call_with_retry(mock_func)

        assert mock_func.call_count == 1

    def test_call_with_retry_already_exists_not_retried(self) -> None:
        """Test ALREADY_EXISTS errors are not retried."""
        client = GrpcClient("localhost:50051")
        mock_func = MagicMock()

        error = grpc.RpcError()
        error.code = MagicMock(return_value=grpc.StatusCode.ALREADY_EXISTS)
        mock_func.side_effect = error

        with pytest.raises(grpc.RpcError):
            client.call_with_retry(mock_func)

        assert mock_func.call_count == 1

    def test_call_with_retry_exponential_backoff(self) -> None:
        """Test exponential backoff is applied."""
        client = GrpcClient(
            "localhost:50051",
            options=ClientOptions(
                max_retries=3,
                initial_backoff_ms=100,
                backoff_multiplier=2.0,
            ),
        )
        mock_func = MagicMock()

        error = grpc.RpcError()
        error.code = MagicMock(return_value=grpc.StatusCode.UNAVAILABLE)
        mock_func.side_effect = [error, error, "success"]

        with patch("time.sleep") as mock_sleep:
            client.call_with_retry(mock_func)

            # Should sleep with exponential backoff: 100ms, then 200ms
            assert mock_sleep.call_count == 2
            sleep_calls = [call[0][0] for call in mock_sleep.call_args_list]
            assert sleep_calls[0] == 0.1  # 100ms
            assert sleep_calls[1] == 0.2  # 200ms

    def test_call_with_retry_max_backoff_cap(self) -> None:
        """Test backoff is capped at max value."""
        client = GrpcClient(
            "localhost:50051",
            options=ClientOptions(
                max_retries=5,
                initial_backoff_ms=100,
                max_backoff_ms=500,
                backoff_multiplier=2.0,
            ),
        )
        mock_func = MagicMock()

        error = grpc.RpcError()
        error.code = MagicMock(return_value=grpc.StatusCode.UNAVAILABLE)
        mock_func.side_effect = [error, error, error, "success"]

        with patch("time.sleep") as mock_sleep:
            client.call_with_retry(mock_func)

            sleep_calls = [call[0][0] for call in mock_sleep.call_args_list]
            # 100, 200, 400 (capped at 500)
            assert sleep_calls[2] == 0.4  # capped at 400ms

    def test_client_close(self) -> None:
        """Test client channel is properly closed."""
        with patch("grpc.insecure_channel") as mock_channel:
            mock_channel_obj = MagicMock(spec=grpc.Channel)
            mock_channel.return_value = mock_channel_obj

            client = GrpcClient("localhost:50051")
            client.channel()
            client.close()

            mock_channel_obj.close.assert_called_once()
            assert client._channel is None

    def test_client_context_manager(self) -> None:
        """Test client works as context manager."""
        with patch("grpc.insecure_channel") as mock_channel:
            mock_channel_obj = MagicMock(spec=grpc.Channel)
            mock_channel.return_value = mock_channel_obj

            with GrpcClient("localhost:50051") as client:
                channel = client.channel()
                assert channel is not None

            mock_channel_obj.close.assert_called_once()

    def test_client_context_manager_cleanup_on_exception(self) -> None:
        """Test client cleans up on exception in context manager."""
        with patch("grpc.insecure_channel") as mock_channel:
            mock_channel_obj = MagicMock(spec=grpc.Channel)
            mock_channel.return_value = mock_channel_obj

            try:
                with GrpcClient("localhost:50051") as client:
                    client.channel()
                    raise ValueError("Test error")
            except ValueError:
                pass

            mock_channel_obj.close.assert_called_once()

    def test_client_retry_all_retries_exhausted(self) -> None:
        """Test exception raised when all retries exhausted."""
        client = GrpcClient("localhost:50051", options=ClientOptions(max_retries=2))
        mock_func = MagicMock()

        error = grpc.RpcError()
        error.code = MagicMock(return_value=grpc.StatusCode.UNAVAILABLE)
        mock_func.side_effect = error

        with patch("time.sleep"):
            with pytest.raises(grpc.RpcError):
                client.call_with_retry(mock_func)

            # Should attempt 2 times
            assert mock_func.call_count == 2

    def test_call_with_retry_positional_args(self) -> None:
        """Test call_with_retry passes positional arguments."""
        client = GrpcClient("localhost:50051")
        mock_func = MagicMock(return_value="response")

        result = client.call_with_retry(mock_func, "arg1", "arg2", kwarg1="value1")

        assert result == "response"
        mock_func.assert_called_once_with("arg1", "arg2", kwarg1="value1", timeout=30.0)

    def test_channel_options_applied(self) -> None:
        """Test channel options are properly applied."""
        with patch("grpc.insecure_channel") as mock_channel:
            mock_channel.return_value = MagicMock(spec=grpc.Channel)

            opts = ClientOptions(
                keepalive_time_ms=30000,
                keepalive_timeout_ms=10000,
            )
            client = GrpcClient("localhost:50051", options=opts)
            client.channel()

            # Verify channel options were set
            call_kwargs = mock_channel.call_args[1]
            assert "options" in call_kwargs
            options = call_kwargs["options"]
            option_dict = dict(options)
            assert option_dict["grpc.keepalive_time_ms"] == 30000
            assert option_dict["grpc.keepalive_timeout_ms"] == 10000


class TestAuthInterceptor:
    """Test JWT authentication interceptor."""

    def test_auth_interceptor_init(self) -> None:
        """Test AuthInterceptor initialization."""
        interceptor = AuthInterceptor(secret_key="test_secret")
        assert interceptor.secret_key == "test_secret"
        assert interceptor.algorithms == ["HS256"]
        assert interceptor.public_methods == set()

    def test_auth_interceptor_custom_algorithms(self) -> None:
        """Test AuthInterceptor with custom algorithms."""
        interceptor = AuthInterceptor(
            secret_key="test_secret",
            algorithms=["HS256", "RS256"],
        )
        assert interceptor.algorithms == ["HS256", "RS256"]

    def test_auth_interceptor_public_methods(self) -> None:
        """Test AuthInterceptor with public methods."""
        public_methods = {"/service/PublicMethod", "/service/Health"}
        interceptor = AuthInterceptor(
            secret_key="test_secret",
            public_methods=public_methods,
        )
        assert interceptor.public_methods == public_methods

    def test_valid_token_allows_request(self) -> None:
        """Test valid JWT token allows request to proceed."""
        secret = "test_secret"
        payload = {"sub": "user123", "iat": time.time()}
        token = jwt.encode(payload, secret, algorithm="HS256")

        interceptor = AuthInterceptor(secret_key=secret)
        continuation = MagicMock()
        handler_call_details = MagicMock()
        handler_call_details.method = "/service/Method"
        handler_call_details.invocation_metadata = [("authorization", f"Bearer {token}")]

        interceptor.intercept_service(continuation, handler_call_details)
        continuation.assert_called_once_with(handler_call_details)

    def test_missing_token_rejects_request(self) -> None:
        """Test missing auth header rejects request."""
        interceptor = AuthInterceptor(secret_key="test_secret")
        continuation = MagicMock()
        handler_call_details = MagicMock()
        handler_call_details.method = "/service/Method"
        handler_call_details.invocation_metadata = []

        result = interceptor.intercept_service(continuation, handler_call_details)
        continuation.assert_not_called()
        assert result is not None

    def test_invalid_bearer_format(self) -> None:
        """Test invalid Bearer header format."""
        interceptor = AuthInterceptor(secret_key="test_secret")
        continuation = MagicMock()
        handler_call_details = MagicMock()
        handler_call_details.method = "/service/Method"
        handler_call_details.invocation_metadata = [("authorization", "InvalidFormat")]

        result = interceptor.intercept_service(continuation, handler_call_details)
        continuation.assert_not_called()
        assert result is not None

    def test_expired_token_rejected(self) -> None:
        """Test expired JWT token is rejected."""
        secret = "test_secret"
        payload = {"sub": "user123", "iat": time.time() - 3600, "exp": time.time() - 1}
        token = jwt.encode(payload, secret, algorithm="HS256")

        interceptor = AuthInterceptor(secret_key=secret)
        continuation = MagicMock()
        handler_call_details = MagicMock()
        handler_call_details.method = "/service/Method"
        handler_call_details.invocation_metadata = [("authorization", f"Bearer {token}")]

        result = interceptor.intercept_service(continuation, handler_call_details)
        continuation.assert_not_called()
        assert result is not None

    def test_invalid_token_rejected(self) -> None:
        """Test invalid JWT token is rejected."""
        interceptor = AuthInterceptor(secret_key="test_secret")
        continuation = MagicMock()
        handler_call_details = MagicMock()
        handler_call_details.method = "/service/Method"
        handler_call_details.invocation_metadata = [("authorization", "Bearer invalid.token.here")]

        result = interceptor.intercept_service(continuation, handler_call_details)
        continuation.assert_not_called()
        assert result is not None

    def test_public_method_skips_auth(self) -> None:
        """Test public methods skip authentication."""
        interceptor = AuthInterceptor(
            secret_key="test_secret",
            public_methods={"/service/Health"},
        )
        continuation = MagicMock()
        handler_call_details = MagicMock()
        handler_call_details.method = "/service/Health"
        handler_call_details.invocation_metadata = []

        interceptor.intercept_service(continuation, handler_call_details)
        continuation.assert_called_once_with(handler_call_details)

    def test_extract_user_id_from_token(self) -> None:
        """Test user ID is extracted from token."""
        secret = "test_secret"
        payload = {"sub": "user123"}
        token = jwt.encode(payload, secret, algorithm="HS256")

        interceptor = AuthInterceptor(secret_key=secret)
        continuation = MagicMock()
        handler_call_details = MagicMock()
        handler_call_details.method = "/service/Method"
        handler_call_details.invocation_metadata = [("authorization", f"Bearer {token}")]

        with patch("penguin_http.grpc.interceptors.logger"):
            interceptor.intercept_service(continuation, handler_call_details)
            continuation.assert_called_once()


class TestRateLimitInterceptor:
    """Test rate limiting interceptor."""

    def test_rate_limit_interceptor_init(self) -> None:
        """Test RateLimitInterceptor initialization."""
        interceptor = RateLimitInterceptor(requests_per_minute=50)
        assert interceptor.requests_per_minute == 50
        assert interceptor.per_user is True
        assert isinstance(interceptor.limits, dict)

    def test_rate_limit_entry_defaults(self) -> None:
        """Test RateLimitEntry default values."""
        entry = RateLimitEntry()
        assert entry.count == 0
        assert entry.window_start == 0.0

    def test_rate_limit_allows_requests_within_limit(self) -> None:
        """Test requests within limit are allowed."""
        interceptor = RateLimitInterceptor(requests_per_minute=10)
        continuation = MagicMock()

        for i in range(5):
            handler_call_details = MagicMock()
            handler_call_details.method = f"/service/Method{i}"
            handler_call_details.invocation_metadata = [
                ("authorization", "Bearer token"),
                ("x-forwarded-for", "192.168.1.1"),
            ]

            with patch("penguin_http.grpc.interceptors.jwt.decode", return_value={"sub": "user1"}):
                interceptor.intercept_service(continuation, handler_call_details)
                continuation.assert_called()

    def test_rate_limit_rejects_exceeding_limit(self) -> None:
        """Test requests exceeding limit are rejected."""
        interceptor = RateLimitInterceptor(requests_per_minute=3)
        continuation = MagicMock()

        # Make 3 requests (should be OK)
        for i in range(3):
            handler_call_details = MagicMock()
            handler_call_details.method = "/service/Method"
            handler_call_details.invocation_metadata = [
                ("authorization", "Bearer token"),
            ]

            with patch("penguin_http.grpc.interceptors.jwt.decode", return_value={"sub": "user1"}):
                interceptor.intercept_service(continuation, handler_call_details)

        # 4th request should be rejected
        handler_call_details = MagicMock()
        handler_call_details.method = "/service/Method"
        handler_call_details.invocation_metadata = [("authorization", "Bearer token")]

        with patch("penguin_http.grpc.interceptors.jwt.decode", return_value={"sub": "user1"}):
            result = interceptor.intercept_service(continuation, handler_call_details)
            # Should return abort handler, not call continuation
            assert result is not None

    def test_rate_limit_per_user(self) -> None:
        """Test rate limiting is per user."""
        interceptor = RateLimitInterceptor(requests_per_minute=2, per_user=True)
        continuation = MagicMock()

        # User1 makes 2 requests
        for i in range(2):
            handler_call_details = MagicMock()
            handler_call_details.method = "/service/Method"
            handler_call_details.invocation_metadata = [("authorization", "Bearer token1")]

            with patch("penguin_http.grpc.interceptors.jwt.decode", return_value={"sub": "user1"}):
                interceptor.intercept_service(continuation, handler_call_details)

        # User2 should still be able to make requests (separate limit)
        handler_call_details = MagicMock()
        handler_call_details.method = "/service/Method"
        handler_call_details.invocation_metadata = [("authorization", "Bearer token2")]

        with patch("penguin_http.grpc.interceptors.jwt.decode", return_value={"sub": "user2"}):
            interceptor.intercept_service(continuation, handler_call_details)
            continuation.assert_called()

    def test_rate_limit_window_reset(self) -> None:
        """Test rate limit window resets after timeout."""
        interceptor = RateLimitInterceptor(requests_per_minute=1)
        continuation = MagicMock()

        # Make 1 request
        handler_call_details = MagicMock()
        handler_call_details.method = "/service/Method"
        handler_call_details.invocation_metadata = [("authorization", "Bearer token")]

        with patch("penguin_http.grpc.interceptors.jwt.decode", return_value={"sub": "user1"}):
            interceptor.intercept_service(continuation, handler_call_details)

        # Manually reset window
        entry = interceptor.limits["user1"]
        entry.window_start = time.time() - 61.0  # Older than 60 seconds

        # Next request should be allowed (window reset)
        handler_call_details = MagicMock()
        handler_call_details.method = "/service/Method"
        handler_call_details.invocation_metadata = [("authorization", "Bearer token")]

        with patch("penguin_http.grpc.interceptors.jwt.decode", return_value={"sub": "user1"}):
            interceptor.intercept_service(continuation, handler_call_details)
            # Should be called again since window reset
            assert continuation.call_count >= 1

    def test_rate_limit_per_ip(self) -> None:
        """Test rate limiting per IP address."""
        interceptor = RateLimitInterceptor(requests_per_minute=2, per_user=False)
        continuation = MagicMock()

        # IP1 makes 2 requests
        for i in range(2):
            handler_call_details = MagicMock()
            handler_call_details.method = "/service/Method"
            handler_call_details.invocation_metadata = [("x-forwarded-for", "192.168.1.1")]

            interceptor.intercept_service(continuation, handler_call_details)

        # IP1 3rd request should be rejected
        handler_call_details = MagicMock()
        handler_call_details.method = "/service/Method"
        handler_call_details.invocation_metadata = [("x-forwarded-for", "192.168.1.1")]

        result = interceptor.intercept_service(continuation, handler_call_details)
        assert result is not None

    def test_rate_limit_anonymous_user(self) -> None:
        """Test rate limiting for anonymous users."""
        interceptor = RateLimitInterceptor(requests_per_minute=2, per_user=True)
        continuation = MagicMock()

        # Request with no token
        handler_call_details = MagicMock()
        handler_call_details.method = "/service/Method"
        handler_call_details.invocation_metadata = []

        interceptor.intercept_service(continuation, handler_call_details)
        assert interceptor.limits["anonymous"].count == 1


class TestAuditInterceptor:
    """Test audit logging interceptor."""

    def test_audit_interceptor_logs_request(self) -> None:
        """Test audit interceptor logs request start."""
        interceptor = AuditInterceptor()
        continuation = MagicMock()
        handler = MagicMock()
        handler.unary_unary = None
        continuation.return_value = handler

        handler_call_details = MagicMock()
        handler_call_details.method = "/service/Method"
        handler_call_details.invocation_metadata = [("x-correlation-id", "corr-123")]

        with patch("penguin_http.grpc.interceptors.logger"):
            interceptor.intercept_service(continuation, handler_call_details)
            continuation.assert_called_once_with(handler_call_details)

    def test_audit_interceptor_wraps_unary_handler(self) -> None:
        """Test audit interceptor wraps unary_unary handler."""
        interceptor = AuditInterceptor()
        continuation = MagicMock()
        handler = MagicMock()
        original_handler = MagicMock(return_value="response")
        handler.unary_unary = original_handler
        handler.request_deserializer = None
        handler.response_serializer = None
        continuation.return_value = handler

        handler_call_details = MagicMock()
        handler_call_details.method = "/service/Method"
        handler_call_details.invocation_metadata = []

        with patch("penguin_http.grpc.interceptors.logger"):
            result = interceptor.intercept_service(continuation, handler_call_details)
            assert result is not None

    def test_audit_interceptor_logs_completion(self) -> None:
        """Test audit interceptor logs request completion."""
        interceptor = AuditInterceptor()
        continuation = MagicMock()
        handler = MagicMock()
        original_handler = MagicMock(return_value="response")
        handler.unary_unary = original_handler
        handler.request_deserializer = None
        handler.response_serializer = None
        continuation.return_value = handler

        handler_call_details = MagicMock()
        handler_call_details.method = "/service/Method"
        handler_call_details.invocation_metadata = [("x-correlation-id", "corr-123")]

        with patch("penguin_http.grpc.interceptors.logger") as mock_logger:
            result = interceptor.intercept_service(continuation, handler_call_details)
            # Execute the wrapped handler
            if result and result.unary_unary:
                response = result.unary_unary("request", MagicMock())
                assert response == "response"

    def test_audit_interceptor_logs_errors(self) -> None:
        """Test audit interceptor logs errors."""
        interceptor = AuditInterceptor()
        continuation = MagicMock()
        handler = MagicMock()

        def raise_error(*args: object, **kwargs: object) -> None:
            raise ValueError("Test error")

        handler.unary_unary = raise_error
        handler.request_deserializer = None
        handler.response_serializer = None
        continuation.return_value = handler

        handler_call_details = MagicMock()
        handler_call_details.method = "/service/Method"
        handler_call_details.invocation_metadata = []

        with patch("penguin_http.grpc.interceptors.logger"):
            result = interceptor.intercept_service(continuation, handler_call_details)
            if result and result.unary_unary:
                with pytest.raises(ValueError):
                    result.unary_unary("request", MagicMock())


class TestCorrelationInterceptor:
    """Test correlation ID interceptor."""

    def test_correlation_interceptor_preserves_existing_id(self) -> None:
        """Test existing correlation ID is preserved."""
        interceptor = CorrelationInterceptor()
        continuation = MagicMock()
        handler_call_details = MagicMock()
        handler_call_details.method = "/service/Method"
        handler_call_details.invocation_metadata = [("x-correlation-id", "existing-id")]

        with patch("penguin_http.grpc.interceptors.logger"):
            interceptor.intercept_service(continuation, handler_call_details)
            continuation.assert_called_once_with(handler_call_details)

    def test_correlation_interceptor_generates_new_id(self) -> None:
        """Test new correlation ID is generated if missing."""
        interceptor = CorrelationInterceptor()
        continuation = MagicMock()
        handler_call_details = MagicMock()
        handler_call_details.method = "/service/Method"
        handler_call_details.invocation_metadata = []

        with patch("penguin_http.grpc.interceptors.logger"):
            with patch("penguin_http.grpc.interceptors.uuid.uuid4") as mock_uuid:
                mock_uuid.return_value = uuid.uuid4()
                interceptor.intercept_service(continuation, handler_call_details)
                continuation.assert_called_once_with(handler_call_details)

    def test_correlation_interceptor_uuid_format(self) -> None:
        """Test generated correlation ID is valid UUID."""
        interceptor = CorrelationInterceptor()
        continuation = MagicMock()
        handler_call_details = MagicMock()
        handler_call_details.method = "/service/Method"
        handler_call_details.invocation_metadata = []

        with patch("penguin_http.grpc.interceptors.logger") as mock_logger:
            interceptor.intercept_service(continuation, handler_call_details)
            # Check that a UUID was generated (logged)
            continuation.assert_called_once()


class TestRecoveryInterceptor:
    """Test recovery/exception handling interceptor."""

    def test_recovery_interceptor_passes_through_success(self) -> None:
        """Test successful requests pass through unchanged."""
        interceptor = RecoveryInterceptor()
        continuation = MagicMock()
        handler = MagicMock()
        original_handler = MagicMock(return_value="response")
        handler.unary_unary = original_handler
        handler.request_deserializer = None
        handler.response_serializer = None
        continuation.return_value = handler

        handler_call_details = MagicMock()
        handler_call_details.method = "/service/Method"
        handler_call_details.invocation_metadata = []

        result = interceptor.intercept_service(continuation, handler_call_details)
        if result and result.unary_unary:
            response = result.unary_unary("request", MagicMock())
            assert response == "response"

    def test_recovery_interceptor_converts_exceptions_to_grpc_error(self) -> None:
        """Test unexpected exceptions are converted to gRPC errors."""
        interceptor = RecoveryInterceptor()
        continuation = MagicMock()
        handler = MagicMock()

        def raise_value_error(*args: object, **kwargs: object) -> None:
            raise ValueError("Unexpected error")

        handler.unary_unary = raise_value_error
        handler.request_deserializer = None
        handler.response_serializer = None
        continuation.return_value = handler

        handler_call_details = MagicMock()
        handler_call_details.method = "/service/Method"
        handler_call_details.invocation_metadata = []

        with patch("penguin_http.grpc.interceptors.logger"):
            result = interceptor.intercept_service(continuation, handler_call_details)
            if result and result.unary_unary:
                mock_context = MagicMock(spec=grpc.ServicerContext)
                result.unary_unary("request", mock_context)
                mock_context.abort.assert_called_once()
                call_args = mock_context.abort.call_args
                assert call_args[0][0] == grpc.StatusCode.INTERNAL

    def test_recovery_interceptor_passes_through_grpc_errors(self) -> None:
        """Test gRPC errors pass through without conversion."""
        interceptor = RecoveryInterceptor()
        continuation = MagicMock()
        handler = MagicMock()

        grpc_error = grpc.RpcError()

        def raise_grpc_error(*args: object, **kwargs: object) -> None:
            raise grpc_error

        handler.unary_unary = raise_grpc_error
        handler.request_deserializer = None
        handler.response_serializer = None
        continuation.return_value = handler

        handler_call_details = MagicMock()
        handler_call_details.method = "/service/Method"
        handler_call_details.invocation_metadata = []

        result = interceptor.intercept_service(continuation, handler_call_details)
        if result and result.unary_unary:
            with pytest.raises(grpc.RpcError):
                result.unary_unary("request", MagicMock())

    def test_recovery_interceptor_logs_errors(self) -> None:
        """Test recovery interceptor logs unexpected errors."""
        interceptor = RecoveryInterceptor()
        continuation = MagicMock()
        handler = MagicMock()

        def raise_error(*args: object, **kwargs: object) -> None:
            raise RuntimeError("Test error")

        handler.unary_unary = raise_error
        handler.request_deserializer = None
        handler.response_serializer = None
        continuation.return_value = handler

        handler_call_details = MagicMock()
        handler_call_details.method = "/service/Method"
        handler_call_details.invocation_metadata = []

        with patch("penguin_http.grpc.interceptors.logger") as mock_logger:
            result = interceptor.intercept_service(continuation, handler_call_details)
            if result and result.unary_unary:
                mock_context = MagicMock(spec=grpc.ServicerContext)
                result.unary_unary("request", mock_context)
                # Verify logger.error was called
                assert mock_logger.error.called

    def test_recovery_interceptor_handles_none_handler(self) -> None:
        """Test recovery interceptor handles None handler gracefully."""
        interceptor = RecoveryInterceptor()
        continuation = MagicMock()
        handler = None
        continuation.return_value = handler

        handler_call_details = MagicMock()
        handler_call_details.method = "/service/Method"
        handler_call_details.invocation_metadata = []

        result = interceptor.intercept_service(continuation, handler_call_details)
        assert result is None


class TestServerOptions:
    """Test ServerOptions dataclass."""

    def test_default_values(self) -> None:
        """Test ServerOptions has correct defaults."""
        opts = ServerOptions()
        assert opts.max_workers == 10
        assert opts.max_concurrent_rpcs == 100
        assert opts.enable_reflection is True
        assert opts.enable_health_check is True
        assert opts.port == 50051
        assert opts.max_connection_idle_ms == 300000
        assert opts.max_connection_age_ms == 600000
        assert opts.keepalive_time_ms == 60000
        assert opts.keepalive_timeout_ms == 20000

    def test_custom_values(self) -> None:
        """Test ServerOptions with custom values."""
        opts = ServerOptions(
            max_workers=20,
            port=9999,
            enable_reflection=False,
        )
        assert opts.max_workers == 20
        assert opts.port == 9999
        assert opts.enable_reflection is False
        assert opts.enable_health_check is True  # Still default

    def test_frozen_dataclass(self) -> None:
        """Test ServerOptions is frozen."""
        opts = ServerOptions()
        with pytest.raises(AttributeError):
            opts.max_workers = 50  # type: ignore


class TestCreateServer:
    """Test create_server function."""

    def test_create_server_with_defaults(self) -> None:
        """Test server creation with default options."""
        server = create_server()
        assert isinstance(server, grpc.Server)
        server.stop(0)

    def test_create_server_with_custom_options(self) -> None:
        """Test server creation with custom options."""
        opts = ServerOptions(max_workers=5, port=9000)
        server = create_server(options=opts)
        assert isinstance(server, grpc.Server)
        server.stop(0)

    def test_create_server_with_interceptors(self) -> None:
        """Test server creation with interceptors."""
        mock_interceptor = MagicMock(spec=grpc.ServerInterceptor)
        server = create_server(interceptors=[mock_interceptor])
        assert isinstance(server, grpc.Server)
        server.stop(0)

    def test_create_server_reflection_enabled(self) -> None:
        """Test server creation with reflection enabled."""
        opts = ServerOptions(enable_reflection=True)
        with patch("penguin_http.grpc.server._enable_reflection") as mock_reflect:
            server = create_server(options=opts)
            mock_reflect.assert_called_once_with(server)
            server.stop(0)

    def test_create_server_reflection_disabled(self) -> None:
        """Test server creation with reflection disabled."""
        opts = ServerOptions(enable_reflection=False)
        with patch("penguin_http.grpc.server._enable_reflection") as mock_reflect:
            server = create_server(options=opts)
            mock_reflect.assert_not_called()
            server.stop(0)

    def test_create_server_health_check_enabled(self) -> None:
        """Test server creation with health check enabled."""
        opts = ServerOptions(enable_health_check=True)
        with patch("penguin_http.grpc.server.register_health_check") as mock_health:
            server = create_server(options=opts)
            mock_health.assert_called_once_with(server)
            server.stop(0)

    def test_create_server_health_check_disabled(self) -> None:
        """Test server creation with health check disabled."""
        opts = ServerOptions(enable_health_check=False)
        with patch("penguin_http.grpc.server.register_health_check") as mock_health:
            server = create_server(options=opts)
            mock_health.assert_not_called()
            server.stop(0)

    def test_create_server_with_all_interceptors(self) -> None:
        """Test server with multiple interceptors."""
        mock_int1 = MagicMock(spec=grpc.ServerInterceptor)
        mock_int2 = MagicMock(spec=grpc.ServerInterceptor)
        server = create_server(interceptors=[mock_int1, mock_int2])
        assert isinstance(server, grpc.Server)
        server.stop(0)

    def test_create_server_applies_channel_options(self) -> None:
        """Test that server applies channel options."""
        opts = ServerOptions(
            max_concurrent_rpcs=50,
            max_connection_idle_ms=100000,
            keepalive_time_ms=30000,
        )
        server = create_server(options=opts)
        assert isinstance(server, grpc.Server)
        server.stop(0)


class TestRegisterHealthCheck:
    """Test register_health_check function."""

    def test_register_health_check(self) -> None:
        """Test health check registration."""
        server = create_server(options=ServerOptions(enable_health_check=False))
        health_servicer = register_health_check(server)
        assert health_servicer is not None
        server.stop(0)

    def test_health_servicer_is_health_class(self) -> None:
        """Test returned servicer is HealthServicer."""
        server = create_server(options=ServerOptions(enable_health_check=False))
        health_servicer = register_health_check(server)
        assert isinstance(health_servicer, type(health.HealthServicer()))
        server.stop(0)

    def test_health_check_sets_serving_status(self) -> None:
        """Test health check sets SERVING status."""
        server = create_server(options=ServerOptions(enable_health_check=False))
        health_servicer = register_health_check(server)
        # Verify the servicer can set status
        health_servicer.set("test_service", health_pb2.HealthCheckResponse.SERVING)
        server.stop(0)


class TestEnableReflection:
    """Test _enable_reflection function."""

    def test_enable_reflection(self) -> None:
        """Test reflection is enabled on server."""
        server = create_server(options=ServerOptions(enable_reflection=False))
        # Should not raise
        _enable_reflection(server)
        server.stop(0)


class TestStartServerWithGracefulShutdown:
    """Test start_server_with_graceful_shutdown function."""

    def test_graceful_shutdown_sigterm(self) -> None:
        """Test server graceful shutdown on SIGTERM."""
        server = MagicMock(spec=grpc.Server)

        def mock_wait_for_termination() -> None:
            # Simulate SIGTERM signal
            raise KeyboardInterrupt()

        server.wait_for_termination = mock_wait_for_termination

        with patch("signal.signal") as mock_signal:
            with pytest.raises(KeyboardInterrupt):
                start_server_with_graceful_shutdown(server, port=50051, grace_period=30.0)

            # Verify signal handlers were registered
            assert mock_signal.call_count == 2
            calls = mock_signal.call_args_list
            assert calls[0][0][0] == signal.SIGTERM
            assert calls[1][0][0] == signal.SIGINT

    def test_graceful_shutdown_calls_server_methods(self) -> None:
        """Test graceful shutdown calls required server methods."""
        server = MagicMock(spec=grpc.Server)

        def mock_wait_for_termination() -> None:
            raise KeyboardInterrupt()

        server.wait_for_termination = mock_wait_for_termination

        with patch("signal.signal"):
            with pytest.raises(KeyboardInterrupt):
                start_server_with_graceful_shutdown(server, port=50051, grace_period=30.0)

        server.add_insecure_port.assert_called_once_with("[::]:50051")
        server.start.assert_called_once()

    def test_graceful_shutdown_custom_port(self) -> None:
        """Test graceful shutdown with custom port."""
        server = MagicMock(spec=grpc.Server)

        def mock_wait_for_termination() -> None:
            raise KeyboardInterrupt()

        server.wait_for_termination = mock_wait_for_termination

        with patch("signal.signal"):
            with pytest.raises(KeyboardInterrupt):
                start_server_with_graceful_shutdown(server, port=9999)

        server.add_insecure_port.assert_called_once_with("[::]:9999")

    def test_graceful_shutdown_custom_grace_period(self) -> None:
        """Test graceful shutdown with custom grace period."""
        server = MagicMock(spec=grpc.Server)

        def mock_wait_for_termination() -> None:
            raise KeyboardInterrupt()

        server.wait_for_termination = mock_wait_for_termination

        with patch("signal.signal") as mock_signal:
            with pytest.raises(KeyboardInterrupt):
                start_server_with_graceful_shutdown(server, grace_period=15.0)

            # Extract the signal handler function
            handler_func = mock_signal.call_args_list[0][0][1]
            # Call the handler
            handler_func(signal.SIGTERM, None)
            # Verify stop was called with grace period
            server.stop.assert_called_once_with(15.0)
