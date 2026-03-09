"""Tests for TableProxy."""

import pytest
from sqlalchemy import Column, Integer, MetaData, String, Boolean, Table, text
from sqlalchemy.ext.asyncio import create_async_engine

from penguin_dal.field_proxy import FieldProxy
from penguin_dal.table_proxy import TableProxy


class TestTableProxy:
    def test_getattr_returns_field_proxy(self, db):
        field = db.users.email
        assert isinstance(field, FieldProxy)

    def test_getattr_nonexistent_raises(self, db):
        with pytest.raises(AttributeError, match="no column"):
            db.users.nonexistent_column

    def test_getattr_private_raises(self, db):
        with pytest.raises(AttributeError):
            db.users._private

    def test_table_name_property(self, db):
        proxy = db.users
        assert proxy.table_name == "users"

    def test_table_property(self, db):
        proxy = db.users
        assert proxy.table is not None
        assert str(proxy.table.name) == "users"

    def test_repr(self, db):
        assert "users" in repr(db.users)

    def test_bulk_insert_empty(self, db):
        """Empty bulk_insert should be a no-op."""
        initial_count = db(db.users.id > 0).count()
        db.users.bulk_insert([])
        assert db(db.users.id > 0).count() == initial_count


def _create_composite_pk_tables(conn):
    metadata = MetaData()
    Table(
        "tags",
        metadata,
        Column("post_id", Integer, primary_key=True),
        Column("tag_name", String(255), primary_key=True),
    )
    metadata.create_all(conn)


class TestTableProxyCompositePK:
    def test_pk_lookup_composite_raises(self):
        """PK lookup with composite PK should raise ValueError."""
        from sqlalchemy import create_engine
        from sqlalchemy.orm import sessionmaker
        from penguin_dal.db import DB

        eng = create_engine("sqlite://", echo=False)
        metadata = MetaData()
        Table(
            "tags",
            metadata,
            Column("post_id", Integer, primary_key=True),
            Column("tag_name", String(255), primary_key=True),
        )
        metadata.create_all(eng)

        d = DB.__new__(DB)
        d._uri = "sqlite://"
        d._engine = eng
        d._session_factory = sessionmaker(bind=eng)
        d._metadata = MetaData()
        d._metadata.reflect(bind=eng)
        d._validators = {}
        d._models = {}

        with pytest.raises(ValueError, match="single-column PK"):
            d.tags[1]


def _create_async_tables(conn):
    metadata = MetaData()
    Table(
        "items",
        metadata,
        Column("id", Integer, primary_key=True, autoincrement=True),
        Column("name", String(255), nullable=False),
    )
    metadata.create_all(conn)


@pytest.fixture
async def async_db_for_proxy():
    """Create an AsyncDB for testing async table proxy operations."""
    from penguin_dal.db import AsyncDB

    db = AsyncDB("sqlite://", pool_size=5, echo=False)
    async with db.engine.begin() as conn:
        await conn.run_sync(_create_async_tables)
        await conn.execute(text("INSERT INTO items (name) VALUES ('item1'), ('item2')"))
    await db.reflect()
    yield db
    await db.close()


class TestTableProxyAsync:
    async def test_async_insert(self, async_db_for_proxy):
        db = async_db_for_proxy
        pk = await db.items.async_insert(name="item3")
        assert pk is not None
        count = await db(db.items.id > 0).count()
        assert count == 3

    async def test_async_bulk_insert(self, async_db_for_proxy):
        db = async_db_for_proxy
        await db.items.async_bulk_insert([
            {"name": "item3"},
            {"name": "item4"},
        ])
        count = await db(db.items.id > 0).count()
        assert count == 4

    async def test_async_bulk_insert_empty(self, async_db_for_proxy):
        db = async_db_for_proxy
        await db.items.async_bulk_insert([])
        count = await db(db.items.id > 0).count()
        assert count == 2

    async def test_async_insert_with_validators(self, async_db_for_proxy):
        db = async_db_for_proxy
        db.register_validators("items", {"name": [lambda x: None]})
        pk = await db.items.async_insert(name="validated_item")
        assert pk is not None

    async def test_async_bulk_insert_with_validators(self, async_db_for_proxy):
        db = async_db_for_proxy
        db.register_validators("items", {"name": [lambda x: None]})
        await db.items.async_bulk_insert([{"name": "v1"}, {"name": "v2"}])
        count = await db(db.items.id > 0).count()
        assert count == 4
