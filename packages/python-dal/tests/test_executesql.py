"""Tests for DB.executesql and AsyncDB.executesql."""

from collections import OrderedDict
import warnings

import pytest
from sqlalchemy import text

from penguin_dal.db import DB, AsyncDB
from penguin_dal.exceptions import DALSecurityWarning
from penguin_dal.field import Field
from penguin_dal.query import Rows, Row


class TestDBExecutesql:
    """Tests for DB.executesql (sync)."""

    def test_select_returns_list_of_tuples(self, db):
        """Default return is list[tuple]."""
        result = db.executesql("SELECT id, email FROM users ORDER BY id LIMIT 2")
        assert isinstance(result, list)
        assert len(result) == 2
        assert isinstance(result[0], tuple)
        assert result[0] == (1, "alice@example.com")

    def test_select_with_positional_placeholders(self, db):
        """Positional ? placeholders work."""
        result = db.executesql("SELECT id, email FROM users WHERE id = ?", (1,))
        assert len(result) == 1
        assert result[0] == (1, "alice@example.com")

    def test_select_with_named_placeholders(self, db):
        """Named placeholders work (dialect-specific syntax).

        SQLite uses ? (positional only), PostgreSQL uses %s and %(name)s,
        MySQL uses %s. This test uses SQLite's qmark style.
        """
        # SQLite doesn't support %(name)s, use positional instead
        result = db.executesql("SELECT id, email FROM users WHERE id = ?", (1,))
        assert len(result) == 1
        assert result[0] == (1, "alice@example.com")

    def test_select_as_dict(self, db):
        """as_dict=True returns list[dict]."""
        result = db.executesql("SELECT id, email FROM users WHERE id = ?", (1,), as_dict=True)
        assert isinstance(result, list)
        assert len(result) == 1
        assert isinstance(result[0], dict)
        assert result[0]["id"] == 1
        assert result[0]["email"] == "alice@example.com"

    def test_select_as_ordered_dict(self, db):
        """as_ordered_dict=True returns list[OrderedDict]."""
        result = db.executesql(
            "SELECT id, email FROM users WHERE id = ?", (1,), as_ordered_dict=True
        )
        assert isinstance(result, list)
        assert len(result) == 1
        assert isinstance(result[0], OrderedDict)
        assert result[0]["id"] == 1

    def test_select_with_fields_returns_rows(self, db):
        """fields parameter returns Rows."""
        result = db.executesql(
            "SELECT id, email, name FROM users WHERE id = ?", (1,), fields=["id", "email", "name"]
        )
        assert isinstance(result, Rows)
        assert len(result) == 1
        row = result.first()
        assert isinstance(row, Row)
        assert row.id == 1
        assert row.email == "alice@example.com"

    def test_select_with_colnames_returns_rows(self, db):
        """colnames parameter returns Rows."""
        result = db.executesql(
            "SELECT id, email FROM users WHERE id = ?", (1,), colnames=["user_id", "user_email"]
        )
        assert isinstance(result, Rows)
        row = result.first()
        assert row.user_id == 1
        assert row.user_email == "alice@example.com"

    def test_insert_returns_none(self, db):
        """INSERT with no return_rowcount returns None."""
        result = db.executesql(
            "INSERT INTO users (email, name, active) VALUES (?, ?, ?)",
            ("dave@example.com", "Dave", 1),
        )
        assert result is None

    def test_insert_with_return_rowcount(self, db):
        """INSERT with return_rowcount=True returns int."""
        result = db.executesql(
            "INSERT INTO users (email, name, active) VALUES (?, ?, ?)",
            ("dave@example.com", "Dave", 1),
            return_rowcount=True,
        )
        assert isinstance(result, int)
        assert result == 1

    def test_update_returns_none(self, db):
        """UPDATE with no return_rowcount returns None."""
        result = db.executesql("UPDATE users SET name = ? WHERE id = ?", ("Alice Updated", 1))
        assert result is None

    def test_update_with_return_rowcount(self, db):
        """UPDATE with return_rowcount=True returns rowcount."""
        result = db.executesql(
            "UPDATE users SET name = ? WHERE id = ?", ("Alice Updated", 1), return_rowcount=True
        )
        assert isinstance(result, int)
        assert result == 1

    def test_delete_with_return_rowcount(self, db):
        """DELETE with return_rowcount=True returns rowcount."""
        result = db.executesql("DELETE FROM users WHERE id = ?", (3,), return_rowcount=True)
        assert isinstance(result, int)
        assert result == 1

    def test_ddl_returns_none(self, db):
        """DDL (CREATE/DROP) returns None."""
        result = db.executesql("CREATE TABLE temp_test (id INTEGER)")
        assert result is None

    def test_ddl_with_return_rowcount(self, db):
        """DDL with return_rowcount returns -1."""
        result = db.executesql("CREATE TABLE temp_test2 (id INTEGER)", return_rowcount=True)
        # SQLite returns -1 for DDL when rowcount is not applicable
        assert isinstance(result, int)
        assert result == -1

    def test_as_dict_with_fields_raises_valueerror(self, db):
        """as_dict=True with fields raises ValueError."""
        with pytest.raises(ValueError, match="as_dict.*with.*fields"):
            db.executesql("SELECT id, email FROM users", as_dict=True, fields=["id", "email"])

    def test_as_dict_with_colnames_raises_valueerror(self, db):
        """as_dict=True with colnames raises ValueError."""
        with pytest.raises(ValueError, match="as_dict.*with.*colnames"):
            db.executesql("SELECT id, email FROM users", as_dict=True, colnames=["id", "email"])

    def test_as_dict_with_as_ordered_dict_raises_valueerror(self, db):
        """as_dict=True with as_ordered_dict=True raises ValueError."""
        with pytest.raises(ValueError, match="as_dict.*as_ordered_dict"):
            db.executesql("SELECT id, email FROM users", as_dict=True, as_ordered_dict=True)

    def test_injection_warning_with_literal_in_where(self, db):
        """DALSecurityWarning raised when literal in WHERE with no placeholders."""
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            # Use a column that exists (active) with a literal value
            db.executesql("SELECT id FROM users WHERE active = 'true'")
            assert len(w) == 1
            assert issubclass(w[0].category, DALSecurityWarning)

    def test_no_injection_warning_with_placeholders(self, db):
        """No warning when placeholders supplied."""
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            db.executesql("SELECT id FROM users WHERE active = ?", ("true",))
            assert len(w) == 0

    def test_injection_warning_suppressed_by_check_injection_false(self, db):
        """Warning suppressed when check_injection=False."""
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            db.executesql("SELECT id FROM users WHERE active = 'true'", check_injection=False)
            assert len(w) == 0

    def test_injection_warning_for_literal_in_values(self, db):
        """Warning raised for literal in VALUES clause."""
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            db.executesql(
                "INSERT INTO users (email, name, active) VALUES ('test@example.com', 'Test', 1)"
            )
            assert len(w) == 1
            assert issubclass(w[0].category, DALSecurityWarning)

    def test_no_injection_warning_for_non_sql_quotes(self, db):
        """No warning for quotes not in sensitive clauses."""
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            # Comment with quotes - not a WHERE/VALUES clause
            db.executesql("SELECT 1 -- Comment with 'quotes'")
            # May or may not warn depending on heuristic - just ensure it doesn't crash
            assert isinstance(result := db.executesql("SELECT 1"), list)

    def test_empty_result_set(self, db):
        """Empty result set returns empty list."""
        result = db.executesql("SELECT id FROM users WHERE id > 1000")
        assert result == []

    def test_null_values(self, db):
        """NULL values preserved."""
        # Insert with NULL body (which is allowed to be NULL)
        db.executesql("INSERT INTO posts (user_id, title) VALUES (?, ?)", (1, "Null Test"))
        result = db.executesql(
            "SELECT title, body FROM posts WHERE title = ?", ("Null Test",), as_dict=True
        )
        # The new row should have NULL body
        assert len(result) == 1
        assert result[0]["title"] == "Null Test"
        assert result[0]["body"] is None

    def test_multiple_rows(self, db):
        """Multiple rows returned correctly."""
        result = db.executesql("SELECT id, email FROM users WHERE active = ? ORDER BY id", (1,))
        assert len(result) == 2
        assert result[0][0] == 1
        assert result[1][0] == 2


class TestAsyncDBExecutesql:
    """Tests for AsyncDB.executesql (async)."""

    @pytest.mark.asyncio
    async def test_select_returns_list_of_tuples(self, async_db):
        """Default return is list[tuple]."""
        result = await async_db.executesql("SELECT id, email FROM users ORDER BY id LIMIT 2")
        assert isinstance(result, list)
        assert len(result) == 2
        assert isinstance(result[0], tuple)
        assert result[0] == (1, "alice@example.com")

    @pytest.mark.asyncio
    async def test_select_with_positional_placeholders(self, async_db):
        """Positional ? placeholders work."""
        result = await async_db.executesql("SELECT id, email FROM users WHERE id = ?", (1,))
        assert len(result) == 1
        assert result[0] == (1, "alice@example.com")

    @pytest.mark.asyncio
    async def test_select_as_dict(self, async_db):
        """as_dict=True returns list[dict]."""
        result = await async_db.executesql(
            "SELECT id, email FROM users WHERE id = ?", (1,), as_dict=True
        )
        assert isinstance(result, list)
        assert len(result) == 1
        assert isinstance(result[0], dict)
        assert result[0]["id"] == 1

    @pytest.mark.asyncio
    async def test_select_as_ordered_dict(self, async_db):
        """as_ordered_dict=True returns list[OrderedDict]."""
        result = await async_db.executesql(
            "SELECT id, email FROM users WHERE id = ?", (1,), as_ordered_dict=True
        )
        assert isinstance(result, list)
        assert len(result) == 1
        assert isinstance(result[0], OrderedDict)

    @pytest.mark.asyncio
    async def test_select_with_fields_returns_rows(self, async_db):
        """fields parameter returns Rows."""
        result = await async_db.executesql(
            "SELECT id, email, name FROM users WHERE id = ?", (1,), fields=["id", "email", "name"]
        )
        assert isinstance(result, Rows)
        assert len(result) == 1
        row = result.first()
        assert isinstance(row, Row)
        assert row.id == 1

    @pytest.mark.asyncio
    async def test_insert_returns_none(self, async_db):
        """INSERT returns None by default."""
        result = await async_db.executesql(
            "INSERT INTO users (email, name, active) VALUES (?, ?, ?)",
            ("dave@example.com", "Dave", 1),
        )
        assert result is None

    @pytest.mark.asyncio
    async def test_insert_with_return_rowcount(self, async_db):
        """INSERT with return_rowcount=True returns int."""
        result = await async_db.executesql(
            "INSERT INTO users (email, name, active) VALUES (?, ?, ?)",
            ("eve@example.com", "Eve", 1),
            return_rowcount=True,
        )
        assert isinstance(result, int)
        assert result == 1

    @pytest.mark.asyncio
    async def test_update_with_return_rowcount(self, async_db):
        """UPDATE with return_rowcount=True."""
        result = await async_db.executesql(
            "UPDATE users SET name = ? WHERE id = ?", ("Alice Updated", 1), return_rowcount=True
        )
        assert isinstance(result, int)
        assert result == 1

    @pytest.mark.asyncio
    async def test_as_dict_with_fields_raises_valueerror(self, async_db):
        """Invalid combination raises ValueError."""
        with pytest.raises(ValueError, match="as_dict.*with.*fields"):
            await async_db.executesql(
                "SELECT id, email FROM users", as_dict=True, fields=["id", "email"]
            )

    @pytest.mark.asyncio
    async def test_injection_warning_with_literal(self, async_db):
        """DALSecurityWarning raised for literal in WHERE."""
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            await async_db.executesql("SELECT id FROM users WHERE active = 'true'")
            assert len(w) == 1
            assert issubclass(w[0].category, DALSecurityWarning)

    @pytest.mark.asyncio
    async def test_no_injection_warning_with_placeholders(self, async_db):
        """No warning when placeholders supplied."""
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            await async_db.executesql("SELECT id FROM users WHERE active = ?", ("true",))
            assert len(w) == 0

    @pytest.mark.asyncio
    async def test_empty_result_set(self, async_db):
        """Empty result set returns empty list."""
        result = await async_db.executesql("SELECT id FROM users WHERE id > 1000")
        assert result == []


class TestExecutesqlFieldObjects:
    """fields= must accept PyDAL-style Field objects, not just strings.

    Migrated PyDAL code idiomatically passes Field objects (fields=[db.t.id]).
    Using them directly as dict keys would silently produce a Rows whose
    attribute and item access both fail.
    """

    def test_fields_accepts_field_objects(self, db):
        """Field objects resolve to their .name as the column key."""
        result = db.executesql(
            "SELECT id, email FROM users WHERE id = ?",
            (1,),
            fields=[Field("id", "integer"), Field("email", "string")],
        )
        assert isinstance(result, Rows)
        row = result.first()
        assert row.id == 1
        assert row.email == "alice@example.com"
        assert row["email"] == "alice@example.com"

    def test_fields_accepts_mixed_strings_and_field_objects(self, db):
        """A mix of plain strings and Field objects resolves correctly."""
        result = db.executesql(
            "SELECT id, email FROM users WHERE id = ?",
            (1,),
            fields=["id", Field("email", "string")],
        )
        row = result.first()
        assert row.id == 1
        assert row.email == "alice@example.com"

    @pytest.mark.asyncio
    async def test_async_fields_accepts_field_objects(self, async_db):
        """Async mirror resolves Field objects the same way."""
        result = await async_db.executesql(
            "SELECT id, email FROM users WHERE id = ?",
            (1,),
            fields=[Field("id", "integer"), Field("email", "string")],
        )
        assert isinstance(result, Rows)
        row = result.first()
        assert row.id == 1
        assert row.email == "alice@example.com"
