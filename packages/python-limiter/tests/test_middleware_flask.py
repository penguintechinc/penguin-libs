"""Tests for FlaskRateLimiter middleware."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from penguin_limiter.algorithms import RateLimitResult
from penguin_limiter.config import Algorithm, RateLimitConfig
from penguin_limiter.middleware.flask import FlaskRateLimiter, _rate_limit_headers
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

    def test_forged_xff_does_not_bypass_public_peer(self, app) -> None:  # type: ignore[return]
        """Regression (a): default config (trusted_proxy_count=0) — a public
        peer sending a forged private X-Forwarded-For must still be
        rate-limited. Before the fix, the client-supplied XFF was trusted
        unconditionally and this request would bypass entirely."""
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
        headers = {"X-Forwarded-For": "10.0.0.1"}  # attacker-forged private hop
        client.get("/xff", headers=headers, environ_base={"REMOTE_ADDR": "8.8.8.8"})
        client.get("/xff", headers=headers, environ_base={"REMOTE_ADDR": "8.8.8.8"})
        resp = client.get("/xff", headers=headers, environ_base={"REMOTE_ADDR": "8.8.8.8"})
        assert resp.status_code == 429

    def test_trusted_proxy_xff_used_for_key(self, app) -> None:  # type: ignore[return]
        """With trusted_proxy_count=1 configured, the rightmost XFF hop is
        honored as the real client for rate-limit keying."""
        storage = MemoryStorage()
        limiter = FlaskRateLimiter(
            config=RateLimitConfig.from_string("2/minute", trusted_proxy_count=1),
            storage=storage,
        )
        limiter.init_app(app)

        from flask import jsonify

        @app.route("/xff-trusted")
        def xff_trusted_route():  # type: ignore[return]
            return jsonify({"ok": True})

        client = app.test_client()
        headers = {"X-Forwarded-For": "5.5.5.5"}
        client.get("/xff-trusted", headers=headers, environ_base={"REMOTE_ADDR": "10.0.0.1"})
        client.get("/xff-trusted", headers=headers, environ_base={"REMOTE_ADDR": "10.0.0.1"})
        resp = client.get("/xff-trusted", headers=headers, environ_base={"REMOTE_ADDR": "10.0.0.1"})
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

    def test_decorator_private_ip_bypasses_by_default(self, app) -> None:  # type: ignore[return]
        """skip_private_ips=True (default): a private-IP caller on a
        decorated route bypasses without counting against the limit."""
        storage = MemoryStorage()
        limiter = FlaskRateLimiter(
            config=RateLimitConfig.from_string("1/minute"),
            storage=storage,
        )
        limiter.init_app(app)

        from flask import jsonify

        @app.route("/internal")
        @limiter.limit("1/minute")
        def internal():  # type: ignore[return]
            return jsonify({"ok": True})

        client = app.test_client()
        for _ in range(5):
            resp = client.get("/internal", environ_base={"REMOTE_ADDR": "192.168.0.5"})
            assert resp.status_code == 200


class TestFlaskRateLimiterMisc:
    def test_default_storage_is_memory_storage(self) -> None:
        """storage=None falls back to a MemoryStorage instance."""
        limiter = FlaskRateLimiter(config=RateLimitConfig.from_string("10/minute"))
        assert isinstance(limiter._storage, MemoryStorage)

    @pytest.mark.parametrize(
        "algorithm",
        [Algorithm.FIXED_WINDOW, Algorithm.TOKEN_BUCKET, Algorithm.SLIDING_WINDOW],
    )
    def test_build_algorithm_selects_configured_algorithm(self, algorithm: Algorithm) -> None:
        limiter = FlaskRateLimiter(
            config=RateLimitConfig.from_string("10/minute", algorithm=algorithm),
            storage=MemoryStorage(),
        )
        assert limiter._algo is not None

    def test_exempt_marks_function(self) -> None:
        limiter = FlaskRateLimiter(config=RateLimitConfig.from_string("10/minute"))

        def view() -> str:
            return "ok"

        marked = limiter.exempt(view)
        assert marked._rate_limit_exempt is True  # type: ignore[attr-defined]

    def test_rate_limit_headers_shape(self) -> None:
        result = RateLimitResult(
            allowed=True, limit=10, remaining=9, reset_after=30.0, current_count=1
        )
        headers = _rate_limit_headers(result)
        assert headers["X-RateLimit-Limit"] == "10"
        assert headers["X-RateLimit-Remaining"] == "9"
        assert headers["Retry-After"] == "0"

    def test_before_request_fail_open_on_storage_error(self, app) -> None:  # type: ignore[return]
        """fail_open=True (default): a broken algorithm backend must not
        block requests."""
        limiter = FlaskRateLimiter(
            config=RateLimitConfig.from_string("10/minute"),
            storage=MemoryStorage(),
        )
        limiter._algo = MagicMock(is_allowed=MagicMock(side_effect=RuntimeError("boom")))
        limiter.init_app(app)

        from flask import jsonify

        @app.route("/flaky")
        def flaky():  # type: ignore[return]
            return jsonify({"ok": True})

        client = app.test_client()
        resp = client.get("/flaky", environ_base={"REMOTE_ADDR": "9.9.9.9"})
        assert resp.status_code == 200

    def test_before_request_fail_closed_on_storage_error(self, app) -> None:  # type: ignore[return]
        """fail_open=False: a broken algorithm backend must reject with 503."""
        limiter = FlaskRateLimiter(
            config=RateLimitConfig.from_string("10/minute", fail_open=False),
            storage=MemoryStorage(),
        )
        limiter._algo = MagicMock(is_allowed=MagicMock(side_effect=RuntimeError("boom")))
        limiter.init_app(app)

        from flask import jsonify

        @app.route("/flaky-strict")
        def flaky_strict():  # type: ignore[return]
            return jsonify({"ok": True})

        client = app.test_client()
        resp = client.get("/flaky-strict", environ_base={"REMOTE_ADDR": "9.9.9.9"})
        assert resp.status_code == 503

    def test_decorator_fail_closed_on_storage_error(self, app) -> None:  # type: ignore[return]
        """Decorator path: fail_open=False rejects with 503 when the route's
        own algorithm instance raises (not merely a storage hiccup the
        algorithm itself already fails open on)."""
        from unittest.mock import patch

        storage = MemoryStorage()
        limiter = FlaskRateLimiter(
            config=RateLimitConfig.from_string("10/minute", fail_open=False),
            storage=storage,
        )
        limiter.init_app(app)

        from flask import jsonify

        broken_algo = MagicMock(is_allowed=MagicMock(side_effect=RuntimeError("boom")))
        with patch("penguin_limiter.middleware.flask._build_algorithm", return_value=broken_algo):

            @app.route("/decorated-flaky")
            @limiter.limit("10/minute", skip_private_ips=False)
            def decorated_flaky():  # type: ignore[return]
                return jsonify({"ok": True})

        client = app.test_client()
        resp = client.get("/decorated-flaky", environ_base={"REMOTE_ADDR": "9.9.9.9"})
        assert resp.status_code == 503
