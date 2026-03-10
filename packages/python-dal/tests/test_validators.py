"""Tests for validator integration."""

import pytest

from penguin_dal.exceptions import ValidationError
from penguin_dal.validators import validated_columns


def is_not_empty(value):
    """Validator that rejects empty values."""
    if not value:
        raise ValueError("Value cannot be empty")


def is_email(value):
    """Validator that checks for @ in email."""
    if "@" not in str(value):
        raise ValueError("Invalid email address")


class TestValidators:
    def test_register_validators(self, db):
        db.register_validators(
            "users",
            {
                "email": [is_not_empty, is_email],
                "name": [is_not_empty],
            },
        )
        # Should succeed
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
