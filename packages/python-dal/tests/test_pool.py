"""Tests for connection pooling helpers."""

from unittest.mock import MagicMock, patch

import pytest

from penguin_dal.pool import check_galera_readiness, get_pool_config


class TestGetPoolConfig:
    def test_sqlite(self):
        config = get_pool_config("sqlite:///test.db")
        assert config == {"connect_args": {"check_same_thread": False}}
        assert "pool_size" not in config

    def test_mysql(self):
        config = get_pool_config("mysql://user:pass@host/db")
        assert config["pool_size"] == 10
        assert config["max_overflow"] == 10
        assert config["pool_pre_ping"] is True
        assert config["pool_recycle"] == 3600
        assert config["connect_args"] == {"charset": "utf8mb4"}

    def test_mysql_galera(self):
        config = get_pool_config("mysql://user:pass@host/db", galera=True)
        assert config["pool_pre_ping"] is True
        assert config["pool_recycle"] == 1800
        assert config["pool_timeout"] == 10
        assert config["connect_args"]["charset"] == "utf8mb4"
        assert config["connect_args"]["connect_timeout"] == 5

    def test_postgresql(self):
        config = get_pool_config("postgresql://user:pass@host/db", pool_size=20)
        assert config["pool_size"] == 20
        assert config["max_overflow"] == 20
        assert config["pool_pre_ping"] is True
        assert config["pool_recycle"] == 3600
        assert "connect_args" not in config

    def test_mssql(self):
        config = get_pool_config("mssql://user:pass@host/db")
        assert config["pool_recycle"] == 1800
        assert config["pool_size"] == 10

    def test_custom_pool_size(self):
        config = get_pool_config("postgresql://host/db", pool_size=5)
        assert config["pool_size"] == 5
        assert config["max_overflow"] == 5


class TestCheckGaleraReadiness:
    def test_galera_ready(self):
        mock_engine = MagicMock()
        mock_conn = MagicMock()
        mock_result = MagicMock()
        mock_row = ("wsrep_ready", "ON")
        mock_result.first.return_value = mock_row
        mock_conn.execute.return_value = mock_result
        mock_engine.connect.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_engine.connect.return_value.__exit__ = MagicMock(return_value=False)

        assert check_galera_readiness(mock_engine) is True

    def test_galera_not_ready(self):
        mock_engine = MagicMock()
        mock_conn = MagicMock()
        mock_result = MagicMock()
        mock_result.first.return_value = None
        mock_conn.execute.return_value = mock_result
        mock_engine.connect.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_engine.connect.return_value.__exit__ = MagicMock(return_value=False)

        assert check_galera_readiness(mock_engine) is False

    def test_galera_exception(self):
        mock_engine = MagicMock()
        mock_engine.connect.side_effect = Exception("Connection refused")

        assert check_galera_readiness(mock_engine) is False

    def test_galera_off(self):
        mock_engine = MagicMock()
        mock_conn = MagicMock()
        mock_result = MagicMock()
        mock_row = ("wsrep_ready", "OFF")
        mock_result.first.return_value = mock_row
        mock_conn.execute.return_value = mock_result
        mock_engine.connect.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_engine.connect.return_value.__exit__ = MagicMock(return_value=False)

        assert check_galera_readiness(mock_engine) is False
