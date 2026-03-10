"""Flask integration for Penguin-DAL."""

from __future__ import annotations

import os
from typing import Any

from penguin_dal.db import DB, DatabaseManager

_DAL_KEY = "_penguin_dal"


def init_dal(
    app: Any,
    uri: str | None = None,
    read_uri: str | None = None,
    pool_size: int = 10,
    echo: bool = False,
) -> DB | DatabaseManager:
    """Initialize Penguin-DAL for a Flask application.

    Stores DB or DatabaseManager instance on app.extensions and registers
    teardown. Uses Flask's g object for request-scoped access.

    If read_uri is provided (or DATABASE_READ_URL env var is set),
    creates a DatabaseManager with read/write splitting. Otherwise
    creates a plain DB instance.

    Args:
        app: Flask application instance.
        uri: Write database URI. If None, reads from app.config['DATABASE_URL']
            or DATABASE_URL environment variable.
        read_uri: Read replica URI. If None, checks app.config['DATABASE_READ_URL']
            or DATABASE_READ_URL environment variable.
        pool_size: Connection pool size.
        echo: If True, echo SQL statements.

    Returns:
        DB instance if no read replica configured, DatabaseManager otherwise.
    """
    write_url = (
        uri
        or app.config.get("DATABASE_URL")
        or os.environ.get("DATABASE_URL")
        or app.config.get("DATABASE_URI", app.config.get("SQLALCHEMY_DATABASE_URI", ""))
    )
    if not write_url:
        raise ValueError(
            "Database URI required. Set DATABASE_URL in app.config or pass uri= to init_dal()."
        )

    read_url = (
        read_uri or app.config.get("DATABASE_READ_URL") or os.environ.get("DATABASE_READ_URL")
    )

    if read_url and read_url != write_url:
        db: DB | DatabaseManager = DatabaseManager(
            write_url=write_url,
            read_url=read_url,
            pool_size=pool_size,
            echo=echo,
        )
    else:
        db = DB(uri=write_url, pool_size=pool_size, echo=echo)

    app.extensions[_DAL_KEY] = db

    @app.teardown_appcontext
    def _teardown_dal(exc: BaseException | None) -> None:
        pass  # DB uses connection pooling; no per-request teardown needed

    return db


def get_db() -> DB:
    """Get the Penguin-DAL DB instance for the current Flask app.

    Must be called within a Flask application context.

    Returns:
        DB instance.

    Raises:
        RuntimeError: If called outside application context or init_dal not called.
    """
    from flask import current_app

    if _DAL_KEY not in current_app.extensions:
        raise RuntimeError("Penguin-DAL not initialized. Call init_dal(app) during app setup.")
    return current_app.extensions[_DAL_KEY]
