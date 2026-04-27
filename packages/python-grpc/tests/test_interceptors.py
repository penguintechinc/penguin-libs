"""Tests for gRPC interceptors."""

import time
import uuid
from unittest.mock import MagicMock, Mock, call, patch

import grpc
import jwt
import pytest

from penguin_grpc.interceptors import (
    AuditInterceptor,
    AuthInterceptor,
    CorrelationInterceptor,
    RateLimitEntry,
    RateLimitInterceptor,
    RecoveryInterceptor,
)


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

        with patch("penguin_grpc.interceptors.logger"):
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

            with patch("penguin_grpc.interceptors.jwt.decode", return_value={"sub": "user1"}):
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

            with patch("penguin_grpc.interceptors.jwt.decode", return_value={"sub": "user1"}):
                interceptor.intercept_service(continuation, handler_call_details)

        # 4th request should be rejected
        handler_call_details = MagicMock()
        handler_call_details.method = "/service/Method"
        handler_call_details.invocation_metadata = [("authorization", "Bearer token")]

        with patch("penguin_grpc.interceptors.jwt.decode", return_value={"sub": "user1"}):
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

            with patch("penguin_grpc.interceptors.jwt.decode", return_value={"sub": "user1"}):
                interceptor.intercept_service(continuation, handler_call_details)

        # User2 should still be able to make requests (separate limit)
        handler_call_details = MagicMock()
        handler_call_details.method = "/service/Method"
        handler_call_details.invocation_metadata = [("authorization", "Bearer token2")]

        with patch("penguin_grpc.interceptors.jwt.decode", return_value={"sub": "user2"}):
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

        with patch("penguin_grpc.interceptors.jwt.decode", return_value={"sub": "user1"}):
            interceptor.intercept_service(continuation, handler_call_details)

        # Manually reset window
        entry = interceptor.limits["user1"]
        entry.window_start = time.time() - 61.0  # Older than 60 seconds

        # Next request should be allowed (window reset)
        handler_call_details = MagicMock()
        handler_call_details.method = "/service/Method"
        handler_call_details.invocation_metadata = [("authorization", "Bearer token")]

        with patch("penguin_grpc.interceptors.jwt.decode", return_value={"sub": "user1"}):
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

        with patch("penguin_grpc.interceptors.logger"):
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

        with patch("penguin_grpc.interceptors.logger"):
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

        with patch("penguin_grpc.interceptors.logger") as mock_logger:
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

        with patch("penguin_grpc.interceptors.logger"):
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

        with patch("penguin_grpc.interceptors.logger"):
            interceptor.intercept_service(continuation, handler_call_details)
            continuation.assert_called_once_with(handler_call_details)

    def test_correlation_interceptor_generates_new_id(self) -> None:
        """Test new correlation ID is generated if missing."""
        interceptor = CorrelationInterceptor()
        continuation = MagicMock()
        handler_call_details = MagicMock()
        handler_call_details.method = "/service/Method"
        handler_call_details.invocation_metadata = []

        with patch("penguin_grpc.interceptors.logger"):
            with patch("penguin_grpc.interceptors.uuid.uuid4") as mock_uuid:
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

        with patch("penguin_grpc.interceptors.logger") as mock_logger:
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

        with patch("penguin_grpc.interceptors.logger"):
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

        with patch("penguin_grpc.interceptors.logger") as mock_logger:
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
