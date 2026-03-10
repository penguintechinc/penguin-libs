"""Tests for Flask integration using mocks."""

from unittest.mock import MagicMock, patch

import pytest


class TestFlaskIntegration:
    def test_init_dal_with_uri(self):
        """Test init_dal stores DB on app.extensions."""
        mock_app = MagicMock()
        mock_app.config = {}
        mock_app.extensions = {}

        from penguin_dal.flask_ext import init_dal

        init_dal(mock_app, uri="sqlite://")

        assert "_penguin_dal" in mock_app.extensions
        mock_app.teardown_appcontext.assert_called_once()

    def test_init_dal_from_config(self):
        """Test init_dal reads URI from app.config."""
        mock_app = MagicMock()
        mock_app.config = {"DATABASE_URI": "sqlite://"}
        mock_app.extensions = {}

        from penguin_dal.flask_ext import init_dal

        init_dal(mock_app)

        assert "_penguin_dal" in mock_app.extensions

    def test_init_dal_from_sqlalchemy_config(self):
        """Test init_dal reads from SQLALCHEMY_DATABASE_URI fallback."""
        mock_app = MagicMock()
        mock_app.config = {"SQLALCHEMY_DATABASE_URI": "sqlite://"}
        mock_app.extensions = {}

        from penguin_dal.flask_ext import init_dal

        init_dal(mock_app)

        assert "_penguin_dal" in mock_app.extensions

    def test_init_dal_no_uri_raises(self):
        """Test init_dal raises ValueError without URI."""
        mock_app = MagicMock()
        mock_app.config = {}
        mock_app.extensions = {}

        from penguin_dal.flask_ext import init_dal

        with pytest.raises(ValueError, match="Database URI required"):
            init_dal(mock_app)

    def test_get_db_success(self):
        """Test get_db returns DB from current_app.extensions."""
        from penguin_dal.db import DB

        mock_db = MagicMock(spec=DB)
        mock_current_app = MagicMock()
        mock_current_app.extensions = {"_penguin_dal": mock_db}

        with patch("penguin_dal.flask_ext.current_app", mock_current_app, create=True):
            # We need to patch at the import site
            with patch.dict("sys.modules", {"flask": MagicMock()}):
                # Re-import to get the patched version
                import penguin_dal.flask_ext as flask_ext_mod

                # Directly patch the import within get_db
                with patch(
                    "penguin_dal.flask_ext.current_app",
                    new=mock_current_app,
                    create=True,
                ):
                    # Mock the flask import inside get_db
                    mock_flask = MagicMock()
                    mock_flask.current_app = mock_current_app
                    with patch.dict("sys.modules", {"flask": mock_flask}):
                        result = flask_ext_mod.get_db()
                        assert result is mock_db

    def test_get_db_not_initialized(self):
        """Test get_db raises RuntimeError when not initialized."""
        mock_current_app = MagicMock()
        mock_current_app.extensions = {}

        mock_flask = MagicMock()
        mock_flask.current_app = mock_current_app

        with patch.dict("sys.modules", {"flask": mock_flask}):
            from penguin_dal.flask_ext import get_db

            with pytest.raises(RuntimeError, match="not initialized"):
                get_db()
