"""Validator integration and PyDAL-compatible validator classes.

Validators follow two compatible call conventions:

1. **PyDAL-style** (preferred for new code): callable returns a ``(value, error)``
   tuple where *error* is ``None`` on success or a string message on failure.
   These are the named classes in this module (``IS_NOT_EMPTY``, ``IS_EMAIL``, …).

2. **Raise-style** (legacy): callable raises ``ValueError`` or ``TypeError`` on
   failure and returns nothing.  Lambdas and plain functions used before this
   module was expanded still work unchanged.

Both conventions are handled transparently by :meth:`TableProxy._run_validators`.
"""

from __future__ import annotations

import ipaddress
import json
import re
from collections.abc import Callable
from datetime import datetime
from typing import Any


# ---------------------------------------------------------------------------
# @validated_columns decorator
# ---------------------------------------------------------------------------


def validated_columns(
    validators: dict[str, list[Callable[..., Any]]],
) -> Callable[..., Any]:
    """Decorator to attach validators to a SQLAlchemy model class.

    Validators are stored as ``_dal_validators`` on the class and picked up
    by :meth:`DB.register_model`.

    Args:
        validators: Dict of column_name -> list of validator callables.
            Each validator may either raise ``ValueError``/``TypeError`` on
            failure, or return a ``(value, error_str | None)`` tuple.

    Returns:
        Class decorator.

    Example::

        @validated_columns({
            'email': [IS_EMAIL()],
            'name': [IS_NOT_EMPTY()],
        })
        class User(Base):
            __tablename__ = 'users'
            ...
    """

    def decorator(cls: Any) -> Any:
        cls._dal_validators = validators
        return cls

    return decorator


# ---------------------------------------------------------------------------
# PyDAL-compatible validator classes
# ---------------------------------------------------------------------------


class IS_NOT_EMPTY:
    """Reject ``None``, empty strings, empty lists, and empty dicts.

    Equivalent to PyDAL ``IS_NOT_EMPTY``.

    Args:
        error_message: Message returned on failure.

    Example::

        Field("name", "string", requires=IS_NOT_EMPTY())
    """

    def __init__(self, error_message: str = "Enter a value") -> None:
        self.error_message = error_message

    def __call__(self, value: Any) -> tuple[Any, str | None]:
        """Validate *value*.

        Uses explicit equality checks rather than ``not value``, so the integer
        ``0`` and the boolean ``False`` are accepted as valid non-empty values.

        Returns:
            ``(value, None)`` on success; ``(value, error_message)`` on failure.
        """
        if value is None or value == "" or value == [] or value == {}:
            return value, self.error_message
        return value, None


class IS_LENGTH:
    """Validate that the length of a value (coerced to string) is within bounds.

    Equivalent to PyDAL ``IS_LENGTH``.

    Args:
        maxsize: Maximum allowed length (inclusive, default 255).
        minsize: Minimum allowed length (inclusive, default 0).
        error_message: Override the default message.

    Example::

        Field("username", "string", requires=IS_LENGTH(maxsize=32, minsize=3))
    """

    def __init__(
        self,
        maxsize: int = 255,
        minsize: int = 0,
        error_message: str | None = None,
    ) -> None:
        self.maxsize = maxsize
        self.minsize = minsize
        self.error_message = error_message

    def __call__(self, value: Any) -> tuple[Any, str | None]:
        """Validate *value*.

        Returns:
            ``(value, None)`` on success; ``(value, error_message)`` on failure.
        """
        s = "" if value is None else str(value)
        length = len(s)
        if length < self.minsize or length > self.maxsize:
            msg = self.error_message or (
                f"Enter between {self.minsize} and {self.maxsize} characters"
            )
            return value, msg
        return value, None


class IS_EMAIL:
    """Validate an e-mail address with a basic RFC-5321-like pattern.

    Equivalent to PyDAL ``IS_EMAIL``.

    Args:
        error_message: Message returned on failure.

    Example::

        Field("email", "string", requires=IS_EMAIL())
    """

    _EMAIL_RE: re.Pattern[str] = re.compile(
        r"^[^@\s]+@[^@\s]+\.[^@\s]+$",
        re.IGNORECASE,
    )

    def __init__(self, error_message: str = "Enter a valid email address") -> None:
        self.error_message = error_message

    def __call__(self, value: Any) -> tuple[Any, str | None]:
        """Validate *value*.

        Returns:
            ``(value, None)`` on success; ``(value, error_message)`` on failure.
        """
        if not value or not self._EMAIL_RE.match(str(value)):
            return value, self.error_message
        return value, None


class IS_IN_SET:
    """Validate that a value is a member of an allowed set.

    Equivalent to PyDAL ``IS_IN_SET``.

    Args:
        theset: Allowed values (any iterable).  Converted to a ``frozenset``
            for O(1) membership tests.
        error_message: Message returned on failure.
        zero: Placeholder value that is *always* accepted (e.g. empty string
            for optional selects).  ``None`` disables this.

    Example::

        Field("role", "string", requires=IS_IN_SET(["admin", "viewer"]))
    """

    def __init__(
        self,
        theset: Any,
        error_message: str = "Value not allowed",
        zero: Any = None,
    ) -> None:
        self._set = frozenset(theset)
        self.error_message = error_message
        self.zero = zero

    def __call__(self, value: Any) -> tuple[Any, str | None]:
        """Validate *value*.

        Returns:
            ``(value, None)`` on success; ``(value, error_message)`` on failure.
        """
        if self.zero is not None and value == self.zero:
            return value, None
        if value not in self._set:
            return value, self.error_message
        return value, None


class IS_MATCH:
    """Validate that a value matches a regular-expression pattern.

    Equivalent to PyDAL ``IS_MATCH``.

    Args:
        expression: Regular expression string.
        error_message: Message returned on failure.
        strict: If ``True`` use :func:`re.fullmatch` (whole string must match).
            If ``False`` (default) use :func:`re.search` (substring match).
        flags: Optional :mod:`re` flags (e.g. ``re.IGNORECASE``).

    Example::

        Field("slug", "string", requires=IS_MATCH(r'^[a-z0-9-]+$', strict=True))
    """

    def __init__(
        self,
        expression: str,
        error_message: str = "Invalid value",
        strict: bool = False,
        flags: int = 0,
    ) -> None:
        self._pattern = re.compile(expression, flags)
        self.error_message = error_message
        self.strict = strict

    def __call__(self, value: Any) -> tuple[Any, str | None]:
        """Validate *value*.

        Returns:
            ``(value, None)`` on success; ``(value, error_message)`` on failure.
        """
        s = "" if value is None else str(value)
        fn = self._pattern.fullmatch if self.strict else self._pattern.search
        if not fn(s):
            return value, self.error_message
        return value, None


class IS_NOT_IN_DB:
    """Validate that a value does not already exist in a database column.

    Equivalent to PyDAL ``IS_NOT_IN_DB``.

    The *db* argument is a :class:`~penguin_dal.db.DB` instance.  The check is
    performed with a live SQL query each time the validator is called.

    Args:
        db: A :class:`~penguin_dal.db.DB` instance.
        field: A ``"table.column"`` reference string (e.g. ``"users.email"``).
        error_message: Message returned on failure.

    Example::

        Field("email", "string",
              requires=IS_NOT_IN_DB(db, "users.email"))
    """

    def __init__(
        self,
        db: Any,
        field: str,
        error_message: str = "Value already in database",
    ) -> None:
        self._db = db
        parts = field.split(".", 1)
        if len(parts) != 2:
            raise ValueError(f"IS_NOT_IN_DB field must be 'table.column', got: {field!r}")
        self._table_name, self._column_name = parts
        self.error_message = error_message

    def __call__(self, value: Any) -> tuple[Any, str | None]:
        """Validate *value*.

        Returns:
            ``(value, None)`` if the value is **absent** from the column;
            ``(value, error_message)`` if it is already present.
        """
        from sqlalchemy import select as sa_select

        try:
            table = self._db._get_table(self._table_name)
            col = table.c[self._column_name]
            stmt = sa_select(table).where(col == value).limit(1)
            with self._db._session_factory() as session:
                result = session.execute(stmt)
                if result.first() is not None:
                    return value, self.error_message
        except Exception:
            # If the table/column doesn't exist yet, treat as valid.
            pass
        return value, None


class IS_IN_DB:
    """Validate that a value exists in a database column.

    Equivalent to PyDAL ``IS_IN_DB``.

    The *db* argument is a :class:`~penguin_dal.db.DB` instance.  The check is
    performed with a live SQL query each time the validator is called.

    Args:
        db: A :class:`~penguin_dal.db.DB` instance.
        field: A ``"table.column"`` reference string (e.g. ``"categories.id"``).
        error_message: Message returned on failure.

    Example::

        Field("category_id", "integer",
              requires=IS_IN_DB(db, "categories.id"))
    """

    def __init__(
        self,
        db: Any,
        field: str,
        error_message: str = "Value not found in database",
    ) -> None:
        self._db = db
        parts = field.split(".", 1)
        if len(parts) != 2:
            raise ValueError(f"IS_IN_DB field must be 'table.column', got: {field!r}")
        self._table_name, self._column_name = parts
        self.error_message = error_message

    def __call__(self, value: Any) -> tuple[Any, str | None]:
        """Validate *value*.

        Returns:
            ``(value, None)`` if the value is **present** in the column;
            ``(value, error_message)`` if it is absent.
        """
        from sqlalchemy import select as sa_select

        try:
            table = self._db._get_table(self._table_name)
            col = table.c[self._column_name]
            stmt = sa_select(table).where(col == value).limit(1)
            with self._db._session_factory() as session:
                result = session.execute(stmt)
                if result.first() is None:
                    return value, self.error_message
        except Exception:
            return value, self.error_message
        return value, None


class IS_INT_IN_RANGE:
    """Validate that an integer value lies within ``[minimum, maximum)``.

    Equivalent to PyDAL ``IS_INT_IN_RANGE``.

    The range is **half-open**: *minimum* is inclusive, *maximum* is exclusive.
    Pass ``None`` for *minimum* or *maximum* to leave that bound unrestricted.

    Args:
        minimum: Lower bound (inclusive).  ``None`` means no lower bound.
        maximum: Upper bound (exclusive).  ``None`` means no upper bound.
        error_message: Override the default message.

    Example::

        Field("age", "integer", requires=IS_INT_IN_RANGE(0, 120))
    """

    def __init__(
        self,
        minimum: int | None = None,
        maximum: int | None = None,
        error_message: str | None = None,
    ) -> None:
        self.minimum = minimum
        self.maximum = maximum
        self.error_message = error_message

    def __call__(self, value: Any) -> tuple[Any, str | None]:
        """Validate *value*.

        Returns:
            ``(value, None)`` on success; ``(value, error_message)`` on failure.
        """
        try:
            intval = int(value)
        except (TypeError, ValueError):
            return value, self.error_message or "Enter an integer"

        if self.minimum is not None and intval < self.minimum:
            msg = self.error_message or f"Enter a value between {self.minimum} and {self.maximum}"
            return value, msg
        if self.maximum is not None and intval >= self.maximum:
            msg = self.error_message or f"Enter a value between {self.minimum} and {self.maximum}"
            return value, msg
        return value, None


class IS_IPADDRESS:
    """Validate an IPv4 or IPv6 address using :mod:`ipaddress`.

    Equivalent to PyDAL ``IS_IPADDRESS``.

    Args:
        is_ipv4: If ``True``, only accept IPv4.  Default ``False`` (both).
        is_ipv6: If ``True``, only accept IPv6.  Default ``False`` (both).
        error_message: Message returned on failure.

    Example::

        Field("ip_addr", "string", requires=IS_IPADDRESS())
        Field("ipv4", "string", requires=IS_IPADDRESS(is_ipv4=True))
    """

    def __init__(
        self,
        is_ipv4: bool = False,
        is_ipv6: bool = False,
        error_message: str = "Enter a valid IP address",
    ) -> None:
        self.is_ipv4 = is_ipv4
        self.is_ipv6 = is_ipv6
        self.error_message = error_message

    def __call__(self, value: Any) -> tuple[Any, str | None]:
        """Validate *value*.

        Returns:
            ``(value, None)`` on success; ``(value, error_message)`` on failure.
        """
        try:
            addr = ipaddress.ip_address(str(value))
        except (ValueError, TypeError):
            return value, self.error_message

        if self.is_ipv4 and not isinstance(addr, ipaddress.IPv4Address):
            return value, self.error_message
        if self.is_ipv6 and not isinstance(addr, ipaddress.IPv6Address):
            return value, self.error_message
        return value, None


class IS_JSON:
    """Validate that a value is valid JSON (string) or a JSON-serialisable object.

    Equivalent to PyDAL ``IS_JSON``.

    Accepts strings (parsed with :func:`json.loads`) and any Python object that
    is already JSON-serialisable (dicts, lists, numbers, etc.).

    Args:
        error_message: Message returned on failure.
        native_json: If ``True`` (default), also accept Python dicts/lists/etc.
            directly.  If ``False``, only accept string values.

    Example::

        Field("metadata", "json", requires=IS_JSON())
    """

    def __init__(
        self,
        error_message: str = "Invalid JSON",
        native_json: bool = True,
    ) -> None:
        self.error_message = error_message
        self.native_json = native_json

    def __call__(self, value: Any) -> tuple[Any, str | None]:
        """Validate *value*.

        Returns:
            ``(value, None)`` on success; ``(value, error_message)`` on failure.
        """
        if isinstance(value, str):
            try:
                json.loads(value)
                return value, None
            except (json.JSONDecodeError, ValueError):
                return value, self.error_message

        if self.native_json:
            try:
                json.dumps(value)
                return value, None
            except (TypeError, ValueError):
                return value, self.error_message

        return value, self.error_message


class IS_DATETIME:
    """Validate a datetime string against one or more format strings.

    Equivalent to PyDAL ``IS_DATETIME``.

    Args:
        format: A :func:`datetime.strptime` format string, or a list of
            formats to try in order.  Defaults to ISO 8601
            ``"%Y-%m-%d %H:%M:%S"``.
        error_message: Override the default message.

    Example::

        Field("created_on", "datetime",
              requires=IS_DATETIME(format="%Y-%m-%d %H:%M:%S"))
    """

    _DEFAULT_FORMATS: list[str] = [
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%dT%H:%M:%SZ",
        "%Y-%m-%d",
    ]

    def __init__(
        self,
        format: str | list[str] | None = None,
        error_message: str | None = None,
    ) -> None:
        if format is None:
            self._formats = self._DEFAULT_FORMATS
        elif isinstance(format, str):
            self._formats = [format]
        else:
            self._formats = list(format)
        self.error_message = error_message

    def __call__(self, value: Any) -> tuple[Any, str | None]:
        """Validate *value*.

        Returns:
            ``(value, None)`` on success; ``(value, error_message)`` on failure.
        """
        if isinstance(value, datetime):
            return value, None

        s = str(value) if value is not None else ""
        for fmt in self._formats:
            try:
                datetime.strptime(s, fmt)
                return value, None
            except (ValueError, TypeError):
                continue

        msg = self.error_message or (
            f"Enter datetime as {self._formats[0]}"
        )
        return value, msg


class IS_NULL_OR:
    """Pass validation if the value is empty/null; otherwise delegate to *other*.

    Equivalent to PyDAL ``IS_NULL_OR``.  Useful for optional fields that, when
    provided, must still satisfy a constraint.

    A value is considered *null* if it is ``None``, an empty string ``""``,
    or the string ``"None"``.

    Args:
        other: Another validator (e.g. ``IS_EMAIL()``) applied when the value
            is non-null.
        error_message: Unused — the wrapped validator's message is returned
            instead.  Provided for API symmetry.

    Example::

        Field("website", "string",
              requires=IS_NULL_OR(IS_MATCH(r'^https?://')))
    """

    def __init__(
        self,
        other: Callable[..., Any],
        error_message: str | None = None,
    ) -> None:
        self.other = other
        self.error_message = error_message

    def __call__(self, value: Any) -> tuple[Any, str | None]:
        """Validate *value*.

        Returns:
            ``(value, None)`` if *value* is null/empty, or delegates to
            *other* otherwise.
        """
        if value is None or value == "" or value == "None":
            return value, None

        result = self.other(value)
        # Handle both raise-style (None return) and tuple-style validators.
        if isinstance(result, tuple) and len(result) == 2:
            return result
        return value, None


__all__ = [
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
