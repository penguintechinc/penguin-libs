"""Connection pooling helpers with per-backend tuning."""

from __future__ import annotations

from typing import Any


def get_pool_config(
    uri: str,
    pool_size: int = 10,
    galera: bool = False,
) -> dict[str, Any]:
    """Get pool configuration tuned for the specific backend.

    Args:
        uri: Database URI.
        pool_size: Base pool size.
        galera: If True, apply MariaDB Galera-specific tuning.

    Returns:
        Dict of pool-related engine kwargs.
    """
    scheme = uri.split("://")[0].split("+")[0]

    config: dict[str, Any] = {
        "pool_pre_ping": True,
        "pool_recycle": 3600,
    }

    if scheme == "sqlite":
        return {"connect_args": {"check_same_thread": False}}

    config["pool_size"] = pool_size
    config["max_overflow"] = pool_size

    if scheme == "mysql" and galera:
        # MariaDB Galera optimizations
        config["pool_pre_ping"] = True
        config["pool_recycle"] = 1800  # Shorter recycle for Galera
        config["pool_timeout"] = 10
        config["connect_args"] = {
            "charset": "utf8mb4",
            "connect_timeout": 5,
        }

    elif scheme == "mysql":
        config["connect_args"] = {"charset": "utf8mb4"}

    elif scheme == "postgresql":
        # PostgreSQL defaults are good
        pass

    elif scheme == "mssql":
        config["pool_recycle"] = 1800

    return config


def check_galera_readiness(engine: Any) -> bool:
    """Check if a MariaDB Galera node is ready for writes.

    Executes SHOW STATUS LIKE 'wsrep_ready' to verify.

    Args:
        engine: SQLAlchemy engine connected to MariaDB Galera.

    Returns:
        True if the node is ready, False otherwise.
    """
    from sqlalchemy import text

    try:
        with engine.connect() as conn:
            result = conn.execute(text("SHOW STATUS LIKE 'wsrep_ready'"))
            row = result.first()
            return row is not None and row[1] == "ON"
    except Exception:
        return False
