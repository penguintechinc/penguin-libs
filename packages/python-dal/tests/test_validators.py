"""Tests for validator integration and PyDAL-compatible validator classes."""

from __future__ import annotations

import pytest

from penguin_dal.exceptions import ValidationError
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


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def is_not_empty(value):
    """Legacy raise-style validator: rejects empty values."""
    if not value:
        raise ValueError("Value cannot be empty")


def is_email(value):
    """Legacy raise-style validator: checks for @ in email."""
    if "@" not in str(value):
        raise ValueError("Invalid email address")


# ---------------------------------------------------------------------------
# Legacy raise-style validators (backward-compat)
# ---------------------------------------------------------------------------


class TestLegacyValidators:
    def test_register_validators(self, db):
        db.register_validators(
            "users",
            {
                "email": [is_not_empty, is_email],
                "name": [is_not_empty],
            },
        )
        pk = db.users.insert(email="valid@test.com", name="Valid", active=True)
        assert pk is not None

    def test_validation_failure_on_insert(self, db):
        db.register_validators(
            "users",
            {
                "email": [is_email],
            },
        )
        with pytest.raises(ValidationError, match="Invalid email"):
            db.users.insert(email="not-an-email", name="Bad", active=True)

    def test_validated_columns_decorator(self, db):
        @validated_columns(
            {
                "email": [is_email],
                "name": [is_not_empty],
            }
        )
        class FakeModel:
            __tablename__ = "users"

        assert hasattr(FakeModel, "_dal_validators")
        db.register_model(FakeModel)

        with pytest.raises(ValidationError):
            db.users.insert(email="bad", name="Test", active=True)

    def test_register_model_without_tablename(self, db):
        class NoTable:
            pass

        with pytest.raises(ValueError, match="__tablename__"):
            db.register_model(NoTable)


# ---------------------------------------------------------------------------
# IS_NOT_EMPTY
# ---------------------------------------------------------------------------


class TestIsNotEmpty:
    def test_valid_string(self):
        v, err = IS_NOT_EMPTY()("hello")
        assert err is None

    def test_valid_zero(self):
        # 0 is falsy but it IS a meaningful value — not None/""/[]/{}
        # Our IS_NOT_EMPTY uses explicit equality checks rather than `not value`,
        # so integer 0 passes (unlike raw PyDAL which uses `not value`).
        _, err = IS_NOT_EMPTY()(0)
        assert err is None

    def test_none_fails(self):
        v, err = IS_NOT_EMPTY()(None)
        assert err is not None

    def test_empty_string_fails(self):
        v, err = IS_NOT_EMPTY()("")
        assert err is not None

    def test_empty_list_fails(self):
        v, err = IS_NOT_EMPTY()([])
        assert err is not None

    def test_empty_dict_fails(self):
        v, err = IS_NOT_EMPTY()({})
        assert err is not None

    def test_custom_message(self):
        _, err = IS_NOT_EMPTY(error_message="Required!")("")
        assert err == "Required!"

    def test_with_table_proxy(self, db):
        db.register_validators("users", {"name": [IS_NOT_EMPTY()]})
        with pytest.raises(ValidationError, match="Enter a value"):
            db.users.insert(email="a@b.com", name="", active=True)


# ---------------------------------------------------------------------------
# IS_LENGTH
# ---------------------------------------------------------------------------


class TestIsLength:
    def test_within_range(self):
        _, err = IS_LENGTH(maxsize=10, minsize=2)("hello")
        assert err is None

    def test_too_short(self):
        _, err = IS_LENGTH(maxsize=10, minsize=5)("hi")
        assert err is not None

    def test_too_long(self):
        _, err = IS_LENGTH(maxsize=3)("toolong")
        assert err is not None

    def test_exact_max(self):
        _, err = IS_LENGTH(maxsize=5)("hello")
        assert err is None

    def test_none_treated_as_empty_string(self):
        _, err = IS_LENGTH(minsize=1)(None)
        assert err is not None

    def test_custom_message(self):
        _, err = IS_LENGTH(maxsize=3, error_message="Too long!")("toolong")
        assert err == "Too long!"

    def test_default_max(self):
        _, err = IS_LENGTH()("x" * 255)
        assert err is None

    def test_over_default_max(self):
        _, err = IS_LENGTH()("x" * 256)
        assert err is not None


# ---------------------------------------------------------------------------
# IS_EMAIL
# ---------------------------------------------------------------------------


class TestIsEmail:
    def test_valid_email(self):
        _, err = IS_EMAIL()("user@example.com")
        assert err is None

    def test_missing_at(self):
        _, err = IS_EMAIL()("userexample.com")
        assert err is not None

    def test_missing_domain(self):
        _, err = IS_EMAIL()("user@")
        assert err is not None

    def test_none_fails(self):
        _, err = IS_EMAIL()(None)
        assert err is not None

    def test_subdomain(self):
        _, err = IS_EMAIL()("user@mail.example.co.uk")
        assert err is None

    def test_custom_message(self):
        _, err = IS_EMAIL(error_message="Bad email")("bad")
        assert err == "Bad email"

    def test_with_table_proxy(self, db):
        db.register_validators("users", {"email": [IS_EMAIL()]})
        with pytest.raises(ValidationError):
            db.users.insert(email="not-valid", name="Test", active=True)


# ---------------------------------------------------------------------------
# IS_IN_SET
# ---------------------------------------------------------------------------


class TestIsInSet:
    def test_valid_member(self):
        _, err = IS_IN_SET(["admin", "viewer"])("admin")
        assert err is None

    def test_invalid_member(self):
        _, err = IS_IN_SET(["admin", "viewer"])("superuser")
        assert err is not None

    def test_zero_placeholder_accepted(self):
        _, err = IS_IN_SET(["a", "b"], zero="")("")
        assert err is None

    def test_numeric_set(self):
        _, err = IS_IN_SET({1, 2, 3})(2)
        assert err is None

    def test_numeric_not_in_set(self):
        _, err = IS_IN_SET({1, 2, 3})(99)
        assert err is not None

    def test_custom_message(self):
        _, err = IS_IN_SET(["x"], error_message="Pick one")("y")
        assert err == "Pick one"


# ---------------------------------------------------------------------------
# IS_MATCH
# ---------------------------------------------------------------------------


class TestIsMatch:
    def test_valid_match(self):
        _, err = IS_MATCH(r"\d+")("12345")
        assert err is None

    def test_no_match(self):
        _, err = IS_MATCH(r"^\d+$", strict=True)("12a45")
        assert err is not None

    def test_strict_full_match(self):
        _, err = IS_MATCH(r"[a-z]+", strict=True)("hello")
        assert err is None

    def test_strict_partial_fails(self):
        _, err = IS_MATCH(r"[a-z]+", strict=True)("hello123")
        assert err is not None

    def test_non_strict_partial_passes(self):
        _, err = IS_MATCH(r"[a-z]+", strict=False)("hello123")
        assert err is None

    def test_none_coerced_to_empty_string(self):
        _, err = IS_MATCH(r".+", strict=True)(None)
        assert err is not None

    def test_custom_message(self):
        _, err = IS_MATCH(r"\d+", error_message="Digits only")("abc")
        assert err == "Digits only"


# ---------------------------------------------------------------------------
# IS_NOT_IN_DB
# ---------------------------------------------------------------------------


class TestIsNotInDb:
    def test_value_absent_passes(self, db):
        db.users.insert(email="taken@example.com", name="Alice", active=True)
        v = IS_NOT_IN_DB(db, "users.email")
        _, err = v("free@example.com")
        assert err is None

    def test_value_present_fails(self, db):
        db.users.insert(email="taken@example.com", name="Alice", active=True)
        v = IS_NOT_IN_DB(db, "users.email")
        _, err = v("taken@example.com")
        assert err is not None

    def test_invalid_field_format(self, db):
        with pytest.raises(ValueError, match="table.column"):
            IS_NOT_IN_DB(db, "users_email")

    def test_custom_message(self, db):
        db.users.insert(email="dup@example.com", name="Bob", active=True)
        _, err = IS_NOT_IN_DB(db, "users.email", error_message="Duplicate!")("dup@example.com")
        assert err == "Duplicate!"


# ---------------------------------------------------------------------------
# IS_IN_DB
# ---------------------------------------------------------------------------


class TestIsInDb:
    def test_value_present_passes(self, db):
        db.users.insert(email="exists@example.com", name="Carol", active=True)
        v = IS_IN_DB(db, "users.email")
        _, err = v("exists@example.com")
        assert err is None

    def test_value_absent_fails(self, db):
        v = IS_IN_DB(db, "users.email")
        _, err = v("ghost@example.com")
        assert err is not None

    def test_invalid_field_format(self, db):
        with pytest.raises(ValueError, match="table.column"):
            IS_IN_DB(db, "usersid")

    def test_custom_message(self, db):
        _, err = IS_IN_DB(db, "users.email", error_message="Not found!")("nobody@example.com")
        assert err == "Not found!"


# ---------------------------------------------------------------------------
# IS_INT_IN_RANGE
# ---------------------------------------------------------------------------


class TestIsIntInRange:
    def test_valid_in_range(self):
        _, err = IS_INT_IN_RANGE(0, 10)(5)
        assert err is None

    def test_at_minimum(self):
        _, err = IS_INT_IN_RANGE(0, 10)(0)
        assert err is None

    def test_at_maximum_exclusive(self):
        _, err = IS_INT_IN_RANGE(0, 10)(10)
        assert err is not None

    def test_below_minimum(self):
        _, err = IS_INT_IN_RANGE(5, 10)(4)
        assert err is not None

    def test_string_integer(self):
        _, err = IS_INT_IN_RANGE(0, 100)("42")
        assert err is None

    def test_non_integer_fails(self):
        _, err = IS_INT_IN_RANGE(0, 100)("abc")
        assert err is not None

    def test_no_lower_bound(self):
        _, err = IS_INT_IN_RANGE(maximum=10)(-999)
        assert err is None

    def test_no_upper_bound(self):
        _, err = IS_INT_IN_RANGE(minimum=0)(99999)
        assert err is None

    def test_custom_message(self):
        _, err = IS_INT_IN_RANGE(0, 5, error_message="Out of range")(10)
        assert err == "Out of range"


# ---------------------------------------------------------------------------
# IS_IPADDRESS
# ---------------------------------------------------------------------------


class TestIsIpAddress:
    def test_valid_ipv4(self):
        _, err = IS_IPADDRESS()("192.168.1.1")
        assert err is None

    def test_valid_ipv6(self):
        _, err = IS_IPADDRESS()("::1")
        assert err is None

    def test_invalid(self):
        _, err = IS_IPADDRESS()("not-an-ip")
        assert err is not None

    def test_ipv4_only_accepts_ipv4(self):
        _, err = IS_IPADDRESS(is_ipv4=True)("10.0.0.1")
        assert err is None

    def test_ipv4_only_rejects_ipv6(self):
        _, err = IS_IPADDRESS(is_ipv4=True)("::1")
        assert err is not None

    def test_ipv6_only_accepts_ipv6(self):
        _, err = IS_IPADDRESS(is_ipv6=True)("2001:db8::1")
        assert err is None

    def test_ipv6_only_rejects_ipv4(self):
        _, err = IS_IPADDRESS(is_ipv6=True)("192.168.0.1")
        assert err is not None

    def test_custom_message(self):
        _, err = IS_IPADDRESS(error_message="Bad IP")("bad")
        assert err == "Bad IP"


# ---------------------------------------------------------------------------
# IS_JSON
# ---------------------------------------------------------------------------


class TestIsJson:
    def test_valid_json_string(self):
        _, err = IS_JSON()('{"key": "value"}')
        assert err is None

    def test_valid_json_array(self):
        _, err = IS_JSON()("[1, 2, 3]")
        assert err is None

    def test_invalid_json_string(self):
        _, err = IS_JSON()("{not valid}")
        assert err is not None

    def test_native_dict_accepted(self):
        _, err = IS_JSON()({"key": "value"})
        assert err is None

    def test_native_list_accepted(self):
        _, err = IS_JSON()([1, 2, 3])
        assert err is None

    def test_native_dict_rejected_when_native_json_false(self):
        _, err = IS_JSON(native_json=False)({"key": "value"})
        assert err is not None

    def test_custom_message(self):
        _, err = IS_JSON(error_message="Bad JSON")("{bad}")
        assert err == "Bad JSON"


# ---------------------------------------------------------------------------
# IS_DATETIME
# ---------------------------------------------------------------------------


class TestIsDatetime:
    def test_valid_datetime_string(self):
        _, err = IS_DATETIME()("2024-01-15 10:30:00")
        assert err is None

    def test_valid_iso_format(self):
        _, err = IS_DATETIME()("2024-01-15T10:30:00")
        assert err is None

    def test_valid_date_only(self):
        _, err = IS_DATETIME()("2024-01-15")
        assert err is None

    def test_invalid_format(self):
        _, err = IS_DATETIME()("15/01/2024")
        assert err is not None

    def test_datetime_object_accepted(self):
        from datetime import datetime

        _, err = IS_DATETIME()(datetime(2024, 1, 15))
        assert err is None

    def test_custom_format(self):
        _, err = IS_DATETIME(format="%d/%m/%Y")("15/01/2024")
        assert err is None

    def test_multiple_formats(self):
        _, err = IS_DATETIME(format=["%d/%m/%Y", "%Y-%m-%d"])("2024-01-15")
        assert err is None

    def test_custom_message(self):
        _, err = IS_DATETIME(error_message="Bad date")("nope")
        assert err == "Bad date"


# ---------------------------------------------------------------------------
# IS_NULL_OR
# ---------------------------------------------------------------------------


class TestIsNullOr:
    def test_none_passes(self):
        _, err = IS_NULL_OR(IS_EMAIL())(None)
        assert err is None

    def test_empty_string_passes(self):
        _, err = IS_NULL_OR(IS_EMAIL())("")
        assert err is None

    def test_string_none_passes(self):
        _, err = IS_NULL_OR(IS_EMAIL())("None")
        assert err is None

    def test_valid_value_delegates(self):
        _, err = IS_NULL_OR(IS_EMAIL())("user@example.com")
        assert err is None

    def test_invalid_value_delegates(self):
        _, err = IS_NULL_OR(IS_EMAIL())("not-an-email")
        assert err is not None

    def test_with_is_match(self):
        _, err = IS_NULL_OR(IS_MATCH(r"^\d+$", strict=True))(None)
        assert err is None
        _, err2 = IS_NULL_OR(IS_MATCH(r"^\d+$", strict=True))("abc")
        assert err2 is not None

    def test_with_legacy_validator(self):
        """IS_NULL_OR should also wrap raise-style validators."""
        def must_be_positive(v):
            if int(v) <= 0:
                raise ValueError("Must be positive")

        v = IS_NULL_OR(must_be_positive)
        _, err = v(None)
        assert err is None
        # Raise-style validator: IS_NULL_OR delegates and doesn't blow up
        try:
            v("5")
            passed = True
        except Exception:
            passed = False
        assert passed


# ---------------------------------------------------------------------------
# Integration: PyDAL-style validators with define_table
# ---------------------------------------------------------------------------


class TestValidatorsWithDefineTable:
    def test_define_table_with_pydal_validator(self, db_plain):
        """PyDAL-style validators work end-to-end with define_table."""
        from penguin_dal.field import Field

        db_plain.define_table(
            "products",
            Field("name", "string", requires=[IS_NOT_EMPTY()]),
            Field("price", "integer", requires=[IS_INT_IN_RANGE(0, 10000)]),
        )

        pk = db_plain.products.insert(name="Widget", price=99)
        assert pk is not None

    def test_define_table_validator_failure(self, db_plain):
        from penguin_dal.field import Field

        db_plain.define_table(
            "items",
            Field("code", "string", requires=[IS_MATCH(r"^[A-Z]{3}\d{3}$", strict=True)]),
        )

        with pytest.raises(ValidationError):
            db_plain.items.insert(code="bad-code")

    def test_combined_validators(self, db):
        """Multiple validators on one column: all must pass."""
        db.register_validators(
            "users",
            {"email": [IS_NOT_EMPTY(), IS_EMAIL(), IS_LENGTH(maxsize=50)]},
        )
        with pytest.raises(ValidationError):
            db.users.insert(email="", name="Test", active=True)
        with pytest.raises(ValidationError):
            db.users.insert(email="bad-email", name="Test", active=True)

    def test_validated_columns_with_pydal_validators(self, db):
        @validated_columns({"email": [IS_EMAIL()]})
        class UserModel:
            __tablename__ = "users"

        db.register_model(UserModel)
        with pytest.raises(ValidationError):
            db.users.insert(email="notvalid", name="X", active=True)
