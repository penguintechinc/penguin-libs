"""Tests for Flask integration."""

import pytest


class TestFlaskIntegration:
    def test_init_and_get_db(self):
        """Test Flask init_dal and get_db lifecycle."""
        try:
            from flask import Flask
        except ImportError:
            pytest.skip("Flask not installed")

        from penguin_dal.flask_ext import init_dal, get_db
        from penguin_dal.db import DB

        app = Flask(__name__)
        init_dal(app, uri="sqlite://")

        with app.app_context():
            db = get_db()
            assert isinstance(db, DB)

    def test_get_db_without_init(self):
        """Test get_db raises without init_dal."""
        try:
            from flask import Flask
        except ImportError:
            pytest.skip("Flask not installed")

        from penguin_dal.flask_ext import get_db

        app = Flask(__name__)
        with app.app_context():
            with pytest.raises(RuntimeError, match="not initialized"):
                get_db()

    def test_init_without_uri(self):
        """Test init_dal raises without URI."""
        try:
            from flask import Flask
        except ImportError:
            pytest.skip("Flask not installed")

        from penguin_dal.flask_ext import init_dal

        app = Flask(__name__)
        with pytest.raises(ValueError, match="Database URI required"):
            init_dal(app)
