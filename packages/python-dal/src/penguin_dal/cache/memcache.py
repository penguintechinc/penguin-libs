"""Memcache cache backend for penguin-dal."""
from __future__ import annotations

from dataclasses import dataclass

from penguin_dal.exceptions import UnsupportedOperationError


@dataclass(slots=True)
class MemcacheConfig:
    """Configuration for Memcache backend."""

    servers: list[str]
    prefix: str = ""
    connect_timeout: float = 5.0
    timeout: float = 5.0
    max_pool_size: int = 10
    ignore_exc: bool = False


class MemcacheCache:
    """Memcache backend using pymemcache PooledClient (thread-safe)."""

    def __init__(self, config: MemcacheConfig) -> None:
        """Initialize Memcache cache with given config."""
        try:
            from pymemcache.client.pool import ObjectPooledClient
        except ImportError as e:
            raise ImportError(
                "Install pymemcache: pip install penguin-dal[memcache]"
            ) from e

        self.config = config
        # Parse servers list and create pool
        server_addrs = [self._parse_server(s) for s in config.servers]

        # Create pooled client connecting to first server with fallbacks
        self.client = ObjectPooledClient(
            server_addrs[0] if server_addrs else ("localhost", 11211),
            connect_timeout=config.connect_timeout,
            timeout=config.timeout,
            max_pool_size=config.max_pool_size,
            ignore_exc=config.ignore_exc,
        )

    def _parse_server(self, server: str) -> tuple[str, int]:
        """Parse server string 'host:port' into (host, port) tuple."""
        if ":" in server:
            host, port_str = server.rsplit(":", 1)
            return (host, int(port_str))
        return (server, 11211)

    def _make_key(self, key: str) -> str:
        """Prepend prefix to key."""
        return f"{self.config.prefix}{key}".encode() if self.config.prefix else key.encode()

    def get(self, key: str) -> bytes | None:
        """Get value by key. Returns None if missing."""
        result = self.client.get(self._make_key(key))
        return result

    def set(self, key: str, value: bytes, ttl: int | None = None) -> None:
        """Set key-value pair with optional TTL in seconds."""
        expire = ttl if ttl is not None else 0
        self.client.set(self._make_key(key), value, expire=expire)

    def delete(self, key: str) -> None:
        """Delete key."""
        self.client.delete(self._make_key(key))

    def exists(self, key: str) -> bool:
        """Check if key exists."""
        result = self.client.get(self._make_key(key))
        return result is not None

    def increment(self, key: str, amount: int = 1) -> int:
        """Increment key by amount, return new value."""
        result = self.client.incr(self._make_key(key), amount)
        return int(result) if result is not None else 0

    def flush(self, prefix: str | None = None) -> None:
        """Delete all keys matching prefix. Memcache doesn't support prefix scans."""
        if prefix is not None:
            raise UnsupportedOperationError("memcache", "flush_with_prefix")
        # Flush entire cache for this server
        self.client.flush_all()

    def get_many(self, keys: list[str]) -> dict[str, bytes | None]:
        """Get multiple keys. Returns dict keyed by original keys."""
        if not keys:
            return {}

        full_keys = [self._make_key(k) for k in keys]
        values = self.client.get_many(full_keys)

        result = {}
        for original_key, full_key in zip(keys, full_keys):
            result[original_key] = values.get(full_key)

        return result

    def set_many(
        self, mapping: dict[str, bytes], ttl: int | None = None
    ) -> None:
        """Set multiple key-value pairs."""
        if not mapping:
            return

        expire = ttl if ttl is not None else 0
        for key, value in mapping.items():
            self.client.set(self._make_key(key), value, expire=expire)

    def close(self) -> None:
        """Close Memcache connection."""
        self.client.close()
