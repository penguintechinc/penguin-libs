"""Tests for penguin_libs.h3.health module."""

import pytest

from penguin_libs.h3.health import HealthCheck


def test_health_check_initial_healthy():
    """Test that new HealthCheck starts as healthy."""
    health = HealthCheck()
    assert health.is_healthy() is True


def test_set_status_and_check():
    """Test setting and checking service status."""
    health = HealthCheck()
    health.set_status("db", False)
    assert health.is_healthy("db") is False

    health.set_status("db", True)
    assert health.is_healthy("db") is True


def test_is_healthy_unknown_service():
    """Test that unknown service returns False."""
    health = HealthCheck()
    assert health.is_healthy("unknown") is False


@pytest.mark.asyncio
async def test_asgi_call_healthy():
    """Test ASGI call when healthy returns 200."""
    health = HealthCheck()
    scope = {"type": "http"}
    messages = []

    async def receive():
        return {}

    async def send(msg):
        messages.append(msg)

    await health(scope, receive, send)

    assert messages[0]["status"] == 200
    assert any(b"healthy" in msg.get("body", b"") for msg in messages)


@pytest.mark.asyncio
async def test_asgi_call_unhealthy():
    """Test ASGI call when unhealthy returns 503."""
    health = HealthCheck()
    health.set_status("db", False)

    scope = {"type": "http"}
    messages = []

    async def receive():
        return {}

    async def send(msg):
        messages.append(msg)

    await health(scope, receive, send)

    assert messages[0]["status"] == 503
    assert any(b"unhealthy" in msg.get("body", b"") for msg in messages)
