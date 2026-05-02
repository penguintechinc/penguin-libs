"""Tests for H3RateLimitMiddleware (ASGI)."""

from __future__ import annotations

import pytest

from penguin_limiter.config import RateLimitConfig
from penguin_limiter.middleware.h3 import H3RateLimitMiddleware
from penguin_limiter.storage.memory import MemoryStorage


async def _dummy_app(scope, receive, send):  # type: ignore[return]
    await send({"type": "http.response.start", "status": 200, "headers": []})
    await send({"type": "http.response.body", "body": b"ok", "more_body": False})


def _make_scope(client_ip: str = "1.2.3.4", xff: str | None = None) -> dict:
    headers = []
    if xff:
        headers.append((b"x-forwarded-for", xff.encode()))
    return {
        "type": "http",
        "client": [client_ip, 54321],
        "headers": headers,
    }


async def _collect_response(middleware, scope):  # type: ignore[return]
    events = []

    async def receive():  # type: ignore[return]
        return {}

    async def send(event):  # type: ignore[return]
        events.append(event)

    await middleware(scope, receive, send)
    return events


class TestH3RateLimitMiddleware:
    @pytest.mark.asyncio
    async def test_public_ip_within_limit_passes(self) -> None:
        storage = MemoryStorage()
        mw = H3RateLimitMiddleware(
            _dummy_app,
            config=RateLimitConfig.from_string("5/minute"),
            storage=storage,
        )
        events = await _collect_response(mw, _make_scope("1.2.3.4"))
        status_event = next(e for e in events if e.get("type") == "http.response.start")
        assert status_event["status"] == 200

    @pytest.mark.asyncio
    async def test_public_ip_exceeds_limit_returns_429(self) -> None:
        storage = MemoryStorage()
        mw = H3RateLimitMiddleware(
            _dummy_app,
            config=RateLimitConfig.from_string("2/minute"),
            storage=storage,
        )
        scope = _make_scope("3.3.3.3")
        for _ in range(2):
            await _collect_response(mw, scope)
        events = await _collect_response(mw, scope)
        status_event = next(e for e in events if e.get("type") == "http.response.start")
        assert status_event["status"] == 429

    @pytest.mark.asyncio
    async def test_private_ip_bypasses_rate_limit(self) -> None:
        storage = MemoryStorage()
        mw = H3RateLimitMiddleware(
            _dummy_app,
            config=RateLimitConfig.from_string("1/minute"),  # very tight
            storage=storage,
        )
        scope = _make_scope("192.168.1.1")
        for _ in range(10):
            events = await _collect_response(mw, scope)
            status_event = next(e for e in events if e.get("type") == "http.response.start")
            assert status_event["status"] == 200  # private IP always passes

    @pytest.mark.asyncio
    async def test_xff_public_ip_is_limited(self) -> None:
        storage = MemoryStorage()
        mw = H3RateLimitMiddleware(
            _dummy_app,
            config=RateLimitConfig.from_string("2/minute"),
            storage=storage,
        )
        # Internal client address but XFF reveals real public client
        scope = _make_scope("10.0.0.1", xff="10.0.0.2, 7.7.7.7")
        for _ in range(2):
            await _collect_response(mw, scope)
        events = await _collect_response(mw, scope)
        status_event = next(e for e in events if e.get("type") == "http.response.start")
        assert status_event["status"] == 429

    @pytest.mark.asyncio
    async def test_skip_private_ips_false_counts_private(self) -> None:
        storage = MemoryStorage()
        mw = H3RateLimitMiddleware(
            _dummy_app,
            config=RateLimitConfig.from_string("1/minute", skip_private_ips=False),
            storage=storage,
        )
        scope = _make_scope("10.0.0.1")
        await _collect_response(mw, scope)
        events = await _collect_response(mw, scope)
        status_event = next(e for e in events if e.get("type") == "http.response.start")
        assert status_event["status"] == 429

    @pytest.mark.asyncio
    async def test_non_http_scope_passes_through(self) -> None:
        storage = MemoryStorage()
        mw = H3RateLimitMiddleware(
            _dummy_app,
            config=RateLimitConfig.from_string("1/minute"),
            storage=storage,
        )
        scope = {"type": "lifespan"}
        events = []

        async def receive():  # type: ignore[return]
            return {}

        async def send(event):  # type: ignore[return]
            events.append(event)

        await mw(scope, receive, send)
        # lifespan events pass through — dummy app's response appears
        assert any(e.get("status") == 200 for e in events)

    @pytest.mark.asyncio
    async def test_rate_limit_headers_injected(self) -> None:
        storage = MemoryStorage()
        mw = H3RateLimitMiddleware(
            _dummy_app,
            config=RateLimitConfig.from_string("10/minute", add_headers=True),
            storage=storage,
        )
        events = await _collect_response(mw, _make_scope("4.4.4.4"))
        start = next(e for e in events if e.get("type") == "http.response.start")
        header_names = [n.decode() if isinstance(n, bytes) else n for n, _ in start["headers"]]
        assert "x-ratelimit-limit" in header_names
