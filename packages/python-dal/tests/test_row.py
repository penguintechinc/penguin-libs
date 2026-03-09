"""Tests for Row and Rows."""

from penguin_dal.query import Row, Rows


class TestRow:
    def test_attribute_access(self):
        row = Row({"id": 1, "name": "Alice"})
        assert row.id == 1
        assert row.name == "Alice"

    def test_dict_access(self):
        row = Row({"id": 1, "name": "Alice"})
        assert row["id"] == 1

    def test_attribute_error(self):
        row = Row({"id": 1})
        import pytest
        with pytest.raises(AttributeError, match="no column"):
            row.nonexistent

    def test_contains(self):
        row = Row({"id": 1, "name": "Alice"})
        assert "id" in row
        assert "missing" not in row

    def test_iter(self):
        row = Row({"id": 1, "name": "Alice"})
        assert list(row) == ["id", "name"]

    def test_len(self):
        row = Row({"id": 1, "name": "Alice"})
        assert len(row) == 2

    def test_as_dict(self):
        data = {"id": 1, "name": "Alice"}
        row = Row(data)
        assert row.as_dict() == data

    def test_get(self):
        row = Row({"id": 1})
        assert row.get("id") == 1
        assert row.get("missing", "default") == "default"

    def test_keys_values_items(self):
        row = Row({"id": 1, "name": "Alice"})
        assert row.keys() == ["id", "name"]
        assert row.values() == [1, "Alice"]
        assert row.items() == [("id", 1), ("name", "Alice")]

    def test_eq(self):
        r1 = Row({"id": 1})
        r2 = Row({"id": 1})
        r3 = Row({"id": 2})
        assert r1 == r2
        assert r1 != r3

    def test_repr(self):
        row = Row({"id": 1})
        assert "Row(" in repr(row)


class TestRows:
    def test_first(self):
        rows = Rows([Row({"id": 1}), Row({"id": 2})])
        assert rows.first().id == 1

    def test_first_empty(self):
        rows = Rows([])
        assert rows.first() is None

    def test_last(self):
        rows = Rows([Row({"id": 1}), Row({"id": 2})])
        assert rows.last().id == 2

    def test_len(self):
        rows = Rows([Row({"id": 1}), Row({"id": 2})])
        assert len(rows) == 2

    def test_iter(self):
        rows = Rows([Row({"id": 1}), Row({"id": 2})])
        ids = [r.id for r in rows]
        assert ids == [1, 2]

    def test_getitem(self):
        rows = Rows([Row({"id": 1}), Row({"id": 2})])
        assert rows[1].id == 2

    def test_bool(self):
        assert bool(Rows([Row({"id": 1})])) is True
        assert bool(Rows([])) is False

    def test_as_list(self):
        rows = Rows([Row({"id": 1}), Row({"id": 2})])
        result = rows.as_list()
        assert result == [{"id": 1}, {"id": 2}]

    def test_repr(self):
        rows = Rows([Row({"id": 1})])
        assert "1 rows" in repr(rows)
