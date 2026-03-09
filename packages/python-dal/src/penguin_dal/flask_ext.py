"""Flask integration for Penguin-DAL."""

from __future__ import annotations

from typing import Any

from penguin_dal.db import DB


_DAL_KEY = "_penguin_dal"


def init_dal(
    app: Any,
    uri: str | None = None,
    pool_size: int = 10,
    echo: bool = False,
) -> None:
    """Initialize Penguin-DAL for a Flask application.

    Stores DB instance on app.extensions and registers teardown.
    Uses Flask's g object for request-scoped access.

    Args:
        app: Flask application instance.
        uri: Database URI. If None, reads from app.config['DATABASE_URI'].
        pool_size: Connection pool size.
        echo: If True, echo SQL statements.
    """
    if uri is None:
        uri = app.config.get("DATABASE_URI", app.config.get("SQLALCHEMY_DATABASE_URI", ""))
    if not uri:
        raise ValueError(
            "Database URI required. Set DATABASE_URI in app.config or pass uri= to init_dal()."
        )

    db = DB(uri=uri, pool_size=pool_size, echo=echo)
    app.extensions[_DAL_KEY] = db

    @app.teardown_appcontext
    def _teardown_dal(exc: BaseException | None) -> None:
        pass  # DB uses connection pooling; no per-request teardown needed


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
        raise RuntimeError(
            "Penguin-DAL not initialized. Call init_dal(app) during app setup."
        )
    return current_app.extensions[_DAL_KEY]
