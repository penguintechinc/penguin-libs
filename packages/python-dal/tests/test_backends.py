"""Tests for backend URI normalization and dialect configuration."""

import pytest

from penguin_dal.backends import ensure_async_uri, get_engine_kwargs, normalize_uri


class TestNormalizeUri:
    def test_sqlite_memory(self):
        assert normalize_uri("sqlite:memory:") == "sqlite://"
        assert normalize_uri("sqlite://:memory:") == "sqlite://"

    def test_postgres_to_postgresql(self):
        assert normalize_uri("postgres://host/db") == "postgresql://host/db"

    def test_postgres_asyncpg(self):
        assert normalize_uri("postgres+asyncpg://host/db") == "postgresql+asyncpg://host/db"

    def test_sqlite_file(self):
        # sqlite:// maps to sqlite:/// via _URI_MAP, then path appended
        assert normalize_uri("sqlite:///path/to/db") == "sqlite:////path/to/db"


class TestEnsureAsyncUri:
    def test_postgresql_to_asyncpg(self):
        result = ensure_async_uri("postgresql://host/db")
        assert result == "postgresql+asyncpg://host/db"

    def test_sqlite_to_aiosqlite(self):
        result = ensure_async_uri("sqlite://")
        # normalize_uri maps sqlite:// to sqlite:/// first
        assert result == "sqlite+aiosqlite:///"

    def test_mysql_to_aiomysql(self):
        result = ensure_async_uri("mysql://host/db")
        assert result == "mysql+aiomysql://host/db"

    def test_mssql_to_aioodbc(self):
        result = ensure_async_uri("mssql://host/db")
        assert result == "mssql+aioodbc://host/db"

    def test_already_async(self):
        result = ensure_async_uri("postgresql+asyncpg://host/db")
        assert result == "postgresql+asyncpg://host/db"

    def test_unsupported_scheme(self):
        with pytest.raises(ValueError, match="No async driver known"):
            ensure_async_uri("firebird://host/db")


class TestGetEngineKwargs:
    def test_sqlite(self):
        kwargs = get_engine_kwargs("sqlite:///test.db")
        assert "pool_pre_ping" not in kwargs
        assert "pool_recycle" not in kwargs
        assert kwargs["connect_args"] == {"check_same_thread": False}

    def test_postgresql(self):
        kwargs = get_engine_kwargs("postgresql://host/db", pool_size=20)
        assert kwargs["pool_size"] == 20
        assert kwargs["max_overflow"] == 20
        assert kwargs["pool_pre_ping"] is True

    def test_mysql(self):
        kwargs = get_engine_kwargs("mysql://host/db")
        assert kwargs["pool_size"] == 10
        assert kwargs["connect_args"]["charset"] == "utf8mb4"

    def test_mysql_with_driver(self):
        kwargs = get_engine_kwargs("mysql+pymysql://host/db")
        assert kwargs["connect_args"]["charset"] == "utf8mb4"

    def test_mssql(self):
        kwargs = get_engine_kwargs("mssql://host/db", pool_size=5)
        assert kwargs["pool_size"] == 5
        assert kwargs["max_overflow"] == 5
        assert kwargs["pool_pre_ping"] is True
