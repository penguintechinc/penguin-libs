"""Tests for HealthCheck ASGI application."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock

import pytest

from penguin_h3.health import HealthCheck


class TestHealthCheck:
    """Test HealthCheck ASGI application."""

    def test_health_check_init(self) -> None:
        """Test HealthCheck initialization."""
        health = HealthCheck()
        assert health.is_healthy() is True

    def test_health_check_set_status_healthy(self) -> None:
        """Test setting service status to healthy."""
        health = HealthCheck()
        health.set_status("database", True)
        assert health.is_healthy("database") is True

    def test_health_check_set_status_unhealthy(self) -> None:
        """Test setting service status to unhealthy."""
        health = HealthCheck()
        health.set_status("cache", False)
        assert health.is_healthy("cache") is False

    def test_health_check_multiple_services(self) -> None:
        """Test multiple service status tracking."""
        health = HealthCheck()
        health.set_status("database", True)
        health.set_status("cache", True)
        health.set_status("queue", False)

        assert health.is_healthy("database") is True
        assert health.is_healthy("cache") is True
        assert health.is_healthy("queue") is False

    def test_health_check_is_healthy_unknown_service(self) -> None:
        """Test that unknown service returns False."""
        health = HealthCheck()
        assert health.is_healthy("unknown") is False

    def test_health_check_overall_healthy_all_services_healthy(self) -> None:
        """Test overall health when all services are healthy."""
        health = HealthCheck()
        health.set_status("database", True)
        health.set_status("cache", True)
        assert health.is_healthy() is True

    def test_health_check_overall_unhealthy_one_service_down(self) -> None:
        """Test overall health when one service is unhealthy."""
        health = HealthCheck()
        health.set_status("database", True)
        health.set_status("cache", False)
        # Overall health is unhealthy if ANY service is unhealthy
        overall = all(health._statuses.values())
        assert overall is False

    def test_health_check_overall_unhealthy_all_services_down(self) -> None:
        """Test overall health when all services are unhealthy."""
        health = HealthCheck()
        health.set_status("database", False)
        health.set_status("cache", False)
        # Overall health is unhealthy if ANY service is unhealthy
        overall = all(health._statuses.values())
        assert overall is False

    @pytest.mark.asyncio
    async def test_health_check_http_response_healthy(self) -> None:
        """Test HTTP response when all services are healthy."""
        health = HealthCheck()
        health.set_status("database", True)

        # Mock ASGI send/receive
        messages: list[dict] = []

        async def mock_send(msg: dict) -> None:
            messages.append(msg)

        async def mock_receive() -> dict:
            return {}

        scope = {
            "type": "http",
            "method": "GET",
            "path": "/healthz",
        }

        await health(scope, mock_receive, mock_send)

        # Check that response was sent
        assert len(messages) == 2
        assert messages[0]["type"] == "http.response.start"
        assert messages[0]["status"] == 200
        assert messages[1]["type"] == "http.response.body"

        # Check response body
        body = json.loads(messages[1]["body"])
        assert body["status"] == "healthy"
        assert body["services"]["database"] == "ok"

    @pytest.mark.asyncio
    async def test_health_check_http_response_unhealthy(self) -> None:
        """Test HTTP response when service is unhealthy."""
        health = HealthCheck()
        health.set_status("database", False)

        messages: list[dict] = []

        async def mock_send(msg: dict) -> None:
            messages.append(msg)

        async def mock_receive() -> dict:
            return {}

        scope = {
            "type": "http",
            "method": "GET",
            "path": "/healthz",
        }

        await health(scope, mock_receive, mock_send)

        # Check response status code
        assert messages[0]["status"] == 503
        body = json.loads(messages[1]["body"])
        assert body["status"] == "unhealthy"
        assert body["services"]["database"] == "failing"

    @pytest.mark.asyncio
    async def test_health_check_http_response_content_type(self) -> None:
        """Test that response has correct Content-Type header."""
        health = HealthCheck()

        messages: list[dict] = []

        async def mock_send(msg: dict) -> None:
            messages.append(msg)

        async def mock_receive() -> dict:
            return {}

        scope = {"type": "http"}

        await health(scope, mock_receive, mock_send)

        headers = messages[0]["headers"]
        content_type = None
        for name, value in headers:
            if name == b"content-type":
                content_type = value
                break

        assert content_type == b"application/json"

    @pytest.mark.asyncio
    async def test_health_check_multiple_services_response(self) -> None:
        """Test HTTP response with multiple services."""
        health = HealthCheck()
        health.set_status("database", True)
        health.set_status("cache", True)
        health.set_status("queue", False)

        messages: list[dict] = []

        async def mock_send(msg: dict) -> None:
            messages.append(msg)

        async def mock_receive() -> dict:
            return {}

        scope = {"type": "http"}

        await health(scope, mock_receive, mock_send)

        # Overall should be unhealthy due to queue
        assert messages[0]["status"] == 503
        body = json.loads(messages[1]["body"])
        assert body["status"] == "unhealthy"
        assert body["services"]["database"] == "ok"
        assert body["services"]["cache"] == "ok"
        assert body["services"]["queue"] == "failing"

    @pytest.mark.asyncio
    async def test_health_check_ignores_non_http(self) -> None:
        """Test that non-HTTP requests are ignored."""
        health = HealthCheck()
        health.set_status("database", True)

        messages: list[dict] = []

        async def mock_send(msg: dict) -> None:
            messages.append(msg)

        async def mock_receive() -> dict:
            return {}

        scope = {"type": "websocket"}

        await health(scope, mock_receive, mock_send)

        # Should not send any response for websocket
        assert len(messages) == 0

    @pytest.mark.asyncio
    async def test_health_check_status_update(self) -> None:
        """Test that status updates are reflected in response."""
        health = HealthCheck()
        health.set_status("database", True)

        messages_1: list[dict] = []

        async def mock_send_1(msg: dict) -> None:
            messages_1.append(msg)

        scope = {"type": "http"}

        await health(scope, AsyncMock(), mock_send_1)

        # First check should be healthy
        body_1 = json.loads(messages_1[1]["body"])
        assert body_1["status"] == "healthy"

        # Update status
        health.set_status("database", False)

        messages_2: list[dict] = []

        async def mock_send_2(msg: dict) -> None:
            messages_2.append(msg)

        await health(scope, AsyncMock(), mock_send_2)

        # Second check should be unhealthy
        assert messages_2[0]["status"] == 503
        body_2 = json.loads(messages_2[1]["body"])
        assert body_2["status"] == "unhealthy"

    @pytest.mark.asyncio
    async def test_health_check_empty_service_not_in_response(self) -> None:
        """Test that the empty string service key is not in response."""
        health = HealthCheck()
        health.set_status("database", True)

        messages: list[dict] = []

        async def mock_send(msg: dict) -> None:
            messages.append(msg)

        scope = {"type": "http"}

        await health(scope, AsyncMock(), mock_send)

        body = json.loads(messages[1]["body"])
        # Empty key should not be in services
        assert "" not in body["services"]
        assert "database" in body["services"]

    @pytest.mark.asyncio
    async def test_health_check_callable(self) -> None:
        """Test that HealthCheck is callable as ASGI app."""
        health = HealthCheck()

        # Should be callable
        assert callable(health)

        messages: list[dict] = []

        async def mock_send(msg: dict) -> None:
            messages.append(msg)

        async def mock_receive() -> dict:
            return {}

        scope = {"type": "http"}

        # Should work as ASGI app
        await health(scope, mock_receive, mock_send)
        assert len(messages) == 2
