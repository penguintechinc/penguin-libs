"""Tests for license validation decorators."""

import asyncio
from datetime import datetime, timezone
from unittest.mock import MagicMock

import flask
import pytest

from penguin_licensing.client import Feature, LicenseInfo
from penguin_licensing.decorators import feature_required, license_required


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_license_info(
    tier: str = "enterprise",
    valid: bool = True,
    features: list[Feature] | None = None,
) -> LicenseInfo:
    return LicenseInfo(
        valid=valid,
        customer="Test Customer",
        product="elder",
        license_version="2.0",
        license_key="PENG-TEST-1234",
        expires_at=datetime(2030, 1, 1, tzinfo=timezone.utc),
        issued_at=datetime(2024, 1, 1, tzinfo=timezone.utc),
        tier=tier,
        features=features or [],
        limits={},
        metadata={},
    )


_TIER_LEVELS = {"community": 1, "professional": 2, "enterprise": 3}


def _make_mock_client(
    tier: str = "enterprise",
    features: list[Feature] | None = None,
) -> MagicMock:
    client = MagicMock()
    info = _make_license_info(tier=tier, features=features)
    client.validate.return_value = info
    client.check_tier.side_effect = lambda req: _TIER_LEVELS.get(
        info.tier, 0
    ) >= _TIER_LEVELS.get(req, 99)
    client.check_feature.side_effect = lambda name: any(
        f.name == name and f.entitled for f in (features or [])
    )
    return client


def _make_app(client: MagicMock) -> flask.Flask:
    app = flask.Flask(__name__)
    app.config["LICENSE_CLIENT"] = client
    app.config["TESTING"] = True
    return app


# ---------------------------------------------------------------------------
# license_required
# ---------------------------------------------------------------------------


class TestLicenseRequiredDecorator:
    """Tests for license_required decorator."""

    def test_enterprise_license_allows_enterprise_route(self) -> None:
        client = _make_mock_client(tier="enterprise")
        app = _make_app(client)

        @app.route("/test")
        @license_required("enterprise")
        def view() -> flask.Response:
            return flask.jsonify({"ok": True})

        with app.test_client() as c:
            resp = c.get("/test")
        assert resp.status_code == 200

    def test_community_license_blocked_on_enterprise_route(self) -> None:
        client = _make_mock_client(tier="community")
        app = _make_app(client)

        @app.route("/test")
        @license_required("enterprise")
        def view() -> flask.Response:
            return flask.jsonify({"ok": True})

        with app.test_client() as c:
            resp = c.get("/test")
        assert resp.status_code == 403
        data = resp.get_json()
        assert data["error"] == "License Required"
        assert data["required_tier"] == "enterprise"
        assert data["current_tier"] == "community"
        assert "upgrade_url" in data

    def test_professional_license_allowed_for_professional_tier(self) -> None:
        client = _make_mock_client(tier="professional")
        app = _make_app(client)

        @app.route("/test")
        @license_required("professional")
        def view() -> flask.Response:
            return flask.jsonify({"ok": True})

        with app.test_client() as c:
            resp = c.get("/test")
        assert resp.status_code == 200

    def test_professional_license_blocked_on_enterprise_route(self) -> None:
        client = _make_mock_client(tier="professional")
        app = _make_app(client)

        @app.route("/test")
        @license_required("enterprise")
        def view() -> flask.Response:
            return flask.jsonify({"ok": True})

        with app.test_client() as c:
            resp = c.get("/test")
        assert resp.status_code == 403

    def test_domain_bypass_penguincloud_io(self) -> None:
        """penguincloud.io hosts skip license checks even with community tier."""
        client = _make_mock_client(tier="community")
        app = _make_app(client)

        @app.route("/test")
        @license_required("enterprise")
        def view() -> flask.Response:
            return flask.jsonify({"ok": True})

        with app.test_client() as c:
            resp = c.get("/test", headers={"Host": "elder.penguincloud.io"})
        assert resp.status_code == 200
        client.check_tier.assert_not_called()

    def test_domain_bypass_penguintech_cloud(self) -> None:
        client = _make_mock_client(tier="community")
        app = _make_app(client)

        @app.route("/test")
        @license_required("enterprise")
        def view() -> flask.Response:
            return flask.jsonify({"ok": True})

        with app.test_client() as c:
            resp = c.get("/test", headers={"Host": "app.penguintech.cloud"})
        assert resp.status_code == 200
        client.check_tier.assert_not_called()

    def test_outside_flask_context_transparent(self) -> None:
        """Outside Flask context, decorator passes through without blocking."""

        @license_required("enterprise")
        async def my_func(x: int) -> int:
            return x * 2

        assert asyncio.run(my_func(5)) == 10

    def test_sync_function_outside_flask(self) -> None:
        @license_required()
        def sync_func(x: int) -> int:
            return x * 3

        assert sync_func(4) == 12

    def test_preserves_function_name(self) -> None:
        @license_required()
        def my_named_function() -> None:
            pass

        assert my_named_function.__name__ == "my_named_function"


# ---------------------------------------------------------------------------
# feature_required
# ---------------------------------------------------------------------------


class TestFeatureRequiredDecorator:
    """Tests for feature_required decorator."""

    def test_entitled_feature_allows_access(self) -> None:
        sso = Feature(name="sso", entitled=True, units=0, description="", metadata={})
        client = _make_mock_client(tier="enterprise", features=[sso])
        app = _make_app(client)

        @app.route("/test")
        @feature_required("sso")
        def view() -> flask.Response:
            return flask.jsonify({"ok": True})

        with app.test_client() as c:
            resp = c.get("/test")
        assert resp.status_code == 200

    def test_missing_feature_returns_403(self) -> None:
        client = _make_mock_client(tier="enterprise", features=[])
        app = _make_app(client)

        @app.route("/test")
        @feature_required("sso")
        def view() -> flask.Response:
            return flask.jsonify({"ok": True})

        with app.test_client() as c:
            resp = c.get("/test")
        assert resp.status_code == 403
        data = resp.get_json()
        assert data["error"] == "Feature Not Available"
        assert data["feature"] == "sso"
        assert "upgrade_url" in data

    def test_non_entitled_feature_blocked(self) -> None:
        sso = Feature(name="sso", entitled=False, units=0, description="", metadata={})
        client = _make_mock_client(tier="enterprise", features=[sso])
        app = _make_app(client)

        @app.route("/test")
        @feature_required("sso")
        def view() -> flask.Response:
            return flask.jsonify({"ok": True})

        with app.test_client() as c:
            resp = c.get("/test")
        assert resp.status_code == 403

    def test_domain_bypass_skips_feature_check(self) -> None:
        client = _make_mock_client(tier="enterprise", features=[])
        app = _make_app(client)

        @app.route("/test")
        @feature_required("sso")
        def view() -> flask.Response:
            return flask.jsonify({"ok": True})

        with app.test_client() as c:
            resp = c.get("/test", headers={"Host": "elder.penguincloud.io"})
        assert resp.status_code == 200
        client.check_feature.assert_not_called()

    def test_outside_flask_context_transparent(self) -> None:
        @feature_required("sso")
        async def my_func(x: int) -> int:
            return x * 3

        assert asyncio.run(my_func(4)) == 12

    def test_preserves_function_name(self) -> None:
        @feature_required("sso")
        def my_feature_function() -> None:
            pass

        assert my_feature_function.__name__ == "my_feature_function"
