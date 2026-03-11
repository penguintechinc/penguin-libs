"""Tests for penguin_libs.http module."""

import time
import uuid
from unittest.mock import MagicMock, patch

import httpx
import pytest
from flask import Flask

from penguin_libs.http.client import (
    CircuitBreakerConfig,
    CircuitState,
    HTTPClient,
    HTTPClientConfig,
    RetryConfig,
)
from penguin_libs.http.correlation import (
    CorrelationMiddleware,
    _correlation_id,
    _extract_correlation_id,
    generate_correlation_id,
    get_correlation_id,
)

# ──────────────────────── correlation.py ────────────────────────


class TestGenerateCorrelationId:
    def test_returns_uuid(self):
        cid = generate_correlation_id()
        parsed = uuid.UUID(cid, version=4)
        assert str(parsed) == cid

    def test_unique(self):
        ids = {generate_correlation_id() for _ in range(100)}
        assert len(ids) == 100


class TestGetCorrelationId:
    def test_from_context_var(self):
        token = _correlation_id.set("test-id-123")
        try:
            assert get_correlation_id() == "test-id-123"
        finally:
            _correlation_id.set(None)

    def test_from_flask_g(self):
        app = Flask(__name__)
        _correlation_id.set(None)
        with app.test_request_context():
            from flask import g

            g.correlation_id = "flask-cid"
            assert get_correlation_id() == "flask-cid"

    def test_no_context_returns_none(self):
        _correlation_id.set(None)
        app = Flask(__name__)
        with app.test_request_context():
            # g has no correlation_id attribute
            result = get_correlation_id()
            assert result is None


class TestExtractCorrelationId:
    def test_from_correlation_header(self):
        req = MagicMock()
        req.headers.get = lambda h: "abc-123" if h == "X-Correlation-ID" else None
        assert _extract_correlation_id(req) == "abc-123"

    def test_from_request_id_header(self):
        req = MagicMock()

        def header_get(h):
            if h == "X-Request-ID":
                return "req-456"
            return None

        req.headers.get = header_get
        assert _extract_correlation_id(req) == "req-456"

    def test_generates_new(self):
        req = MagicMock()
        req.headers.get = lambda h: None
        cid = _extract_correlation_id(req)
        assert cid is not None
        uuid.UUID(cid, version=4)


class TestCorrelationMiddleware:
    def test_init_with_app(self):
        app = Flask(__name__)
        middleware = CorrelationMiddleware(app)
        assert middleware.app is app

    def test_init_without_app(self):
        middleware = CorrelationMiddleware()
        assert middleware.app is None

    def test_init_app(self):
        app = Flask(__name__)
        middleware = CorrelationMiddleware()
        middleware.init_app(app)
        assert middleware.app is app

    def test_request_lifecycle(self):
        app = Flask(__name__)
        CorrelationMiddleware(app)

        @app.route("/test")
        def test_route():
            from flask import g

            return {"cid": g.correlation_id}

        with app.test_client() as client:
            resp = client.get("/test", headers={"X-Correlation-ID": "my-id"})
            assert resp.json["cid"] == "my-id"
            assert resp.headers.get("X-Correlation-ID") == "my-id"
            assert resp.headers.get("X-Request-ID") == "my-id"

    def test_auto_generates_id(self):
        app = Flask(__name__)
        CorrelationMiddleware(app)

        @app.route("/test")
        def test_route():
            from flask import g

            return {"cid": g.correlation_id}

        with app.test_client() as client:
            resp = client.get("/test")
            cid = resp.json["cid"]
            assert cid is not None
            uuid.UUID(cid, version=4)


# ──────────────────────── client.py ────────────────────────


class TestRetryConfig:
    def test_defaults(self):
        rc = RetryConfig()
        assert rc.max_retries == 3
        assert rc.base_delay == 1.0
        assert rc.max_delay == 30.0
        assert rc.exponential_base == 2.0
        assert rc.jitter is True


class TestCircuitBreakerConfig:
    def test_defaults(self):
        cb = CircuitBreakerConfig()
        assert cb.enabled is False
        assert cb.failure_threshold == 5
        assert cb.timeout == 60.0


class TestHTTPClientConfig:
    def test_defaults(self):
        cfg = HTTPClientConfig()
        assert cfg.timeout == 30.0
        assert cfg.follow_redirects is True
        assert cfg.verify_ssl is True


class TestHTTPClient:
    def _make_client(self, **kwargs):
        """Create an HTTPClient, to be closed by caller."""
        return HTTPClient(HTTPClientConfig(**kwargs))

    def test_context_manager(self):
        with HTTPClient() as client:
            assert client is not None

    def test_close(self):
        client = HTTPClient()
        client.close()

    def test_calculate_delay_no_jitter(self):
        cfg = HTTPClientConfig(
            retry=RetryConfig(base_delay=1.0, exponential_base=2.0, jitter=False)
        )
        client = HTTPClient(cfg)
        assert client._calculate_delay(0) == 1.0
        assert client._calculate_delay(1) == 2.0
        assert client._calculate_delay(2) == 4.0
        client.close()

    def test_calculate_delay_max_cap(self):
        cfg = HTTPClientConfig(
            retry=RetryConfig(base_delay=10.0, exponential_base=10.0, max_delay=30.0, jitter=False)
        )
        client = HTTPClient(cfg)
        assert client._calculate_delay(5) == 30.0
        client.close()

    def test_calculate_delay_with_jitter(self):
        cfg = HTTPClientConfig(retry=RetryConfig(base_delay=1.0, jitter=True))
        client = HTTPClient(cfg)
        delays = {client._calculate_delay(0) for _ in range(20)}
        assert len(delays) > 1
        client.close()

    def test_prepare_headers_basic(self):
        cfg = HTTPClientConfig(headers={"X-Custom": "value"})
        client = HTTPClient(cfg)
        with patch("penguin_libs.http.client.get_correlation_id", return_value=None):
            headers = client._prepare_headers({"Authorization": "Bearer tok"})
            assert headers["X-Custom"] == "value"
            assert headers["Authorization"] == "Bearer tok"
        client.close()

    def test_prepare_headers_with_correlation(self):
        cfg = HTTPClientConfig()
        client = HTTPClient(cfg)
        with patch("penguin_libs.http.client.get_correlation_id", return_value="corr-123"):
            headers = client._prepare_headers(None)
            assert headers["X-Correlation-ID"] == "corr-123"
            assert headers["X-Request-ID"] == "corr-123"
        client.close()

    def test_prepare_headers_no_overwrite_correlation(self):
        cfg = HTTPClientConfig()
        client = HTTPClient(cfg)
        with patch("penguin_libs.http.client.get_correlation_id", return_value="auto-id"):
            headers = client._prepare_headers({"X-Correlation-ID": "manual-id"})
            assert headers["X-Correlation-ID"] == "manual-id"
        client.close()

    def _mock_response(self, status=200, content=b"ok"):
        resp = MagicMock(spec=httpx.Response)
        resp.status_code = status
        resp.content = content
        resp.raise_for_status = MagicMock()
        return resp

    def test_get_success(self):
        client = HTTPClient()
        mock_resp = self._mock_response()
        with (
            patch("penguin_libs.http.client.get_correlation_id", return_value=None),
            patch.object(client._client, "request", return_value=mock_resp),
        ):
            resp = client.get("http://test.example.com/api")
            assert resp.status_code == 200
        client.close()

    def test_post_success(self):
        client = HTTPClient()
        mock_resp = self._mock_response(201, b'{"id": 1}')
        with (
            patch("penguin_libs.http.client.get_correlation_id", return_value=None),
            patch.object(client._client, "request", return_value=mock_resp),
        ):
            resp = client.post("http://test.example.com/api", json={"name": "test"})
            assert resp.status_code == 201
        client.close()

    def test_put_patch_delete_head_options(self):
        client = HTTPClient()
        mock_resp = self._mock_response()
        with (
            patch("penguin_libs.http.client.get_correlation_id", return_value=None),
            patch.object(client._client, "request", return_value=mock_resp),
        ):
            for method in [client.put, client.patch, client.delete, client.head, client.options]:
                resp = method("http://test.example.com/api")
                assert resp.status_code == 200
        client.close()

    def test_retry_on_server_error(self):
        cfg = HTTPClientConfig(retry=RetryConfig(max_retries=2, base_delay=0.01, jitter=False))
        client = HTTPClient(cfg)
        mock_resp = self._mock_response()
        call_count = 0

        def side_effect(method, url, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise httpx.RequestError("Connection failed")
            return mock_resp

        with (
            patch("penguin_libs.http.client.get_correlation_id", return_value=None),
            patch.object(client._client, "request", side_effect=side_effect),
        ):
            resp = client.get("http://test.example.com/api")
            assert resp.status_code == 200
            assert call_count == 3
        client.close()

    def test_no_retry_on_4xx(self):
        cfg = HTTPClientConfig(retry=RetryConfig(max_retries=3, base_delay=0.01, jitter=False))
        client = HTTPClient(cfg)
        mock_resp = MagicMock(spec=httpx.Response)
        mock_resp.status_code = 404
        error = httpx.HTTPStatusError("Not Found", request=MagicMock(), response=mock_resp)

        with (
            patch("penguin_libs.http.client.get_correlation_id", return_value=None),
            patch.object(client._client, "request", side_effect=error),
        ):
            with pytest.raises(httpx.HTTPStatusError):
                client.get("http://test.example.com/notfound")
        client.close()

    def test_retry_on_429(self):
        cfg = HTTPClientConfig(retry=RetryConfig(max_retries=1, base_delay=0.01, jitter=False))
        client = HTTPClient(cfg)
        mock_429 = MagicMock(spec=httpx.Response)
        mock_429.status_code = 429
        error = httpx.HTTPStatusError("Rate Limited", request=MagicMock(), response=mock_429)
        mock_ok = self._mock_response()
        call_count = 0

        def side_effect(method, url, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise error
            return mock_ok

        with (
            patch("penguin_libs.http.client.get_correlation_id", return_value=None),
            patch.object(client._client, "request", side_effect=side_effect),
        ):
            resp = client.get("http://test.example.com/api")
            assert resp.status_code == 200
        client.close()

    def test_exhausted_retries(self):
        cfg = HTTPClientConfig(retry=RetryConfig(max_retries=1, base_delay=0.01, jitter=False))
        client = HTTPClient(cfg)
        with (
            patch("penguin_libs.http.client.get_correlation_id", return_value=None),
            patch.object(client._client, "request", side_effect=httpx.RequestError("fail")),
        ):
            with pytest.raises(httpx.RequestError):
                client.get("http://test.example.com/api")
        client.close()


class TestCircuitBreaker:
    def test_circuit_closed_by_default(self):
        cfg = HTTPClientConfig(
            circuit_breaker=CircuitBreakerConfig(enabled=True, failure_threshold=3)
        )
        client = HTTPClient(cfg)
        assert client._circuit_state.state == CircuitState.CLOSED
        client.close()

    def test_circuit_opens_after_threshold(self):
        cfg = HTTPClientConfig(
            circuit_breaker=CircuitBreakerConfig(enabled=True, failure_threshold=2)
        )
        client = HTTPClient(cfg)
        client._record_failure()
        assert client._circuit_state.state == CircuitState.CLOSED
        client._record_failure()
        assert client._circuit_state.state == CircuitState.OPEN
        client.close()

    def test_circuit_open_rejects_requests(self):
        cfg = HTTPClientConfig(
            circuit_breaker=CircuitBreakerConfig(enabled=True, failure_threshold=1, timeout=60.0)
        )
        client = HTTPClient(cfg)
        client._circuit_state.state = CircuitState.OPEN
        client._circuit_state.last_failure_time = time.time()
        with pytest.raises(httpx.HTTPError, match="Circuit breaker is OPEN"):
            client._check_circuit_breaker()
        client.close()

    def test_circuit_half_open_after_timeout(self):
        cfg = HTTPClientConfig(
            circuit_breaker=CircuitBreakerConfig(enabled=True, failure_threshold=1, timeout=0.01)
        )
        client = HTTPClient(cfg)
        client._circuit_state.state = CircuitState.OPEN
        client._circuit_state.last_failure_time = time.time() - 1.0
        client._check_circuit_breaker()
        assert client._circuit_state.state == CircuitState.HALF_OPEN
        client.close()

    def test_circuit_closes_after_success_threshold(self):
        cfg = HTTPClientConfig(
            circuit_breaker=CircuitBreakerConfig(enabled=True, success_threshold=2)
        )
        client = HTTPClient(cfg)
        client._circuit_state.state = CircuitState.HALF_OPEN
        client._record_success()
        assert client._circuit_state.state == CircuitState.HALF_OPEN
        client._record_success()
        assert client._circuit_state.state == CircuitState.CLOSED
        client.close()

    def test_circuit_reopens_on_half_open_failure(self):
        cfg = HTTPClientConfig(circuit_breaker=CircuitBreakerConfig(enabled=True))
        client = HTTPClient(cfg)
        client._circuit_state.state = CircuitState.HALF_OPEN
        client._record_failure()
        assert client._circuit_state.state == CircuitState.OPEN
        client.close()

    def test_success_resets_failure_count_when_closed(self):
        cfg = HTTPClientConfig(
            circuit_breaker=CircuitBreakerConfig(enabled=True, failure_threshold=5)
        )
        client = HTTPClient(cfg)
        client._circuit_state.failure_count = 3
        client._record_success()
        assert client._circuit_state.failure_count == 0
        client.close()

    def test_disabled_circuit_breaker_noop(self):
        cfg = HTTPClientConfig(circuit_breaker=CircuitBreakerConfig(enabled=False))
        client = HTTPClient(cfg)
        client._check_circuit_breaker()
        client._record_success()
        client._record_failure()
        assert client._circuit_state.state == CircuitState.CLOSED
        client.close()


class TestCircuitStateEnum:
    def test_enum_values(self):
        assert CircuitState.CLOSED.value == "closed"
        assert CircuitState.OPEN.value == "open"
        assert CircuitState.HALF_OPEN.value == "half_open"


class TestHTTPModuleExports:
    def test_all_exports(self):
        from penguin_libs.http import __all__

        assert "HTTPClient" in __all__
        assert "CorrelationMiddleware" in __all__
        assert "get_correlation_id" in __all__
        assert "CircuitState" in __all__
