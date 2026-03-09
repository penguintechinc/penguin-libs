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
            Row if found, None otherwise.
        """
        from penguin_dal.query import Row, Rows

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

            return asyncio.get_event_loop().run_until_complete(_async_get())
        else:
            with self._session_factory() as session:
                result = session.execute(stmt)
                row = result.first()
                return Row(dict(row._mapping)) if row else None

    def _run_validators(self, data: dict[str, Any]) -> None:
        """Run registered validators on data before insert.

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
                        validator(value)
                    except (ValueError, TypeError) as e:
                        errors.append({"field": col_name, "message": str(e)})
        if errors:
            raise ValidationError(errors)

    def insert(self, **kwargs: Any) -> Any:
        """Insert a row and return the primary key.

        Runs validators if registered. Returns the inserted PK value.

        Args:
            **kwargs: Column=value pairs.

        Returns:
            Primary key of the inserted row.
        """
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
