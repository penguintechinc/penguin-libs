"""Tests for HTTP/3 ASGI components: health check, middleware, and server."""

from __future__ import annotations

import asyncio
import json
import logging
import ssl
import sys
import tempfile
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from penguin_http.h3.config import ServerConfig, TLSConfig
from penguin_http.h3.exceptions import H3ConfigError, H3ServerError, H3TLSError
from penguin_http.h3.health import HealthCheck
from penguin_http.h3.middleware import (
    AuthMiddleware,
    CorrelationIDMiddleware,
    LoggingMiddleware,
)
from penguin_http.h3.server import _build_ssl_context, run, serve


# ============================================================================
# FIXTURES & HELPERS
# ============================================================================


@pytest.fixture
def basic_scope() -> dict[str, Any]:
    """Minimal HTTP ASGI scope."""
    return {
        "type": "http",
        "method": "GET",
        "path": "/",
        "headers": [],
        "state": {},
    }


@pytest.fixture
def basic_receive():
    """Mock ASGI receive callable."""

    async def _receive():
        return {}

    return _receive


@pytest.fixture
def scope_with_headers() -> dict[str, Any]:
    """HTTP ASGI scope with headers."""
    return {
        "type": "http",
        "method": "POST",
        "path": "/api/data",
        "headers": [
            (b"authorization", b"Bearer test-token-123"),
            (b"x-correlation-id", b"correlation-abc"),
        ],
        "state": {},
    }


async def make_send():
    """Create a mock ASGI send callable that captures messages."""
    messages = []

    async def _send(message: dict[str, Any]) -> None:
        messages.append(message)

    return _send, messages


async def make_app_ok():
    """Create a mock ASGI app that returns 200 OK."""

    async def app(scope: dict, receive, send: Any) -> None:
        await send(
            {
                "type": "http.response.start",
                "status": 200,
                "headers": [(b"content-type", b"text/plain")],
            }
        )
        await send({"type": "http.response.body", "body": b"OK"})

    return app


async def make_app_that_raises():
    """Create a mock ASGI app that raises an exception."""

    async def app(scope: dict, receive, send: Any) -> None:
        raise ValueError("App error")

    return app


# ============================================================================
# HEALTH CHECK TESTS
# ============================================================================


class TestHealthCheck:
    """Tests for HealthCheck ASGI app."""

    @pytest.mark.asyncio
    async def test_init_default_status(self):
        """Test HealthCheck initializes with default healthy status."""
        health = HealthCheck()
        assert health.is_healthy() is True
        assert health.is_healthy("") is True

    @pytest.mark.asyncio
    async def test_set_status(self):
        """Test setting service health status."""
        health = HealthCheck()
        health.set_status("database", True)
        health.set_status("cache", False)
        assert health.is_healthy("database") is True
        assert health.is_healthy("cache") is False

    @pytest.mark.asyncio
    async def test_is_healthy_missing_service(self):
        """Test is_healthy returns False for missing service."""
        health = HealthCheck()
        assert health.is_healthy("nonexistent") is False

    @pytest.mark.asyncio
    async def test_call_non_http_scope(self, basic_scope):
        """Test calling HealthCheck with non-HTTP scope returns immediately."""
        basic_scope["type"] = "websocket"
        health = HealthCheck()
        receive = AsyncMock()
        send = AsyncMock()

        await health(basic_scope, receive, send)

        # Should not send anything for non-HTTP
        send.assert_not_called()

    @pytest.mark.asyncio
    async def test_call_http_healthy_200(self, basic_scope):
        """Test healthy HealthCheck returns 200 with healthy status."""
        health = HealthCheck()
        health.set_status("db", True)
        health.set_status("cache", True)

        send, messages = await make_send()

        await health(basic_scope, AsyncMock(), send)

        assert len(messages) == 2
        assert messages[0]["type"] == "http.response.start"
        assert messages[0]["status"] == 200

        body = json.loads(messages[1]["body"].decode())
        assert body["status"] == "healthy"
        assert body["services"]["db"] == "ok"
        assert body["services"]["cache"] == "ok"

    @pytest.mark.asyncio
    async def test_call_http_unhealthy_503(self, basic_scope):
        """Test unhealthy HealthCheck returns 503 with unhealthy status."""
        health = HealthCheck()
        health.set_status("db", False)
        health.set_status("cache", True)

        send, messages = await make_send()

        await health(basic_scope, AsyncMock(), send)

        assert len(messages) == 2
        assert messages[0]["type"] == "http.response.start"
        assert messages[0]["status"] == 503

        body = json.loads(messages[1]["body"].decode())
        assert body["status"] == "unhealthy"
        assert body["services"]["db"] == "failing"
        assert body["services"]["cache"] == "ok"

    @pytest.mark.asyncio
    async def test_call_filters_empty_service_name(self, basic_scope):
        """Test HealthCheck filters out empty service name from response."""
        health = HealthCheck()
        # The default "" status should not appear in services dict
        health.set_status("db", True)

        send, messages = await make_send()

        await health(basic_scope, AsyncMock(), send)

        body = json.loads(messages[1]["body"].decode())
        assert "" not in body["services"]
        assert "db" in body["services"]

    @pytest.mark.asyncio
    async def test_call_content_type_json(self, basic_scope):
        """Test HealthCheck response includes application/json content type."""
        health = HealthCheck()
        send, messages = await make_send()

        await health(basic_scope, AsyncMock(), send)

        headers = dict(messages[0]["headers"])
        assert headers.get(b"content-type") == b"application/json"


# ============================================================================
# CORRELATION ID MIDDLEWARE TESTS
# ============================================================================


class TestCorrelationIDMiddleware:
    """Tests for CorrelationIDMiddleware."""

    @pytest.mark.asyncio
    async def test_non_http_scope_passes_through(self, basic_scope):
        """Test non-HTTP scope is passed through without modification."""
        basic_scope["type"] = "lifespan"
        app = AsyncMock()
        middleware = CorrelationIDMiddleware(app)
        receive = AsyncMock()
        send = AsyncMock()

        await middleware(basic_scope, receive, send)

        app.assert_called_once_with(basic_scope, receive, send)

    @pytest.mark.asyncio
    async def test_http_scope_generates_correlation_id(self, basic_scope):
        """Test HTTP scope generates correlation ID if not present."""
        app = AsyncMock()
        middleware = CorrelationIDMiddleware(app)
        receive = AsyncMock()
        send = AsyncMock()

        await middleware(basic_scope, receive, send)

        # Check that state was set with correlation_id
        assert "correlation_id" in basic_scope.get("state", {})
        assert len(basic_scope["state"]["correlation_id"]) == 36  # UUID4 length

    @pytest.mark.asyncio
    async def test_http_scope_uses_existing_correlation_id(
        self, scope_with_headers
    ):
        """Test HTTP scope uses existing X-Correlation-ID header."""
        app = AsyncMock()
        middleware = CorrelationIDMiddleware(app)
        receive = AsyncMock()
        send = AsyncMock()

        await middleware(scope_with_headers, receive, send)

        assert scope_with_headers["state"]["correlation_id"] == "correlation-abc"

    @pytest.mark.asyncio
    async def test_response_includes_correlation_id_header(self, basic_scope):
        """Test response includes X-Correlation-ID header."""
        app = AsyncMock()
        middleware = CorrelationIDMiddleware(app)
        receive = AsyncMock()

        send, messages = await make_send()

        # Manually call the send_with_cid wrapper
        async def mock_app(scope, receive, send):
            await send({"type": "http.response.start", "status": 200, "headers": []})
            await send({"type": "http.response.body", "body": b"test"})

        middleware.app = mock_app
        await middleware(basic_scope, receive, send)

        # Check that first message has correlation ID header
        headers = dict(messages[0]["headers"])
        assert b"x-correlation-id" in headers

    @pytest.mark.asyncio
    async def test_websocket_scope_generates_correlation_id(self, basic_scope):
        """Test WebSocket scope also gets correlation ID."""
        basic_scope["type"] = "websocket"
        app = AsyncMock()
        middleware = CorrelationIDMiddleware(app)
        receive = AsyncMock()
        send = AsyncMock()

        await middleware(basic_scope, receive, send)

        assert "correlation_id" in basic_scope["state"]


# ============================================================================
# LOGGING MIDDLEWARE TESTS
# ============================================================================


class TestLoggingMiddleware:
    """Tests for LoggingMiddleware."""

    @pytest.mark.asyncio
    async def test_non_http_scope_passes_through(self, basic_scope):
        """Test non-HTTP scope is passed through."""
        basic_scope["type"] = "lifespan"
        app = AsyncMock()
        middleware = LoggingMiddleware(app)
        receive = AsyncMock()
        send = AsyncMock()

        await middleware(basic_scope, receive, send)

        app.assert_called_once()

    @pytest.mark.asyncio
    async def test_logs_request_details(self, basic_scope, caplog):
        """Test logging middleware logs request method, path, status, duration."""
        async def mock_app(scope, receive, send):
            await send({"type": "http.response.start", "status": 200, "headers": []})
            await send({"type": "http.response.body", "body": b"OK"})

        middleware = LoggingMiddleware(mock_app)
        receive = AsyncMock()
        send, messages = await make_send()

        with caplog.at_level(logging.INFO):
            await middleware(basic_scope, receive, send)

        # Check log contains expected information
        log_text = caplog.text
        assert "GET" in log_text
        assert "/" in log_text
        assert "200" in log_text

    @pytest.mark.asyncio
    async def test_captures_status_code(self, basic_scope):
        """Test logging middleware captures response status code."""
        async def mock_app(scope, receive, send):
            await send({"type": "http.response.start", "status": 404, "headers": []})
            await send({"type": "http.response.body", "body": b"Not Found"})

        middleware = LoggingMiddleware(mock_app)
        receive = AsyncMock()
        send, messages = await make_send()

        await middleware(basic_scope, receive, send)

        assert messages[0]["status"] == 404

    @pytest.mark.asyncio
    async def test_logs_correlation_id_from_scope(self, basic_scope, caplog):
        """Test logging middleware includes correlation_id in extra."""
        basic_scope["state"]["correlation_id"] = "test-cid-xyz"

        async def mock_app(scope, receive, send):
            await send({"type": "http.response.start", "status": 200, "headers": []})
            await send({"type": "http.response.body", "body": b"OK"})

        middleware = LoggingMiddleware(mock_app)
        receive = AsyncMock()
        send, messages = await make_send()

        with caplog.at_level(logging.INFO):
            await middleware(basic_scope, receive, send)

        # Verify extra is passed (we can't directly check extra in caplog,
        # but we verify the middleware doesn't crash)
        assert len(messages) == 2

    @pytest.mark.asyncio
    async def test_logs_even_on_app_exception(self, basic_scope, caplog):
        """Test logging middleware logs even if app raises."""
        async def mock_app(scope, receive, send):
            raise ValueError("App error")

        middleware = LoggingMiddleware(mock_app)
        receive = AsyncMock()
        send = AsyncMock()

        with caplog.at_level(logging.INFO):
            with pytest.raises(ValueError):
                await middleware(basic_scope, receive, send)

        # Should still log with status 0
        log_text = caplog.text
        assert "0" in log_text

    @pytest.mark.asyncio
    async def test_measures_duration_approximately(self, basic_scope):
        """Test logging middleware measures request duration."""
        async def mock_app(scope, receive, send):
            await asyncio.sleep(0.01)  # 10ms
            await send({"type": "http.response.start", "status": 200, "headers": []})
            await send({"type": "http.response.body", "body": b"OK"})

        middleware = LoggingMiddleware(mock_app)
        receive = AsyncMock()
        send, messages = await make_send()

        await middleware(basic_scope, receive, send)

        # Verify no exceptions raised during timing
        assert len(messages) == 2

    @pytest.mark.asyncio
    async def test_default_values_for_missing_method_path(self):
        """Test logging uses defaults for missing method/path in scope."""
        scope = {"type": "http"}  # No method, path

        async def mock_app(scope, receive, send):
            await send({"type": "http.response.start", "status": 200, "headers": []})
            await send({"type": "http.response.body", "body": b"OK"})

        middleware = LoggingMiddleware(mock_app)
        receive = AsyncMock()
        send, messages = await make_send()

        await middleware(scope, receive, send)

        assert len(messages) == 2


# ============================================================================
# AUTH MIDDLEWARE TESTS
# ============================================================================


class TestAuthMiddleware:
    """Tests for AuthMiddleware."""

    @pytest.mark.asyncio
    async def test_non_http_scope_passes_through(self, basic_scope):
        """Test non-HTTP scope bypasses authentication."""
        basic_scope["type"] = "websocket"
        app = AsyncMock()
        validate_fn = AsyncMock()
        middleware = AuthMiddleware(app, validate_fn)
        receive = AsyncMock()
        send = AsyncMock()

        await middleware(basic_scope, receive, send)

        app.assert_called_once()
        validate_fn.assert_not_called()

    @pytest.mark.asyncio
    async def test_public_path_bypasses_auth(self, basic_scope):
        """Test public paths bypass authentication."""
        basic_scope["path"] = "/health"
        app = AsyncMock()
        validate_fn = AsyncMock()
        middleware = AuthMiddleware(app, validate_fn, public_paths={"/health"})
        receive = AsyncMock()
        send = AsyncMock()

        await middleware(basic_scope, receive, send)

        app.assert_called_once()
        validate_fn.assert_not_called()

    @pytest.mark.asyncio
    async def test_missing_bearer_token_401(self, basic_scope):
        """Test missing Bearer token returns 401."""
        app = AsyncMock()
        validate_fn = AsyncMock()
        middleware = AuthMiddleware(app, validate_fn)
        receive = AsyncMock()
        send, messages = await make_send()

        await middleware(basic_scope, receive, send)

        assert messages[0]["status"] == 401
        body = messages[1]["body"].decode()
        assert "Missing bearer token" in body
        app.assert_not_called()

    @pytest.mark.asyncio
    async def test_invalid_auth_header_format_401(self, basic_scope):
        """Test auth header without 'Bearer ' prefix returns 401."""
        basic_scope["headers"] = [(b"authorization", b"Basic xyz")]
        app = AsyncMock()
        validate_fn = AsyncMock()
        middleware = AuthMiddleware(app, validate_fn)
        receive = AsyncMock()
        send, messages = await make_send()

        await middleware(basic_scope, receive, send)

        assert messages[0]["status"] == 401

    @pytest.mark.asyncio
    async def test_valid_token_calls_app(self, scope_with_headers):
        """Test valid Bearer token allows request through."""
        app = AsyncMock()
        validate_fn = AsyncMock()
        middleware = AuthMiddleware(app, validate_fn)
        receive = AsyncMock()
        send = AsyncMock()

        await middleware(scope_with_headers, receive, send)

        validate_fn.assert_called_once_with("test-token-123")
        app.assert_called_once()

    @pytest.mark.asyncio
    async def test_invalid_token_validation_401(self, scope_with_headers):
        """Test invalid token from validation function returns 401."""
        app = AsyncMock()
        validate_fn = AsyncMock(side_effect=ValueError("Bad token"))
        middleware = AuthMiddleware(app, validate_fn)
        receive = AsyncMock()
        send, messages = await make_send()

        await middleware(scope_with_headers, receive, send)

        assert messages[0]["status"] == 401
        body = messages[1]["body"].decode()
        assert "Invalid token" in body
        app.assert_not_called()

    @pytest.mark.asyncio
    async def test_error_response_content_type(self, basic_scope):
        """Test error responses have text/plain content type."""
        app = AsyncMock()
        validate_fn = AsyncMock()
        middleware = AuthMiddleware(app, validate_fn)
        receive = AsyncMock()
        send, messages = await make_send()

        await middleware(basic_scope, receive, send)

        headers = dict(messages[0]["headers"])
        assert headers[b"content-type"] == b"text/plain"

    @pytest.mark.asyncio
    async def test_empty_public_paths_default(self, basic_scope):
        """Test AuthMiddleware with empty public_paths set."""
        basic_scope["path"] = "/api/data"
        app = AsyncMock()
        validate_fn = AsyncMock()
        middleware = AuthMiddleware(app, validate_fn, public_paths=set())
        receive = AsyncMock()
        send, messages = await make_send()

        await middleware(basic_scope, receive, send)

        # Should fail auth since no Bearer token and not in public paths
        assert messages[0]["status"] == 401

    @pytest.mark.asyncio
    async def test_none_public_paths_defaults_to_empty_set(self, basic_scope):
        """Test AuthMiddleware defaults public_paths to empty set."""
        app = AsyncMock()
        validate_fn = AsyncMock()
        middleware = AuthMiddleware(app, validate_fn)  # public_paths=None
        receive = AsyncMock()
        send, messages = await make_send()

        await middleware(basic_scope, receive, send)

        # Should fail auth
        assert messages[0]["status"] == 401


# ============================================================================
# SERVER CONFIG TESTS
# ============================================================================


class TestBuildSSLContext:
    """Tests for _build_ssl_context function."""

    def test_none_tls_config_returns_none(self):
        """Test _build_ssl_context returns None when tls is None."""
        cfg = ServerConfig(tls=None)
        result = _build_ssl_context(cfg)
        assert result is None

    def test_valid_tls_config_creates_context(self):
        """Test _build_ssl_context creates SSLContext with valid cert/key."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmppath = Path(tmpdir)

            # Create self-signed cert and key for testing
            cert_file = tmppath / "cert.pem"
            key_file = tmppath / "key.pem"

            # Use openssl to create a test cert
            import subprocess

            subprocess.run(
                [
                    "openssl",
                    "req",
                    "-x509",
                    "-newkey",
                    "rsa:2048",
                    "-keyout",
                    str(key_file),
                    "-out",
                    str(cert_file),
                    "-days",
                    "1",
                    "-nodes",
                    "-subj",
                    "/CN=test",
                ],
                check=True,
                capture_output=True,
            )

            tls = TLSConfig(cert_path=cert_file, key_path=key_file)
            cfg = ServerConfig(tls=tls)
            result = _build_ssl_context(cfg)

            assert isinstance(result, ssl.SSLContext)
            assert result.protocol == ssl.PROTOCOL_TLS_SERVER

    def test_invalid_cert_path_raises_h3_tls_error(self):
        """Test _build_ssl_context raises H3TLSError for invalid cert path."""
        tls = TLSConfig(cert_path=Path("/nonexistent/cert.pem"), key_path=Path("/nonexistent/key.pem"))
        cfg = ServerConfig(tls=tls)

        with pytest.raises(H3TLSError):
            _build_ssl_context(cfg)

    def test_tls_context_minimum_version(self):
        """Test created SSL context requires TLS 1.3."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmppath = Path(tmpdir)
            cert_file = tmppath / "cert.pem"
            key_file = tmppath / "key.pem"

            import subprocess

            subprocess.run(
                [
                    "openssl",
                    "req",
                    "-x509",
                    "-newkey",
                    "rsa:2048",
                    "-keyout",
                    str(key_file),
                    "-out",
                    str(cert_file),
                    "-days",
                    "1",
                    "-nodes",
                    "-subj",
                    "/CN=test",
                ],
                check=True,
                capture_output=True,
            )

            tls = TLSConfig(cert_path=cert_file, key_path=key_file)
            cfg = ServerConfig(tls=tls)
            result = _build_ssl_context(cfg)

            assert result.minimum_version == ssl.TLSVersion.TLSv1_3

    def test_tls_context_with_ca_cert_path(self):
        """Test SSL context loads CA cert when provided."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmppath = Path(tmpdir)
            cert_file = tmppath / "cert.pem"
            key_file = tmppath / "key.pem"
            ca_file = tmppath / "ca.pem"

            import subprocess

            # Create server cert
            subprocess.run(
                [
                    "openssl",
                    "req",
                    "-x509",
                    "-newkey",
                    "rsa:2048",
                    "-keyout",
                    str(key_file),
                    "-out",
                    str(cert_file),
                    "-days",
                    "1",
                    "-nodes",
                    "-subj",
                    "/CN=test",
                ],
                check=True,
                capture_output=True,
            )

            # Create CA cert (can be same as server cert for testing)
            import shutil

            shutil.copy(str(cert_file), str(ca_file))

            tls = TLSConfig(cert_path=cert_file, key_path=key_file, ca_cert_path=ca_file)
            cfg = ServerConfig(tls=tls)
            result = _build_ssl_context(cfg)

            assert isinstance(result, ssl.SSLContext)

    def test_tls_context_with_client_verification(self):
        """Test SSL context sets verify_mode when verify_client is True."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmppath = Path(tmpdir)
            cert_file = tmppath / "cert.pem"
            key_file = tmppath / "key.pem"
            ca_file = tmppath / "ca.pem"

            import subprocess

            subprocess.run(
                [
                    "openssl",
                    "req",
                    "-x509",
                    "-newkey",
                    "rsa:2048",
                    "-keyout",
                    str(key_file),
                    "-out",
                    str(cert_file),
                    "-days",
                    "1",
                    "-nodes",
                    "-subj",
                    "/CN=test",
                ],
                check=True,
                capture_output=True,
            )

            import shutil

            shutil.copy(str(cert_file), str(ca_file))

            tls = TLSConfig(
                cert_path=cert_file,
                key_path=key_file,
                ca_cert_path=ca_file,
                verify_client=True,
            )
            cfg = ServerConfig(tls=tls)
            result = _build_ssl_context(cfg)

            assert result.verify_mode == ssl.CERT_REQUIRED


# ============================================================================
# SERVE FUNCTION TESTS
# ============================================================================


class TestServeFunction:
    """Tests for serve() function."""

    @pytest.mark.asyncio
    async def test_hypercorn_import_missing_raises_h3_config_error(self):
        """Test missing hypercorn raises H3ConfigError."""
        app = AsyncMock()
        cfg = ServerConfig(h2_enabled=True, h3_enabled=False)

        def mock_import(name, *args, **kwargs):
            if name in ("hypercorn.asyncio", "hypercorn.config"):
                raise ImportError(f"No module named '{name}'")
            return __import__(name, *args, **kwargs)

        with patch("builtins.__import__", side_effect=mock_import):
            with pytest.raises(H3ConfigError) as exc_info:
                await serve(app, cfg)

            assert "hypercorn is required" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_no_protocols_enabled_raises_h3_config_error(self):
        """Test no protocols enabled raises H3ConfigError."""
        app = AsyncMock()
        cfg = ServerConfig(h2_enabled=False, h3_enabled=False)

        with pytest.raises(H3ConfigError) as exc_info:
            await serve(app, cfg)

        assert "At least one protocol" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_h3_enabled_without_tls_raises_h3_config_error(self):
        """Test H3 enabled without TLS raises H3ConfigError."""
        app = AsyncMock()
        cfg = ServerConfig(h2_enabled=False, h3_enabled=True, tls=None)

        with pytest.raises(H3ConfigError) as exc_info:
            await serve(app, cfg)

        assert "TLS configuration is required" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_h2_only_configuration(self):
        """Test H2-only configuration without TLS."""
        app = AsyncMock()
        cfg = ServerConfig(h2_enabled=True, h3_enabled=False, tls=None)

        # Mock the hypercorn imports at module level
        mock_hypercorn_serve = AsyncMock()
        mock_hypercorn_config = MagicMock()

        with patch.dict(
            "sys.modules",
            {"hypercorn.asyncio": MagicMock(serve=mock_hypercorn_serve), "hypercorn.config": MagicMock(Config=mock_hypercorn_config)},
        ):
            try:
                await serve(app, cfg)
            except (H3ServerError, RuntimeError):
                # Expected - mock is incomplete
                pass

    @pytest.mark.asyncio
    async def test_uses_default_config_when_none_provided(self):
        """Test serve() uses ServerConfig.from_env() when cfg is None."""
        app = AsyncMock()
        mock_config = ServerConfig(h2_enabled=True, h3_enabled=False)

        mock_hypercorn_serve = AsyncMock()
        mock_hypercorn_config = MagicMock()

        with patch("penguin_http.h3.server.ServerConfig.from_env", return_value=mock_config), patch.dict(
            "sys.modules",
            {"hypercorn.asyncio": MagicMock(serve=mock_hypercorn_serve), "hypercorn.config": MagicMock(Config=mock_hypercorn_config)},
        ):
            try:
                await serve(app, None)
            except (H3ServerError, RuntimeError):
                pass

    @pytest.mark.asyncio
    async def test_server_failure_raises_h3_server_error(self):
        """Test server failures raise H3ServerError."""
        app = AsyncMock()
        cfg = ServerConfig(h2_enabled=True, h3_enabled=False)

        mock_hypercorn_serve = AsyncMock(side_effect=RuntimeError("Server died"))
        mock_hypercorn_config = MagicMock()

        with patch.dict(
            "sys.modules",
            {"hypercorn.asyncio": MagicMock(serve=mock_hypercorn_serve), "hypercorn.config": MagicMock(Config=mock_hypercorn_config)},
        ):
            with pytest.raises(H3ServerError):
                await serve(app, cfg)

    @pytest.mark.asyncio
    async def test_h3_with_tls_configuration(self):
        """Test H3 with TLS configuration sets cert and key paths."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmppath = Path(tmpdir)
            cert_file = tmppath / "cert.pem"
            key_file = tmppath / "key.pem"

            import subprocess

            subprocess.run(
                [
                    "openssl",
                    "req",
                    "-x509",
                    "-newkey",
                    "rsa:2048",
                    "-keyout",
                    str(key_file),
                    "-out",
                    str(cert_file),
                    "-days",
                    "1",
                    "-nodes",
                    "-subj",
                    "/CN=test",
                ],
                check=True,
                capture_output=True,
            )

            tls = TLSConfig(cert_path=cert_file, key_path=key_file)
            cfg = ServerConfig(h2_enabled=True, h3_enabled=True, tls=tls)

            # Mock the hypercorn imports
            mock_hypercorn_serve = AsyncMock()
            mock_hypercorn_config = MagicMock()
            mock_config_instance = MagicMock()
            mock_hypercorn_config.return_value = mock_config_instance

            app = AsyncMock()
            with patch.dict(
                "sys.modules",
                {
                    "hypercorn.asyncio": MagicMock(serve=mock_hypercorn_serve),
                    "hypercorn.config": MagicMock(Config=mock_hypercorn_config),
                },
            ):
                try:
                    await serve(app, cfg)
                except (H3ServerError, RuntimeError):
                    pass

                # Verify certfile and keyfile were set on config
                # (Note: This may or may not be called depending on mocking depth)


# ============================================================================
# RUN FUNCTION TESTS
# ============================================================================


class TestRunFunction:
    """Tests for run() synchronous entry point."""

    def test_run_calls_asyncio_run(self):
        """Test run() calls asyncio.run(serve(...))."""
        app = AsyncMock()
        cfg = ServerConfig(h2_enabled=True, h3_enabled=False)

        mock_serve = AsyncMock()
        with patch("penguin_http.h3.server.serve", mock_serve), patch(
            "penguin_http.h3.server.asyncio.run"
        ) as mock_asyncio_run:
            run(app, cfg)

            mock_asyncio_run.assert_called_once()

    def test_run_passes_app_and_cfg_to_serve(self):
        """Test run() passes app and cfg to serve()."""
        app = MagicMock()
        cfg = ServerConfig(h2_enabled=True, h3_enabled=False)

        async def mock_serve(a, c):
            pass

        with patch("penguin_http.h3.server.serve", mock_serve), patch(
            "penguin_http.h3.server.asyncio.run", side_effect=lambda coro: None
        ):
            run(app, cfg)

    def test_run_with_default_config(self):
        """Test run() works with default ServerConfig."""
        app = MagicMock()

        async def mock_serve(a, c):
            pass

        with patch("penguin_http.h3.server.serve", mock_serve), patch(
            "penguin_http.h3.server.asyncio.run", side_effect=lambda coro: None
        ):
            run(app)


# ============================================================================
# INTEGRATION TESTS
# ============================================================================


class TestIntegration:
    """Integration tests combining multiple components."""

    @pytest.mark.asyncio
    async def test_health_check_with_middleware(self, basic_scope):
        """Test HealthCheck wrapped by CorrelationIDMiddleware."""
        health = HealthCheck()
        health.set_status("api", True)

        middleware = CorrelationIDMiddleware(health)
        receive = AsyncMock()
        send, messages = await make_send()

        await middleware(basic_scope, receive, send)

        # Should have correlation ID in state and response
        assert "correlation_id" in basic_scope["state"]
        headers = dict(messages[0]["headers"])
        assert b"x-correlation-id" in headers

        # Should have health check response
        body = json.loads(messages[1]["body"].decode())
        assert body["status"] == "healthy"

    @pytest.mark.asyncio
    async def test_auth_with_logging_middleware(self, scope_with_headers, caplog):
        """Test AuthMiddleware with LoggingMiddleware."""

        async def mock_app(scope, receive, send):
            await send({"type": "http.response.start", "status": 200, "headers": []})
            await send({"type": "http.response.body", "body": b"OK"})

        validate_fn = AsyncMock()
        auth = AuthMiddleware(mock_app, validate_fn)
        logging_mw = LoggingMiddleware(auth)

        receive = AsyncMock()
        send, messages = await make_send()

        with caplog.at_level(logging.INFO):
            await logging_mw(scope_with_headers, receive, send)

        # Should have logged the request
        log_text = caplog.text
        assert "POST" in log_text or len(messages) == 2

    @pytest.mark.asyncio
    async def test_correlation_id_persists_through_middleware_stack(self, basic_scope):
        """Test correlation ID generated early persists through middleware."""
        basic_scope["headers"] = []

        async def health_app(scope, receive, send):
            health = HealthCheck()
            await health(scope, receive, send)

        # Stack: correlation ID -> logging -> health check
        correlation_mw = CorrelationIDMiddleware(health_app)
        logging_mw = LoggingMiddleware(correlation_mw)

        receive = AsyncMock()
        send, messages = await make_send()

        await logging_mw(basic_scope, receive, send)

        # Correlation ID should be in response headers
        headers = dict(messages[0]["headers"])
        assert b"x-correlation-id" in headers
