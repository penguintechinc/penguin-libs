"""Shared test fixtures for penguin-dal."""

import sys
from unittest.mock import MagicMock, AsyncMock

import pytest
from sqlalchemy import Boolean, Column, Integer, MetaData, String, Table, create_engine, text
from sqlalchemy.orm import sessionmaker

# Mock external cache/db libraries that may not be installed
mock_redis = MagicMock()
mock_redis.Redis = MagicMock()
mock_redis.asyncio = MagicMock()
mock_redis.asyncio.Redis = MagicMock()

mock_valkey = MagicMock()
mock_valkey.Valkey = MagicMock()
mock_valkey.asyncio = MagicMock()
mock_valkey.asyncio.Valkey = MagicMock()

mock_pymemcache = MagicMock()
mock_pymemcache.client = MagicMock()
mock_pymemcache.client.pool = MagicMock()
mock_pymemcache.client.pool.ObjectPooledClient = MagicMock()

mock_pymongo = MagicMock()
mock_pymongo.MongoClient = MagicMock()

mock_motor = MagicMock()
mock_motor.motor_asyncio = MagicMock()
mock_motor.motor_asyncio.AsyncMongoClient = MagicMock()

mock_bson = MagicMock()
# Create a mock ObjectId class
class MockObjectId(str):
    def __new__(cls, oid=None):
        if oid is None:
            oid = "507f1f77bcf86cd799439000"
        return str.__new__(cls, oid)

mock_bson.ObjectId = MockObjectId

# Pre-populate sys.modules to avoid ImportError during test collection
sys.modules["redis"] = mock_redis
sys.modules["redis.asyncio"] = mock_redis.asyncio
sys.modules["valkey"] = mock_valkey
sys.modules["valkey.asyncio"] = mock_valkey.asyncio
sys.modules["pymemcache"] = mock_pymemcache
sys.modules["pymemcache.client"] = mock_pymemcache.client
sys.modules["pymemcache.client.pool"] = mock_pymemcache.client.pool
sys.modules["pymongo"] = mock_pymongo
sys.modules["motor"] = mock_motor
sys.modules["motor.motor_asyncio"] = mock_motor.motor_asyncio
sys.modules["bson"] = mock_bson


@pytest.fixture
def engine():
    """Create an in-memory SQLite engine with test tables."""
    eng = create_engine("sqlite://", echo=False)

    metadata = MetaData()
    Table(
        "users",
        metadata,
        Column("id", Integer, primary_key=True, autoincrement=True),
        Column("email", String(255), nullable=False, unique=True),
        Column("name", String(255), nullable=False),
        Column("active", Boolean, default=True),
    )
    Table(
        "posts",
        metadata,
        Column("id", Integer, primary_key=True, autoincrement=True),
        Column("user_id", Integer, nullable=False),
        Column("title", String(255), nullable=False),
        Column("body", String(1000)),
    )
    metadata.create_all(eng)

    # Seed some data
    with eng.connect() as conn:
        conn.execute(
            text(
                "INSERT INTO users (email, name, active) VALUES "
                "('alice@example.com', 'Alice', 1), "
                "('bob@example.com', 'Bob', 1), "
                "('charlie@example.com', 'Charlie', 0)"
            )
        )
        conn.execute(
            text(
                "INSERT INTO posts (user_id, title, body) VALUES "
                "(1, 'First Post', 'Hello world'), "
                "(1, 'Second Post', 'More content'), "
                "(2, 'Bob Post', 'Bob writes')"
            )
        )
        conn.commit()

    return eng


@pytest.fixture
def db(engine):
    """Create a DB instance connected to the test database."""
    from penguin_dal.db import DB

    d = DB.__new__(DB)
    d._uri = "sqlite://"
    d._engine = engine
    d._session_factory = sessionmaker(bind=engine)
    d._metadata = MetaData()
    d._metadata.reflect(bind=engine)
    d._validators = {}
    d._models = {}
    d._migrate = False
    return d


@pytest.fixture
def db_plain():
    """Create a fresh DB instance on an empty in-memory SQLite database.

    Unlike the ``db`` fixture, no tables are pre-created, making this fixture
    suitable for tests that exercise ``define_table``.
    """
    from penguin_dal.db import DB

    return DB("sqlite://", pool_size=1, reflect=False)
