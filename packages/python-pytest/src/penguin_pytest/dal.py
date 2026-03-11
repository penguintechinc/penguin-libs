"""DAL engine and DB fixtures for PenguinTech penguin-dal tests."""

from __future__ import annotations

from typing import Any

import pytest
from sqlalchemy import (
    Boolean,
    Column,
    Engine,
    Integer,
    MetaData,
    String,
    Table,
    create_engine,
    text,
)
from sqlalchemy.orm import sessionmaker


@pytest.fixture
def sqlite_engine() -> Engine:
    """Create a bare in-memory SQLite engine with no tables.

    Useful when you want to define your own schema in a test.

    Returns:
        A :class:`~sqlalchemy.engine.Engine` backed by ``sqlite://`` (memory).
    """
    return create_engine("sqlite://", echo=False)


@pytest.fixture
def users_posts_engine() -> Engine:
    """Create an in-memory SQLite engine pre-populated with ``users``/``posts`` tables.

    The schema mirrors the fixture used across penguin-dal tests:

    * ``users`` — ``id``, ``email``, ``name``, ``active``
    * ``posts`` — ``id``, ``user_id``, ``title``, ``body``

    Three users (alice, bob, charlie) and three posts are seeded.

    Returns:
        A ready-to-use :class:`~sqlalchemy.engine.Engine`.
    """
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
def dal_db(users_posts_engine: Engine) -> Any:
    """Create a ``penguin_dal.db.DB`` instance wired to *users_posts_engine*.

    This fixture constructs a ``DB`` object without going through its normal
    ``__init__`` so tests can work against the shared in-memory SQLite engine
    rather than a real database.

    Args:
        users_posts_engine: A SQLAlchemy engine (typically the
            :func:`users_posts_engine` fixture).

    Returns:
        A ``penguin_dal.db.DB`` instance with ``_engine`` set and metadata
        reflected from the engine.
    """
    from penguin_dal.db import DB

    d: Any = DB.__new__(DB)
    d._uri = "sqlite://"
    d._engine = users_posts_engine
    d._session_factory = sessionmaker(bind=users_posts_engine)
    d._metadata = MetaData()
    d._metadata.reflect(bind=users_posts_engine)
    d._validators = {}
    d._models = {}
    return d
