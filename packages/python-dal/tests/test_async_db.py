"""Tests for AsyncDB."""

import pytest
from sqlalchemy import Column, Integer, MetaData, String, Boolean, Table, text
from sqlalchemy.ext.asyncio import create_async_engine

from penguin_dal.db import AsyncDB
from penguin_dal.query import AsyncQuerySet, Rows


@pytest.fixture
async def async_db():
    """Create an AsyncDB with in-memory SQLite."""
    db = AsyncDB("sqlite://", pool_size=5, echo=False)

    # Manually create tables since reflect needs them to exist
    async with db.engine.begin() as conn:
        await conn.run_sync(_create_tables)
        await conn.execute(text(
            "INSERT INTO users (email, name, active) VALUES "
            "('alice@example.com', 'Alice', 1), "
            "('bob@example.com', 'Bob', 1), "
            "('charlie@example.com', 'Charlie', 0)"
        ))

    await db.reflect()
    yield db
    await db.close()


def _create_tables(conn):
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


class TestAsyncDB:
    async def test_reflect(self, async_db):
        assert "users" in async_db.tables

    async def test_call_returns_async_queryset(self, async_db):
        qs = async_db(async_db.users.id > 0)
        assert isinstance(qs, AsyncQuerySet)

    async def test_select(self, async_db):
        rows = await async_db(async_db.users.id > 0).select()
        assert isinstance(rows, Rows)
        assert len(rows) == 3

    async def test_select_filter(self, async_db):
        rows = await async_db(async_db.users.active == True).select()
        assert len(rows) == 2

    async def test_select_first(self, async_db):
        row = (await async_db(async_db.users.email == "alice@example.com").select()).first()
        assert row is not None
        assert row.name == "Alice"

    async def test_insert(self, async_db):
        pk = await async_db.users.async_insert(
            email="dave@example.com", name="Dave", active=True
        )
        assert pk is not None
        count = await async_db(async_db.users.id > 0).count()
        assert count == 4

    async def test_update(self, async_db):
        count = await async_db(async_db.users.email == "alice@example.com").update(
            name="Alice Updated"
        )
        assert count == 1

    async def test_delete(self, async_db):
        count = await async_db(async_db.users.email == "charlie@example.com").delete()
        assert count == 1
        remaining = await async_db(async_db.users.id > 0).count()
        assert remaining == 2

    async def test_count(self, async_db):
        count = await async_db(async_db.users.active == True).count()
        assert count == 2

    async def test_exists(self, async_db):
        assert await async_db(async_db.users.email == "alice@example.com").exists() is True
        assert await async_db(async_db.users.email == "nobody@example.com").exists() is False

    async def test_bulk_insert(self, async_db):
        await async_db.users.async_bulk_insert([
            {"email": "x@example.com", "name": "X", "active": True},
            {"email": "y@example.com", "name": "Y", "active": True},
        ])
        count = await async_db(async_db.users.id > 0).count()
        assert count == 5

    async def test_commit_noop(self, async_db):
        await async_db.commit()  # Should not raise

    async def test_repr(self, async_db):
        assert "AsyncDB(" in repr(async_db)

    async def test_metadata_property(self, async_db):
        assert async_db.metadata is not None

    async def test_getattr_private_raises(self, async_db):
        with pytest.raises(AttributeError):
            async_db._private

    async def test_getattr_nonexistent_raises(self, async_db):
        from penguin_dal.exceptions import TableNotFoundError
        with pytest.raises(TableNotFoundError):
            async_db.nonexistent_table

    async def test_extract_table_no_table(self, async_db):
        q = (async_db.users.id > 0)
        q._table = None
        with pytest.raises(ValueError, match="Cannot determine table"):
            async_db(q)

    async def test_register_validators(self, async_db):
        async_db.register_validators("users", {"name": [lambda x: None]})
        assert "users" in async_db._validators

    async def test_register_model(self, async_db):
        class FakeModel:
            __tablename__ = "users"
        async_db.register_model(FakeModel)
        assert "users" in async_db._models

    async def test_register_model_with_validators(self, async_db):
        class ValidatedModel:
            __tablename__ = "users"
            _dal_validators = {"name": [lambda x: None]}
        async_db.register_model(ValidatedModel)
        assert "users" in async_db._validators

    async def test_register_model_no_tablename(self, async_db):
        class NoTable:
            pass
        with pytest.raises(ValueError, match="__tablename__"):
            async_db.register_model(NoTable)
