"""Tests for penguin_pytest.asgi helpers."""

from __future__ import annotations

from penguin_pytest.asgi import asgi_http_scope, asgi_ok_app, asgi_send_collector


def test_asgi_http_scope_defaults() -> None:
    scope = asgi_http_scope()
    assert scope["type"] == "http"
    assert scope["method"] == "GET"
    assert scope["path"] == "/api"
    assert scope["headers"] == []
    assert "state" in scope


def test_asgi_http_scope_custom_values() -> None:
    headers = [(b"authorization", b"Bearer tok")]
    scope = asgi_http_scope(path="/health", method="POST", headers=headers)
    assert scope["path"] == "/health"
    assert scope["method"] == "POST"
    assert scope["headers"] == headers


async def test_asgi_send_collector_collects_messages() -> None:
    messages, send = asgi_send_collector()
    assert messages == []

    await send({"type": "http.response.start", "status": 200})
    assert len(messages) == 1
    assert messages[0]["status"] == 200


async def test_asgi_ok_app_returns_200() -> None:
    scope = asgi_http_scope()
    messages, send = asgi_send_collector()
    app = asgi_ok_app()
    await app(scope, None, send)
    assert messages[0]["status"] == 200
    assert messages[1]["body"] == b"ok"


async def test_asgi_ok_app_custom_status() -> None:
    scope = asgi_http_scope()
    messages, send = asgi_send_collector()
    app = asgi_ok_app(status=404)
    await app(scope, None, send)
    assert messages[0]["status"] == 404
