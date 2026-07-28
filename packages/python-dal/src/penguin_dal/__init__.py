"""Penguin-DAL: SQLAlchemy runtime wrapper with PyDAL ergonomics."""

from penguin_dal.db import DB, AsyncDB, DatabaseManager
from penguin_dal.exceptions import DALError, TableNotFoundError, ValidationError
from penguin_dal.field import Field
from penguin_dal.field_proxy import FieldProxy
from penguin_dal.pagination import Cursor, Page
from penguin_dal.query import AsyncQuerySet, Query, QuerySet, Row, Rows
from penguin_dal.table_proxy import TableProxy
from penguin_dal.validators import (
    IS_DATETIME,
    IS_EMAIL,
    IS_IN_DB,
    IS_IN_SET,
    IS_INT_IN_RANGE,
    IS_IPADDRESS,
    IS_JSON,
    IS_LENGTH,
    IS_MATCH,
    IS_NOT_EMPTY,
    IS_NOT_IN_DB,
    IS_NULL_OR,
    validated_columns,
)

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
    # validators
    "validated_columns",
    "IS_NOT_EMPTY",
    "IS_LENGTH",
    "IS_EMAIL",
    "IS_IN_SET",
    "IS_MATCH",
    "IS_NOT_IN_DB",
    "IS_IN_DB",
    "IS_INT_IN_RANGE",
    "IS_IPADDRESS",
    "IS_JSON",
    "IS_DATETIME",
    "IS_NULL_OR",
]
