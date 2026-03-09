"""Tests for Quart integration."""

import pytest


class TestQuartIntegration:
    def test_init_stores_async_db(self):
        """Test Quart init_dal stores AsyncDB."""
        try:
            from quart import Quart
        except ImportError:
            pytest.skip("Quart not installed")

        from penguin_dal.quart_ext import init_dal
        from penguin_dal.db import AsyncDB

        app = Quart(__name__)
        init_dal(app, uri="sqlite://")

        assert "_penguin_dal" in app.extensions
        assert isinstance(app.extensions["_penguin_dal"], AsyncDB)

    def test_init_without_uri(self):
        """Test init_dal raises without URI."""
        try:
            from quart import Quart
        except ImportError:
            pytest.skip("Quart not installed")

        from penguin_dal.quart_ext import init_dal

        app = Quart(__name__)
        with pytest.raises(ValueError, match="Database URI required"):
            init_dal(app)
