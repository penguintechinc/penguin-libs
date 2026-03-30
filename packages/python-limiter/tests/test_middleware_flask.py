"""Tests for FlaskRateLimiter middleware."""

from __future__ import annotations

import pytest

from penguin_limiter.config import RateLimitConfig
from penguin_limiter.middleware.flask import FlaskRateLimiter
from penguin_limiter.storage.memory import MemoryStorage


@pytest.fixture()
def app():  # type: ignore[return]
    try:
        from flask import Flask
    except ImportError:
        pytest.skip("Flask not installed")
    a = Flask(__name__)
    a.config["TESTING"] = True
    return a


@pytest.fixture()
def client_and_limiter(app):  # type: ignore[return]
    storage = MemoryStorage()
    config = RateLimitConfig.from_string("3/minute")
    limiter = FlaskRateLimiter(config=config, storage=storage)
    limiter.init_app(app)

    from flask import jsonify

    @app.route("/test")
    def test_route():  # type: ignore[return]
        return jsonify({"ok": True})

    return app.test_client(), limiter


class TestFlaskRateLimiterGlobal:
    def test_requests_within_limit_succeed(self, client_and_limiter) -> None:  # type: ignore[return]
        client, _ = client_and_limiter
        for _ in range(3):
            resp = client.get("/test", environ_base={"REMOTE_ADDR": "1.2.3.4"})
            assert resp.status_code == 200

    def test_request_exceeding_limit_returns_429(self, client_and_limiter) -> None:  # type: ignore[return]
        client, _ = client_and_limiter
        for _ in range(3):
            client.get("/test", environ_base={"REMOTE_ADDR": "1.2.3.4"})
        resp = client.get("/test", environ_base={"REMOTE_ADDR": "1.2.3.4"})
        assert resp.status_code == 429

    def test_private_ip_always_allowed(self, client_and_limiter) -> None:  # type: ignore[return]
        """Private IPs must bypass rate limiting when skip_private_ips=True."""
        client, _ = client_and_limiter
        # Exhaust limit for a different IP first to ensure counting works
        for _ in range(10):  # well above limit of 3
            resp = client.get("/test", environ_base={"REMOTE_ADDR": "192.168.1.1"})
            assert resp.status_code == 200  # private IP always 200

    def test_xff_public_ip_is_limited(self, app) -> None:  # type: ignore[return]
        storage = MemoryStorage()
        limiter = FlaskRateLimiter(
            config=RateLimitConfig.from_string("2/minute"),
            storage=storage,
        )
        limiter.init_app(app)

        from flask import jsonify

        @app.route("/xff")
        def xff_route():  # type: ignore[return]
            return jsonify({"ok": True})

        client = app.test_client()
        headers = {"X-Forwarded-For": "5.5.5.5"}
        client.get("/xff", headers=headers, environ_base={"REMOTE_ADDR": "10.0.0.1"})
        client.get("/xff", headers=headers, environ_base={"REMOTE_ADDR": "10.0.0.1"})
        resp = client.get("/xff", headers=headers, environ_base={"REMOTE_ADDR": "10.0.0.1"})
        assert resp.status_code == 429

    def test_skip_private_ips_false_counts_private(self, app) -> None:  # type: ignore[return]
        """skip_private_ips=False forces rate limiting of internal IPs."""
        storage = MemoryStorage()
        limiter = FlaskRateLimiter(
            config=RateLimitConfig.from_string("2/minute", skip_private_ips=False),
            storage=storage,
        )
        limiter.init_app(app)

        from flask import jsonify

        @app.route("/strict")
        def strict_route():  # type: ignore[return]
            return jsonify({"ok": True})

        client = app.test_client()
        client.get("/strict", environ_base={"REMOTE_ADDR": "10.0.0.1"})
        client.get("/strict", environ_base={"REMOTE_ADDR": "10.0.0.1"})
        resp = client.get("/strict", environ_base={"REMOTE_ADDR": "10.0.0.1"})
        assert resp.status_code == 429


class TestFlaskRateLimiterDecorator:
    def test_route_limit_decorator(self, app) -> None:  # type: ignore[return]
        storage = MemoryStorage()
        limiter = FlaskRateLimiter(
            config=RateLimitConfig.from_string("100/minute"),
            storage=storage,
        )
        limiter.init_app(app)

        from flask import jsonify

        @app.route("/search")
        @limiter.limit("2/minute")
        def search():  # type: ignore[return]
            return jsonify({"results": []})

        client = app.test_client()
        client.get("/search", environ_base={"REMOTE_ADDR": "9.9.9.9"})
        client.get("/search", environ_base={"REMOTE_ADDR": "9.9.9.9"})
        resp = client.get("/search", environ_base={"REMOTE_ADDR": "9.9.9.9"})
        assert resp.status_code == 429

    def test_decorator_skip_private_ips_override(self, app) -> None:  # type: ignore[return]
        """Per-route skip_private_ips=False should rate-limit private callers."""
        storage = MemoryStorage()
        limiter = FlaskRateLimiter(
            config=RateLimitConfig.from_string("100/minute", skip_private_ips=True),
            storage=storage,
        )
        limiter.init_app(app)

        from flask import jsonify

        @app.route("/admin")
        @limiter.limit("1/minute", skip_private_ips=False)
        def admin():  # type: ignore[return]
            return jsonify({"ok": True})

        client = app.test_client()
        client.get("/admin", environ_base={"REMOTE_ADDR": "192.168.0.1"})
        resp = client.get("/admin", environ_base={"REMOTE_ADDR": "192.168.0.1"})
        assert resp.status_code == 429
