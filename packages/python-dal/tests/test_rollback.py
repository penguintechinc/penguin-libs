"""Tests for DB.rollback() / AsyncDB.rollback() (gh-68).

Both are documented no-ops (per-statement autocommit; only
DB.transaction() is atomic and rolls back internally on exception).
They exist so the PyDAL ``except: db.rollback(); raise`` idiom no longer
falls through DB.__getattr__ and masks the caller's real exception behind
a TableNotFoundError for a nonexistent "rollback" table.
"""

import pytest

from penguin_dal.exceptions import TableNotFoundError


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

    def test_table_named_rollback_no_longer_reachable_via_getattr(self, db):
        """Compat note: a real method shadows __getattr__ table routing.

        A table literally named "rollback" would no longer be reachable
        as db.rollback (it resolves to the method). It remains reachable
        via db.tables / db._get_table. This is the documented, accepted
        compat tradeoff from gh-68.
        """
        assert db.rollback() is None
        with pytest.raises(TableNotFoundError):
            db._get_table("rollback")


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
