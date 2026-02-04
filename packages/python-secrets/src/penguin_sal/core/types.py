"""Core data types for penguin-sal secrets management."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass(slots=True)
class Secret:
    """Represents a secret retrieved from a backend."""

    key: str
    value: str | bytes | dict[str, Any]
    version: int | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None
    metadata: dict[str, Any] | None = None


@dataclass(slots=True)
class SecretList:
    """Paginated list of secret keys."""

    keys: list[str]
    cursor: str | None = None


@dataclass(slots=True)
class ConnectionConfig:
    """Parsed connection configuration for a backend adapter."""

    scheme: str
    host: str
    port: int | None = None
    path: str = ""
    username: str | None = None
    password: str | None = None
    params: dict[str, str] = field(default_factory=dict)
