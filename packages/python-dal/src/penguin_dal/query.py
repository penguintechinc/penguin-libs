"""Query, QuerySet, AsyncQuerySet, Rows, and Row classes."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

from sqlalchemy import ColumnElement, and_, not_, or_


class Query:
    """Represents a composable SQL WHERE clause.

    Built from FieldProxy comparisons. Supports & (AND), | (OR), ~ (NOT).
    Immutable — each operation returns a new Query.
    """

    def __init__(self, clause: ColumnElement[bool], table: Any = None) -> None:
        self._clause = clause
        self._table = table

    @property
    def clause(self) -> ColumnElement[bool]:
        """Underlying SQLAlchemy clause element."""
        return self._clause

    @property
    def table(self) -> Any:
        """Table associated with this query, if known."""
        return self._table

    def __and__(self, other: Query) -> Query:
        tbl = self._table if self._table is not None else other._table
        return Query(and_(self._clause, other._clause), table=tbl)

    def __or__(self, other: Query) -> Query:
        tbl = self._table if self._table is not None else other._table
        return Query(or_(self._clause, other._clause), table=tbl)

    def __invert__(self) -> Query:
        return Query(not_(self._clause), table=self._table)

    def __repr__(self) -> str:
        return f"Query({self._clause!r})"


class Row:
    """Dict-backed row with attribute access.

    Provides both dict-style and attribute-style access to row data.
    Compatible with ElderBaseModel.from_row().
    """

    def __init__(self, data: dict[str, Any]) -> None:
        self._data = data

    def __getattr__(self, name: str) -> Any:
        if name.startswith("_"):
            raise AttributeError(name)
        try:
            return self._data[name]
        except KeyError:
            raise AttributeError(f"Row has no column '{name}'") from None

    def __getitem__(self, key: str) -> Any:
        return self._data[key]

    def __contains__(self, key: str) -> bool:
        return key in self._data

    def __iter__(self) -> Iterator[str]:
        return iter(self._data)

    def __len__(self) -> int:
        return len(self._data)

    def __eq__(self, other: object) -> bool:
        if isinstance(other, Row):
            return self._data == other._data
        return NotImplemented

    def __repr__(self) -> str:
        return f"Row({self._data!r})"

    def keys(self) -> list[str]:
        """Return column names."""
        return list(self._data.keys())

    def values(self) -> list[Any]:
        """Return column values."""
        return list(self._data.values())

    def items(self) -> list[tuple[str, Any]]:
        """Return (column, value) pairs."""
        return list(self._data.items())

    def as_dict(self) -> dict[str, Any]:
        """Return a plain dict copy of the row data."""
        return dict(self._data)

    def get(self, key: str, default: Any = None) -> Any:
        """Get a column value with optional default."""
        return self._data.get(key, default)


class Rows:
    """List-like container of Row objects.

    Supports .first(), len(), iteration, indexing, and bool checks.
    """

    def __init__(self, rows: list[Row]) -> None:
        self._rows = rows

    def first(self) -> Row | None:
        """Return the first row, or None if empty."""
        return self._rows[0] if self._rows else None

    def last(self) -> Row | None:
        """Return the last row, or None if empty."""
        return self._rows[-1] if self._rows else None

    def as_list(self) -> list[dict[str, Any]]:
        """Convert all rows to a list of dicts."""
        return [r.as_dict() for r in self._rows]

    def __iter__(self) -> Iterator[Row]:
        return iter(self._rows)

    def __len__(self) -> int:
        return len(self._rows)

    def __getitem__(self, index: int) -> Row:
        return self._rows[index]

    def __bool__(self) -> bool:
        return len(self._rows) > 0

    def __repr__(self) -> str:
        return f"Rows({len(self._rows)} rows)"


class QuerySet:
    """Represents a filtered set of rows for sync operations.

    Created by DB.__call__(query). Provides select/update/delete/count.
    """

    def __init__(
        self,
        table: Any,
        query: Query | None,
        session_factory: Any,
    ) -> None:
        from sqlalchemy import delete as sa_delete
        from sqlalchemy import select as sa_select
        from sqlalchemy import update as sa_update

        self._table = table
        self._query = query
        self._session_factory = session_factory
        self._sa_select = sa_select
        self._sa_delete = sa_delete
        self._sa_update = sa_update

    def select(
        self,
        *columns: Any,
        orderby: Any = None,
        limitby: tuple[int, int] | None = None,
    ) -> Rows:
        """Execute SELECT and return Rows.

        Args:
            *columns: Specific FieldProxy or column objects to select.
                     If empty, selects all columns.
            orderby: Column or list of columns for ORDER BY.
            limitby: Tuple of (offset, limit) for pagination.

        Returns:
            Rows object containing the results.
        """
        from penguin_dal.field_proxy import FieldProxy

        if columns:
            cols = [c.column if isinstance(c, FieldProxy) else c for c in columns]
            stmt = self._sa_select(*cols)
        else:
            stmt = self._sa_select(self._table)

        if self._query is not None:
            stmt = stmt.where(self._query.clause)

        if orderby is not None:
            if isinstance(orderby, (list, tuple)):
                order_cols = []
                for o in orderby:
                    if isinstance(o, FieldProxy):
                        order_cols.append(o.column)
                    else:
                        order_cols.append(o)
                stmt = stmt.order_by(*order_cols)
            elif isinstance(orderby, FieldProxy):
                stmt = stmt.order_by(orderby.column)
            else:
                stmt = stmt.order_by(orderby)

        if limitby is not None:
            offset, limit = limitby
            stmt = stmt.offset(offset).limit(limit)

        with self._session_factory() as session:
            result = session.execute(stmt)
            rows = [Row(dict(r._mapping)) for r in result]
            return Rows(rows)

    def update(self, **kwargs: Any) -> int:
        """Execute UPDATE and return rowcount.

        Args:
            **kwargs: Column=value pairs to update.

        Returns:
            Number of rows updated.
        """
        stmt = self._sa_update(self._table)
        if self._query is not None:
            stmt = stmt.where(self._query.clause)
        stmt = stmt.values(**kwargs)

        with self._session_factory() as session:
            result = session.execute(stmt)
            session.commit()
            return result.rowcount  # type: ignore[return-value]

    def delete(self) -> int:
        """Execute DELETE and return rowcount.

        Returns:
            Number of rows deleted.
        """
        stmt = self._sa_delete(self._table)
        if self._query is not None:
            stmt = stmt.where(self._query.clause)

        with self._session_factory() as session:
            result = session.execute(stmt)
            session.commit()
            return result.rowcount  # type: ignore[return-value]

    def count(self) -> int:
        """Return count of matching rows."""
        from sqlalchemy import func

        stmt = self._sa_select(func.count()).select_from(self._table)
        if self._query is not None:
            stmt = stmt.where(self._query.clause)

        with self._session_factory() as session:
            result = session.execute(stmt)
            return result.scalar() or 0

    def exists(self) -> bool:
        """Check if any matching rows exist (efficient SELECT 1 LIMIT 1)."""
        from sqlalchemy import literal

        stmt = self._sa_select(literal(1)).select_from(self._table)
        if self._query is not None:
            stmt = stmt.where(self._query.clause)
        stmt = stmt.limit(1)

        with self._session_factory() as session:
            result = session.execute(stmt)
            return result.scalar() is not None


class AsyncQuerySet:
    """Represents a filtered set of rows for async operations.

    Created by AsyncDB.__call__(query). All methods are async.
    """

    def __init__(
        self,
        table: Any,
        query: Query | None,
        session_factory: Any,
    ) -> None:
        from sqlalchemy import delete as sa_delete
        from sqlalchemy import select as sa_select
        from sqlalchemy import update as sa_update

        self._table = table
        self._query = query
        self._session_factory = session_factory
        self._sa_select = sa_select
        self._sa_delete = sa_delete
        self._sa_update = sa_update

    async def select(
        self,
        *columns: Any,
        orderby: Any = None,
        limitby: tuple[int, int] | None = None,
    ) -> Rows:
        """Execute SELECT and return Rows (async).

        Args:
            *columns: Specific FieldProxy or column objects to select.
            orderby: Column or list of columns for ORDER BY.
            limitby: Tuple of (offset, limit) for pagination.

        Returns:
            Rows object containing the results.
        """
        from penguin_dal.field_proxy import FieldProxy

        if columns:
            cols = [c.column if isinstance(c, FieldProxy) else c for c in columns]
            stmt = self._sa_select(*cols)
        else:
            stmt = self._sa_select(self._table)

        if self._query is not None:
            stmt = stmt.where(self._query.clause)

        if orderby is not None:
            if isinstance(orderby, (list, tuple)):
                order_cols = []
                for o in orderby:
                    if isinstance(o, FieldProxy):
                        order_cols.append(o.column)
                    else:
                        order_cols.append(o)
                stmt = stmt.order_by(*order_cols)
            elif isinstance(orderby, FieldProxy):
                stmt = stmt.order_by(orderby.column)
            else:
                stmt = stmt.order_by(orderby)

        if limitby is not None:
            offset, limit = limitby
            stmt = stmt.offset(offset).limit(limit)

        async with self._session_factory() as session:
            result = await session.execute(stmt)
            rows = [Row(dict(r._mapping)) for r in result]
            return Rows(rows)

    async def update(self, **kwargs: Any) -> int:
        """Execute UPDATE and return rowcount (async)."""
        stmt = self._sa_update(self._table)
        if self._query is not None:
            stmt = stmt.where(self._query.clause)
        stmt = stmt.values(**kwargs)

        async with self._session_factory() as session:
            result = await session.execute(stmt)
            await session.commit()
            return result.rowcount  # type: ignore[return-value]

    async def delete(self) -> int:
        """Execute DELETE and return rowcount (async)."""
        stmt = self._sa_delete(self._table)
        if self._query is not None:
            stmt = stmt.where(self._query.clause)

        async with self._session_factory() as session:
            result = await session.execute(stmt)
            await session.commit()
            return result.rowcount  # type: ignore[return-value]

    async def count(self) -> int:
        """Return count of matching rows (async)."""
        from sqlalchemy import func

        stmt = self._sa_select(func.count()).select_from(self._table)
        if self._query is not None:
            stmt = stmt.where(self._query.clause)

        async with self._session_factory() as session:
            result = await session.execute(stmt)
            return result.scalar() or 0

    async def exists(self) -> bool:
        """Check if any matching rows exist (async)."""
        from sqlalchemy import literal

        stmt = self._sa_select(literal(1)).select_from(self._table)
        if self._query is not None:
            stmt = stmt.where(self._query.clause)
        stmt = stmt.limit(1)

        async with self._session_factory() as session:
            result = await session.execute(stmt)
            return result.scalar() is not None
