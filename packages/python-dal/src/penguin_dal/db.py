"""DB (sync) and AsyncDB (async) entry points."""

from __future__ import annotations

from typing import Any

from sqlalchemy import MetaData, Table, create_engine
from sqlalchemy.orm import sessionmaker

from penguin_dal.backends import ensure_async_uri, get_engine_kwargs, normalize_uri
from penguin_dal.exceptions import TableNotFoundError
from penguin_dal.query import AsyncQuerySet, Query, QuerySet
from penguin_dal.table_proxy import TableProxy


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
