"""Cursor-based and offset pagination helpers."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from penguin_dal.query import Rows


@dataclass(slots=True, frozen=True)
class Cursor:
    """Cursor for keyset pagination.

    Args:
        after: Value of the cursor column to start after (exclusive).
        size: Number of rows to return.
    """

    after: Any = None
    size: int = 25


@dataclass(slots=True, frozen=True)
class Page:
    """Result of a cursor-paginated query.

    Attributes:
        rows: The rows in this page.
        next_cursor: Cursor value for fetching the next page, or None.
        has_more: Whether more rows exist after this page.
    """

    rows: Rows
    next_cursor: Any
    has_more: bool

    def as_list(self) -> list[dict[str, Any]]:
        """Convert page rows to list of dicts."""
        return self.rows.as_list()


def paginate_query(
    queryset: Any,
    cursor_column: Any,
    cursor: Cursor,
) -> Page:
    """Execute a cursor-paginated query (sync).

    Fetches cursor.size + 1 rows to determine has_more.

    Args:
        queryset: A QuerySet instance.
        cursor_column: FieldProxy for the cursor column.
        cursor: Cursor with after and size.

    Returns:
        Page with rows, next_cursor, and has_more.
    """
    from penguin_dal.field_proxy import FieldProxy
    from penguin_dal.query import QuerySet

    # Build the query with cursor constraint
    if cursor.after is not None:
        cursor_query = cursor_column > cursor.after
        if queryset._query is not None:
            combined = queryset._query & cursor_query
        else:
            combined = cursor_query
        qs = QuerySet(queryset._table, combined, queryset._session_factory)
    else:
        qs = queryset

    # Fetch one extra row to check has_more
    col = cursor_column.column if isinstance(cursor_column, FieldProxy) else cursor_column
    rows = qs.select(orderby=col, limitby=(0, cursor.size + 1))

    has_more = len(rows) > cursor.size
    result_rows = Rows(list(rows)[: cursor.size])

    next_cursor = None
    if has_more and result_rows:
        last_row = result_rows.last()
        if last_row is not None:
            col_name = (
                cursor_column.name if isinstance(cursor_column, FieldProxy) else str(col.name)
            )
            next_cursor = last_row[col_name]

    return Page(rows=result_rows, next_cursor=next_cursor, has_more=has_more)


async def async_paginate_query(
    queryset: Any,
    cursor_column: Any,
    cursor: Cursor,
) -> Page:
    """Execute a cursor-paginated query (async).

    Args:
        queryset: An AsyncQuerySet instance.
        cursor_column: FieldProxy for the cursor column.
        cursor: Cursor with after and size.

    Returns:
        Page with rows, next_cursor, and has_more.
    """
    from penguin_dal.field_proxy import FieldProxy
    from penguin_dal.query import AsyncQuerySet

    if cursor.after is not None:
        cursor_query = cursor_column > cursor.after
        if queryset._query is not None:
            combined = queryset._query & cursor_query
        else:
            combined = cursor_query
        qs = AsyncQuerySet(queryset._table, combined, queryset._session_factory)
    else:
        qs = queryset

    col = cursor_column.column if isinstance(cursor_column, FieldProxy) else cursor_column
    rows = await qs.select(orderby=col, limitby=(0, cursor.size + 1))

    has_more = len(rows) > cursor.size
    result_rows = Rows(list(rows)[: cursor.size])

    next_cursor = None
    if has_more and result_rows:
        last_row = result_rows.last()
        if last_row is not None:
            col_name = (
                cursor_column.name if isinstance(cursor_column, FieldProxy) else str(col.name)
            )
            next_cursor = last_row[col_name]

    return Page(rows=result_rows, next_cursor=next_cursor, has_more=has_more)
