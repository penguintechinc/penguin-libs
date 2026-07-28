"""Protocol interfaces for all penguin-dal v2 backends."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Protocol, runtime_checkable


@dataclass(slots=True)
class PutOptions:
    """Options for object storage put operations."""

    content_type: str = "application/octet-stream"
    metadata: dict[str, str] = field(default_factory=dict)
    cache_control: str | None = None


@dataclass(slots=True)
class StreamMessage:
    """Message received from a stream consumer."""

    topic: str
    partition: int
    offset: int
    key: bytes | None
    value: bytes
    headers: dict[str, str]
    timestamp: datetime


@dataclass(slots=True)
class FindOptions:
    """Options for document store find operations."""

    limit: int = 0
    skip: int = 0
    sort: list[tuple[str, int]] | None = None


@runtime_checkable
class StorageStore(Protocol):
    """Protocol for synchronous object/file storage backends."""

    def put(
        self, key: str, data: bytes, opts: PutOptions | None = None
    ) -> None:
        """Store object at key."""
        ...

    def get(self, key: str) -> bytes:
        """Retrieve object at key. Raises KeyError if not found."""
        ...

    def delete(self, key: str) -> None:
        """Delete object at key."""
        ...

    def exists(self, key: str) -> bool:
        """Check if object exists at key."""
        ...

    def list(self, prefix: str = "") -> list[str]:
        """List all keys with given prefix."""
        ...

    def get_url(self, key: str, expires_in: int = 3600) -> str:
        """Get a URL to access object at key."""
        ...


@runtime_checkable
class AsyncStorageStore(Protocol):
    """Protocol for asynchronous object/file storage backends."""

    async def put(
        self, key: str, data: bytes, opts: PutOptions | None = None
    ) -> None:
        """Store object at key."""
        ...

    async def get(self, key: str) -> bytes:
        """Retrieve object at key. Raises KeyError if not found."""
        ...

    async def delete(self, key: str) -> None:
        """Delete object at key."""
        ...

    async def exists(self, key: str) -> bool:
        """Check if object exists at key."""
        ...

    async def list(self, prefix: str = "") -> list[str]:
        """List all keys with given prefix."""
        ...

    async def get_url(self, key: str, expires_in: int = 3600) -> str:
        """Get a URL to access object at key."""
        ...


@runtime_checkable
class CacheStore(Protocol):
    """Protocol for synchronous cache backends."""

    def get(self, key: str) -> bytes | None:
        """Get value from cache. Returns None if not found."""
        ...

    def set(self, key: str, value: bytes, ttl: int | None = None) -> None:
        """Set value in cache with optional TTL in seconds."""
        ...

    def delete(self, key: str) -> None:
        """Delete key from cache."""
        ...

    def exists(self, key: str) -> bool:
        """Check if key exists in cache."""
        ...

    def increment(self, key: str, amount: int = 1) -> int:
        """Increment integer value at key by amount."""
        ...

    def flush(self, prefix: str | None = None) -> None:
        """Flush all cache or keys matching prefix."""
        ...

    def get_many(self, keys: list[str]) -> dict[str, bytes | None]:
        """Get multiple values. Non-existent keys map to None."""
        ...

    def set_many(
        self, mapping: dict[str, bytes], ttl: int | None = None
    ) -> None:
        """Set multiple key-value pairs."""
        ...


@runtime_checkable
class AsyncCacheStore(Protocol):
    """Protocol for asynchronous cache backends."""

    async def get(self, key: str) -> bytes | None:
        """Get value from cache. Returns None if not found."""
        ...

    async def set(self, key: str, value: bytes, ttl: int | None = None) -> None:
        """Set value in cache with optional TTL in seconds."""
        ...

    async def delete(self, key: str) -> None:
        """Delete key from cache."""
        ...

    async def exists(self, key: str) -> bool:
        """Check if key exists in cache."""
        ...

    async def increment(self, key: str, amount: int = 1) -> int:
        """Increment integer value at key by amount."""
        ...

    async def flush(self, prefix: str | None = None) -> None:
        """Flush all cache or keys matching prefix."""
        ...

    async def get_many(self, keys: list[str]) -> dict[str, bytes | None]:
        """Get multiple values. Non-existent keys map to None."""
        ...

    async def set_many(
        self, mapping: dict[str, bytes], ttl: int | None = None
    ) -> None:
        """Set multiple key-value pairs."""
        ...


@runtime_checkable
class StreamProducer(Protocol):
    """Protocol for synchronous stream producer backends."""

    def publish(
        self,
        topic: str,
        message: bytes,
        key: bytes | None = None,
        headers: dict[str, str] | None = None,
    ) -> None:
        """Publish message to topic."""
        ...

    def flush(self, timeout: float = 10.0) -> None:
        """Wait for all pending messages to be published."""
        ...

    def close(self) -> None:
        """Close producer and cleanup resources."""
        ...


@runtime_checkable
class AsyncStreamProducer(Protocol):
    """Protocol for asynchronous stream producer backends."""

    async def publish(
        self,
        topic: str,
        message: bytes,
        key: bytes | None = None,
        headers: dict[str, str] | None = None,
    ) -> None:
        """Publish message to topic."""
        ...

    async def flush(self, timeout: float = 10.0) -> None:
        """Wait for all pending messages to be published."""
        ...

    async def close(self) -> None:
        """Close producer and cleanup resources."""
        ...


@runtime_checkable
class StreamConsumer(Protocol):
    """Protocol for synchronous stream consumer backends."""

    def subscribe(self, topics: list[str]) -> None:
        """Subscribe to topics."""
        ...

    def poll(self, timeout_ms: int = 1000) -> list[StreamMessage]:
        """Poll for messages with timeout."""
        ...

    def commit(self) -> None:
        """Commit current offset."""
        ...

    def close(self) -> None:
        """Close consumer and cleanup resources."""
        ...


@runtime_checkable
class AsyncStreamConsumer(Protocol):
    """Protocol for asynchronous stream consumer backends."""

    async def subscribe(self, topics: list[str]) -> None:
        """Subscribe to topics."""
        ...

    async def poll(self, timeout_ms: int = 1000) -> list[StreamMessage]:
        """Poll for messages with timeout."""
        ...

    async def commit(self) -> None:
        """Commit current offset."""
        ...

    async def close(self) -> None:
        """Close consumer and cleanup resources."""
        ...


@runtime_checkable
class DocumentStore(Protocol):
    """Protocol for synchronous document store backends."""

    def insert_one(self, collection: str, document: dict[str, Any]) -> str:
        """Insert document into collection. Returns document ID."""
        ...

    def find_one(
        self, collection: str, filter: dict[str, Any]
    ) -> dict[str, Any] | None:
        """Find one document matching filter."""
        ...

    def find(
        self,
        collection: str,
        filter: dict[str, Any],
        opts: FindOptions | None = None,
    ) -> list[dict[str, Any]]:
        """Find documents matching filter with options."""
        ...

    def update_one(
        self,
        collection: str,
        filter: dict[str, Any],
        update: dict[str, Any],
        upsert: bool = False,
    ) -> int:
        """Update one document. Returns count of documents updated."""
        ...

    def delete_one(
        self, collection: str, filter: dict[str, Any]
    ) -> int:
        """Delete one document. Returns count of documents deleted."""
        ...

    def count(
        self,
        collection: str,
        filter: dict[str, Any] | None = None,
    ) -> int:
        """Count documents matching filter."""
        ...

    def create_index(
        self,
        collection: str,
        keys: list[tuple[str, int]],
        unique: bool = False,
    ) -> None:
        """Create index on collection."""
        ...


@runtime_checkable
class AsyncDocumentStore(Protocol):
    """Protocol for asynchronous document store backends."""

    async def insert_one(self, collection: str, document: dict[str, Any]) -> str:
        """Insert document into collection. Returns document ID."""
        ...

    async def find_one(
        self, collection: str, filter: dict[str, Any]
    ) -> dict[str, Any] | None:
        """Find one document matching filter."""
        ...

    async def find(
        self,
        collection: str,
        filter: dict[str, Any],
        opts: FindOptions | None = None,
    ) -> list[dict[str, Any]]:
        """Find documents matching filter with options."""
        ...

    async def update_one(
        self,
        collection: str,
        filter: dict[str, Any],
        update: dict[str, Any],
        upsert: bool = False,
    ) -> int:
        """Update one document. Returns count of documents updated."""
        ...

    async def delete_one(
        self, collection: str, filter: dict[str, Any]
    ) -> int:
        """Delete one document. Returns count of documents deleted."""
        ...

    async def count(
        self,
        collection: str,
        filter: dict[str, Any] | None = None,
    ) -> int:
        """Count documents matching filter."""
        ...

    async def create_index(
        self,
        collection: str,
        keys: list[tuple[str, int]],
        unique: bool = False,
    ) -> None:
        """Create index on collection."""
        ...
