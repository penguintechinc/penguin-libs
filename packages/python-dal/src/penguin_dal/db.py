"""DB (sync) and AsyncDB (async) entry points."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any, cast

from sqlalchemy import MetaData, Table, create_engine
from sqlalchemy.orm import sessionmaker

from penguin_dal.backends import ensure_async_uri, get_engine_kwargs, normalize_uri
from penguin_dal.exceptions import TableNotFoundError
from penguin_dal.query import AsyncQuerySet, Query, QuerySet, Rows
from penguin_dal.table_proxy import TableProxy


def _shape_result(
    result: Any,
    as_dict: bool = False,
    as_ordered_dict: bool = False,
    fields: list[Any] | tuple[Any, ...] | None = None,
    colnames: list[str] | tuple[str, ...] | None = None,
    return_rowcount: bool = False,
) -> list[tuple[Any, ...]] | list[dict[str, Any]] | list[Any] | Rows | int | None:
    """Shape a SQLAlchemy CursorResult into penguin_dal's executesql return types.

    Shared by DB.executesql and Tx.executesql so both raw-SQL entry points
    (single-statement autocommit and pinned-connection transaction) apply
    identical row-shaping rules.
    """
    from collections import OrderedDict

    from penguin_dal.query import Row, Rows

    if not result.returns_rows:
        if return_rowcount:
            return result.rowcount if result.rowcount is not None else -1
        return None

    rows = result.fetchall()
    col_names = list(result.keys())
    field_list = fields or colnames

    if as_ordered_dict:
        return [OrderedDict(zip(col_names, row)) for row in rows]
    if as_dict:
        return [dict(zip(col_names, row)) for row in rows]
    if field_list:
        col_names_custom = [getattr(f, "name", None) or str(f) for f in field_list]
        row_objs = [Row(dict(zip(col_names_custom, row))) for row in rows]
        return Rows(row_objs)
    return [tuple(row) for row in rows]


class Tx:
    """Raw-SQL executor bound to one open connection inside a transaction.

    Yielded by DB.transaction(); every executesql() call on this instance
    runs on the same pinned connection so multi-statement raw-SQL units
    (advisory locks, hash-chain writes) share session state.
    """

    def __init__(self, conn: Any) -> None:
        self._conn = conn

    def executesql(
        self,
        query: str,
        placeholders: list[Any] | tuple[Any, ...] | dict[str, Any] | None = None,
        as_dict: bool = False,
        return_rowcount: bool = False,
    ) -> list[tuple[Any, ...]] | list[dict[str, Any]] | int | None:
        """Execute raw SQL on the transaction's pinned connection.

        Same driver-native paramstyle as DB.executesql (? sqlite, %s/%(name)s
        psycopg2). Does not commit — the enclosing DB.transaction() context
        commits on clean exit or rolls back on exception.
        """
        if placeholders is not None:
            result = self._conn.exec_driver_sql(query, placeholders)
        else:
            result = self._conn.exec_driver_sql(query)
        # Tx.executesql never passes fields/colnames/as_ordered_dict, so
        # _shape_result's broader union collapses to this narrower type.
        return cast(
            "list[tuple[Any, ...]] | list[dict[str, Any]] | int | None",
            _shape_result(result, as_dict=as_dict, return_rowcount=return_rowcount),
        )


class DB:
    """Synchronous database access with PyDAL-style ergonomics.

    Tables are discovered via SQLAlchemy MetaData.reflect().
    Access tables as attributes: db.users, db.auth_user, etc.
    Build queries with: db(db.users.active == True).select()

    Args:
        uri: Database URI (SQLAlchemy or PyDAL-style).
        pool_size: Connection pool size (default 10).
        echo: If True, echo SQL statements (default False).
        reflect: If True, reflect tables on init (default True).
    """

    def __init__(
        self,
        uri: str,
        pool_size: int = 10,
        echo: bool = False,
        reflect: bool = True,
        migrate: bool = False,
    ) -> None:
        self._uri = normalize_uri(uri)
        self._engine = create_engine(
            self._uri,
            echo=echo,
            **get_engine_kwargs(self._uri, pool_size),
        )
        self._session_factory = sessionmaker(bind=self._engine)
        self._metadata = MetaData()
        self._validators: dict[str, dict[str, list[Any]]] = {}
        self._models: dict[str, Any] = {}
        self._migrate = migrate

        if reflect:
            self._metadata.reflect(bind=self._engine)

    @property
    def engine(self) -> Any:
        """Underlying SQLAlchemy engine."""
        return self._engine

    @property
    def metadata(self) -> MetaData:
        """SQLAlchemy MetaData with reflected tables."""
        return self._metadata

    @property
    def tables(self) -> dict[str, Table]:
        """All reflected tables."""
        return dict(self._metadata.tables)

    def _get_table(self, name: str) -> Table:
        """Get a reflected table by name.

        Args:
            name: Table name.

        Returns:
            SQLAlchemy Table.

        Raises:
            TableNotFoundError: If table does not exist.
        """
        if name not in self._metadata.tables:
            raise TableNotFoundError(name)
        return self._metadata.tables[name]

    def __getattr__(self, name: str) -> TableProxy:
        if name.startswith("_"):
            raise AttributeError(name)
        table = self._get_table(name)
        validators = self._validators.get(name, {})
        return TableProxy(table, self._session_factory, validators)

    def __call__(self, query: Query) -> QuerySet:
        """Create a QuerySet for a query.

        Usage: db(db.users.active == True).select()

        Args:
            query: Query object from FieldProxy comparisons.

        Returns:
            QuerySet for executing select/update/delete.
        """
        table = self._extract_table(query)
        return QuerySet(table, query, self._session_factory)

    def _extract_table(self, query: Query) -> Table:
        """Extract the table from a query's clause.

        Args:
            query: Query object.

        Returns:
            SQLAlchemy Table referenced in the query.
        """
        if query.table is not None:
            return query.table
        raise ValueError("Cannot determine table from query")

    def commit(self) -> None:
        """Commit is a no-op for sync DB since QuerySet methods auto-commit.

        Provided for API compatibility with PyDAL.
        """
        pass

    def rollback(self) -> None:
        """Rollback is a documented no-op, mirroring commit().

        QuerySet methods (insert/update/delete/select) auto-commit per
        statement, so there is never a pending write for rollback() to
        undo. This method exists for API compatibility with PyDAL's
        common ``try: ... except: db.rollback(); raise`` idiom: without
        it, ``db.rollback()`` fell through to ``__getattr__`` and raised
        ``TableNotFoundError`` (no table named "rollback"), masking
        whatever exception the caller was trying to handle.

        For an atomic multi-statement unit that genuinely rolls back on
        exception, use ``transaction()`` instead — it pins one
        connection and rolls back internally on error.

        Compat note: because this is now a real method, it shadows
        ``__getattr__`` — a table literally named "rollback" is no
        longer reachable as ``db.rollback`` (use ``db.tables["rollback"]``).
        """
        pass

    def close(self) -> None:
        """Dispose of the engine and connection pool."""
        self._engine.dispose()

    def register_validators(self, table_name: str, validators: dict[str, list[Any]]) -> None:
        """Register validators for a table's columns.

        Args:
            table_name: Name of the table.
            validators: Dict of column_name -> list of validator callables.
        """
        self._validators[table_name] = validators

    def register_model(self, model_class: Any) -> None:
        """Register a SQLAlchemy model, picking up validators if decorated.

        Args:
            model_class: SQLAlchemy model class (may have _dal_validators).
        """
        table_name = getattr(model_class, "__tablename__", None)
        if table_name is None:
            raise ValueError(f"Model {model_class} has no __tablename__")
        self._models[table_name] = model_class
        validators = getattr(model_class, "_dal_validators", None)
        if validators:
            self._validators[table_name] = validators

    def define_table(
        self,
        name: str,
        *fields: Any,
        migrate: bool = False,
        **kwargs: Any,
    ) -> TableProxy:
        """Define a table with PyDAL-style Field objects.

        Creates the table in the database using SQLAlchemy if it doesn't exist.
        If migrate=False (default), only creates if missing (like PyDAL's migrate=False).

        Args:
            name: Table name.
            *fields: Field objects (from penguin_dal.field).
            migrate: If False, create table if not exists. If True, would alter (not supported yet).
            **kwargs: Additional SQLAlchemy Table kwargs.

        Returns:
            TableProxy for the defined table.
        """
        # Import Field here to avoid circular imports
        try:
            from penguin_dal.field import Field
        except ImportError:
            raise ImportError("Field class not available; ensure penguin_dal.field is installed")

        # Build SQLAlchemy columns from Field objects
        columns: list[Any] = []
        validators_dict: dict[str, list[Any]] = {}
        has_id_field = False

        for field in fields:
            if not isinstance(field, Field):
                raise TypeError(f"Expected Field object, got {type(field)}")

            # Convert Field to SQLAlchemy Column
            col = field.to_sa_column()
            columns.append(col)

            # Track if an 'id' field was provided
            if field.type_ == "id":
                has_id_field = True

            # Register validators for this field
            if field.requires:
                validators_dict[field.name] = field.requires

        # Auto-add 'id' primary key if not provided
        if not has_id_field:
            from sqlalchemy import Column, Integer

            id_col = Column(
                "id",
                Integer(),
                primary_key=True,
                autoincrement=True,
            )
            columns.insert(0, id_col)

        # Create SQLAlchemy Table
        table = Table(name, self._metadata, *columns, **kwargs)

        # Create the table in the database
        self._metadata.create_all(self._engine, tables=[table])

        # Register validators if any
        if validators_dict:
            self._validators[name] = validators_dict

        # Return a TableProxy for the table
        return TableProxy(table, self._session_factory, validators_dict)

    def executesql(
        self,
        query: str,
        placeholders: list[Any] | tuple[Any, ...] | dict[str, Any] | None = None,
        as_dict: bool = False,
        fields: list[Any] | tuple[Any, ...] | None = None,
        colnames: list[str] | tuple[str, ...] | None = None,
        as_ordered_dict: bool = False,
        return_rowcount: bool = False,
        check_injection: bool = True,
    ) -> list[tuple[Any, ...]] | list[dict[str, Any]] | list[Any] | Rows | int | None:
        """Execute raw SQL using driver-native paramstyle.

        Raw SQL escape hatch for migrations and bulk operations. Supports
        driver-native parameter styles: ? (sqlite), %s (psycopg2/pymysql),
        %(name)s (pyformat). SQLAlchemy :name style is NOT supported.

        Args:
            query: Raw SQL string with driver-native placeholders.
            placeholders: Positional tuple/list or named dict. Passed directly
                to DBAPI without interpretation.
            as_dict: Return list[dict] with column names as keys.
            fields: Column names for penguin_dal Rows (overrides cursor names).
                Accepts plain strings or PyDAL-style Field objects, whose .name
                is used as the column key.
            colnames: Alias for fields (for PyDAL compatibility).
            as_ordered_dict: Return list[OrderedDict].
            return_rowcount: Return cursor.rowcount (int) instead of None
                for writes/DDL. Enables checking rows affected.
            check_injection: Heuristic SQL injection check (warns only, never
                rejects). Disable per-call if you have legitimate static SQL
                with quoted literals. Disable with check_injection=False.

        Returns:
            None: If no result set (INSERT/UPDATE/DELETE/DDL) and
                return_rowcount=False.
            list[tuple]: Default for SELECT (raw cursor rows).
            list[dict]: If as_dict=True.
            list[OrderedDict]: If as_ordered_dict=True.
            Rows: If fields or colnames provided.
            int: If return_rowcount=True (cursor.rowcount; -1 for DDL).

        Raises:
            ValueError: If invalid parameter combinations (as_dict with fields,
                as_dict with as_ordered_dict, etc.).

        Examples:
            SELECT with positional placeholders (SQLite):
                db.executesql("SELECT * FROM users WHERE id = ?", (1,))

            SELECT with named placeholders (psycopg2):
                db.executesql("SELECT * FROM users WHERE id = %(id)s", {"id": 1})

            INSERT with rowcount:
                count = db.executesql(
                    "INSERT INTO t (col) VALUES (?)",
                    ("val",),
                    return_rowcount=True
                )

            Bulk UPDATE with Rows:
                rows = db.executesql(
                    "SELECT id, name FROM users WHERE active = ?",
                    (1,),
                    fields=["id", "name"]
                )
        """
        import warnings

        from penguin_dal.exceptions import DALSecurityWarning

        # Validate parameter combinations
        if as_dict and (fields or colnames):
            raise ValueError("as_dict=True cannot be used together with fields or colnames")
        if as_dict and as_ordered_dict:
            raise ValueError("as_dict=True cannot be used together with as_ordered_dict=True")

        # Check for SQL injection (heuristic, can be disabled)
        if check_injection and not placeholders:
            if self._check_potential_injection(query):
                warnings.warn(
                    "Potential SQL injection: query contains quoted string literals "
                    "in WHERE/VALUES/IN clause but no placeholders provided. "
                    "Pass values via the placeholders parameter, or disable with check_injection=False.",
                    DALSecurityWarning,
                    stacklevel=2,
                )

        # Execute query using driver-native paramstyle
        # Use begin() for writes to ensure auto-commit; connect() for reads
        with self._engine.begin() as conn:
            if placeholders is not None:
                result = conn.exec_driver_sql(query, placeholders)
            else:
                result = conn.exec_driver_sql(query)

            return _shape_result(
                result,
                as_dict=as_dict,
                as_ordered_dict=as_ordered_dict,
                fields=fields,
                colnames=colnames,
                return_rowcount=return_rowcount,
            )

    def _check_potential_injection(self, query: str) -> bool:
        """Heuristic check for quoted string literals in sensitive clauses.

        Returns True if the query contains a quoted string (single or double)
        in a WHERE, VALUES, or IN clause. This is a heuristic and will
        false-positive on legitimate static SQL.

        Args:
            query: SQL query string.

        Returns:
            True if a potential injection risk is detected.
        """
        import re

        # Look for quoted strings in WHERE/VALUES/IN clauses
        # Pattern: case-insensitive WHERE/VALUES/IN followed by quoted content
        pattern = r"(?i)\b(WHERE|VALUES|IN)\s+[^;]+'[^']*'"
        return bool(re.search(pattern, query))

    @contextmanager
    def transaction(self) -> Iterator[Tx]:
        """Pin one connection for a multi-statement raw-SQL unit.

        Commits on clean exit, rolls back on exception. Use for advisory
        locks, hash-chain writes, and any raw unit whose statements must
        share session state (a naive per-call executesql would drop that
        state, since each call opens its own connection).
        """
        conn = self._engine.connect()
        try:
            trans = conn.begin()
            try:
                yield Tx(conn)
                trans.commit()
            except Exception:
                trans.rollback()
                raise
        finally:
            conn.close()

    def __repr__(self) -> str:
        table_count = len(self._metadata.tables)
        return f"DB(uri='{self._uri}', tables={table_count})"


class AsyncDB:
    """Asynchronous database access with PyDAL-style ergonomics.

    First-class async support using SQLAlchemy async engine.
    Access tables as attributes: db.users, db.auth_user, etc.
    Build queries with: await db(db.users.active == True).select()

    Args:
        uri: Database URI (will be converted to async driver if needed).
        pool_size: Connection pool size (default 10).
        echo: If True, echo SQL statements (default False).

    Migration gotchas (sync DB -> AsyncDB):
        * **Explicit reflect required.** Sync ``DB`` reflects tables in
          ``__init__``. ``AsyncDB`` cannot — ``__init__`` can't run
          coroutines — so you must ``await db.reflect()`` before
          accessing any ``db.<table>`` attribute, or it raises
          ``TableNotFoundError``.
        * **Async method naming.** Most write operations that need a
          coroutine are separately named: ``async_insert()``,
          ``async_bulk_insert()``. Plain ``insert()`` on a table bound
          to ``AsyncDB`` also now works, but returns a coroutine (it
          delegates to ``async_insert()``) rather than the PK directly —
          you still need ``await db.users.insert(...)``. The
          ``async_``-prefixed names are the stable, explicit spelling;
          prefer them for clarity.
        * **``db.<table>[pk]`` has two modes.** Outside a running event
          loop it resolves synchronously and returns ``Row | None``
          directly (same as sync ``DB``). From inside a running loop it
          instead returns a coroutine — ``await db.users[42]`` — since a
          blocking ``run_until_complete()`` can't execute inside an
          already-running loop. Check with ``asyncio.get_running_loop()``
          if your code needs to handle both callers.
    """

    def __init__(
        self,
        uri: str,
        pool_size: int = 10,
        echo: bool = False,
        migrate: bool = False,
    ) -> None:
        from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
        from sqlalchemy.orm import sessionmaker as sync_sessionmaker

        self._uri = ensure_async_uri(uri)
        self._engine = create_async_engine(
            self._uri,
            echo=echo,
            **get_engine_kwargs(self._uri, pool_size),
        )
        self._session_factory = sync_sessionmaker(
            bind=self._engine,
            class_=AsyncSession,
            expire_on_commit=False,
        )
        self._metadata = MetaData()
        self._validators: dict[str, dict[str, list[Any]]] = {}
        self._models: dict[str, Any] = {}
        self._reflected = False
        self._migrate = migrate

    async def reflect(self) -> None:
        """Reflect database tables (must be called after init for async).

        Unlike sync DB which reflects in __init__, async DB requires
        an explicit await db.reflect() call.
        """
        async with self._engine.begin() as conn:
            await conn.run_sync(self._metadata.reflect)
        self._reflected = True

    @property
    def engine(self) -> Any:
        """Underlying SQLAlchemy async engine."""
        return self._engine

    @property
    def metadata(self) -> MetaData:
        """SQLAlchemy MetaData with reflected tables."""
        return self._metadata

    @property
    def tables(self) -> dict[str, Table]:
        """All reflected tables."""
        return dict(self._metadata.tables)

    def _get_table(self, name: str) -> Table:
        if name not in self._metadata.tables:
            raise TableNotFoundError(name)
        return self._metadata.tables[name]

    def __getattr__(self, name: str) -> TableProxy:
        if name.startswith("_"):
            raise AttributeError(name)
        table = self._get_table(name)
        validators = self._validators.get(name, {})
        return TableProxy(table, self._session_factory, validators, is_async=True)

    def __call__(self, query: Query) -> AsyncQuerySet:
        """Create an AsyncQuerySet for a query.

        Usage: await db(db.users.active == True).select()
        """
        table = self._extract_table(query)
        return AsyncQuerySet(table, query, self._session_factory)

    def _extract_table(self, query: Query) -> Table:
        if query.table is not None:
            return query.table
        raise ValueError("Cannot determine table from query")

    async def commit(self) -> None:
        """Commit is a no-op since AsyncQuerySet methods auto-commit."""
        pass

    async def rollback(self) -> None:
        """Rollback is a documented no-op, mirroring commit().

        AsyncQuerySet methods (insert/update/delete/select) auto-commit
        per statement, so there is never a pending write for rollback()
        to undo. Provided for API compatibility with PyDAL's ``try: ...
        except: await db.rollback(); raise`` idiom: without it,
        ``db.rollback()`` fell through to ``__getattr__`` and raised
        ``TableNotFoundError`` (no table named "rollback"), masking
        whatever exception the caller was trying to handle.

        AsyncDB has no ``transaction()`` equivalent yet (only sync
        ``DB.transaction()`` pins a connection for an atomic
        multi-statement unit) — this rollback() cannot provide that
        atomicity, it is a no-op like commit().

        Compat note: because this is now a real method, it shadows
        ``__getattr__`` — a table literally named "rollback" is no
        longer reachable as ``db.rollback`` (use ``db.tables["rollback"]``).
        """
        pass

    async def close(self) -> None:
        """Dispose of the async engine."""
        await self._engine.dispose()

    def register_validators(self, table_name: str, validators: dict[str, list[Any]]) -> None:
        """Register validators for a table's columns."""
        self._validators[table_name] = validators

    def register_model(self, model_class: Any) -> None:
        """Register a SQLAlchemy model, picking up validators if decorated."""
        table_name = getattr(model_class, "__tablename__", None)
        if table_name is None:
            raise ValueError(f"Model {model_class} has no __tablename__")
        self._models[table_name] = model_class
        validators = getattr(model_class, "_dal_validators", None)
        if validators:
            self._validators[table_name] = validators

    async def define_table(
        self,
        name: str,
        *fields: Any,
        migrate: bool = False,
        **kwargs: Any,
    ) -> TableProxy:
        """Define a table with PyDAL-style Field objects (async).

        Creates the table in the database using SQLAlchemy if it doesn't exist.
        If migrate=False (default), only creates if missing (like PyDAL's migrate=False).

        Args:
            name: Table name.
            *fields: Field objects (from penguin_dal.field).
            migrate: If False, create table if not exists. If True, would alter (not supported yet).
            **kwargs: Additional SQLAlchemy Table kwargs.

        Returns:
            TableProxy for the defined table.
        """
        # Import Field here to avoid circular imports
        try:
            from penguin_dal.field import Field
        except ImportError:
            raise ImportError("Field class not available; ensure penguin_dal.field is installed")

        # Build SQLAlchemy columns from Field objects
        columns: list[Any] = []
        validators_dict: dict[str, list[Any]] = {}
        has_id_field = False

        for field in fields:
            if not isinstance(field, Field):
                raise TypeError(f"Expected Field object, got {type(field)}")

            # Convert Field to SQLAlchemy Column
            col = field.to_sa_column()
            columns.append(col)

            # Track if an 'id' field was provided
            if field.type_ == "id":
                has_id_field = True

            # Register validators for this field
            if field.requires:
                validators_dict[field.name] = field.requires

        # Auto-add 'id' primary key if not provided
        if not has_id_field:
            from sqlalchemy import Column, Integer

            id_col = Column(
                "id",
                Integer(),
                primary_key=True,
                autoincrement=True,
            )
            columns.insert(0, id_col)

        # Create SQLAlchemy Table
        table = Table(name, self._metadata, *columns, **kwargs)

        # Create the table in the database (async)
        async with self._engine.begin() as conn:
            await conn.run_sync(self._metadata.create_all, tables=[table])

        # Register validators if any
        if validators_dict:
            self._validators[name] = validators_dict

        # Return a TableProxy for the table
        return TableProxy(table, self._session_factory, validators_dict, is_async=True)

    async def executesql(
        self,
        query: str,
        placeholders: list[Any] | tuple[Any, ...] | dict[str, Any] | None = None,
        as_dict: bool = False,
        fields: list[Any] | tuple[Any, ...] | None = None,
        colnames: list[str] | tuple[str, ...] | None = None,
        as_ordered_dict: bool = False,
        return_rowcount: bool = False,
        check_injection: bool = True,
    ) -> list[tuple[Any, ...]] | list[dict[str, Any]] | list[Any] | Rows | int | None:
        """Execute raw SQL using driver-native paramstyle (async).

        Raw SQL escape hatch for migrations and bulk operations. Supports
        driver-native parameter styles: ? (sqlite), %s (psycopg2/pymysql),
        %(name)s (pyformat). SQLAlchemy :name style is NOT supported.

        Args:
            query: Raw SQL string with driver-native placeholders.
            placeholders: Positional tuple/list or named dict. Passed directly
                to DBAPI without interpretation.
            as_dict: Return list[dict] with column names as keys.
            fields: Column names for penguin_dal Rows (overrides cursor names).
                Accepts plain strings or PyDAL-style Field objects, whose .name
                is used as the column key.
            colnames: Alias for fields (for PyDAL compatibility).
            as_ordered_dict: Return list[OrderedDict].
            return_rowcount: Return cursor.rowcount (int) instead of None
                for writes/DDL. Enables checking rows affected.
            check_injection: Heuristic SQL injection check (warns only, never
                rejects). Disable per-call if you have legitimate static SQL
                with quoted literals. Disable with check_injection=False.

        Returns:
            None: If no result set (INSERT/UPDATE/DELETE/DDL) and
                return_rowcount=False.
            list[tuple]: Default for SELECT (raw cursor rows).
            list[dict]: If as_dict=True.
            list[OrderedDict]: If as_ordered_dict=True.
            Rows: If fields or colnames provided.
            int: If return_rowcount=True (cursor.rowcount; -1 for DDL).

        Raises:
            ValueError: If invalid parameter combinations (as_dict with fields,
                as_dict with as_ordered_dict, etc.).

        Examples:
            SELECT with positional placeholders (SQLite):
                await db.executesql("SELECT * FROM users WHERE id = ?", (1,))

            SELECT with named placeholders (psycopg2):
                await db.executesql("SELECT * FROM users WHERE id = %(id)s", {"id": 1})

            INSERT with rowcount:
                count = await db.executesql(
                    "INSERT INTO t (col) VALUES (?)",
                    ("val",),
                    return_rowcount=True
                )
        """
        from collections import OrderedDict
        import warnings

        from penguin_dal.exceptions import DALSecurityWarning
        from penguin_dal.query import Row, Rows

        # Validate parameter combinations
        if as_dict and (fields or colnames):
            raise ValueError("as_dict=True cannot be used together with fields or colnames")
        if as_dict and as_ordered_dict:
            raise ValueError("as_dict=True cannot be used together with as_ordered_dict=True")

        # Check for SQL injection (heuristic, can be disabled)
        if check_injection and not placeholders:
            if self._check_potential_injection(query):
                warnings.warn(
                    "Potential SQL injection: query contains quoted string literals "
                    "in WHERE/VALUES/IN clause but no placeholders provided. "
                    "Pass values via the placeholders parameter, or disable with check_injection=False.",
                    DALSecurityWarning,
                    stacklevel=2,
                )

        # Use the provided fields or colnames
        field_list = fields or colnames

        # Execute query using driver-native paramstyle
        # Use begin() for writes to ensure auto-commit; connect() for reads
        async with self._engine.begin() as conn:
            if placeholders is not None:
                result = await conn.exec_driver_sql(query, placeholders)
            else:
                result = await conn.exec_driver_sql(query)

            # No result set (INSERT/UPDATE/DELETE/DDL)
            if not result.returns_rows:
                if return_rowcount:
                    return result.rowcount if result.rowcount is not None else -1
                return None

            # Fetch all rows
            rows = result.fetchall()
            col_names = list(result.keys())

            # Apply return format
            if as_ordered_dict:
                return [OrderedDict(zip(col_names, row)) for row in rows]
            elif as_dict:
                return [dict(zip(col_names, row)) for row in rows]
            elif field_list:
                # Build Rows with custom field names
                # Accept plain column names or PyDAL-style Field objects; Field
                # instances carry the column name on .name, strings are used as-is.
                col_names_custom = [getattr(f, "name", None) or str(f) for f in field_list]
                row_objs = [Row(dict(zip(col_names_custom, row))) for row in rows]
                return Rows(row_objs)
            else:
                # Default: return raw tuples (convert from SQLAlchemy Row)
                return [tuple(row) for row in rows]

    def _check_potential_injection(self, query: str) -> bool:
        """Heuristic check for quoted string literals in sensitive clauses.

        Returns True if the query contains a quoted string (single or double)
        in a WHERE, VALUES, or IN clause. This is a heuristic and will
        false-positive on legitimate static SQL.

        Args:
            query: SQL query string.

        Returns:
            True if a potential injection risk is detected.
        """
        import re

        # Look for quoted strings in WHERE/VALUES/IN clauses
        # Pattern: case-insensitive WHERE/VALUES/IN followed by quoted content
        pattern = r"(?i)\b(WHERE|VALUES|IN)\s+[^;]+'[^']*'"
        return bool(re.search(pattern, query))

    def __repr__(self) -> str:
        table_count = len(self._metadata.tables)
        return f"AsyncDB(uri='{self._uri}', tables={table_count})"


class DatabaseManager:
    """Manages primary (write) and optional replica (read) connections.

    Provides read/write splitting by routing SELECT-style operations to a
    read replica and write operations to the primary database.

    Usage::

        manager = DatabaseManager(
            write_url="postgresql://primary/db",
            read_url="postgresql://replica/db",
        )
        # Routes to replica
        rows = manager.read.select(manager.read.users.id > 0)
        # Routes to primary
        manager.write.insert(manager.write.users, name="Alice")
    """

    def __init__(
        self,
        write_url: str,
        read_url: str | None = None,
        **kwargs: Any,
    ) -> None:
        self.write: DB = DB(write_url, **kwargs)
        self.read: DB = DB(read_url, **kwargs) if read_url else self.write

    def __call__(self, query: Query) -> QuerySet:
        """Route top-level queries through the read connection by default."""
        return self.read(query)

    def close(self) -> None:
        """Close both connections (safely handles shared read==write case)."""
        self.write.close()
        if self.read is not self.write:
            self.read.close()

    def __repr__(self) -> str:
        has_replica = self.read is not self.write
        return f"DatabaseManager(write={self.write!r}, has_replica={has_replica})"
