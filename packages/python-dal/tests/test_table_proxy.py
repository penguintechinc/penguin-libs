"""Tests for TableProxy."""

from penguin_dal.field_proxy import FieldProxy
from penguin_dal.table_proxy import TableProxy
import pytest


class TestTableProxy:
    def test_getattr_returns_field_proxy(self, db):
        field = db.users.email
        assert isinstance(field, FieldProxy)

    def test_getattr_nonexistent_raises(self, db):
        with pytest.raises(AttributeError, match="no column"):
            db.users.nonexistent_column

    def test_table_name(self, db):
        assert db.users.table_name == "users"

    def test_repr(self, db):
        assert "users" in repr(db.users)
