"""Test define_table() method for DB and AsyncDB."""

import pytest
from sqlalchemy import MetaData, create_engine, text
from sqlalchemy.orm import sessionmaker

from penguin_dal import DB, AsyncDB, DAL, Field


@pytest.fixture
def sync_db():
    """Create a sync DB instance with SQLite in-memory."""
    # Use DB directly with in-memory SQLite
    db = DB("sqlite://", reflect=False)
    yield db
    db.close()


@pytest.fixture
async def async_db():
    """Create an async DB instance with SQLite in-memory."""
    db = AsyncDB("sqlite+aiosqlite:///:memory:")
    yield db
    await db.close()


class TestDefineTableSync:
    """Test define_table() for sync DB."""

    def test_define_table_basic(self, sync_db):
        """Test basic define_table creates a table."""
        # Define a simple table
        table_proxy = sync_db.define_table(
            "users",
            Field("name", "string", length=128),
            Field("email", "string", length=255, notnull=True, unique=True),
        )

        # Check table exists in metadata
        assert "users" in sync_db.metadata.tables
        table = sync_db.metadata.tables["users"]
        assert "id" in table.columns  # Auto-added
        assert "name" in table.columns
        assert "email" in table.columns

    def test_define_table_auto_id(self, sync_db):
        """Test auto-adds id primary key when not specified."""
        sync_db.define_table(
            "posts",
            Field("title", "string", length=255),
            Field("content", "text"),
        )

        table = sync_db.metadata.tables["posts"]
        id_col = table.columns["id"]
        assert id_col.primary_key
        assert id_col.autoincrement

    def test_define_table_no_auto_id_when_provided(self, sync_db):
        """Test doesn't auto-add id when Field with type='id' is provided."""
        sync_db.define_table(
            "articles",
            Field("id", "id"),
            Field("title", "string", length=255),
        )

        table = sync_db.metadata.tables["articles"]
        id_col = table.columns["id"]
        # Should have only one id column
        id_cols = [col for col in table.columns.values() if col.primary_key]
        assert len(id_cols) == 1
        assert id_cols[0].name == "id"

    def test_define_table_with_validators(self, sync_db):
        """Test validators from Field.requires are registered."""

        def is_valid_email(value):
            return "@" in value

        sync_db.define_table(
            "users",
            Field("email", "string", requires=[is_valid_email]),
        )

        # Check validators are registered
        assert "users" in sync_db._validators
        assert "email" in sync_db._validators["users"]
        assert is_valid_email in sync_db._validators["users"]["email"]

    def test_define_table_accessible_via_db(self, sync_db):
        """Test defined table is accessible via db.tablename."""
        sync_db.define_table(
            "books",
            Field("title", "string", length=255),
            Field("author", "string", length=255),
        )

        # Access table via attribute
        table_proxy = sync_db.books
        assert table_proxy is not None

    def test_define_table_insert_and_select(self, sync_db):
        """Test insert and select after define_table."""
        sync_db.define_table(
            "users",
            Field("name", "string", length=128),
            Field("email", "string", length=255),
        )

        # Insert
        table = sync_db.metadata.tables["users"]
        with sync_db._session_factory() as session:
            session.execute(
                table.insert().values(name="Alice", email="alice@example.com")
            )
            session.commit()

        # Select using PyDAL-style syntax
        result = sync_db(sync_db.users.name == "Alice").select()
        assert len(result) == 1
        assert result[0].name == "Alice"
        assert result[0].email == "alice@example.com"

    def test_dal_alias_is_db(self, sync_db):
        """Test DAL alias works as drop-in for DB."""
        # DAL should be an alias for DB
        assert DAL is DB

    def test_import_dal_and_field(self):
        """Test from penguin_dal import DAL, Field works."""
        # This test just verifies imports work
        from penguin_dal import DAL, Field

        assert DAL is not None
        assert Field is not None


class TestDefineTableAsync:
    """Test define_table() for async AsyncDB."""

    @pytest.mark.asyncio
    async def test_define_table_basic_async(self, async_db):
        """Test basic define_table creates a table (async)."""
        # Define a simple table
        table_proxy = await async_db.define_table(
            "users",
            Field("name", "string", length=128),
            Field("email", "string", length=255, notnull=True, unique=True),
        )

        # Check table exists in metadata
        assert "users" in async_db.metadata.tables
        table = async_db.metadata.tables["users"]
        assert "id" in table.columns  # Auto-added
        assert "name" in table.columns
        assert "email" in table.columns

    @pytest.mark.asyncio
    async def test_define_table_auto_id_async(self, async_db):
        """Test auto-adds id primary key when not specified (async)."""
        await async_db.define_table(
            "posts",
            Field("title", "string", length=255),
            Field("content", "text"),
        )

        table = async_db.metadata.tables["posts"]
        id_col = table.columns["id"]
        assert id_col.primary_key
        assert id_col.autoincrement

    @pytest.mark.asyncio
    async def test_define_table_no_auto_id_when_provided_async(self, async_db):
        """Test doesn't auto-add id when Field with type='id' is provided (async)."""
        await async_db.define_table(
            "articles",
            Field("id", "id"),
            Field("title", "string", length=255),
        )

        table = async_db.metadata.tables["articles"]
        id_col = table.columns["id"]
        # Should have only one id column
        id_cols = [col for col in table.columns.values() if col.primary_key]
        assert len(id_cols) == 1
        assert id_cols[0].name == "id"

    @pytest.mark.asyncio
    async def test_define_table_with_validators_async(self, async_db):
        """Test validators from Field.requires are registered (async)."""

        def is_valid_email(value):
            return "@" in value

        await async_db.define_table(
            "users",
            Field("email", "string", requires=[is_valid_email]),
        )

        # Check validators are registered
        assert "users" in async_db._validators
        assert "email" in async_db._validators["users"]
        assert is_valid_email in async_db._validators["users"]["email"]

    @pytest.mark.asyncio
    async def test_define_table_insert_and_select_async(self, async_db):
        """Test insert and select after define_table (async)."""
        await async_db.define_table(
            "users",
            Field("name", "string", length=128),
            Field("email", "string", length=255),
        )

        # Insert
        table = async_db.metadata.tables["users"]
        from sqlalchemy.ext.asyncio import AsyncSession

        async with async_db._session_factory() as session:
            await session.execute(
                table.insert().values(name="Alice", email="alice@example.com")
            )
            await session.commit()

        # Select using PyDAL-style syntax
        result = await async_db(async_db.users.name == "Alice").select()
        assert len(result) == 1
        assert result[0].name == "Alice"
        assert result[0].email == "alice@example.com"


class TestMigrateParameter:
    """Test migrate parameter in DB.__init__."""

    def test_migrate_parameter_stored(self):
        """Test migrate parameter is stored."""
        db = DB("sqlite://", migrate=True, reflect=False)
        assert db._migrate is True
        db.close()

    def test_migrate_default_false(self):
        """Test migrate defaults to False."""
        db = DB("sqlite://", reflect=False)
        assert db._migrate is False
        db.close()
