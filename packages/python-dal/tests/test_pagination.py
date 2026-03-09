"""Tests for pagination helpers."""

import pytest
from sqlalchemy import Column, Integer, MetaData, String, Boolean, Table, text

from penguin_dal.pagination import Cursor, Page, async_paginate_query, paginate_query


class TestPagination:
    def test_cursor_defaults(self):
        c = Cursor()
        assert c.after is None
        assert c.size == 25

    def test_first_page(self, db):
        qs = db(db.users.id > 0)
        page = paginate_query(qs, db.users.id, Cursor(size=2))
        assert isinstance(page, Page)
        assert len(page.rows) == 2
        assert page.has_more is True
        assert page.next_cursor is not None

    def test_last_page(self, db):
        qs = db(db.users.id > 0)
        page = paginate_query(qs, db.users.id, Cursor(size=10))
        assert len(page.rows) == 3
        assert page.has_more is False
        assert page.next_cursor is None

    def test_cursor_after(self, db):
        qs = db(db.users.id > 0)
        page1 = paginate_query(qs, db.users.id, Cursor(size=1))
        assert len(page1.rows) == 1
        assert page1.has_more is True

        page2 = paginate_query(qs, db.users.id, Cursor(after=page1.next_cursor, size=1))
        assert len(page2.rows) == 1
        assert page2.rows[0].id != page1.rows[0].id

    def test_as_list(self, db):
        qs = db(db.users.id > 0)
        page = paginate_query(qs, db.users.id, Cursor(size=2))
        result = page.as_list()
        assert isinstance(result, list)
        assert len(result) == 2
        assert "id" in result[0]

    def test_no_query_cursor_after(self, db):
        """Test paginate_query with cursor.after but no existing query on queryset."""
        from penguin_dal.query import QuerySet

        table = db._metadata.tables["users"]
        qs = QuerySet(table, None, db._session_factory)
        page = paginate_query(qs, db.users.id, Cursor(after=1, size=10))
        assert isinstance(page, Page)
        assert len(page.rows) == 2  # Bob and Charlie (id > 1)


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
async def async_db_for_pagination():
    """Create an AsyncDB for testing async pagination."""
    from penguin_dal.db import AsyncDB

    db = AsyncDB("sqlite://", pool_size=5, echo=False)
    async with db.engine.begin() as conn:
        await conn.run_sync(_create_async_tables)
        await conn.execute(text(
            "INSERT INTO users (email, name, active) VALUES "
            "('alice@example.com', 'Alice', 1), "
            "('bob@example.com', 'Bob', 1), "
            "('charlie@example.com', 'Charlie', 0)"
        ))
    await db.reflect()
    yield db
    await db.close()


class TestAsyncPagination:
    async def test_async_first_page(self, async_db_for_pagination):
        db = async_db_for_pagination
        qs = db(db.users.id > 0)
        page = await async_paginate_query(qs, db.users.id, Cursor(size=2))
        assert isinstance(page, Page)
        assert len(page.rows) == 2
        assert page.has_more is True
        assert page.next_cursor is not None

    async def test_async_last_page(self, async_db_for_pagination):
        db = async_db_for_pagination
        qs = db(db.users.id > 0)
        page = await async_paginate_query(qs, db.users.id, Cursor(size=10))
        assert len(page.rows) == 3
        assert page.has_more is False
        assert page.next_cursor is None

    async def test_async_cursor_after(self, async_db_for_pagination):
        db = async_db_for_pagination
        qs = db(db.users.id > 0)
        page1 = await async_paginate_query(qs, db.users.id, Cursor(size=1))
        assert page1.has_more is True

        page2 = await async_paginate_query(
            qs, db.users.id, Cursor(after=page1.next_cursor, size=1)
        )
        assert len(page2.rows) == 1
        assert page2.rows[0].id != page1.rows[0].id

    async def test_async_no_query_cursor_after(self, async_db_for_pagination):
        """Test async_paginate_query with cursor.after but no existing query."""
        from penguin_dal.query import AsyncQuerySet

        db = async_db_for_pagination
        table = db._metadata.tables["users"]
        qs = AsyncQuerySet(table, None, db._session_factory)
        page = await async_paginate_query(qs, db.users.id, Cursor(after=1, size=10))
        assert isinstance(page, Page)
        assert len(page.rows) == 2
