"""Tests for TableProxy."""

import asyncio
from asyncio import iscoroutine as asyncio_iscoroutine

import pytest
from sqlalchemy import Column, Integer, MetaData, String, Table, text

from penguin_dal.field_proxy import FieldProxy


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
        await db.items.async_bulk_insert(
            [
                {"name": "item3"},
                {"name": "item4"},
            ]
        )
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

    async def test_async_bulk_insert_parity_with_sync_bulk_insert(self, db, async_db_for_proxy):
        """async_bulk_insert() and sync bulk_insert() must behave the same way:

        both return None, and both insert exactly every row from the
        list in one call. Actually invokes both (sync bulk_insert() on
        the sync `db` fixture's users table, async_bulk_insert() on the
        async `items` table) rather than asserting one and assuming the
        other — a prior version of this test only called
        async_bulk_insert() and never touched sync bulk_insert() at all.
        """
        async_db = async_db_for_proxy
        sync_rows = [
            {"email": "parity-sync-1@example.com", "name": "ParitySync1", "active": True},
            {"email": "parity-sync-2@example.com", "name": "ParitySync2", "active": True},
        ]
        async_rows = [{"name": "parity-async-1"}, {"name": "parity-async-2"}]

        sync_before = db(db.users.id > 0).count()
        sync_result = db.users.bulk_insert(sync_rows)
        sync_after = db(db.users.id > 0).count()

        async_before = await async_db(async_db.items.id > 0).count()
        async_result = await async_db.items.async_bulk_insert(async_rows)
        async_after = await async_db(async_db.items.id > 0).count()

        # Same return-value contract: both are None.
        assert sync_result is None
        assert async_result is None

        # Same row-count-effect contract: exactly len(rows) new rows each.
        assert sync_after - sync_before == len(sync_rows)
        assert async_after - async_before == len(async_rows)


class TestTableProxyInsertOnAsyncTable:
    """gh-67 (2): insert() called on an is_async=True table.

    Investigation finding: insert() was genuinely broken on async tables
    before this fix — calling it raised TypeError immediately because
    `with self._session_factory() as session` can't open a sync context
    manager on an AsyncSession ("'AsyncSession' object does not support
    the context manager protocol"). No prior test exercised this path
    and nothing depended on that crash, so fixing it (delegate to
    async_insert(), return an awaitable) is compat-safe.
    """

    async def test_insert_on_async_table_returns_awaitable(self, async_db_for_proxy):
        db = async_db_for_proxy
        pending = db.items.insert(name="via-insert")
        # insert() on an async table returns a coroutine, not a PK, since
        # it can't block on the loop it's presumably being called from.
        assert asyncio_iscoroutine(pending)
        pk = await pending
        assert pk is not None
        count = await db(db.items.id > 0).count()
        assert count == 3

    async def test_insert_on_async_table_matches_async_insert_result_shape(
        self, async_db_for_proxy
    ):
        db = async_db_for_proxy
        pk_via_insert = await db.items.insert(name="via-insert-2")
        pk_via_async_insert = await db.items.async_insert(name="via-async-insert")
        assert isinstance(pk_via_insert, int)
        assert isinstance(pk_via_async_insert, int)


class TestTableProxyGetItemAsyncDualMode:
    """gh-67 (1): TableProxy.__getitem__ on an is_async=True table.

    Outside a running event loop, behavior is unchanged from before this
    fix (asyncio.get_event_loop().run_until_complete(), resolved
    immediately). Inside a running event loop, this used to
    unconditionally raise RuntimeError("This event loop is already
    running"); it now returns a coroutine for the caller to await
    instead, since nothing could ever succeed on that path before.
    """

    def test_getitem_outside_running_loop_unchanged(self, async_db_for_proxy):
        """Regression pin: sync access from outside a running loop must
        keep resolving immediately to Row | None, not a coroutine."""
        db = async_db_for_proxy
        with pytest.raises(RuntimeError):
            # Confirm the precondition this test relies on: no running
            # loop in this (synchronous) test function.
            asyncio.get_running_loop()

        row = db.items[1]
        assert not asyncio_iscoroutine(row)
        assert row is not None
        assert row.name == "item1"

        missing = db.items[999]
        assert missing is None

    async def test_getitem_inside_running_loop_returns_awaitable(self, async_db_for_proxy):
        """Previously this path always raised RuntimeError('This event
        loop is already running'). Now it returns an awaitable."""
        db = async_db_for_proxy
        pending = db.items[1]
        assert asyncio_iscoroutine(pending)
        row = await pending
        assert row is not None
        assert row.name == "item1"

    async def test_getitem_inside_running_loop_missing_pk_returns_none(self, async_db_for_proxy):
        db = async_db_for_proxy
        row = await db.items[999]
        assert row is None
