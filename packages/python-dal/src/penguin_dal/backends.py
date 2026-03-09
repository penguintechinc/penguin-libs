"""Backend URI normalization and dialect configuration."""

from __future__ import annotations

from typing import Any


# Map PyDAL-style URI prefixes to SQLAlchemy equivalents
_URI_MAP: dict[str, str] = {
    "postgres://": "postgresql://",
    "postgres+asyncpg://": "postgresql+asyncpg://",
    "sqlite://": "sqlite:///",
    # mysql://, mssql://, firebird:// stay as-is
}

# Async driver map: sync scheme -> async scheme
_ASYNC_DRIVER_MAP: dict[str, str] = {
    "postgresql": "postgresql+asyncpg",
    "postgresql+psycopg2": "postgresql+asyncpg",
    "mysql": "mysql+aiomysql",
    "mysql+pymysql": "mysql+aiomysql",
    "sqlite": "sqlite+aiosqlite",
    "mssql": "mssql+aioodbc",
    "mssql+pyodbc": "mssql+aioodbc",
}


def normalize_uri(uri: str) -> str:
    """Normalize a database URI to SQLAlchemy format.

    Handles PyDAL-style URIs (e.g. postgres://) and converts them.
    SQLite memory URIs get special handling.

    Args:
        uri: Database URI string

    Returns:
        Normalized SQLAlchemy-compatible URI
    """
    if uri == "sqlite:memory:" or uri == "sqlite://:memory:":
        return "sqlite://"

    for old, new in _URI_MAP.items():
        if uri.startswith(old):
            uri = new + uri[len(old):]
            break

    return uri


def ensure_async_uri(uri: str) -> str:
    """Convert a sync URI to its async equivalent.

    Args:
        uri: Database URI (sync or async)

    Returns:
        Async-compatible URI

    Raises:
        ValueError: If no async driver is known for the given scheme
    """
    uri = normalize_uri(uri)

    scheme = uri.split("://")[0]
    if scheme in _ASYNC_DRIVER_MAP.values():
        return uri

    if scheme in _ASYNC_DRIVER_MAP:
        async_scheme = _ASYNC_DRIVER_MAP[scheme]
        return async_scheme + uri[len(scheme):]

    raise ValueError(
        f"No async driver known for scheme '{scheme}'. "
        f"Supported: {', '.join(_ASYNC_DRIVER_MAP.keys())}"
    )


def get_engine_kwargs(uri: str, pool_size: int = 10) -> dict[str, Any]:
    """Get backend-specific engine keyword arguments.

    Args:
        uri: Normalized database URI
        pool_size: Connection pool size

    Returns:
        Dict of keyword arguments for create_engine/create_async_engine
    """
    kwargs: dict[str, Any] = {
        "pool_pre_ping": True,
        "pool_recycle": 3600,
    }

    scheme = uri.split("://")[0].split("+")[0]

    if scheme == "sqlite":
        # SQLite doesn't support connection pooling the same way
        kwargs.pop("pool_pre_ping", None)
        kwargs.pop("pool_recycle", None)
        kwargs["connect_args"] = {"check_same_thread": False}
    else:
        kwargs["pool_size"] = pool_size
        kwargs["max_overflow"] = pool_size

    if scheme == "mysql":
        kwargs.setdefault("connect_args", {})
        kwargs["connect_args"]["charset"] = "utf8mb4"

    return kwargs
