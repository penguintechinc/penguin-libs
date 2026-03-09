"""Tests for Query composition."""

from penguin_dal.query import Query


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
