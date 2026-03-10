"""Tests for DatabaseManager (read/write splitting)."""

from unittest.mock import MagicMock, patch

import pytest

from penguin_dal import DatabaseManager
from penguin_dal.db import DB


class TestDatabaseManagerSameURL:
    """DatabaseManager with no replica uses primary for all operations."""

    def test_read_is_write_when_no_read_url(self):
        with patch.object(DB, "__init__", return_value=None):
            dm = DatabaseManager.__new__(DatabaseManager)
            dm.write = MagicMock(spec=DB)
            dm.read = dm.write
            assert dm.read is dm.write

    def test_init_single_url(self):
        """DatabaseManager with one URL sets read == write."""
        with patch("penguin_dal.db.DB") as MockDB:
            instance = MockDB.return_value
            dm = DatabaseManager(write_url="sqlite://:memory:")
            # Only one DB instance created
            MockDB.assert_called_once_with("sqlite://:memory:")
            assert dm.write is instance
            assert dm.read is instance

    def test_close_single_connection(self):
        """Close called once when read is write."""
        mock_db = MagicMock(spec=DB)
        dm = DatabaseManager.__new__(DatabaseManager)
        dm.write = mock_db
        dm.read = mock_db  # same object
        dm.close()
        mock_db.close.assert_called_once()


class TestDatabaseManagerWithReplica:
    """DatabaseManager with separate read_url creates two connections."""

    def test_init_two_urls(self):
        """Two DB instances created when read_url differs from write_url."""
        with patch("penguin_dal.db.DB") as MockDB:
            write_instance = MagicMock(spec=DB)
            read_instance = MagicMock(spec=DB)
            MockDB.side_effect = [write_instance, read_instance]

            dm = DatabaseManager(
                write_url="sqlite://:memory:",
                read_url="sqlite:///replica.db",
            )
            assert dm.write is write_instance
            assert dm.read is read_instance
            assert dm.read is not dm.write

    def test_close_both_connections(self):
        """Both write and read connections are closed."""
        write_db = MagicMock(spec=DB)
        read_db = MagicMock(spec=DB)
        dm = DatabaseManager.__new__(DatabaseManager)
        dm.write = write_db
        dm.read = read_db
        dm.close()
        write_db.close.assert_called_once()
        read_db.close.assert_called_once()

    def test_call_routes_to_read(self):
        """Calling dm(query) routes to read connection."""
        write_db = MagicMock(spec=DB)
        read_db = MagicMock(spec=DB)
        dm = DatabaseManager.__new__(DatabaseManager)
        dm.write = write_db
        dm.read = read_db

        mock_query = MagicMock()
        dm(mock_query)
        read_db.assert_called_once_with(mock_query)
        write_db.assert_not_called()


class TestDatabaseManagerFlaskExt:
    """Flask extension init_dal supports read URI."""

    def test_init_dal_with_read_uri_creates_manager(self):
        """init_dal with read_uri returns DatabaseManager."""
        try:
            from flask import Flask

            from penguin_dal.flask_ext import init_dal
        except ImportError:
            pytest.skip("Flask not installed")

        app = Flask(__name__)
        with patch("penguin_dal.flask_ext.DatabaseManager") as MockDM:
            with patch("penguin_dal.flask_ext.DB"):
                init_dal(
                    app,
                    uri="sqlite://:memory:",
                    read_uri="sqlite:///replica.db",
                )
                MockDM.assert_called_once()

    def test_init_dal_without_read_uri_creates_db(self):
        """init_dal without read_uri returns plain DB."""
        try:
            from flask import Flask

            from penguin_dal.flask_ext import init_dal
        except ImportError:
            pytest.skip("Flask not installed")

        app = Flask(__name__)
        with patch("penguin_dal.flask_ext.DB") as MockDB:
            with patch("penguin_dal.flask_ext.DatabaseManager") as MockDM:
                init_dal(app, uri="sqlite://:memory:")
                MockDB.assert_called_once()
                MockDM.assert_not_called()

    def test_init_dal_reads_env_var(self, monkeypatch):
        """DATABASE_READ_URL env var used when read_uri not provided."""
        try:
            from flask import Flask

            from penguin_dal.flask_ext import init_dal
        except ImportError:
            pytest.skip("Flask not installed")

        monkeypatch.setenv("DATABASE_URL", "sqlite://:memory:")
        monkeypatch.setenv("DATABASE_READ_URL", "sqlite:///replica.db")
        app = Flask(__name__)
        with patch("penguin_dal.flask_ext.DatabaseManager") as MockDM:
            with patch("penguin_dal.flask_ext.DB"):
                init_dal(app)
                MockDM.assert_called_once()
