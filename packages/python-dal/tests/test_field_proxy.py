"""Tests for FieldProxy."""

from penguin_dal.field_proxy import FieldProxy
from penguin_dal.query import Query


class TestFieldProxy:
    def test_eq(self, db):
        q = db.users.id == 1
        assert isinstance(q, Query)

    def test_ne(self, db):
        q = db.users.id != 1
        assert isinstance(q, Query)

    def test_gt(self, db):
        q = db.users.id > 1
        assert isinstance(q, Query)

    def test_lt(self, db):
        q = db.users.id < 1
        assert isinstance(q, Query)

    def test_ge(self, db):
        q = db.users.id >= 1
        assert isinstance(q, Query)

    def test_le(self, db):
        q = db.users.id <= 1
        assert isinstance(q, Query)

    def test_eq_none(self, db):
        q = db.users.name == None
        assert isinstance(q, Query)

    def test_ne_none(self, db):
        q = db.users.name != None
        assert isinstance(q, Query)

    def test_like(self, db):
        q = db.users.email.like("%@example.com")
        assert isinstance(q, Query)

    def test_ilike(self, db):
        q = db.users.email.ilike("%EXAMPLE%")
        assert isinstance(q, Query)

    def test_contains(self, db):
        q = db.users.email.contains("alice")
        assert isinstance(q, Query)

    def test_startswith(self, db):
        q = db.users.name.startswith("A")
        assert isinstance(q, Query)

    def test_endswith(self, db):
        q = db.users.name.endswith("e")
        assert isinstance(q, Query)

    def test_belongs(self, db):
        q = db.users.id.belongs([1, 2, 3])
        assert isinstance(q, Query)

    def test_invert_desc(self, db):
        desc = ~db.users.id
        assert desc is not None

    def test_pos_asc(self, db):
        asc = +db.users.id
        assert asc is not None

    def test_name(self, db):
        assert db.users.email.name == "email"

    def test_lower(self, db):
        lowered = db.users.name.lower()
        assert isinstance(lowered, FieldProxy)

    def test_upper(self, db):
        uppered = db.users.name.upper()
        assert isinstance(uppered, FieldProxy)

    def test_asc(self, db):
        asc_col = db.users.id.asc()
        assert asc_col is not None

    def test_desc(self, db):
        desc_col = db.users.id.desc()
        assert desc_col is not None

    def test_repr(self, db):
        assert "FieldProxy" in repr(db.users.id)
