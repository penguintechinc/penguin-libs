"""Validator integration and @validated_columns decorator."""

from __future__ import annotations

from typing import Any, Callable


def validated_columns(
    validators: dict[str, list[Callable[..., Any]]],
) -> Callable[..., Any]:
    """Decorator to attach validators to a SQLAlchemy model class.

    Validators are stored as _dal_validators on the class and picked up
    by DB.register_model().

    Args:
        validators: Dict of column_name -> list of validator callables.
            Each validator should accept a single value and raise
            ValueError or TypeError on failure.

    Returns:
        Class decorator.

    Example:
        @validated_columns({
            'email': [lambda v: None if '@' in str(v) else (_ for _ in ()).throw(ValueError('Invalid email'))],
            'name': [lambda v: None if v else (_ for _ in ()).throw(ValueError('Required'))],
        })
        class User(Base):
            __tablename__ = 'users'
            ...
    """

    def decorator(cls: Any) -> Any:
        cls._dal_validators = validators
        return cls

    return decorator
