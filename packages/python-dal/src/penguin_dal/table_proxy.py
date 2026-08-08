"""TableProxy: table-level accessor providing PyDAL-style operations."""

from __future__ import annotations

from typing import Any

from sqlalchemy import Table

from penguin_dal.field_proxy import FieldProxy


class TableProxy:
    """Wraps a SQLAlchemy Table to provide PyDAL-style column access and DML.

    Accessed via db.table_name. Column access via db.table_name.column_name
    returns FieldProxy objects for building queries.
    """

    def __init__(
        self,
        table: Table,
        session_factory: Any,
        validators: dict[str, list[Any]] | None = None,
        is_async: bool = False,
    ) -> None:
        self._table = table
        self._session_factory = session_factory
        self._validators = validators or {}
        self._is_async = is_async

    @property
    def table(self) -> Table:
        """Underlying SQLAlchemy Table."""
        return self._table

    @property
    def table_name(self) -> str:
        """Table name."""
        return str(self._table.name)

    def __getattr__(self, name: str) -> FieldProxy:
        if name.startswith("_"):
            raise AttributeError(name)
        if name in self._table.columns:
            return FieldProxy(self._table.columns[name])
        raise AttributeError(
            f"Table '{self._table.name}' has no column '{name}'. "
            f"Available: {[str(c.name) for c in self._table.columns]}"
        )

    def __getitem__(self, pk: Any) -> Any:
        """Lookup by primary key: db.users[42] -> Row or None.

        Args:
            pk: Primary key value.

        Returns:
            Sync table, or async table (is_async=True) called from
            *outside* a running event loop: Row if found, None otherwise
            — resolved immediately via
            ``asyncio.get_event_loop().run_until_complete()``, unchanged
            from prior behavior.

            Async table called from *inside* a running event loop: a
            coroutine resolving to Row | None, e.g. ``await
            db.users[42]``. Previously this path unconditionally called
            ``run_until_complete()`` and always raised
            ``RuntimeError("This event loop is already running")`` — there
            was no working synchronous form of PK lookup from inside a
            running loop, so returning an awaitable here is purely
            additive; it does not change behavior for any caller that
            worked before.
        """
        from penguin_dal.query import Row

        pk_cols = self._table.primary_key.columns
        if len(pk_cols) != 1:
            raise ValueError(
                f"PK lookup requires single-column PK, "
                f"table '{self._table.name}' has {len(pk_cols)}"
            )
        pk_col = list(pk_cols)[0]

        from sqlalchemy import select as sa_select

        stmt = sa_select(self._table).where(pk_col == pk)

        if self._is_async:
            import asyncio

            async def _async_get() -> Row | None:
                async with self._session_factory() as session:
                    result = await session.execute(stmt)
                    row = result.first()
                    return Row(dict(row._mapping)) if row else None

            try:
                asyncio.get_running_loop()
            except RuntimeError:
                # No running loop in this thread: preserve the original
                # synchronous resolve-immediately behavior byte-for-byte.
                return asyncio.get_event_loop().run_until_complete(_async_get())
            # Running loop: can't block on it, so hand back the coroutine
            # for the caller to await instead of crashing.
            return _async_get()
        else:
            with self._session_factory() as session:
                result = session.execute(stmt)
                row = result.first()
                return Row(dict(row._mapping)) if row else None

    def _run_validators(self, data: dict[str, Any]) -> None:
        """Run registered validators on data before insert.

        Supports two validator call conventions:

        * **PyDAL-style** (preferred): callable returns ``(value, error)`` where
          *error* is ``None`` on success or a string message on failure.
        * **Raise-style** (legacy): callable raises ``ValueError`` or
          ``TypeError`` on failure and returns nothing.

        Args:
            data: Column name -> value mapping.

        Raises:
            ValidationError: If any validators fail.
        """
        from penguin_dal.exceptions import ValidationError

        errors: list[dict[str, str]] = []
        for col_name, validators in self._validators.items():
            if col_name in data:
                value = data[col_name]
                for validator in validators:
                    try:
                        result = validator(value)
                        # PyDAL-style: (value, error_or_None) tuple
                        if isinstance(result, tuple) and len(result) == 2:
                            _, error = result
                            if error is not None:
                                errors.append({"field": col_name, "message": str(error)})
                    except (ValueError, TypeError) as e:
                        errors.append({"field": col_name, "message": str(e)})
        if errors:
            raise ValidationError(errors)

    def insert(self, **kwargs: Any) -> Any:
        """Insert a row and return the primary key.

        Runs validators if registered. Returns the inserted PK value.

        On a table bound to AsyncDB (is_async=True), this delegates to
        async_insert() and returns a coroutine instead of a PK value —
        e.g. ``pk = await db.users.insert(...)``. Previously calling
        insert() on an async table raised TypeError immediately
        ("'AsyncSession' object does not support the context manager
        protocol") because the sync ``with self._session_factory()``
        can't open an AsyncSession; there was no working synchronous
        path on an async table to preserve, so returning an awaitable
        here is purely additive. async_insert() remains the stable,
        explicitly-named async entry point and is unchanged.

        WARNING: on an async table, forgetting ``await`` no longer
        crashes loudly — it silently returns a never-awaited coroutine
        and performs no write (you'll only see a GC-time
        RuntimeWarning, if that). Always ``await db.users.insert(...)``
        on an AsyncDB table.

        Args:
            **kwargs: Column=value pairs.

        Returns:
            Primary key of the inserted row (sync table), or a coroutine
            resolving to the primary key (async table).
        """
        if self._is_async:
            return self.async_insert(**kwargs)

        if self._validators:
            self._run_validators(kwargs)

        stmt = self._table.insert().values(**kwargs)

        with self._session_factory() as session:
            result = session.execute(stmt)
            session.commit()
            return result.inserted_primary_key[0]

    async def async_insert(self, **kwargs: Any) -> Any:
        """Insert a row and return the primary key (async).

        Args:
            **kwargs: Column=value pairs.

        Returns:
            Primary key of the inserted row.
        """
        if self._validators:
            self._run_validators(kwargs)

        stmt = self._table.insert().values(**kwargs)

        async with self._session_factory() as session:
            result = await session.execute(stmt)
            await session.commit()
            return result.inserted_primary_key[0]

    def bulk_insert(self, rows: list[dict[str, Any]]) -> None:
        """Insert multiple rows in a single statement.

        Args:
            rows: List of column=value dicts.
        """
        if not rows:
            return
        if self._validators:
            for row_data in rows:
                self._run_validators(row_data)

        stmt = self._table.insert()

        with self._session_factory() as session:
            session.execute(stmt, rows)
            session.commit()

    async def async_bulk_insert(self, rows: list[dict[str, Any]]) -> None:
        """Insert multiple rows in a single statement (async).

        Args:
            rows: List of column=value dicts.
        """
        if not rows:
            return
        if self._validators:
            for row_data in rows:
                self._run_validators(row_data)

        stmt = self._table.insert()

        async with self._session_factory() as session:
            await session.execute(stmt, rows)
            await session.commit()

    def __repr__(self) -> str:
        return f"TableProxy('{self._table.name}')"
