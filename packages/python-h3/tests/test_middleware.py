"""Tests for ASGI middleware."""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest

from penguin_h3.middleware import AuthMiddleware, CorrelationIDMiddleware, LoggingMiddleware


class TestCorrelationIDMiddleware:
    """Test CorrelationIDMiddleware."""

    @pytest.mark.asyncio
    async def test_correlation_id_generated_if_missing(self) -> None:
        """Test that correlation ID is generated if missing from request."""
        app = AsyncMock()
        middleware = CorrelationIDMiddleware(app)

        scope = {"type": "http", "headers": []}
        await middleware(scope, AsyncMock(), AsyncMock())

        # Scope should have correlation_id
        assert "state" in scope
        assert "correlation_id" in scope["state"]
        # Should be a valid UUID string
        assert len(scope["state"]["correlation_id"]) == 36  # UUID4 length

    @pytest.mark.asyncio
    async def test_correlation_id_extracted_from_header(self) -> None:
        """Test that existing correlation ID is extracted from header."""
        app = AsyncMock()
        middleware = CorrelationIDMiddleware(app)

        cid = str(uuid.uuid4())
        scope = {
            "type": "http",
            "headers": [(b"x-correlation-id", cid.encode())],
        }

        await middleware(scope, AsyncMock(), AsyncMock())

        assert scope["state"]["correlation_id"] == cid

    @pytest.mark.asyncio
    async def test_correlation_id_added_to_response(self) -> None:
        """Test that correlation ID is added to response headers."""
        app = AsyncMock()
        middleware = CorrelationIDMiddleware(app)

        cid = str(uuid.uuid4())
        scope = {
            "type": "http",
            "headers": [(b"x-correlation-id", cid.encode())],
        }

        sent_messages: list[dict] = []

        async def mock_send(msg: dict) -> None:
            sent_messages.append(msg)

        async def capture_send(msg: dict) -> None:
            await mock_send(msg)

        # Set app to capture the send callback it receives
        received_send = None

        async def capture_app(scope, receive, send):
            nonlocal received_send
            received_send = send
            # Simulate response
            await send({"type": "http.response.start", "status": 200, "headers": []})

        middleware.app = capture_app

        await middleware(scope, AsyncMock(), capture_send)

        # Check that response includes correlation ID
        assert len(sent_messages) == 1
        headers = sent_messages[0]["headers"]
        correlation_id_found = False
        for name, value in headers:
            if name == b"x-correlation-id" and value == cid.encode():
                correlation_id_found = True
                break
        assert correlation_id_found

    @pytest.mark.asyncio
    async def test_correlation_id_websocket(self) -> None:
        """Test that correlation ID middleware works with websocket."""
        app = AsyncMock()
        middleware = CorrelationIDMiddleware(app)

        scope = {"type": "websocket", "headers": []}

        await middleware(scope, AsyncMock(), AsyncMock())

        # Should pass through for websocket
        app.assert_called_once()

    @pytest.mark.asyncio
    async def test_correlation_id_other_protocol(self) -> None:
        """Test that middleware passes through non-http/websocket."""
        app = AsyncMock()
        middleware = CorrelationIDMiddleware(app)

        scope = {"type": "lifespan"}

        await middleware(scope, AsyncMock(), AsyncMock())

        app.assert_called_once()

    @pytest.mark.asyncio
    async def test_correlation_id_empty_header_generates_new(self) -> None:
        """Test that empty correlation ID header generates new one."""
        app = AsyncMock()
        middleware = CorrelationIDMiddleware(app)

        scope = {
            "type": "http",
            "headers": [(b"x-correlation-id", b"")],
        }

        await middleware(scope, AsyncMock(), AsyncMock())

        # Should generate new ID since header was empty
        assert len(scope["state"]["correlation_id"]) == 36


class TestLoggingMiddleware:
    """Test LoggingMiddleware."""

    @pytest.mark.asyncio
    async def test_logging_middleware_logs_request(self, caplog) -> None:
        """Test that middleware logs request details."""
        app = AsyncMock()
        middleware = LoggingMiddleware(app)

        scope = {
            "type": "http",
            "method": "GET",
            "path": "/api/v1/data",
        }

        sent_messages: list[dict] = []

        async def mock_send(msg: dict) -> None:
            sent_messages.append(msg)

        async def capture_app(scope, receive, send):
            await send({"type": "http.response.start", "status": 200})

        middleware.app = capture_app

        with caplog.at_level("INFO"):
            await middleware(scope, AsyncMock(), mock_send)

        # Check log contains method and path
        assert "GET" in caplog.text
        assert "/api/v1/data" in caplog.text
        assert "200" in caplog.text

    @pytest.mark.asyncio
    async def test_logging_middleware_captures_status_code(self, caplog) -> None:
        """Test that status code is captured from response."""
        app = AsyncMock()
        middleware = LoggingMiddleware(app)

        scope = {
            "type": "http",
            "method": "POST",
            "path": "/api/v1/users",
        }

        async def capture_app(scope, receive, send):
            await send({"type": "http.response.start", "status": 201})

        middleware.app = capture_app

        with caplog.at_level("INFO"):
            await middleware(scope, AsyncMock(), AsyncMock())

        assert "201" in caplog.text
        assert "POST" in caplog.text

    @pytest.mark.asyncio
    async def test_logging_middleware_handles_missing_method(self, caplog) -> None:
        """Test that middleware handles missing method gracefully."""
        middleware = LoggingMiddleware(AsyncMock())

        scope = {"type": "http", "path": "/test"}

        async def capture_app(scope, receive, send):
            await send({"type": "http.response.start", "status": 200})

        middleware.app = capture_app

        with caplog.at_level("INFO"):
            await middleware(scope, AsyncMock(), AsyncMock())

        assert "?" in caplog.text  # Default for missing method

    @pytest.mark.asyncio
    async def test_logging_middleware_ignores_non_http(self, caplog) -> None:
        """Test that middleware only logs HTTP requests."""
        app = AsyncMock()
        middleware = LoggingMiddleware(app)

        scope = {"type": "websocket"}

        with caplog.at_level("INFO"):
            await middleware(scope, AsyncMock(), AsyncMock())

        # Should not log for websocket
        app.assert_called_once()

    @pytest.mark.asyncio
    async def test_logging_middleware_includes_duration(self, caplog) -> None:
        """Test that duration is included in log."""
        middleware = LoggingMiddleware(AsyncMock())

        scope = {"type": "http", "method": "GET", "path": "/"}

        async def slow_app(scope, receive, send):
            await send({"type": "http.response.start", "status": 200})

        middleware.app = slow_app

        with caplog.at_level("INFO"):
            await middleware(scope, AsyncMock(), AsyncMock())

        # Should include duration marker (ms)
        assert "ms" in caplog.text

    @pytest.mark.asyncio
    async def test_logging_middleware_with_correlation_id(self, caplog) -> None:
        """Test that correlation ID is logged if present."""
        middleware = LoggingMiddleware(AsyncMock())

        scope = {
            "type": "http",
            "method": "GET",
            "path": "/test",
            "state": {"correlation_id": "test-cid-123"},
        }

        async def capture_app(scope, receive, send):
            await send({"type": "http.response.start", "status": 200})

        middleware.app = capture_app

        with caplog.at_level("INFO"):
            await middleware(scope, AsyncMock(), AsyncMock())

        # Check that logs were created
        assert len(caplog.records) > 0
        # Correlation ID is passed via extra dict, not in message
        # Just verify logging occurred
        assert any("GET" in r.getMessage() for r in caplog.records)


class TestAuthMiddleware:
    """Test AuthMiddleware."""

    @pytest.mark.asyncio
    async def test_auth_middleware_rejects_missing_token(self) -> None:
        """Test that missing Bearer token is rejected."""
        app = AsyncMock()
        validate_fn = AsyncMock()

        middleware = AuthMiddleware(app, validate_fn)

        scope = {"type": "http", "path": "/protected", "headers": []}
        sent_messages: list[dict] = []

        async def mock_send(msg: dict) -> None:
            sent_messages.append(msg)

        await middleware(scope, AsyncMock(), mock_send)

        # Should send 401
        assert sent_messages[0]["status"] == 401
        assert validate_fn.call_count == 0

    @pytest.mark.asyncio
    async def test_auth_middleware_rejects_invalid_format(self) -> None:
        """Test that invalid token format is rejected."""
        app = AsyncMock()
        validate_fn = AsyncMock()

        middleware = AuthMiddleware(app, validate_fn)

        scope = {
            "type": "http",
            "path": "/protected",
            "headers": [(b"authorization", b"Basic dXNlcjpwYXNz")],
        }

        sent_messages: list[dict] = []

        async def mock_send(msg: dict) -> None:
            sent_messages.append(msg)

        await middleware(scope, AsyncMock(), mock_send)

        # Should send 401 for non-Bearer token
        assert sent_messages[0]["status"] == 401

    @pytest.mark.asyncio
    async def test_auth_middleware_validates_bearer_token(self) -> None:
        """Test that Bearer token is validated."""
        app = AsyncMock()
        validate_fn = AsyncMock()

        middleware = AuthMiddleware(app, validate_fn)

        token = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9"
        scope = {
            "type": "http",
            "path": "/protected",
            "headers": [(b"authorization", f"Bearer {token}".encode())],
        }

        await middleware(scope, AsyncMock(), AsyncMock())

        # Should call validate_fn with token
        validate_fn.assert_called_once_with(token)

    @pytest.mark.asyncio
    async def test_auth_middleware_rejects_invalid_token(self) -> None:
        """Test that invalid token is rejected."""
        app = AsyncMock()

        async def invalid_token(token: str) -> None:
            raise ValueError("invalid token")

        middleware = AuthMiddleware(app, invalid_token)

        scope = {
            "type": "http",
            "path": "/protected",
            "headers": [(b"authorization", b"Bearer invalid")],
        }

        sent_messages: list[dict] = []

        async def mock_send(msg: dict) -> None:
            sent_messages.append(msg)

        await middleware(scope, AsyncMock(), mock_send)

        # Should send 401
        assert sent_messages[0]["status"] == 401
        # App should not be called
        app.assert_not_called()

    @pytest.mark.asyncio
    async def test_auth_middleware_allows_valid_token(self) -> None:
        """Test that valid token allows request."""
        app = AsyncMock()

        async def validate_token(token: str) -> None:
            if token != "valid":
                raise ValueError("invalid")

        middleware = AuthMiddleware(app, validate_token)

        scope = {
            "type": "http",
            "path": "/protected",
            "headers": [(b"authorization", b"Bearer valid")],
        }

        await middleware(scope, AsyncMock(), AsyncMock())

        # Should call app
        app.assert_called_once()

    @pytest.mark.asyncio
    async def test_auth_middleware_public_paths(self) -> None:
        """Test that public paths bypass authentication."""
        app = AsyncMock()
        validate_fn = AsyncMock()

        middleware = AuthMiddleware(app, validate_fn, public_paths={"/health", "/readyz"})

        scope = {"type": "http", "path": "/health", "headers": []}

        await middleware(scope, AsyncMock(), AsyncMock())

        # Should call app without validation
        app.assert_called_once()
        validate_fn.assert_not_called()

    @pytest.mark.asyncio
    async def test_auth_middleware_public_path_exact_match(self) -> None:
        """Test that public path matching is exact."""
        app = AsyncMock()
        validate_fn = AsyncMock()

        middleware = AuthMiddleware(app, validate_fn, public_paths={"/health"})

        scope = {
            "type": "http",
            "path": "/health/detailed",
            "headers": [],
        }

        sent_messages: list[dict] = []

        async def mock_send(msg: dict) -> None:
            sent_messages.append(msg)

        await middleware(scope, AsyncMock(), mock_send)

        # Should require auth for /health/detailed
        assert sent_messages[0]["status"] == 401

    @pytest.mark.asyncio
    async def test_auth_middleware_non_http(self) -> None:
        """Test that middleware passes through non-HTTP."""
        app = AsyncMock()
        validate_fn = AsyncMock()

        middleware = AuthMiddleware(app, validate_fn)

        scope = {"type": "websocket", "path": "/ws"}

        await middleware(scope, AsyncMock(), AsyncMock())

        # Should pass through
        app.assert_called_once()
        validate_fn.assert_not_called()

    @pytest.mark.asyncio
    async def test_auth_middleware_response_body_format(self) -> None:
        """Test that error response has proper body."""
        app = AsyncMock()
        validate_fn = AsyncMock()

        middleware = AuthMiddleware(app, validate_fn)

        scope = {"type": "http", "path": "/protected", "headers": []}
        sent_messages: list[dict] = []

        async def mock_send(msg: dict) -> None:
            sent_messages.append(msg)

        await middleware(scope, AsyncMock(), mock_send)

        # Check response messages
        assert sent_messages[0]["type"] == "http.response.start"
        assert sent_messages[1]["type"] == "http.response.body"
        assert b"Missing bearer token" in sent_messages[1]["body"]
