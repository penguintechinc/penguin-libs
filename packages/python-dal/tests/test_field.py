"""Tests for Field class."""

import pytest
from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    Column,
    Date,
    DateTime,
    Float,
    Integer,
    LargeBinary,
    Numeric,
    String,
    Text,
    Time,
)

from penguin_dal.field import Field


class TestFieldBasics:
    """Test Field instantiation and attributes."""

    def test_field_creation_defaults(self):
        f = Field("name")
        assert f.name == "name"
        assert f.type_ == "string"
        assert f.default is None
        assert f.notnull is False
        assert f.unique is False
        assert f.requires == []
        assert f.readable is True
        assert f.writable is True

    def test_field_creation_with_options(self):
        f = Field(
            "email",
            "string",
            length=255,
            notnull=True,
            unique=True,
            default="test@example.com",
            label="Email Address",
        )
        assert f.name == "email"
        assert f.type_ == "string"
        assert f.length == 255
        assert f.notnull is True
        assert f.unique is True
        assert f.default == "test@example.com"
        assert f.label == "Email Address"

    def test_field_with_validators(self):
        validators = [lambda x: x is not None, lambda x: len(x) > 0]
        f = Field("name", requires=validators)
        assert f.requires == validators


class TestFieldTypeMapping:
    """Test PyDAL type mapping to SQLAlchemy types."""

    def test_string_default_length(self):
        f = Field("name", "string")
        col = f.to_sa_column()
        assert isinstance(col.type, String)
        assert col.type.length == 512

    def test_string_custom_length(self):
        f = Field("name", "string", length=128)
        col = f.to_sa_column()
        assert isinstance(col.type, String)
        assert col.type.length == 128

    def test_text_type(self):
        f = Field("bio", "text")
        col = f.to_sa_column()
        assert isinstance(col.type, Text)

    def test_integer_type(self):
        f = Field("count", "integer")
        col = f.to_sa_column()
        assert isinstance(col.type, Integer)

    def test_bigint_type(self):
        f = Field("big_id", "bigint")
        col = f.to_sa_column()
        assert isinstance(col.type, BigInteger)

    def test_float_type(self):
        f = Field("price", "float")
        col = f.to_sa_column()
        assert isinstance(col.type, Float)

    def test_double_type(self):
        f = Field("score", "double")
        col = f.to_sa_column()
        assert isinstance(col.type, Float)
        assert col.type.precision == 53

    def test_decimal_type(self):
        f = Field("amount", "decimal")
        col = f.to_sa_column()
        assert isinstance(col.type, Numeric)

    def test_boolean_type(self):
        f = Field("is_active", "boolean")
        col = f.to_sa_column()
        assert isinstance(col.type, Boolean)

    def test_date_type(self):
        f = Field("birth_date", "date")
        col = f.to_sa_column()
        assert isinstance(col.type, Date)

    def test_time_type(self):
        f = Field("created_time", "time")
        col = f.to_sa_column()
        assert isinstance(col.type, Time)

    def test_datetime_type(self):
        f = Field("created_on", "datetime")
        col = f.to_sa_column()
        assert isinstance(col.type, DateTime)

    def test_blob_type(self):
        f = Field("photo", "blob")
        col = f.to_sa_column()
        assert isinstance(col.type, LargeBinary)

    def test_json_type(self):
        f = Field("data", "json")
        col = f.to_sa_column()
        assert isinstance(col.type, JSON)

    def test_list_string_type(self):
        f = Field("tags", "list:string")
        col = f.to_sa_column()
        assert isinstance(col.type, JSON)

    def test_list_integer_type(self):
        f = Field("ids", "list:integer")
        col = f.to_sa_column()
        assert isinstance(col.type, JSON)

    def test_list_reference_type(self):
        f = Field("ref_ids", "list:reference users")
        col = f.to_sa_column()
        assert isinstance(col.type, JSON)

    def test_unknown_type_defaults_to_string(self):
        f = Field("unknown", "unknown_type")
        col = f.to_sa_column()
        assert isinstance(col.type, String)


class TestFieldConstraints:
    """Test field constraints (notnull, unique, default)."""

    def test_notnull_constraint(self):
        f = Field("email", notnull=True)
        col = f.to_sa_column()
        assert col.nullable is False

    def test_unique_constraint(self):
        f = Field("email", unique=True)
        col = f.to_sa_column()
        assert col.unique is True

    def test_both_constraints(self):
        f = Field("email", notnull=True, unique=True)
        col = f.to_sa_column()
        assert col.nullable is False
        assert col.unique is True

    def test_default_value_integer(self):
        f = Field("age", "integer", default=0)
        col = f.to_sa_column()
        assert col.default.arg == 0

    def test_default_value_string(self):
        f = Field("status", "string", default="active")
        col = f.to_sa_column()
        assert col.default.arg == "active"

    def test_default_value_boolean(self):
        f = Field("is_active", "boolean", default=True)
        col = f.to_sa_column()
        assert col.default.arg is True

    def test_no_default_when_none(self):
        f = Field("name", "string")
        col = f.to_sa_column()
        assert col.default is None


class TestFieldSpecialTypes:
    """Test special field types (id, reference)."""

    def test_id_type_is_primary_key(self):
        f = Field("id", "id")
        col = f.to_sa_column()
        assert col.primary_key is True
        assert col.autoincrement is True
        assert isinstance(col.type, Integer)

    def test_reference_type(self):
        f = Field("user_id", "reference users")
        col = f.to_sa_column()
        assert isinstance(col.type, Integer)
        assert col.foreign_keys is not None
        assert len(col.foreign_keys) > 0

    def test_reference_foreign_key_format(self):
        f = Field("author_id", "reference users")
        col = f.to_sa_column()
        fk_list = list(col.foreign_keys)
        assert len(fk_list) == 1
        fk = fk_list[0]
        # Check the target table and column from the ForeignKey's _colspec
        assert fk._colspec == "users.id"


class TestFieldColumnAttributes:
    """Test SQLAlchemy Column attributes."""

    def test_column_name_preserved(self):
        f = Field("my_field", "string")
        col = f.to_sa_column()
        assert col.name == "my_field"

    def test_column_type_correct(self):
        f = Field("active", "boolean")
        col = f.to_sa_column()
        assert isinstance(col, Column)
        assert isinstance(col.type, Boolean)

    def test_column_is_sqlalchemy_column(self):
        f = Field("count", "integer")
        col = f.to_sa_column()
        assert isinstance(col, Column)


class TestFieldRepr:
    """Test Field repr."""

    def test_repr(self):
        f = Field("email", "string")
        assert repr(f) == "Field('email', 'string')"

    def test_repr_complex_type(self):
        f = Field("author_id", "reference users")
        assert repr(f) == "Field('author_id', 'reference users')"


class TestFieldIntegration:
    """Integration tests with multiple fields."""

    def test_multiple_fields_create_distinct_columns(self):
        fields = [
            Field("id", "id"),
            Field("email", "string", length=255, notnull=True, unique=True),
            Field("age", "integer", default=0),
            Field("is_active", "boolean", default=True),
            Field("created_on", "datetime"),
        ]
        columns = [f.to_sa_column() for f in fields]

        assert len(columns) == 5
        assert columns[0].primary_key is True
        assert columns[1].nullable is False
        assert columns[1].unique is True
        assert columns[2].default.arg == 0
        assert columns[3].default.arg is True
        assert isinstance(columns[4].type, DateTime)

    def test_table_like_schema_definition(self):
        """Simulate define_table() usage."""
        fields = [
            Field("id", "id"),
            Field("name", "string", length=128),
            Field("email", "string", notnull=True, unique=True),
            Field("age", "integer", default=0),
            Field("bio", "text"),
            Field("is_active", "boolean", default=True),
            Field("created_on", "datetime"),
            Field("score", "double"),
            Field("data", "json"),
            Field("photo", "blob"),
        ]

        columns = [f.to_sa_column() for f in fields]
        assert len(columns) == 10
        assert all(isinstance(c, Column) for c in columns)


class TestFieldValidators:
    """Test validator storage in Field."""

    def test_validators_stored(self):
        validators = [lambda x: x is not None]
        f = Field("name", requires=validators)
        assert f.requires == validators

    def test_multiple_validators(self):
        def not_empty(v):
            return len(v) > 0

        def no_spaces(v):
            return " " not in v

        validators = [not_empty, no_spaces]
        f = Field("name", requires=validators)
        assert len(f.requires) == 2
        assert f.requires[0] == not_empty
        assert f.requires[1] == no_spaces

    def test_empty_validators_by_default(self):
        f = Field("name")
        assert f.requires == []
