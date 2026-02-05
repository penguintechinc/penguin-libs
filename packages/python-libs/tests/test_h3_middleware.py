"""Tests for penguin_libs.h3.middleware module."""

import logging
import uuid
from unittest.mock import AsyncMock

import pytest

from penguin_libs.h3.middleware import (
    AuthMiddleware,
    CorrelationIDMiddleware,
    LoggingMiddleware,
)


async def mock_app(scope, receive, send):
    """Mock ASGI application."""
    await send({
        "type": "http.response.start",
        "status": 200,
        "headers": []
    })
    await send({
        "type": "http.response.body",
        "body": b"ok"
    })


@pytest.mark.asyncio
async def test_correlation_id_generated():
    """Test that middleware generates correlation ID if not provided."""
    middleware = CorrelationIDMiddleware(mock_app)
    scope = {
        "type": "http",
        "headers": [],
        "state": {}
    }
    messages = []

    async def receive():
        return {}

    async def send(msg):
        messages.append(msg)

    await middleware(scope, receive, send)

    # Check that correlation_id was added to scope state
    assert "correlation_id" in scope["state"]
    correlation_id = scope["state"]["correlation_id"]

    # Should be a valid UUID
    try:
        uuid.UUID(correlation_id)
    except ValueError:
        pytest.fail("Generated correlation_id is not a valid UUID")


@pytest.mark.asyncio
async def test_correlation_id_propagated():
    """Test that provided correlation ID is propagated."""
    middleware = CorrelationIDMiddleware(mock_app)
    test_id = "test-correlation-id-123"
    scope = {
        "type": "http",
        "headers": [(b"x-correlation-id", test_id.encode())],
        "state": {}
    }
    messages = []

    async def receive():
        return {}

    async def send(msg):
        messages.append(msg)

    await middleware(scope, receive, send)

    # Check that provided ID was used
    assert scope["state"]["correlation_id"] == test_id

    # Check response headers contain correlation ID
    response_start = messages[0]
    headers = dict(response_start.get("headers", []))
    assert headers.get(b"x-correlation-id") == test_id.encode()


@pytest.mark.asyncio
async def test_logging_captures_status(caplog):
    """Test that LoggingMiddleware logs request status."""
    middleware = LoggingMiddleware(mock_app)
    scope = {
        "type": "http",
        "method": "GET",
        "path": "/test",
        "state": {}
    }

    async def receive():
        return {}

    messages = []

    async def send(msg):
        messages.append(msg)

    with caplog.at_level(logging.INFO, logger="penguin_libs.h3.middleware"):
        await middleware(scope, receive, send)

    # Check that status was logged
    assert any("200" in record.message for record in caplog.records)


@pytest.mark.asyncio
async def test_auth_blocks_missing_token():
    """Test that AuthMiddleware blocks requests without Authorization header."""
    async def validate_fn(token):
        return {"user_id": "123"}

    middleware = AuthMiddleware(mock_app, validate_fn)
    scope = {
        "type": "http",
        "headers": [],
        "state": {}
    }
    messages = []

    async def receive():
        return {}

    async def send(msg):
        messages.append(msg)

    await middleware(scope, receive, send)

    # Should return 401
    assert messages[0]["status"] == 401


@pytest.mark.asyncio
async def test_auth_blocks_invalid_token():
    """Test that AuthMiddleware blocks requests with invalid tokens."""
    async def validate_fn(token):
        raise ValueError("Invalid token")

    middleware = AuthMiddleware(mock_app, validate_fn)
    scope = {
        "type": "http",
        "headers": [(b"authorization", b"Bearer invalid-token")],
        "state": {}
    }
    messages = []

    async def receive():
        return {}

    async def send(msg):
        messages.append(msg)

    await middleware(scope, receive, send)

    # Should return 401
    assert messages[0]["status"] == 401


@pytest.mark.asyncio
async def test_auth_allows_valid_token():
    """Test that AuthMiddleware allows requests with valid tokens."""
    async def validate_fn(token):
        return {"user_id": "123"}

    inner_app_called = False

    async def inner_app(scope, receive, send):
        nonlocal inner_app_called
        inner_app_called = True
        await send({
            "type": "http.response.start",
            "status": 200,
            "headers": []
        })
        await send({
            "type": "http.response.body",
            "body": b"ok"
        })

    middleware = AuthMiddleware(inner_app, validate_fn)
    scope = {
        "type": "http",
        "headers": [(b"authorization", b"Bearer valid-token")],
        "state": {}
    }
    messages = []

    async def receive():
        return {}

    async def send(msg):
        messages.append(msg)

    await middleware(scope, receive, send)

    # Inner app should have been called
    assert inner_app_called
    # Should have returned 200 from inner app
    assert messages[0]["status"] == 200


@pytest.mark.asyncio
async def test_auth_public_path_bypass():
    """Test that AuthMiddleware bypasses auth for public paths."""
    async def validate_fn(token):
        raise ValueError("Should not be called")

    inner_app_called = False

    async def inner_app(scope, receive, send):
        nonlocal inner_app_called
        inner_app_called = True
        await send({
            "type": "http.response.start",
            "status": 200,
            "headers": []
        })
        await send({
            "type": "http.response.body",
            "body": b"ok"
        })

    middleware = AuthMiddleware(
        inner_app,
        validate_fn,
        public_paths={"/health", "/public"}
    )
    scope = {
        "type": "http",
        "path": "/health",
        "headers": [],
        "state": {}
    }

    async def receive():
        return {}

    async def send(msg):
        pass

    await middleware(scope, receive, send)

    # Inner app should have been called without auth
    assert inner_app_called
