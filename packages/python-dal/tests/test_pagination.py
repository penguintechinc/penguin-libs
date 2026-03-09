"""Tests for pagination helpers."""

from penguin_dal.pagination import Cursor, Page, paginate_query


class TestPagination:
    def test_cursor_defaults(self):
        c = Cursor()
        assert c.after is None
        assert c.size == 25

    def test_first_page(self, db):
        qs = db(db.users.id > 0)
        page = paginate_query(qs, db.users.id, Cursor(size=2))
        assert isinstance(page, Page)
        assert len(page.rows) == 2
        assert page.has_more is True
        assert page.next_cursor is not None

    def test_last_page(self, db):
        qs = db(db.users.id > 0)
        page = paginate_query(qs, db.users.id, Cursor(size=10))
        assert len(page.rows) == 3
        assert page.has_more is False
        assert page.next_cursor is None

    def test_cursor_after(self, db):
        qs = db(db.users.id > 0)
        page1 = paginate_query(qs, db.users.id, Cursor(size=1))
        assert len(page1.rows) == 1
        assert page1.has_more is True

        page2 = paginate_query(qs, db.users.id, Cursor(after=page1.next_cursor, size=1))
        assert len(page2.rows) == 1
        assert page2.rows[0].id != page1.rows[0].id

    def test_as_list(self, db):
        qs = db(db.users.id > 0)
        page = paginate_query(qs, db.users.id, Cursor(size=2))
        result = page.as_list()
        assert isinstance(result, list)
        assert len(result) == 2
        assert "id" in result[0]
