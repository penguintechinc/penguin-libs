"""Penguin-DAL: SQLAlchemy runtime wrapper with PyDAL ergonomics."""

from penguin_dal.db import DB, AsyncDB, DatabaseManager
from penguin_dal.exceptions import DALError, TableNotFoundError, ValidationError
from penguin_dal.field import Field
from penguin_dal.field_proxy import FieldProxy
from penguin_dal.pagination import Cursor, Page
from penguin_dal.query import AsyncQuerySet, Query, QuerySet, Row, Rows
from penguin_dal.table_proxy import TableProxy

# PyDAL compatibility aliases
DAL = DB

__all__ = [
    "DB",
    "DAL",
    "AsyncDB",
    "DatabaseManager",
    "Field",
    "TableProxy",
    "FieldProxy",
    "Query",
    "QuerySet",
    "AsyncQuerySet",
    "Row",
    "Rows",
    "Cursor",
    "Page",
    "DALError",
    "TableNotFoundError",
    "ValidationError",
]
