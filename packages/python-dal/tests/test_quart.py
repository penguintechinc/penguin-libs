"""Tests for Quart integration using mocks."""

import sys
from unittest.mock import MagicMock, patch

import pytest


class TestQuartIntegration:
    def test_init_dal_with_uri(self):
        """Test init_dal stores AsyncDB on app.extensions."""
        mock_app = MagicMock()
        mock_app.config = {}
        mock_app.extensions = {}

        from penguin_dal.quart_ext import init_dal

        init_dal(mock_app, uri="sqlite://")

        assert "_penguin_dal" in mock_app.extensions
        mock_app.before_serving.assert_called_once()
        mock_app.after_serving.assert_called_once()

    def test_init_dal_from_config(self):
        """Test init_dal reads URI from app.config."""
        mock_app = MagicMock()
        mock_app.config = {"DATABASE_URI": "sqlite://"}
        mock_app.extensions = {}

        from penguin_dal.quart_ext import init_dal

        init_dal(mock_app)

        assert "_penguin_dal" in mock_app.extensions

    def test_init_dal_from_sqlalchemy_config(self):
        """Test init_dal reads from SQLALCHEMY_DATABASE_URI fallback."""
        mock_app = MagicMock()
        mock_app.config = {"SQLALCHEMY_DATABASE_URI": "sqlite://"}
        mock_app.extensions = {}

        from penguin_dal.quart_ext import init_dal

        init_dal(mock_app)

        assert "_penguin_dal" in mock_app.extensions

    def test_init_dal_no_uri_raises(self):
        """Test init_dal raises ValueError without URI."""
        mock_app = MagicMock()
        mock_app.config = {}
        mock_app.extensions = {}

        from penguin_dal.quart_ext import init_dal

        with pytest.raises(ValueError, match="Database URI required"):
            init_dal(mock_app)

    def test_get_db_success(self):
        """Test get_db returns AsyncDB from current_app.extensions."""
        from penguin_dal.db import AsyncDB

        mock_db = MagicMock(spec=AsyncDB)
        mock_current_app = MagicMock()
        mock_current_app.extensions = {"_penguin_dal": mock_db}

        mock_quart = MagicMock()
        mock_quart.current_app = mock_current_app

        with patch.dict("sys.modules", {"quart": mock_quart}):
            from penguin_dal.quart_ext import get_db

            result = get_db()
            assert result is mock_db

    def test_get_db_not_initialized(self):
        """Test get_db raises RuntimeError when not initialized."""
        mock_current_app = MagicMock()
        mock_current_app.extensions = {}

        mock_quart = MagicMock()
        mock_quart.current_app = mock_current_app

        with patch.dict("sys.modules", {"quart": mock_quart}):
            from penguin_dal.quart_ext import get_db

            with pytest.raises(RuntimeError, match="not initialized"):
                get_db()
