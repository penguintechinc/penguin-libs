"""FieldProxy: column-level comparison operators with PyDAL ergonomics."""

from __future__ import annotations

from typing import Any, Sequence

from sqlalchemy import Column, func

from penguin_dal.query import Query


class FieldProxy:
    """Wraps a SQLAlchemy Column to provide PyDAL-style comparison operators.

    Supports ==, !=, >, <, >=, <= returning Query objects.
    Also provides string helpers and sort direction via __invert__ (desc)
    and __pos__ (asc).
    """

    def __init__(self, column: Column[Any]) -> None:
        self._column = column

    @property
    def name(self) -> str:
        """Column name."""
        return str(self._column.name)

    @property
    def column(self) -> Column[Any]:
        """Underlying SQLAlchemy column."""
        return self._column

    @property
    def _table(self) -> Any:
        """Parent table of the column, if available."""
        return getattr(self._column, "table", None)

    def _query(self, clause: Any) -> Query:
        """Create a Query with table reference."""
        return Query(clause, table=self._table)

    # --- Comparison operators ---

    def __eq__(self, other: Any) -> Query:  # type: ignore[override]
        if other is None:
            return self._query(self._column.is_(None))
        return self._query(self._column == other)

    def __ne__(self, other: Any) -> Query:  # type: ignore[override]
        if other is None:
            return self._query(self._column.is_not(None))
        return self._query(self._column != other)

    def __gt__(self, other: Any) -> Query:
        return self._query(self._column > other)

    def __lt__(self, other: Any) -> Query:
        return self._query(self._column < other)

    def __ge__(self, other: Any) -> Query:
        return self._query(self._column >= other)

    def __le__(self, other: Any) -> Query:
        return self._query(self._column <= other)

    # --- String helpers ---

    def like(self, pattern: str) -> Query:
        """SQL LIKE comparison."""
        return self._query(self._column.like(pattern))

    def ilike(self, pattern: str) -> Query:
        """Case-insensitive LIKE (ILIKE)."""
        return self._query(self._column.ilike(pattern))

    def contains(self, value: str) -> Query:
        """Check if column contains substring (case-insensitive)."""
        return self._query(self._column.ilike(f"%{value}%"))

    def startswith(self, value: str) -> Query:
        """Check if column starts with value."""
        return self._query(self._column.like(f"{value}%"))

    def endswith(self, value: str) -> Query:
        """Check if column ends with value."""
        return self._query(self._column.like(f"%{value}"))

    def belongs(self, values: Sequence[Any]) -> Query:
        """SQL IN operator."""
        return self._query(self._column.in_(values))

    def lower(self) -> FieldProxy:
        """Return a proxy wrapping LOWER(column)."""
        return FieldProxy(func.lower(self._column))

    def upper(self) -> FieldProxy:
        """Return a proxy wrapping UPPER(column)."""
        return FieldProxy(func.upper(self._column))

    # --- Sort direction ---

    def __invert__(self) -> Any:
        """~field => descending order."""
        return self._column.desc()

    def __pos__(self) -> Any:
        """+field => ascending order (explicit)."""
        return self._column.asc()

    def asc(self) -> Any:
        """Ascending order."""
        return self._column.asc()

    def desc(self) -> Any:
        """Descending order."""
        return self._column.desc()

    def __repr__(self) -> str:
        return f"FieldProxy({self._column!r})"
