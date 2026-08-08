"""Tests for DB.rollback() / AsyncDB.rollback() (gh-68).

Both are documented no-ops (per-statement autocommit; only
DB.transaction() is atomic and rolls back internally on exception).
They exist so the PyDAL ``except: db.rollback(); raise`` idiom no longer
falls through DB.__getattr__ and masks the caller's real exception behind
a TableNotFoundError for a nonexistent "rollback" table.
"""

import pytest
from sqlalchemy import Column, Integer, MetaData, String, Table, create_engine
from sqlalchemy.orm import sessionmaker

from penguin_dal.db import DB
from penguin_dal.table_proxy import TableProxy


class TestDBRollback:
    def test_rollback_is_noop(self, db):
        """rollback() must not raise and must not touch data."""
        before = db(db.users.id > 0).count()
        assert db.rollback() is None
        after = db(db.users.id > 0).count()
        assert after == before

    def test_rollback_does_not_shadow_valid_table_lookup(self, db):
        """Sanity: normal table attribute access is unaffected."""
        assert db.users.table_name == "users"

    def test_pydal_idiom_preserves_original_exception(self, db):
        """The classic PyDAL pattern: except: db.rollback(); raise.

        Before gh-68, db.rollback() raised TableNotFoundError (routed
        through __getattr__), masking whatever exception the except
        block was handling. Now it's a real no-op method, so the
        original exception propagates untouched.
        """

        class BoomError(Exception):
            pass

        with pytest.raises(BoomError, match="original failure"):
            try:
                raise BoomError("original failure")
            except BoomError:
                db.rollback()
                raise

    def test_table_named_rollback_shadowed_by_method(self):
        """Compat note: a real method shadows __getattr__ table routing.

        Build a DB against a schema that genuinely has a table named
        "rollback" (the `db` fixture doesn't have one, so this needs its
        own engine). db.rollback must resolve to the bound no-op method
        — not a TableProxy for that table — while the table itself
        remains fully reachable via db.tables / db._get_table. This is
        the documented, accepted compat tradeoff from gh-68.
        """
        eng = create_engine("sqlite://", echo=False)
        metadata = MetaData()
        Table(
            "rollback",
            metadata,
            Column("id", Integer, primary_key=True, autoincrement=True),
            Column("note", String(255)),
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

        # db.rollback resolves to the bound no-op method, not a
        # TableProxy wrapping the "rollback" table.
        assert not isinstance(d.rollback, TableProxy)
        assert callable(d.rollback)
        assert d.rollback() is None

        # The table itself is still fully reachable, just not via
        # attribute access (__getattr__ never fires — rollback is now a
        # real bound method).
        assert "rollback" in d.tables
        assert d._get_table("rollback").name == "rollback"


class TestAsyncDBRollback:
    async def test_rollback_is_noop(self, async_db):
        before = await async_db(async_db.users.id > 0).count()
        result = await async_db.rollback()
        assert result is None
        after = await async_db(async_db.users.id > 0).count()
        assert after == before

    async def test_pydal_idiom_preserves_original_exception(self, async_db):
        """Async equivalent: except: await db.rollback(); raise."""

        class BoomError(Exception):
            pass

        with pytest.raises(BoomError, match="original failure"):
            try:
                raise BoomError("original failure")
            except BoomError:
                await async_db.rollback()
                raise
