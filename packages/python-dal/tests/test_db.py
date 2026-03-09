"""Tests for DB (sync) entry point."""

from penguin_dal.db import DB
from penguin_dal.exceptions import TableNotFoundError
from penguin_dal.query import QuerySet, Row, Rows
from penguin_dal.table_proxy import TableProxy
import pytest


class TestDB:
    def test_init_sqlite_memory(self):
        db = DB("sqlite://")
        assert db.engine is not None
        assert isinstance(db.tables, dict)

    def test_getattr_returns_table_proxy(self, db):
        proxy = db.users
        assert isinstance(proxy, TableProxy)
        assert proxy.table_name == "users"

    def test_getattr_nonexistent_raises(self, db):
        with pytest.raises(TableNotFoundError, match="nonexistent"):
            db.nonexistent

    def test_call_returns_queryset(self, db):
        qs = db(db.users.active == True)
        assert isinstance(qs, QuerySet)

    def test_select_all(self, db):
        rows = db(db.users.id > 0).select()
        assert isinstance(rows, Rows)
        assert len(rows) == 3

    def test_select_with_filter(self, db):
        rows = db(db.users.active == True).select()
        assert len(rows) == 2

    def test_select_first(self, db):
        row = db(db.users.email == "alice@example.com").select().first()
        assert row is not None
        assert row.name == "Alice"
        assert row["email"] == "alice@example.com"

    def test_select_orderby(self, db):
        rows = db(db.users.id > 0).select(orderby=~db.users.name)
        assert rows[0].name == "Charlie"

    def test_select_limitby(self, db):
        rows = db(db.users.id > 0).select(limitby=(0, 2))
        assert len(rows) == 2

    def test_select_specific_columns(self, db):
        rows = db(db.users.id > 0).select(db.users.id, db.users.email)
        assert len(rows) == 3
        first = rows.first()
        assert "id" in first
        assert "email" in first

    def test_insert(self, db):
        pk = db.users.insert(email="dave@example.com", name="Dave", active=True)
        assert pk is not None
        row = db(db.users.email == "dave@example.com").select().first()
        assert row is not None
        assert row.name == "Dave"

    def test_update(self, db):
        count = db(db.users.email == "alice@example.com").update(name="Alice Updated")
        assert count == 1
        row = db(db.users.email == "alice@example.com").select().first()
        assert row.name == "Alice Updated"

    def test_delete(self, db):
        count = db(db.users.email == "charlie@example.com").delete()
        assert count == 1
        assert db(db.users.email == "charlie@example.com").count() == 0

    def test_count(self, db):
        assert db(db.users.active == True).count() == 2
        assert db(db.users.active == False).count() == 1

    def test_exists(self, db):
        assert db(db.users.email == "alice@example.com").exists() is True
        assert db(db.users.email == "nobody@example.com").exists() is False

    def test_pk_lookup(self, db):
        row = db.users[1]
        assert row is not None
        assert row.email == "alice@example.com"

    def test_pk_lookup_not_found(self, db):
        row = db.users[999]
        assert row is None

    def test_and_query(self, db):
        q = (db.users.active == True) & (db.users.name == "Alice")
        rows = db(q).select()
        assert len(rows) == 1
        assert rows[0].name == "Alice"

    def test_or_query(self, db):
        q = (db.users.name == "Alice") | (db.users.name == "Bob")
        rows = db(q).select()
        assert len(rows) == 2

    def test_not_query(self, db):
        q = ~(db.users.active == True)
        rows = db(q).select()
        assert len(rows) == 1
        assert rows[0].name == "Charlie"

    def test_contains(self, db):
        rows = db(db.users.email.contains("alice")).select()
        assert len(rows) == 1

    def test_startswith(self, db):
        rows = db(db.users.name.startswith("A")).select()
        assert len(rows) == 1

    def test_belongs(self, db):
        rows = db(db.users.id.belongs([1, 2])).select()
        assert len(rows) == 2

    def test_bulk_insert(self, db):
        db.users.bulk_insert([
            {"email": "x@example.com", "name": "X", "active": True},
            {"email": "y@example.com", "name": "Y", "active": True},
        ])
        assert db(db.users.id > 0).count() == 5

    def test_repr(self, db):
        assert "DB(" in repr(db)

    def test_close(self):
        db = DB("sqlite://")
        db.close()

    def test_commit_noop(self, db):
        db.commit()  # Should not raise

    def test_getattr_private_raises(self, db):
        with pytest.raises(AttributeError):
            db._private

    def test_extract_table_no_table(self, db):
        q = (db.users.id > 0)
        q._table = None
        with pytest.raises(ValueError, match="Cannot determine table"):
            db(q)

    def test_register_validators(self, db):
        db.register_validators("users", {"name": [lambda x: None]})
        assert "users" in db._validators

    def test_register_model(self, db):
        class FakeModel:
            __tablename__ = "users"
        db.register_model(FakeModel)
        assert "users" in db._models

    def test_register_model_no_tablename(self, db):
        class NoTable:
            pass
        with pytest.raises(ValueError, match="__tablename__"):
            db.register_model(NoTable)

    def test_metadata_property(self, db):
        assert db.metadata is not None
