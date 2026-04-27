"""Comprehensive tests for HTTPClient and correlation utilities."""

import logging
import time
import uuid
from unittest.mock import MagicMock, Mock, patch

import httpx
import pytest
from flask import Flask, g

from penguin_http import (
    CircuitBreakerConfig,
    CircuitState,
    CorrelationMiddleware,
    HTTPClient,
    HTTPClientConfig,
    RetryConfig,
    generate_correlation_id,
    get_correlation_id,
)


class TestGenerateCorrelationId:
    """Tests for generate_correlation_id function."""

    def test_generate_correlation_id_returns_uuid(self) -> None:
        """Test that generate_correlation_id returns a valid UUID4 string."""
        correlation_id = generate_correlation_id()
        assert isinstance(correlation_id, str)
        # Verify it's a valid UUID
        uuid.UUID(correlation_id)

    def test_generate_correlation_id_unique(self) -> None:
        """Test that generated IDs are unique."""
        id1 = generate_correlation_id()
        id2 = generate_correlation_id()
        assert id1 != id2

    def test_generate_correlation_id_format(self) -> None:
        """Test that generated ID follows UUID format."""
        correlation_id = generate_correlation_id()
        assert len(correlation_id) == 36  # Standard UUID length
        assert correlation_id.count("-") == 4  # Standard UUID format


class TestGetCorrelationId:
    """Tests for get_correlation_id function."""

    def test_get_correlation_id_returns_none_when_not_set(self) -> None:
        """Test that get_correlation_id returns None when no ID is set."""
        # Clear any existing context
        from penguin_http.correlation import _correlation_id

        _correlation_id.set(None)

        with patch("penguin_http.correlation.g", {}):
            result = get_correlation_id()
            assert result is None

    def test_get_correlation_id_from_context_var(self) -> None:
        """Test that get_correlation_id retrieves from context variable."""
        from penguin_http.correlation import _correlation_id

        test_id = "test-correlation-id"
        _correlation_id.set(test_id)

        with patch("penguin_http.correlation.g", {}):
            result = get_correlation_id()
            assert result == test_id

        # Cleanup
        _correlation_id.set(None)

    def test_get_correlation_id_from_flask_g(self) -> None:
        """Test that get_correlation_id falls back to Flask g object."""
        from penguin_http.correlation import _correlation_id

        test_id = "test-flask-id"
        _correlation_id.set(None)

        # Create a Flask app context so g works
        app = Flask(__name__)
        with app.app_context():
            g.correlation_id = test_id
            result = get_correlation_id()
            assert result == test_id

    def test_get_correlation_id_prefers_context_over_flask(self) -> None:
        """Test that context variable takes precedence over Flask g."""
        from penguin_http.correlation import _correlation_id

        context_id = "context-id"
        flask_id = "flask-id"
        _correlation_id.set(context_id)

        mock_g = {"correlation_id": flask_id}

        with patch("penguin_http.correlation.g", mock_g):
            result = get_correlation_id()
            assert result == context_id

        _correlation_id.set(None)


class TestCorrelationMiddleware:
    """Tests for CorrelationMiddleware."""

    def test_correlation_middleware_initialization(self) -> None:
        """Test that CorrelationMiddleware initializes correctly."""
        app = Flask(__name__)
        middleware = CorrelationMiddleware(app)
        assert middleware.app is app

    def test_correlation_middleware_init_app(self) -> None:
        """Test init_app method."""
        app = Flask(__name__)
        middleware = CorrelationMiddleware()
        middleware.init_app(app)
        assert middleware.app is app

    def test_middleware_generates_correlation_id_on_request(self) -> None:
        """Test that middleware generates correlation ID for new requests."""
        app = Flask(__name__)
        CorrelationMiddleware(app)

        @app.route("/test")
        def test_route() -> dict:
            correlation_id = get_correlation_id()
            return {"correlation_id": correlation_id}

        with app.test_client() as client:
            response = client.get("/test")
            data = response.get_json()
            assert data["correlation_id"] is not None
            # Verify it's a valid UUID
            uuid.UUID(data["correlation_id"])

    def test_middleware_extracts_correlation_id_from_header(self) -> None:
        """Test that middleware extracts correlation ID from X-Correlation-ID header."""
        app = Flask(__name__)
        CorrelationMiddleware(app)

        test_id = "test-correlation-123"

        @app.route("/test")
        def test_route() -> dict:
            correlation_id = get_correlation_id()
            return {"correlation_id": correlation_id}

        with app.test_client() as client:
            response = client.get("/test", headers={"X-Correlation-ID": test_id})
            data = response.get_json()
            assert data["correlation_id"] == test_id

    def test_middleware_falls_back_to_x_request_id(self) -> None:
        """Test that middleware falls back to X-Request-ID header."""
        app = Flask(__name__)
        CorrelationMiddleware(app)

        test_id = "request-id-456"

        @app.route("/test")
        def test_route() -> dict:
            correlation_id = get_correlation_id()
            return {"correlation_id": correlation_id}

        with app.test_client() as client:
            response = client.get("/test", headers={"X-Request-ID": test_id})
            data = response.get_json()
            assert data["correlation_id"] == test_id

    def test_middleware_prefers_correlation_id_over_request_id(self) -> None:
        """Test that X-Correlation-ID takes precedence over X-Request-ID."""
        app = Flask(__name__)
        CorrelationMiddleware(app)

        correlation_id = "correlation-789"
        request_id = "request-id-456"

        @app.route("/test")
        def test_route() -> dict:
            cid = get_correlation_id()
            return {"correlation_id": cid}

        with app.test_client() as client:
            response = client.get(
                "/test",
                headers={"X-Correlation-ID": correlation_id, "X-Request-ID": request_id},
            )
            data = response.get_json()
            assert data["correlation_id"] == correlation_id

    def test_middleware_adds_correlation_id_to_response_headers(self) -> None:
        """Test that middleware adds correlation ID to response headers."""
        app = Flask(__name__)
        CorrelationMiddleware(app)

        @app.route("/test")
        def test_route() -> dict:
            return {"status": "ok"}

        with app.test_client() as client:
            response = client.get("/test")
            assert "X-Correlation-ID" in response.headers
            assert "X-Request-ID" in response.headers
            # Verify they're the same
            assert response.headers["X-Correlation-ID"] == response.headers["X-Request-ID"]


class TestRetryConfig:
    """Tests for RetryConfig dataclass."""

    def test_retry_config_defaults(self) -> None:
        """Test RetryConfig default values."""
        config = RetryConfig()
        assert config.max_retries == 3
        assert config.base_delay == 1.0
        assert config.max_delay == 30.0
        assert config.exponential_base == 2.0
        assert config.jitter is True

    def test_retry_config_custom_values(self) -> None:
        """Test RetryConfig with custom values."""
        config = RetryConfig(
            max_retries=5, base_delay=2.0, max_delay=60.0, exponential_base=3.0, jitter=False
        )
        assert config.max_retries == 5
        assert config.base_delay == 2.0
        assert config.max_delay == 60.0
        assert config.exponential_base == 3.0
        assert config.jitter is False


class TestCircuitBreakerConfig:
    """Tests for CircuitBreakerConfig dataclass."""

    def test_circuit_breaker_config_defaults(self) -> None:
        """Test CircuitBreakerConfig default values."""
        config = CircuitBreakerConfig()
        assert config.enabled is False
        assert config.failure_threshold == 5
        assert config.success_threshold == 2
        assert config.timeout == 60.0

    def test_circuit_breaker_config_enabled(self) -> None:
        """Test CircuitBreakerConfig with enabled flag."""
        config = CircuitBreakerConfig(
            enabled=True, failure_threshold=3, success_threshold=1, timeout=30.0
        )
        assert config.enabled is True
        assert config.failure_threshold == 3
        assert config.success_threshold == 1
        assert config.timeout == 30.0


class TestHTTPClientConfig:
    """Tests for HTTPClientConfig dataclass."""

    def test_http_client_config_defaults(self) -> None:
        """Test HTTPClientConfig default values."""
        config = HTTPClientConfig()
        assert config.timeout == 30.0
        assert config.follow_redirects is True
        assert config.verify_ssl is True
        assert config.headers == {}
        assert isinstance(config.retry, RetryConfig)
        assert isinstance(config.circuit_breaker, CircuitBreakerConfig)

    def test_http_client_config_custom_values(self) -> None:
        """Test HTTPClientConfig with custom values."""
        retry = RetryConfig(max_retries=5)
        circuit_breaker = CircuitBreakerConfig(enabled=True)
        custom_headers = {"Authorization": "Bearer token"}

        config = HTTPClientConfig(
            timeout=60.0,
            retry=retry,
            circuit_breaker=circuit_breaker,
            headers=custom_headers,
            follow_redirects=False,
            verify_ssl=False,
        )

        assert config.timeout == 60.0
        assert config.retry is retry
        assert config.circuit_breaker is circuit_breaker
        assert config.headers == custom_headers
        assert config.follow_redirects is False
        assert config.verify_ssl is False


class TestHTTPClientInitialization:
    """Tests for HTTPClient initialization and context manager."""

    def test_http_client_initialization_with_defaults(self) -> None:
        """Test HTTPClient initialization with default config."""
        client = HTTPClient()
        assert client.config is not None
        assert client.config.timeout == 30.0
        assert client._client is not None
        client.close()

    def test_http_client_initialization_with_custom_config(self) -> None:
        """Test HTTPClient initialization with custom config."""
        config = HTTPClientConfig(timeout=60.0)
        client = HTTPClient(config)
        assert client.config is config
        assert client.config.timeout == 60.0
        client.close()

    def test_http_client_context_manager(self) -> None:
        """Test HTTPClient as context manager."""
        with HTTPClient() as client:
            assert client is not None
            assert client._client is not None

    def test_http_client_context_manager_closes_client(self) -> None:
        """Test that context manager properly closes client."""
        client = HTTPClient()
        assert not client._client.is_closed

        with client:
            pass

        # After exiting context, client should be closed
        assert client._client.is_closed

    def test_http_client_close(self) -> None:
        """Test that close() closes the underlying client."""
        client = HTTPClient()
        assert not client._client.is_closed
        client.close()
        assert client._client.is_closed


class TestHTTPClientDelayCalculation:
    """Tests for HTTPClient._calculate_delay method."""

    def test_calculate_delay_exponential_backoff(self) -> None:
        """Test exponential backoff calculation."""
        config = HTTPClientConfig(retry=RetryConfig(base_delay=1.0, exponential_base=2.0, jitter=False))
        client = HTTPClient(config)

        # Attempt 0: 1.0 * 2^0 = 1.0
        delay = client._calculate_delay(0)
        assert delay == 1.0

        # Attempt 1: 1.0 * 2^1 = 2.0
        delay = client._calculate_delay(1)
        assert delay == 2.0

        # Attempt 2: 1.0 * 2^2 = 4.0
        delay = client._calculate_delay(2)
        assert delay == 4.0

        client.close()

    def test_calculate_delay_respects_max_delay(self) -> None:
        """Test that delay calculation respects max_delay."""
        config = HTTPClientConfig(
            retry=RetryConfig(base_delay=1.0, exponential_base=2.0, max_delay=10.0, jitter=False)
        )
        client = HTTPClient(config)

        # Attempt 5: 1.0 * 2^5 = 32.0, but capped at 10.0
        delay = client._calculate_delay(5)
        assert delay == 10.0

        client.close()

    def test_calculate_delay_with_jitter(self) -> None:
        """Test that jitter adds randomness to delay."""
        config = HTTPClientConfig(
            retry=RetryConfig(base_delay=1.0, exponential_base=2.0, jitter=True)
        )
        client = HTTPClient(config)

        # With jitter, delays should vary
        delays = [client._calculate_delay(1) for _ in range(10)]
        assert len(set(delays)) > 1  # Not all delays are the same
        # But all should be in valid range (0.5 * 2.0 to 1.5 * 2.0)
        assert all(1.0 <= d <= 3.0 for d in delays)

        client.close()


class TestHTTPClientCircuitBreaker:
    """Tests for HTTPClient circuit breaker logic."""

    def test_circuit_breaker_check_closed_state(self) -> None:
        """Test that circuit breaker allows requests in CLOSED state."""
        config = HTTPClientConfig(circuit_breaker=CircuitBreakerConfig(enabled=True))
        client = HTTPClient(config)

        # CLOSED state should not raise
        client._check_circuit_breaker()

        client.close()

    def test_circuit_breaker_check_open_state_raises(self) -> None:
        """Test that circuit breaker raises exception in OPEN state."""
        config = HTTPClientConfig(circuit_breaker=CircuitBreakerConfig(enabled=True, timeout=1.0))
        client = HTTPClient(config)

        # Manually set to OPEN
        client._circuit_state.state = CircuitState.OPEN
        client._circuit_state.last_failure_time = time.time()

        with pytest.raises(httpx.HTTPError, match="Circuit breaker is OPEN"):
            client._check_circuit_breaker()

        client.close()

    def test_circuit_breaker_transitions_to_half_open(self) -> None:
        """Test circuit breaker transitions from OPEN to HALF_OPEN after timeout."""
        config = HTTPClientConfig(
            circuit_breaker=CircuitBreakerConfig(enabled=True, timeout=0.1)
        )
        client = HTTPClient(config)

        # Set to OPEN with past timestamp
        client._circuit_state.state = CircuitState.OPEN
        client._circuit_state.last_failure_time = time.time() - 0.2  # 0.2s ago

        # Should transition to HALF_OPEN
        client._check_circuit_breaker()
        assert client._circuit_state.state == CircuitState.HALF_OPEN

        client.close()

    def test_record_success_closes_half_open(self) -> None:
        """Test that successful request closes circuit in HALF_OPEN state."""
        config = HTTPClientConfig(
            circuit_breaker=CircuitBreakerConfig(enabled=True, success_threshold=2)
        )
        client = HTTPClient(config)

        client._circuit_state.state = CircuitState.HALF_OPEN
        client._circuit_state.success_count = 0

        # First success
        client._record_success()
        assert client._circuit_state.success_count == 1

        # Second success
        client._record_success()
        assert client._circuit_state.state == CircuitState.CLOSED

        client.close()

    def test_record_failure_opens_circuit_from_closed(self) -> None:
        """Test that circuit opens after threshold failures."""
        config = HTTPClientConfig(
            circuit_breaker=CircuitBreakerConfig(enabled=True, failure_threshold=2)
        )
        client = HTTPClient(config)

        assert client._circuit_state.state == CircuitState.CLOSED

        client._record_failure()
        assert client._circuit_state.failure_count == 1
        assert client._circuit_state.state == CircuitState.CLOSED

        client._record_failure()
        assert client._circuit_state.state == CircuitState.OPEN

        client.close()

    def test_record_failure_opens_from_half_open(self) -> None:
        """Test that single failure in HALF_OPEN opens circuit."""
        config = HTTPClientConfig(circuit_breaker=CircuitBreakerConfig(enabled=True))
        client = HTTPClient(config)

        client._circuit_state.state = CircuitState.HALF_OPEN

        client._record_failure()
        assert client._circuit_state.state == CircuitState.OPEN

        client.close()


class TestHTTPClientPrepareHeaders:
    """Tests for HTTPClient._prepare_headers method."""

    @patch("penguin_http.client.get_correlation_id", return_value=None)
    def test_prepare_headers_with_default_headers(self, mock_corr: Mock) -> None:
        """Test that default headers are included."""
        default_headers = {"User-Agent": "MyApp/1.0"}
        config = HTTPClientConfig(headers=default_headers)
        client = HTTPClient(config)

        result = client._prepare_headers(None)
        assert result["User-Agent"] == "MyApp/1.0"

        client.close()

    @patch("penguin_http.client.get_correlation_id", return_value=None)
    def test_prepare_headers_merges_user_headers(self, mock_corr: Mock) -> None:
        """Test that user headers are merged with defaults."""
        default_headers = {"User-Agent": "MyApp/1.0"}
        config = HTTPClientConfig(headers=default_headers)
        client = HTTPClient(config)

        user_headers = {"Authorization": "Bearer token"}
        result = client._prepare_headers(user_headers)

        assert result["User-Agent"] == "MyApp/1.0"
        assert result["Authorization"] == "Bearer token"

        client.close()

    @patch("penguin_http.client.get_correlation_id", return_value=None)
    def test_prepare_headers_user_overrides_defaults(self, mock_corr: Mock) -> None:
        """Test that user headers override defaults."""
        default_headers = {"User-Agent": "MyApp/1.0"}
        config = HTTPClientConfig(headers=default_headers)
        client = HTTPClient(config)

        user_headers = {"User-Agent": "CustomAgent/2.0"}
        result = client._prepare_headers(user_headers)

        assert result["User-Agent"] == "CustomAgent/2.0"

        client.close()

    @patch("penguin_http.client.get_correlation_id")
    def test_prepare_headers_adds_correlation_id(self, mock_get_correlation_id: Mock) -> None:
        """Test that correlation ID is added to headers."""
        mock_get_correlation_id.return_value = "test-correlation-123"
        config = HTTPClientConfig()
        client = HTTPClient(config)

        result = client._prepare_headers(None)

        assert result["X-Correlation-ID"] == "test-correlation-123"
        assert result["X-Request-ID"] == "test-correlation-123"

        client.close()

    @patch("penguin_http.client.get_correlation_id")
    def test_prepare_headers_does_not_override_correlation_id(self, mock_get_correlation_id: Mock) -> None:
        """Test that provided correlation ID is not overridden."""
        mock_get_correlation_id.return_value = "generated-id"
        config = HTTPClientConfig()
        client = HTTPClient(config)

        user_headers = {"X-Correlation-ID": "user-provided-id"}
        result = client._prepare_headers(user_headers)

        assert result["X-Correlation-ID"] == "user-provided-id"

        client.close()

    @patch("penguin_http.client.get_correlation_id")
    def test_prepare_headers_skips_correlation_when_none(self, mock_get_correlation_id: Mock) -> None:
        """Test that no correlation ID header is added when not available."""
        mock_get_correlation_id.return_value = None
        config = HTTPClientConfig()
        client = HTTPClient(config)

        result = client._prepare_headers(None)

        assert "X-Correlation-ID" not in result
        assert "X-Request-ID" not in result

        client.close()


class TestHTTPClientMethods:
    """Tests for HTTPClient HTTP methods (GET, POST, etc.)."""

    @patch("penguin_http.client.HTTPClient._request_with_retry")
    def test_get_method(self, mock_request: Mock) -> None:
        """Test GET method."""
        mock_response = Mock(spec=httpx.Response)
        mock_request.return_value = mock_response

        client = HTTPClient()
        result = client.get("https://api.example.com/users")

        mock_request.assert_called_once_with("GET", "https://api.example.com/users")
        assert result is mock_response

        client.close()

    @patch("penguin_http.client.HTTPClient._request_with_retry")
    def test_post_method(self, mock_request: Mock) -> None:
        """Test POST method."""
        mock_response = Mock(spec=httpx.Response)
        mock_request.return_value = mock_response

        client = HTTPClient()
        result = client.post("https://api.example.com/users", json={"name": "John"})

        mock_request.assert_called_once_with(
            "POST", "https://api.example.com/users", json={"name": "John"}
        )

        client.close()

    @patch("penguin_http.client.HTTPClient._request_with_retry")
    def test_put_method(self, mock_request: Mock) -> None:
        """Test PUT method."""
        mock_response = Mock(spec=httpx.Response)
        mock_request.return_value = mock_response

        client = HTTPClient()
        result = client.put("https://api.example.com/users/1", json={"name": "Jane"})

        mock_request.assert_called_once_with(
            "PUT", "https://api.example.com/users/1", json={"name": "Jane"}
        )

        client.close()

    @patch("penguin_http.client.HTTPClient._request_with_retry")
    def test_patch_method(self, mock_request: Mock) -> None:
        """Test PATCH method."""
        mock_response = Mock(spec=httpx.Response)
        mock_request.return_value = mock_response

        client = HTTPClient()
        result = client.patch("https://api.example.com/users/1", json={"status": "active"})

        mock_request.assert_called_once_with(
            "PATCH", "https://api.example.com/users/1", json={"status": "active"}
        )

        client.close()

    @patch("penguin_http.client.HTTPClient._request_with_retry")
    def test_delete_method(self, mock_request: Mock) -> None:
        """Test DELETE method."""
        mock_response = Mock(spec=httpx.Response)
        mock_request.return_value = mock_response

        client = HTTPClient()
        result = client.delete("https://api.example.com/users/1")

        mock_request.assert_called_once_with("DELETE", "https://api.example.com/users/1")

        client.close()

    @patch("penguin_http.client.HTTPClient._request_with_retry")
    def test_head_method(self, mock_request: Mock) -> None:
        """Test HEAD method."""
        mock_response = Mock(spec=httpx.Response)
        mock_request.return_value = mock_response

        client = HTTPClient()
        result = client.head("https://api.example.com/users")

        mock_request.assert_called_once_with("HEAD", "https://api.example.com/users")

        client.close()

    @patch("penguin_http.client.HTTPClient._request_with_retry")
    def test_options_method(self, mock_request: Mock) -> None:
        """Test OPTIONS method."""
        mock_response = Mock(spec=httpx.Response)
        mock_request.return_value = mock_response

        client = HTTPClient()
        result = client.options("https://api.example.com/users")

        mock_request.assert_called_once_with("OPTIONS", "https://api.example.com/users")

        client.close()


class TestHTTPClientRetryLogic:
    """Tests for HTTPClient retry logic."""

    @patch("penguin_http.client.get_correlation_id", return_value=None)
    def test_successful_request_no_retry(self, mock_corr: Mock) -> None:
        """Test that successful request doesn't retry."""
        config = HTTPClientConfig(retry=RetryConfig(max_retries=3))
        client = HTTPClient(config)

        mock_response = Mock(spec=httpx.Response)
        mock_response.status_code = 200
        mock_response.content = b"test"

        with patch.object(client._client, "request", return_value=mock_response):
            result = client._request_with_retry("GET", "https://api.example.com/test")

            # Should be called only once (no retry)
            assert client._client.request.call_count == 1
            assert result is mock_response

        client.close()

    @patch("penguin_http.client.get_correlation_id", return_value=None)
    def test_retries_on_server_error(self, mock_corr: Mock) -> None:
        """Test that client retries on 5xx errors."""
        config = HTTPClientConfig(
            retry=RetryConfig(max_retries=2, base_delay=0.01, jitter=False)
        )
        client = HTTPClient(config)

        # Mock to fail twice, then succeed
        mock_response_success = Mock(spec=httpx.Response)
        mock_response_success.status_code = 200
        mock_response_success.content = b"success"

        mock_response_error = Mock(status_code=500)
        error = httpx.HTTPStatusError("500", request=Mock(), response=mock_response_error)

        with patch.object(client._client, "request") as mock_req:
            mock_req.side_effect = [error, error, mock_response_success]

            result = client._request_with_retry("GET", "https://api.example.com/test")

            # Should retry twice then succeed
            assert mock_req.call_count == 3
            assert result is mock_response_success

        client.close()

    @patch("penguin_http.client.get_correlation_id", return_value=None)
    def test_retries_on_rate_limit(self, mock_corr: Mock) -> None:
        """Test that client retries on 429 (rate limit)."""
        config = HTTPClientConfig(
            retry=RetryConfig(max_retries=1, base_delay=0.01, jitter=False)
        )
        client = HTTPClient(config)

        mock_response_success = Mock(spec=httpx.Response)
        mock_response_success.status_code = 200
        mock_response_success.content = b"ok"

        error = httpx.HTTPStatusError("429", request=Mock(), response=Mock(status_code=429))

        with patch.object(client._client, "request") as mock_request:
            mock_request.side_effect = [error, mock_response_success]

            result = client._request_with_retry("GET", "https://api.example.com/test")

            assert mock_request.call_count == 2

        client.close()

    @patch("penguin_http.client.get_correlation_id", return_value=None)
    def test_no_retry_on_client_error(self, mock_corr: Mock) -> None:
        """Test that client doesn't retry on 4xx (except 429)."""
        config = HTTPClientConfig(retry=RetryConfig(max_retries=3))
        client = HTTPClient(config)

        error = httpx.HTTPStatusError("404", request=Mock(), response=Mock(status_code=404))

        with patch.object(client._client, "request") as mock_request:
            mock_request.side_effect = error

            with pytest.raises(httpx.HTTPStatusError):
                client._request_with_retry("GET", "https://api.example.com/test")

            # Should not retry on 404
            assert mock_request.call_count == 1

        client.close()

    @patch("penguin_http.client.get_correlation_id", return_value=None)
    def test_exhausts_retries_and_raises(self, mock_corr: Mock) -> None:
        """Test that exception is raised after max retries exhausted."""
        config = HTTPClientConfig(
            retry=RetryConfig(max_retries=2, base_delay=0.01, jitter=False)
        )
        client = HTTPClient(config)

        error = httpx.HTTPStatusError("500", request=Mock(), response=Mock(status_code=500))

        with patch.object(client._client, "request") as mock_request:
            mock_request.side_effect = error

            with pytest.raises(httpx.HTTPStatusError):
                client._request_with_retry("GET", "https://api.example.com/test")

            # Should attempt max_retries + 1 times
            assert mock_request.call_count == 3

        client.close()

    @patch("penguin_http.client.get_correlation_id", return_value=None)
    def test_retries_on_connection_error(self, mock_corr: Mock) -> None:
        """Test that client retries on connection errors."""
        config = HTTPClientConfig(
            retry=RetryConfig(max_retries=2, base_delay=0.01, jitter=False)
        )
        client = HTTPClient(config)

        mock_response_success = Mock(spec=httpx.Response)
        mock_response_success.status_code = 200
        mock_response_success.content = b"success"

        error = httpx.ConnectError("Connection failed")

        with patch.object(client._client, "request") as mock_request:
            mock_request.side_effect = [error, error, mock_response_success]

            result = client._request_with_retry("GET", "https://api.example.com/test")

            assert mock_request.call_count == 3

        client.close()


class TestHTTPClientRecordFunctions:
    """Tests for success/failure recording."""

    def test_record_success_clears_failure_count_when_closed(self) -> None:
        """Test that recording success clears failures in CLOSED state."""
        config = HTTPClientConfig(circuit_breaker=CircuitBreakerConfig(enabled=True))
        client = HTTPClient(config)

        client._circuit_state.failure_count = 5
        client._circuit_state.state = CircuitState.CLOSED

        client._record_success()

        assert client._circuit_state.failure_count == 0

        client.close()

    def test_record_failure_disabled_circuit_breaker(self) -> None:
        """Test that failure recording is skipped when circuit breaker disabled."""
        config = HTTPClientConfig(circuit_breaker=CircuitBreakerConfig(enabled=False))
        client = HTTPClient(config)

        client._record_failure()

        assert client._circuit_state.failure_count == 0

        client.close()


class TestHTTPClientEdgeCases:
    """Tests for edge cases and error conditions."""

    def test_client_with_empty_default_headers(self) -> None:
        """Test client with empty default headers."""
        config = HTTPClientConfig(headers={})
        client = HTTPClient(config)
        assert client.config.headers == {}
        client.close()

    def test_client_with_large_timeout(self) -> None:
        """Test client with large timeout value."""
        config = HTTPClientConfig(timeout=3600.0)
        client = HTTPClient(config)
        assert client.config.timeout == 3600.0
        client.close()

    def test_client_with_zero_base_delay(self) -> None:
        """Test retry config with zero base delay."""
        config = HTTPClientConfig(retry=RetryConfig(base_delay=0.0))
        client = HTTPClient(config)
        delay = client._calculate_delay(1)
        assert delay == 0.0
        client.close()

    @patch("penguin_http.client.get_correlation_id", return_value=None)
    def test_request_with_timeout_error(self, mock_corr: Mock) -> None:
        """Test handling of timeout errors."""
        config = HTTPClientConfig(retry=RetryConfig(max_retries=1, base_delay=0.01, jitter=False))
        client = HTTPClient(config)

        error = httpx.TimeoutException("Request timeout")

        with patch.object(client._client, "request") as mock_request:
            mock_request.side_effect = error

            with pytest.raises(httpx.TimeoutException):
                client._request_with_retry("GET", "https://api.example.com/test")

        client.close()

    def test_circuit_state_enum_values(self) -> None:
        """Test CircuitState enum has expected values."""
        assert CircuitState.CLOSED.value == "closed"
        assert CircuitState.OPEN.value == "open"
        assert CircuitState.HALF_OPEN.value == "half_open"

    def test_multiple_client_instances_independent(self) -> None:
        """Test that multiple client instances have independent state."""
        client1 = HTTPClient()
        client2 = HTTPClient()

        client1._circuit_state.failure_count = 5
        client2._circuit_state.failure_count = 0

        assert client1._circuit_state.failure_count == 5
        assert client2._circuit_state.failure_count == 0

        client1.close()
        client2.close()
