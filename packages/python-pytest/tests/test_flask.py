"""Tests for penguin_pytest.flask fixtures."""

from __future__ import annotations

import pytest

pytest.importorskip("flask")

from flask import Flask  # noqa: E402
from flask.testing import FlaskClient  # noqa: E402


def test_flask_app_is_flask_instance(flask_app: Flask) -> None:
    assert isinstance(flask_app, Flask)


def test_flask_app_testing_config(flask_app: Flask) -> None:
    assert flask_app.config["TESTING"] is True


def test_flask_client_is_test_client(flask_client: FlaskClient) -> None:
    assert flask_client is not None


def test_flask_client_returns_404_for_unknown_route(flask_client: FlaskClient) -> None:
    response = flask_client.get("/nonexistent")
    assert response.status_code == 404
