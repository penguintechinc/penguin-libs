"""Tests for Query composition and QuerySet operations."""

import pytest
from sqlalchemy import Boolean, Column, Integer, MetaData, String, Table, text

from penguin_dal.query import Query, Row


class TestQuery:
    def test_and(self, db):
        q1 = db.users.id > 1
        q2 = db.users.active == True
        combined = q1 & q2
        assert isinstance(combined, Query)

    def test_or(self, db):
        q1 = db.users.name == "Alice"
        q2 = db.users.name == "Bob"
        combined = q1 | q2
        assert isinstance(combined, Query)

    def test_not(self, db):
        q = db.users.active == True
        inverted = ~q
        assert isinstance(inverted, Query)

    def test_repr(self, db):
        q = db.users.id == 1
        assert "Query(" in repr(q)


class TestQuerySetOrderByFieldProxyList:
    def test_select_orderby_field_proxy_list(self, db):
        """Test orderby with a list of FieldProxy objects."""
        rows = db(db.users.id > 0).select(orderby=[db.users.active, db.users.name])
        assert len(rows) == 3

    def test_select_orderby_mixed_list(self, db):
        """Test orderby with list containing both FieldProxy and raw columns."""
        raw_col = db.users.name.column  # raw SA column
        rows = db(db.users.id > 0).select(orderby=[db.users.active, raw_col])
        assert len(rows) == 3

    def test_select_orderby_single_field_proxy(self, db):
        """Test orderby with a single FieldProxy object."""
        rows = db(db.users.id > 0).select(orderby=db.users.name)
        assert len(rows) == 3
        assert rows[0].name == "Alice"

    def test_row_eq_non_row(self):
        """Test Row.__eq__ with non-Row object."""
        row = Row({"id": 1})
        assert row.__eq__("not a row") is NotImplemented


def _create_async_tables(conn):
    metadata = MetaData()
    Table(
        "users",
        metadata,
        Column("id", Integer, primary_key=True, autoincrement=True),
        Column("email", String(255), nullable=False),
        Column("name", String(255), nullable=False),
        Column("active", Boolean, default=True),
    )
    metadata.create_all(conn)


@pytest.fixture
async def async_db_for_query():
    """Create an AsyncDB for testing async query operations."""
    from penguin_dal.db import AsyncDB

    db = AsyncDB("sqlite://", pool_size=5, echo=False)
    async with db.engine.begin() as conn:
        await conn.run_sync(_create_async_tables)
        await conn.execute(
            text(
                "INSERT INTO users (email, name, active) VALUES "
                "('alice@example.com', 'Alice', 1), "
                "('bob@example.com', 'Bob', 1), "
                "('charlie@example.com', 'Charlie', 0)"
            )
        )
    await db.reflect()
    yield db
    await db.close()


class TestAsyncQuerySet:
    async def test_select_orderby_field_proxy_list(self, async_db_for_query):
        """Test async orderby with a list of FieldProxy objects."""
        db = async_db_for_query
        rows = await db(db.users.id > 0).select(orderby=[db.users.active, db.users.name])
        assert len(rows) == 3

    async def test_select_orderby_mixed_list(self, async_db_for_query):
        """Test async orderby with list containing both FieldProxy and raw columns."""
        db = async_db_for_query
        raw_col = db.users.name.column
        rows = await db(db.users.id > 0).select(orderby=[db.users.active, raw_col])
        assert len(rows) == 3

    async def test_select_orderby_single_field_proxy(self, async_db_for_query):
        """Test async orderby with single FieldProxy."""
        db = async_db_for_query
        rows = await db(db.users.id > 0).select(orderby=db.users.name)
        assert len(rows) == 3
        assert rows[0].name == "Alice"

    async def test_select_with_limitby(self, async_db_for_query):
        """Test async select with limitby."""
        db = async_db_for_query
        rows = await db(db.users.id > 0).select(limitby=(0, 2))
        assert len(rows) == 2

    async def test_update(self, async_db_for_query):
        """Test async update."""
        db = async_db_for_query
        count = await db(db.users.email == "alice@example.com").update(name="Alice Updated")
        assert count == 1

    async def test_delete(self, async_db_for_query):
        """Test async delete."""
        db = async_db_for_query
        count = await db(db.users.email == "charlie@example.com").delete()
        assert count == 1

    async def test_count(self, async_db_for_query):
        """Test async count."""
        db = async_db_for_query
        count = await db(db.users.active == True).count()
        assert count == 2

    async def test_exists(self, async_db_for_query):
        """Test async exists."""
        db = async_db_for_query
        assert await db(db.users.email == "alice@example.com").exists() is True
        assert await db(db.users.email == "nobody@example.com").exists() is False
