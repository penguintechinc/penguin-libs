"""Shared test fixtures for penguin-dal."""

import pytest
from sqlalchemy import Boolean, Column, Integer, MetaData, String, Table, create_engine, text
from sqlalchemy.orm import sessionmaker


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
    return d
