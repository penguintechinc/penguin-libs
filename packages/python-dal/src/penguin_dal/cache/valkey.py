"""Valkey cache backend for penguin-dal."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(slots=True)
class ValkeyConfig:
    """Configuration for Valkey cache backend."""

    host: str = "localhost"
    port: int = 6379
    db: int = 0
    password: str | None = None
    ssl: bool = False
    prefix: str = ""
    socket_timeout: float = 5.0
    socket_connect_timeout: float = 5.0
    max_connections: int = 50


class ValkeyCache:
    """Synchronous Valkey cache backend using valkey.Valkey."""

    def __init__(self, config: ValkeyConfig) -> None:
        """Initialize Valkey cache with given config."""
        try:
            import valkey
        except ImportError as e:
            raise ImportError(
                "Install valkey: pip install penguin-dal[valkey]"
            ) from e

        self.config = config
        self.client = valkey.Valkey(
            host=config.host,
            port=config.port,
            db=config.db,
            password=config.password,
            ssl=config.ssl,
            socket_timeout=config.socket_timeout,
            socket_connect_timeout=config.socket_connect_timeout,
            max_connections=config.max_connections,
            decode_responses=False,
        )

    def _make_key(self, key: str) -> str:
        """Prepend prefix to key."""
        return f"{self.config.prefix}{key}"

    def get(self, key: str) -> bytes | None:
        """Get value by key. Returns None if missing."""
        result = self.client.get(self._make_key(key))
        return result

    def set(self, key: str, value: bytes, ttl: int | None = None) -> None:
        """Set key-value pair with optional TTL in seconds."""
        full_key = self._make_key(key)
        if ttl is not None:
            self.client.setex(full_key, ttl, value)
        else:
            self.client.set(full_key, value)

    def delete(self, key: str) -> None:
        """Delete key."""
        self.client.delete(self._make_key(key))

    def exists(self, key: str) -> bool:
        """Check if key exists."""
        return bool(self.client.exists(self._make_key(key)))

    def increment(self, key: str, amount: int = 1) -> int:
        """Increment key by amount, return new value."""
        return int(self.client.incrby(self._make_key(key), amount))

    def flush(self, prefix: str | None = None) -> None:
        """Delete all keys matching prefix. If prefix is None, flush entire db."""
        if prefix is None:
            self.client.flushdb()
        else:
            # Scan keys matching the full prefix pattern
            scan_pattern = f"{self.config.prefix}{prefix}*"
            cursor = 0
            batch_size = 100
            while True:
                cursor, keys = self.client.scan(
                    cursor, match=scan_pattern, count=batch_size
                )
                if keys:
                    self.client.delete(*keys)
                if cursor == 0:
                    break

    def get_many(self, keys: list[str]) -> dict[str, bytes | None]:
        """Get multiple keys using MGET. Returns dict keyed by original keys."""
        if not keys:
            return {}

        full_keys = [self._make_key(k) for k in keys]
        values = self.client.mget(full_keys)

        result = {}
        for original_key, value in zip(keys, values):
            result[original_key] = value

        return result

    def set_many(
        self, mapping: dict[str, bytes], ttl: int | None = None
    ) -> None:
        """Set multiple key-value pairs using pipeline."""
        if not mapping:
            return

        pipe = self.client.pipeline()
        for key, value in mapping.items():
            full_key = self._make_key(key)
            if ttl is not None:
                pipe.setex(full_key, ttl, value)
            else:
                pipe.set(full_key, value)
        pipe.execute()

    def close(self) -> None:
        """Close Valkey connection."""
        self.client.close()


class AsyncValkeyCache:
    """Async Valkey cache backend using valkey.asyncio.Valkey."""

    def __init__(self, config: ValkeyConfig) -> None:
        """Initialize async Valkey cache with given config."""
        try:
            import valkey.asyncio
        except ImportError as e:
            raise ImportError(
                "Install valkey: pip install penguin-dal[valkey]"
            ) from e

        self.config = config
        self.client: Any = valkey.asyncio.Valkey(
            host=config.host,
            port=config.port,
            db=config.db,
            password=config.password,
            ssl=config.ssl,
            socket_timeout=config.socket_timeout,
            socket_connect_timeout=config.socket_connect_timeout,
            max_connections=config.max_connections,
            decode_responses=False,
        )

    def _make_key(self, key: str) -> str:
        """Prepend prefix to key."""
        return f"{self.config.prefix}{key}"

    async def get(self, key: str) -> bytes | None:
        """Get value by key. Returns None if missing."""
        result = await self.client.get(self._make_key(key))
        return result

    async def set(self, key: str, value: bytes, ttl: int | None = None) -> None:
        """Set key-value pair with optional TTL in seconds."""
        full_key = self._make_key(key)
        if ttl is not None:
            await self.client.setex(full_key, ttl, value)
        else:
            await self.client.set(full_key, value)

    async def delete(self, key: str) -> None:
        """Delete key."""
        await self.client.delete(self._make_key(key))

    async def exists(self, key: str) -> bool:
        """Check if key exists."""
        return bool(await self.client.exists(self._make_key(key)))

    async def increment(self, key: str, amount: int = 1) -> int:
        """Increment key by amount, return new value."""
        return int(await self.client.incrby(self._make_key(key), amount))

    async def flush(self, prefix: str | None = None) -> None:
        """Delete all keys matching prefix. If prefix is None, flush entire db."""
        if prefix is None:
            await self.client.flushdb()
        else:
            # Scan keys matching the full prefix pattern
            scan_pattern = f"{self.config.prefix}{prefix}*"
            cursor = 0
            batch_size = 100
            while True:
                cursor, keys = await self.client.scan(
                    cursor, match=scan_pattern, count=batch_size
                )
                if keys:
                    await self.client.delete(*keys)
                if cursor == 0:
                    break

    async def get_many(self, keys: list[str]) -> dict[str, bytes | None]:
        """Get multiple keys using MGET. Returns dict keyed by original keys."""
        if not keys:
            return {}

        full_keys = [self._make_key(k) for k in keys]
        values = await self.client.mget(full_keys)

        result = {}
        for original_key, value in zip(keys, values):
            result[original_key] = value

        return result

    async def set_many(
        self, mapping: dict[str, bytes], ttl: int | None = None
    ) -> None:
        """Set multiple key-value pairs using pipeline."""
        if not mapping:
            return

        pipe = await self.client.pipeline()
        for key, value in mapping.items():
            full_key = self._make_key(key)
            if ttl is not None:
                pipe.setex(full_key, ttl, value)
            else:
                pipe.set(full_key, value)
        await pipe.execute()

    async def close(self) -> None:
        """Close Valkey connection."""
        await self.client.close()
