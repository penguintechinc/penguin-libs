"""Flask app and client fixtures for PenguinTech Flask service tests."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from flask import Flask
    from flask.testing import FlaskClient


@pytest.fixture
def flask_app() -> Flask:
    """Create a minimal Flask application configured for testing.

    The app has ``TESTING=True`` and ``SECRET_KEY`` set.  Register additional
    blueprints or config values in your own fixture that depends on this one.

    Returns:
        A :class:`~flask.Flask` application instance.
    """
    from flask import Flask as _Flask  # noqa: PLC0415

    app: _Flask = _Flask(__name__)
    app.config["TESTING"] = True
    app.config["SECRET_KEY"] = "test-secret-key"
    return app


@pytest.fixture
def flask_client(flask_app: Flask) -> FlaskClient:
    """Return a test client for *flask_app*.

    Args:
        flask_app: The Flask application fixture.

    Returns:
        A :class:`~flask.testing.FlaskClient` bound to *flask_app*.
    """
    return flask_app.test_client()
