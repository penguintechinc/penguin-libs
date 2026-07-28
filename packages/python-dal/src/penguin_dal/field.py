"""Field: PyDAL-compatible field definition that translates to SQLAlchemy columns."""

from __future__ import annotations

from typing import Any

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    Column,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    LargeBinary,
    Numeric,
    String,
    Text,
    Time,
)


class Field:
    """PyDAL-compatible field definition for use with define_table().

    Translates PyDAL field syntax to SQLAlchemy Column definitions.
    Supports type mappings, constraints, defaults, and validators.

    Example:
        db.define_table("users",
            Field("name", "string", length=128),
            Field("email", "string", notnull=True, unique=True),
            Field("age", "integer", default=0),
            Field("created_on", "datetime"),
            Field("ref_id", "reference other_table"),
        )

    Args:
        name: Field/column name.
        type: PyDAL type ('string', 'text', 'integer', 'date', 'datetime',
            'boolean', 'double', 'json', 'blob', 'reference', 'id', etc.).
        length: For 'string' type, max character length (default 512).
        default: Default value for the column.
        notnull: If True, NOT NULL constraint.
        unique: If True, UNIQUE constraint.
        requires: Validator functions (stored for later use).
        label: Display label (metadata, not enforced).
        comment: Column comment (metadata).
        readable: If True, column is readable (metadata).
        writable: If True, column is writable (metadata).
    """

    def __init__(
        self,
        name: str,
        type_: str = "string",
        length: int | None = None,
        default: Any = None,
        notnull: bool = False,
        unique: bool = False,
        requires: list[Any] | None = None,
        label: str | None = None,
        comment: str | None = None,
        readable: bool = True,
        writable: bool = True,
    ) -> None:
        self.name = name
        self.type_ = type_
        self.length = length
        self.default = default
        self.notnull = notnull
        self.unique = unique
        self.requires = requires or []
        self.label = label
        self.comment = comment
        self.readable = readable
        self.writable = writable

    def to_sa_column(self) -> Column[Any]:
        """Convert to a SQLAlchemy Column.

        Returns:
            A sqlalchemy.Column configured with appropriate type, constraints,
            and defaults.
        """
        sa_type = self._get_sa_type()
        kwargs: dict[str, Any] = {}

        # Add constraints
        if self.notnull:
            kwargs["nullable"] = False
        if self.unique:
            kwargs["unique"] = True
        if self.default is not None:
            kwargs["default"] = self.default

        # Handle special types (id = primary key, reference = foreign key)
        if self.type_ == "id":
            kwargs["primary_key"] = True
            kwargs["autoincrement"] = True

        col = Column(self.name, sa_type, **kwargs)

        # Add foreign key as a separate constraint if reference type
        if self.type_.startswith("reference"):
            ref_table = self.type_.split()[1]
            col = Column(self.name, sa_type, ForeignKey(f"{ref_table}.id"), **kwargs)

        return col

    def _get_sa_type(self) -> Any:
        """Map PyDAL type to SQLAlchemy type.

        Returns:
            A SQLAlchemy type class/instance.
        """
        type_base = self.type_.split()[0]  # Handle "reference table_name"

        # String types
        if type_base == "string":
            return String(self.length or 512)
        if type_base == "text":
            return Text()

        # Numeric types
        if type_base == "integer" or type_base == "id":
            return Integer()
        if type_base == "bigint":
            return BigInteger()
        if type_base == "float":
            return Float()
        if type_base == "double":
            return Float(precision=53)
        if type_base == "decimal":
            return Numeric()

        # Boolean
        if type_base == "boolean":
            return Boolean()

        # Date/time
        if type_base == "date":
            return Date()
        if type_base == "time":
            return Time()
        if type_base == "datetime":
            return DateTime()

        # Binary/JSON
        if type_base == "blob":
            return LargeBinary()
        if type_base == "json":
            return JSON()

        # List types (stored as JSON arrays)
        if type_base.startswith("list:"):
            return JSON()

        # Reference (foreign key)
        if type_base == "reference":
            return Integer()

        # Fallback to string
        return String(self.length or 512)

    def __repr__(self) -> str:
        return f"Field({self.name!r}, {self.type_!r})"
