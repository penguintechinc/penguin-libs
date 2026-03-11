"""Quart integration for Penguin-DAL (async-first)."""

from __future__ import annotations

from typing import Any

from penguin_dal.db import AsyncDB

_DAL_KEY = "_penguin_dal"


def init_dal(
    app: Any,
    uri: str | None = None,
    pool_size: int = 10,
    echo: bool = False,
) -> None:
    """Initialize Penguin-DAL for a Quart application.

    Stores AsyncDB instance on app.extensions and registers startup
    hook for table reflection.

    Args:
        app: Quart application instance.
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

    db = AsyncDB(uri=uri, pool_size=pool_size, echo=echo)
    app.extensions[_DAL_KEY] = db

    @app.before_serving
    async def _reflect_tables() -> None:
        await db.reflect()

    @app.after_serving
    async def _shutdown_dal() -> None:
        await db.close()


def get_db() -> AsyncDB:
    """Get the Penguin-DAL AsyncDB instance for the current Quart app.

    Must be called within a Quart application context.

    Returns:
        AsyncDB instance.

    Raises:
        RuntimeError: If called outside app context or init_dal not called.
    """
    from quart import current_app

    if _DAL_KEY not in current_app.extensions:
        raise RuntimeError("Penguin-DAL not initialized. Call init_dal(app) during app setup.")
    return current_app.extensions[_DAL_KEY]
