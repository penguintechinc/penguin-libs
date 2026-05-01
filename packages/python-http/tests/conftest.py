"""Pytest fixtures for penguin-http tests."""

import pytest
from flask import Flask


@pytest.fixture
def app() -> Flask:
    """Create a minimal Flask test app."""
    app = Flask(__name__)
    app.config["TESTING"] = True
    return app


@pytest.fixture
def client(app: Flask):
    """Flask test client."""
    return app.test_client()


@pytest.fixture
def app_context(app: Flask):
    """Flask application context."""
    with app.app_context():
        yield app
