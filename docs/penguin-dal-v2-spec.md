# penguin-dal v2 — Universal Data Abstraction Layer

**Status**: Specification  
**Version**: 1.0  
**Target Release**: v0.4.0 (Python), v0.1.0 (Go)  
**Author**: PenguinTech Engineering  
**Date**: 2026-04-27

---

## Table of Contents

1. [Goals & Non-Goals](#goals--non-goals)
2. [Design Principles](#design-principles)
3. [Package Structure (Python)](#package-structure-python)
4. [Protocol Interfaces](#protocol-interfaces)
5. [Factory Function](#factory-function)
6. [Async Variants](#async-variants)
7. [Per-Backend Implementation Notes](#per-backend-implementation-notes)
8. [Migration Guide](#migration-guide)
9. [pyproject.toml Changes](#projecttoml-changes)
10. [Go Mirror: `go-dal`](#go-mirror-go-dal)
11. [Versioning Plan](#versioning-plan)

---

## Goals & Non-Goals

### Goals

- Expand penguin-dal from a DB-only abstraction into a unified data abstraction layer (DAL)
- Support relational databases, object/file storage, document stores, cache layers, and message streaming
- Maintain **100% backwards compatibility** with v0.3.x — no breaking changes to existing `DB`, `AsyncDB`, `DatabaseManager`, `Row`, `Rows`, `Query`, `Field`, or validators
- Provide a single import path: `from penguin_dal import create_dal`
- Async-first design: every backend with async capability provides async variants
- Minimum versions: Python 3.13, Go 1.24.2
- Per-backend feature detection: calling unsupported operations raises `UnsupportedOperationError`

### Non-Goals

- Not a replacement for ORM frameworks or migration tools
- Not a message broker or queue framework — streaming is minimal producer/consumer abstraction
- Not a GraphQL schema generator or API gateway
- Not a multi-database sharding or federation layer
- Not a caching invalidation orchestrator

---

## Design Principles

### 1. Protocol-Based Architecture
Each backend implements a typed Protocol interface (Python 3.12+). Protocols provide:
- Zero runtime overhead (structural subtyping)
- IDE autocompletion without inheritance
- Easy testing via mocks

### 2. Sync + Async Variants
Every backend supporting async operations has both:
- `SyncBackendStore` — blocking operations
- `AsyncBackendStore` — async/await operations
- Pattern: `db = create_dal(...)` vs. `db = await create_async_dal(...)`

### 3. Factory Functions Over Classes
Use factory functions to instantiate backends:
```python
db = create_dal("postgresql", host="localhost", dbname="myapp")
storage = create_dal("s3", bucket="my-bucket", region="us-east-1")
```
This decouples consumers from implementation details and enables registry-based backend discovery.

### 4. Graceful Feature Detection
Backends expose only the operations they support. Calling unsupported operations raises `UnsupportedOperationError` with a clear message:
```python
memcache = create_dal("memcache", servers=["127.0.0.1:11211"])
# UnsupportedOperationError: MemcacheCache does not support async operations
```

### 5. Existing APIs Unchanged
The core database API (`DB`, `AsyncDB`, `DatabaseManager`, `Row`, `Rows`, `Query`, `Field`, validators) is completely unchanged. All existing code continues to work.

---

## Package Structure (Python)

```
packages/python-dal/src/penguin_dal/
├── __init__.py              # Public API: create_dal, StorageDAL, CacheDAL, StreamDAL, DocumentDAL
├── db.py                    # UNCHANGED — DB, AsyncDB, DatabaseManager
├── query.py                 # UNCHANGED
├── table_proxy.py           # UNCHANGED
├── field.py                 # UNCHANGED
├── validators.py            # UNCHANGED
├── row.py                   # UNCHANGED
├── exceptions.py            # Add: UnsupportedOperationError
├── protocols.py             # NEW: Protocol interfaces for all backends
├── storage/
│   ├── __init__.py
│   ├── s3.py                # S3Store
│   ├── nfs.py               # NFSStore
│   └── iscsi.py             # iSCSIStore
├── document/
│   ├── __init__.py
│   └── mongodb.py           # MongoDAL (sync + async)
├── cache/
│   ├── __init__.py
│   ├── redis.py             # RedisCache (sync + async)
│   ├── valkey.py            # ValkeyCache (sync + async)
│   └── memcache.py          # MemcacheCache (sync only)
├── stream/
│   ├── __init__.py
│   ├── kafka.py             # KafkaStream (producer + consumer)
│   ├── redis_streams.py     # RedisStream (sync + async)
│   └── valkey_streams.py    # ValkeyStream (sync + async)
└── factory.py               # create_dal(), create_async_dal()
```

---

## Protocol Interfaces

All protocols are defined in `protocols.py` using Python's `typing.Protocol`.

### StorageStore Protocol

Abstracts file/object storage (S3, NFS, iSCSI):

```python
from typing import Protocol, Optional
from dataclasses import dataclass

@dataclass(slots=True)
class StorageMetadata:
    """Metadata attached to a stored object."""
    content_type: str
    size: int
    last_modified: datetime
    custom_metadata: dict[str, str]

class StorageStore(Protocol):
    """Protocol for file/object storage backends."""
    
    def put(
        self, 
        key: str, 
        data: bytes, 
        content_type: str = "application/octet-stream",
        metadata: Optional[dict[str, str]] = None
    ) -> None:
        """Store data at key."""
        ...
    
    def get(self, key: str) -> bytes:
        """Retrieve data by key. Raises KeyError if not found."""
        ...
    
    def delete(self, key: str) -> None:
        """Delete object by key."""
        ...
    
    def exists(self, key: str) -> bool:
        """Check if key exists."""
        ...
    
    def list(self, prefix: str = "") -> list[str]:
        """List all keys with optional prefix filter."""
        ...
    
    def get_url(self, key: str, expires_in: int = 3600) -> str:
        """
        Get accessible URL for key.
        - S3: presigned URL (expires_in respected)
        - NFS: file:// URL (expires_in ignored)
        - iSCSI: file:// URL (expires_in ignored)
        """
        ...
    
    def get_metadata(self, key: str) -> StorageMetadata:
        """Retrieve object metadata without downloading content."""
        ...
```

### CacheStore Protocol

Abstracts key/value caching (Redis, Valkey, Memcache):

```python
class CacheStore(Protocol):
    """Protocol for key/value cache backends."""
    
    def get(self, key: str) -> Optional[bytes]:
        """Retrieve value by key. Returns None if not found or expired."""
        ...
    
    def set(self, key: str, value: bytes, ttl: Optional[int] = None) -> None:
        """
        Set key/value pair with optional TTL in seconds.
        If ttl=None, key persists until explicit delete.
        """
        ...
    
    def delete(self, key: str) -> None:
        """Delete key. No-op if key doesn't exist."""
        ...
    
    def exists(self, key: str) -> bool:
        """Check if key exists and is not expired."""
        ...
    
    def increment(self, key: str, amount: int = 1) -> int:
        """
        Increment integer value at key. Initializes to 0 if not found.
        Returns new value after increment.
        """
        ...
    
    def flush(self, prefix: Optional[str] = None) -> None:
        """
        Clear all keys or only keys matching prefix.
        If prefix=None, clear entire cache.
        """
        ...
    
    def get_many(self, keys: list[str]) -> dict[str, Optional[bytes]]:
        """Batch retrieve multiple keys. Includes missing keys with None value."""
        ...
    
    def set_many(self, mapping: dict[str, bytes], ttl: Optional[int] = None) -> None:
        """Batch set multiple key/value pairs with same TTL."""
        ...
```

### StreamStore Protocol

Abstracts message streaming (Kafka, Redis Streams, Valkey Streams):

```python
from dataclasses import dataclass
from datetime import datetime

@dataclass(slots=True)
class StreamMessage:
    """A single message from a stream."""
    topic: str
    partition: int
    offset: int
    key: Optional[bytes]
    value: bytes
    headers: dict[str, str]
    timestamp: datetime

class StreamProducer(Protocol):
    """Protocol for message producers."""
    
    def publish(
        self,
        topic: str,
        message: bytes,
        key: Optional[bytes] = None,
        headers: Optional[dict[str, str]] = None
    ) -> None:
        """
        Publish message to topic.
        - key: optional partitioning key (Kafka only)
        - headers: optional metadata headers (Kafka only)
        """
        ...
    
    def close(self) -> None:
        """Flush pending messages and close producer."""
        ...

class StreamConsumer(Protocol):
    """Protocol for message consumers."""
    
    def subscribe(self, topics: list[str]) -> None:
        """Subscribe to one or more topics."""
        ...
    
    def poll(self, timeout_ms: int = 1000) -> list[StreamMessage]:
        """
        Poll for messages with timeout.
        Returns list of messages (may be empty if timeout reached).
        """
        ...
    
    def commit(self) -> None:
        """Commit current offset. Async backends use await."""
        ...
    
    def close(self) -> None:
        """Close consumer and release resources."""
        ...
    
    def seek(self, topic: str, partition: int, offset: int) -> None:
        """
        Seek to specific offset in partition (Kafka only).
        Raises UnsupportedOperationError for Redis/Valkey Streams.
        """
        ...
```

### DocumentStore Protocol

Abstracts document databases (MongoDB):

```python
class DocumentStore(Protocol):
    """Protocol for document store backends."""
    
    def insert_one(self, collection: str, document: dict) -> str:
        """
        Insert document into collection.
        Returns inserted document's _id (as string).
        """
        ...
    
    def find_one(
        self,
        collection: str,
        filter: dict
    ) -> Optional[dict]:
        """Find single document matching filter. Returns None if not found."""
        ...
    
    def find(
        self,
        collection: str,
        filter: dict,
        limit: int = 0,
        skip: int = 0,
        sort: Optional[list[tuple[str, int]]] = None
    ) -> list[dict]:
        """
        Find documents matching filter.
        - limit=0: no limit
        - sort: list of (field, 1|-1) tuples for ascending/descending
        """
        ...
    
    def update_one(
        self,
        collection: str,
        filter: dict,
        update: dict,
        upsert: bool = False
    ) -> int:
        """
        Update single document matching filter.
        Returns count of modified documents (0 or 1).
        If upsert=True, insert if filter matches nothing.
        """
        ...
    
    def delete_one(self, collection: str, filter: dict) -> int:
        """Delete single document matching filter. Returns count deleted (0 or 1)."""
        ...
    
    def count(self, collection: str, filter: Optional[dict] = None) -> int:
        """Count documents in collection matching optional filter."""
        ...
    
    def create_index(
        self,
        collection: str,
        keys: list[tuple[str, int]],
        unique: bool = False
    ) -> None:
        """
        Create index on collection.
        keys: list of (field, 1|-1) tuples for ascending/descending.
        """
        ...
```

---

## Factory Function

The factory function provides a unified entry point for all backends:

```python
from penguin_dal import create_dal, create_async_dal

# Relational database
db = create_dal(
    "postgresql",
    host="localhost",
    port=5432,
    dbname="myapp",
    user="backend-api-rw",
    password="secret",
    pool_size=10
)
rows = db(db.users.active == True).select()

# S3 storage
storage = create_dal(
    "s3",
    bucket="my-bucket",
    region="us-east-1",
    access_key="AKIAIOSFODNN7EXAMPLE",
    secret_key="wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY",
    endpoint_url=None  # Use AWS; set to "https://minio:9000" for MinIO
)
storage.put("uploads/profile.jpg", image_bytes, content_type="image/jpeg")

# Redis cache
cache = create_dal("redis", host="localhost", port=6379, db=0, password=None)
cache.set("session:user:123", session_data, ttl=3600)

# Valkey cache (drop-in Redis replacement)
cache = create_dal("valkey", host="localhost", port=6379, db=0)

# Kafka producer
producer = create_dal(
    "kafka:producer",
    bootstrap_servers=["kafka-1:9092", "kafka-2:9092"],
    client_id="backend-api"
)
producer.publish("user.events", b'{"action": "login", "user_id": "123"}')

# Kafka consumer
consumer = create_dal(
    "kafka:consumer",
    bootstrap_servers=["kafka-1:9092", "kafka-2:9092"],
    group_id="user-service-group",
    auto_offset_reset="earliest"
)
consumer.subscribe(["user.events"])
for message in consumer.poll(timeout_ms=1000):
    print(message.value)
consumer.commit()

# MongoDB document store
mongo = create_dal(
    "mongodb",
    uri="mongodb://localhost:27017",
    db_name="myapp",
    username="backend-api",
    password="secret"
)
user_id = mongo.insert_one("users", {"name": "Alice", "email": "alice@example.com"})

# Redis Streams
stream = create_dal("redis:stream", host="localhost", port=6379)
stream.publish("events", b"user_created")

# Async variant
async_cache = await create_async_dal("redis", host="localhost", port=6379)
await async_cache.set("key", b"value", ttl=300)
```

**Factory Implementation Details**:
- Maintain a registry of backend names → factory callables
- Backend names: `"postgresql"`, `"mysql"`, `"sqlite"`, `"s3"`, `"nfs"`, `"iscsi"`, `"redis"`, `"valkey"`, `"memcache"`, `"mongodb"`, `"kafka:producer"`, `"kafka:consumer"`, `"redis:stream"`, `"valkey:stream"`
- Async variants use `await create_async_dal(...)` pattern
- **Backwards compatibility**: existing `DB()` constructor still works unchanged

---

## Async Variants

Every backend supporting async operations provides async protocol and factory:

```python
class AsyncStorageStore(Protocol):
    async def put(self, key: str, data: bytes, ...) -> None: ...
    async def get(self, key: str) -> bytes: ...
    async def delete(self, key: str) -> None: ...
    # ... all other methods async

class AsyncCacheStore(Protocol):
    async def get(self, key: str) -> Optional[bytes]: ...
    async def set(self, key: str, value: bytes, ...) -> None: ...
    # ... all other methods async

class AsyncStreamProducer(Protocol):
    async def publish(self, topic: str, message: bytes, ...) -> None: ...

class AsyncStreamConsumer(Protocol):
    async def poll(self, timeout_ms: int = 1000) -> list[StreamMessage]: ...
    async def commit(self) -> None: ...

class AsyncDocumentStore(Protocol):
    async def insert_one(self, collection: str, document: dict) -> str: ...
    async def find_one(self, collection: str, filter: dict) -> Optional[dict]: ...
    # ... all other methods async
```

**Usage Pattern**:
```python
async def main():
    # Async database
    db = await create_async_dal("postgresql", host="localhost", dbname="myapp")
    rows = await db.select(db.users)
    await db.close()
    
    # Async cache
    cache = await create_async_dal("redis", host="localhost")
    value = await cache.get("key")
    await cache.set("key", b"value", ttl=300)
    await cache.close()
    
    # Async streams
    consumer = await create_async_dal("kafka:consumer", bootstrap_servers=[...], group_id="my-group")
    await consumer.subscribe(["events"])
    messages = await consumer.poll(timeout_ms=1000)
    await consumer.commit()
    await consumer.close()

asyncio.run(main())
```

**Async Support by Backend**:

| Backend | Sync | Async | Notes |
|---------|------|-------|-------|
| PostgreSQL | ✅ | ✅ | Via `asyncpg` |
| MySQL | ✅ | ✅ | Via `aiomysql` |
| SQLite | ✅ | ✅ | Via `aiosqlite` |
| S3 | ✅ | ✅ | Via `aioboto3` |
| NFS | ✅ | ✅ | Via `aiofiles` |
| iSCSI | ✅ | ✅ | Via `aiofiles` |
| Redis | ✅ | ✅ | Via `redis[asyncio]` |
| Valkey | ✅ | ✅ | Via `valkey[asyncio]` |
| Memcache | ✅ | ❌ | No async client available |
| MongoDB | ✅ | ✅ | Via `motor` |
| Kafka | ✅ | ❌ | `confluent-kafka` lacks native async |
| Redis Streams | ✅ | ✅ | Via `redis[asyncio]` |
| Valkey Streams | ✅ | ✅ | Via `valkey[asyncio]` |

---

## Per-Backend Implementation Notes

### Relational Databases (PostgreSQL, MySQL, SQLite)

**Current**: Already fully implemented in v0.3.0. No changes required.

**Libraries**: 
- Sync: `SQLAlchemy>=2.0` + `psycopg[binary]`, `pymysql`, `sqlite3`
- Async: `SQLAlchemy[asyncio]` + `asyncpg`, `aiomysql`, `aiosqlite`

---

### S3 Storage

**Library**: `boto3>=1.34` (sync), `aioboto3>=13.0` (async)

**Config**:
```python
@dataclass(slots=True)
class S3Config:
    bucket: str
    region: str
    access_key: str
    secret_key: str
    endpoint_url: Optional[str] = None  # For MinIO, set to "https://minio:9000"
    object_acl: str = "private"  # public-read, private, etc.

# Usage
storage = create_dal("s3", bucket="my-bucket", region="us-east-1", access_key="...", secret_key="...")
storage.put("uploads/doc.pdf", pdf_bytes)
url = storage.get_url("uploads/doc.pdf", expires_in=3600)  # Presigned URL
```

**Features**:
- Presigned URLs via `generate_presigned_url()`
- Multipart upload for large objects (backend implementation detail)
- Server-side encryption (SSE-S3 default)
- MinIO compatibility via custom `endpoint_url`

**Thread-Safety**: Boto3 client is thread-safe; connection pooling handled internally.

---

### NFS Storage

**Library**: `pathlib` (stdlib), `aiofiles>=23.0` (async)

**Config**:
```python
@dataclass(slots=True)
class NFSConfig:
    mount_path: str  # e.g., "/mnt/nfs/data"

# Usage
storage = create_dal("nfs", mount_path="/mnt/nfs/data")
storage.put("uploads/doc.pdf", pdf_bytes)
url = storage.get_url("uploads/doc.pdf")  # file:///mnt/nfs/data/uploads/doc.pdf
```

**Notes**:
- Mount path must be pre-mounted on the host
- No special NFS client library — uses stdlib `pathlib`
- URLs are `file://` paths (not presigned)
- `expires_in` parameter ignored

---

### iSCSI Storage

**Library**: `pathlib` (stdlib), `aiofiles>=23.0` (async)

**Config**:
```python
@dataclass(slots=True)
class iSCSIConfig:
    target: str  # e.g., "192.168.1.10:3260"
    lun: int  # Logical Unit Number, e.g., 0
    mount_path: str  # e.g., "/mnt/iscsi/data"

# Usage
storage = create_dal("iscsi", target="192.168.1.10:3260", lun=0, mount_path="/mnt/iscsi/data")
storage.put("backups/full.tar.gz", backup_bytes)
```

**Notes**:
- Block device must be pre-mounted at `mount_path`
- Read/write operations directly on filesystem above mounted block device
- No special iSCSI initiator management — assumes operator handles discovery/login
- URLs are `file://` paths

---

### MongoDB

**Libraries**: 
- Sync: `pymongo>=4.6`
- Async: `motor>=3.3`

**Config**:
```python
@dataclass(slots=True)
class MongoDBConfig:
    uri: str  # mongodb://host:27017 or mongodb+srv://...
    db_name: str
    username: Optional[str] = None
    password: Optional[str] = None
    tls: bool = False

# Usage
mongo = create_dal("mongodb", uri="mongodb://localhost:27017", db_name="myapp")
doc_id = mongo.insert_one("users", {"name": "Alice", "email": "alice@example.com"})
user = mongo.find_one("users", {"_id": ObjectId(doc_id)})
```

**Features**:
- Connection pooling via `MongoClient` (max_pool_size=50)
- Index creation: `create_index(collection, [("email", 1)], unique=True)`
- TTL indexes for expiring documents
- Transactions (PyMongo 3.11+)

**Thread-Safety**: MongoClient is thread-safe with built-in connection pooling.

---

### Redis

**Libraries**: 
- Sync: `redis>=5.0`
- Async: `redis[asyncio]>=5.0`

**Config**:
```python
@dataclass(slots=True)
class RedisConfig:
    host: str = "localhost"
    port: int = 6379
    db: int = 0
    password: Optional[str] = None
    ssl: bool = False
    decode_responses: bool = False  # Return bytes if False

# Usage
cache = create_dal("redis", host="localhost", port=6379, db=0)
cache.set("session:user:123", session_bytes, ttl=3600)
value = cache.get("session:user:123")
cache.increment("counter:logins")
```

**Features**:
- Per-service key prefix ACLs (config: `--user backend-api on >secret ~cache:* &* +@read +@write`)
- Pub/Sub (not exposed via CacheStore protocol, available via Redis Streams)
- Sorted sets, hashes (not exposed; use find() for document queries)
- Expiration: via `EX` in `SET` (TTL in seconds)

**Thread-Safety**: redis-py >= 4.2 supports thread-safe operations; one client instance OK across threads.

---

### Valkey

**Libraries**: 
- Sync: `valkey>=6.0`
- Async: `valkey[asyncio]>=6.0`

**Config**: Identical to Redis (drop-in replacement).

```python
cache = create_dal("valkey", host="localhost", port=6379)
```

**Notes**:
- Valkey is a fork of Redis (older commits) maintained after Redis changed licensing
- Separate client library but identical API
- All Redis operations work unchanged

---

### Memcache

**Library**: `pymemcache>=4.0` (sync only)

**Config**:
```python
@dataclass(slots=True)
class MemcacheConfig:
    servers: list[str]  # e.g., ["127.0.0.1:11211", "127.0.0.2:11211"]

# Usage
cache = create_dal("memcache", servers=["127.0.0.1:11211"])
cache.set("key", b"value", ttl=300)
value = cache.get("key")
```

**Features**:
- Distributed caching via consistent hashing
- No TTL persistence (restarts clear all keys)
- No async variant available in Python ecosystem

**Thread-Safety**: pymemcache client is thread-safe.

**Limitations**:
- `increment()` works but returns `None` (pymemcache limitation)
- No `get_many()` / `set_many()` (use loop instead)

---

### Kafka

**Libraries**: 
- Sync only: `confluent-kafka[schemaregistry]>=2.3`

**Config**:
```python
@dataclass(slots=True)
class KafkaConfig:
    bootstrap_servers: list[str]
    client_id: str
    security_protocol: str = "PLAINTEXT"  # SASL_SSL, etc.
    sasl_mechanism: Optional[str] = None
    sasl_username: Optional[str] = None
    sasl_password: Optional[str] = None

# Producer
producer = create_dal(
    "kafka:producer",
    bootstrap_servers=["kafka:9092"],
    client_id="backend-api"
)
producer.publish("user.events", b'{"action": "login"}', key=b"user:123")

# Consumer
consumer = create_dal(
    "kafka:consumer",
    bootstrap_servers=["kafka:9092"],
    group_id="user-service-group",
    auto_offset_reset="earliest"
)
consumer.subscribe(["user.events"])
messages = consumer.poll(timeout_ms=1000)
consumer.commit()
```

**Features**:
- Partitioning: `key` parameter determines partition
- Consumer groups: auto-scaling and offset management
- Seek to offset: `consumer.seek(topic, partition, offset)`
- No native async client (confluent-kafka is C-based)

**Thread-Safety**: Producer and consumer are not thread-safe; use one per thread or external locking.

---

### Redis Streams

**Libraries**: 
- Sync: `redis>=5.0`
- Async: `redis[asyncio]>=5.0`

**Config**:
```python
@dataclass(slots=True)
class RedisStreamConfig:
    host: str = "localhost"
    port: int = 6379
    db: int = 0
    password: Optional[str] = None

# Usage
stream = create_dal("redis:stream", host="localhost", port=6379)
stream.publish("events", b"user_created")
```

**Features**:
- XADD (append), XREAD (consume), XGROUP (consumer groups)
- Partition count: 1 (Redis Streams has no real partitions like Kafka)
- Offset: auto-generated timestamp-based IDs
- Consumer group offset tracking

**Notes**:
- `partition` field in `StreamMessage` is always 0
- `seek()` operation partially supported (cannot easily seek in Streams; use group offsets instead)

---

### Valkey Streams

**Libraries**: 
- Sync: `valkey>=6.0`
- Async: `valkey[asyncio]>=6.0`

**Config**: Identical to Redis Streams (drop-in replacement).

```python
stream = create_dal("valkey:stream", host="localhost", port=6379)
```

---

## Migration Guide

### For Existing penguin-dal v0.3.x Consumers

**Step 1: No action required for existing code**

All existing code using `DB()`, `AsyncDB()`, `DatabaseManager`, `Row`, `Rows`, `Query`, `Field`, and validators continues to work unchanged:

```python
# v0.3.0 code — STILL WORKS in v0.4.0
from penguin_dal import DB

db = DB("postgresql://localhost/myapp")
rows = db(db.users.active == True).select()
```

**Step 2: Optional — Use new factory for simplicity**

New code can use the factory for databases too:

```python
# v0.4.0 — unified factory
from penguin_dal import create_dal

db = create_dal("postgresql", host="localhost", dbname="myapp")
rows = db(db.users.active == True).select()
```

**Step 3: Install optional backends as needed**

For new backends, install optional extras:

```bash
pip install penguin-dal[s3]               # S3 storage
pip install penguin-dal[redis,mongodb]    # Redis cache + MongoDB documents
pip install penguin-dal[all]              # All backends
```

**Step 4: Replace ad-hoc backend clients**

Replace direct library usage with unified DAL:

```python
# OLD: Direct boto3 usage
import boto3
s3 = boto3.client("s3")
s3.put_object(Bucket="my-bucket", Key="file.txt", Body=data)

# NEW: Unified DAL
from penguin_dal import create_dal
storage = create_dal("s3", bucket="my-bucket", region="us-east-1", ...)
storage.put("file.txt", data)
```

```python
# OLD: Direct redis usage
import redis
r = redis.Redis(host="localhost")
r.set("key", "value", ex=3600)

# NEW: Unified DAL
from penguin_dal import create_dal
cache = create_dal("redis", host="localhost", port=6379)
cache.set("key", b"value", ttl=3600)
```

**Step 5: Alembic migrations unchanged**

Database schema management via Alembic is completely unchanged:

```bash
alembic init alembic
alembic revision --autogenerate -m "Initial schema"
alembic upgrade head
```

No changes to `alembic/env.py`, `alembic/versions/`, or SQLAlchemy models.

---

## pyproject.toml Changes

### Version Bump

```toml
[project]
name = "penguin-dal"
version = "0.4.0"  # Bumped from 0.3.0
```

### New Optional Dependencies

```toml
[project.optional-dependencies]
# Storage backends
s3 = ["boto3>=1.34", "aioboto3>=13.0"]
nfs = []  # Uses stdlib pathlib, aiofiles optional
iscsi = ["aiofiles>=23.0"]  # Block device management

# Cache backends
redis = ["redis>=5.0"]
valkey = ["valkey>=6.0"]
memcache = ["pymemcache>=4.0"]

# Stream backends
kafka = ["confluent-kafka[schemaregistry]>=2.3"]
redis-stream = ["redis>=5.0"]
valkey-stream = ["valkey>=6.0"]

# Document backends
mongodb = ["pymongo>=4.6", "motor>=3.3"]

# Async support (for backends that support it)
async = [
    "aiofiles>=23.0",
    "aioboto3>=13.0",
    "redis[asyncio]>=5.0",
    "valkey[asyncio]>=6.0",
    "motor>=3.3",
    "aiosqlite>=0.19",
    "asyncpg>=0.29",
    "aiomysql>=0.2.0"
]

# Grouped extras
storage = ["boto3>=1.34", "aioboto3>=13.0", "aiofiles>=23.0"]
cache = ["redis>=5.0", "valkey>=6.0", "pymemcache>=4.0"]
stream = ["confluent-kafka[schemaregistry]>=2.3", "redis>=5.0", "valkey>=6.0"]
document = ["pymongo>=4.6", "motor>=3.3"]

# All backends
all = [
    "boto3>=1.34", "aioboto3>=13.0", "aiofiles>=23.0",
    "pymongo>=4.6", "motor>=3.3",
    "redis>=5.0", "valkey>=6.0", "pymemcache>=4.0",
    "confluent-kafka[schemaregistry]>=2.3",
    "asyncpg>=0.29", "aiomysql>=0.2.0", "aiosqlite>=0.19"
]
```

### Dependencies Already Pinned

Existing dependencies remain pinned; no version changes required:

```toml
[project]
dependencies = [
    "SQLAlchemy>=2.0,<3.0",
    "psycopg[binary]>=3.1",
    "pymysql>=1.1",
]
```

---

## Go Mirror: `go-dal`

### Package Location

New Go package at:
```
packages/go-dal/
```

Module path: `github.com/penguintechinc/penguin-libs/packages/go-dal`

Go version requirement: **1.24.2 minimum** (same as penguin-libs standards)

### Directory Structure

```
packages/go-dal/
├── go.mod
├── go.sum
├── dal.go              # Main factory + interface definitions
├── db/
│   ├── db.go           # SQL wrapper (GORM or database/sql)
│   ├── config.go
│   └── types.go
├── storage/
│   ├── storage.go      # StorageStore interface
│   ├── s3.go           # AWS SDK v2
│   ├── nfs.go          # os.OpenFile operations
│   └── iscsi.go        # Block device via filesystem
├── cache/
│   ├── cache.go        # CacheStore interface
│   ├── redis.go        # go-redis/v9
│   └── valkey.go       # valkey-go
├── stream/
│   ├── stream.go       # StreamProducer/Consumer interfaces
│   ├── kafka.go        # confluent-kafka-go/v2
│   ├── redis_streams.go
│   └── valkey_streams.go
├── document/
│   ├── document.go     # DocumentStore interface
│   └── mongodb.go      # go.mongodb.org/mongo-driver/v2
└── examples/
    ├── db.go
    ├── cache.go
    └── kafka.go
```

### Interface Definitions

All interfaces defined in `dal.go`:

```go
package dal

import (
    "context"
    "time"
)

// StorageStore abstracts file/object storage.
type StorageStore interface {
    Put(ctx context.Context, key string, data []byte, opts ...PutOption) error
    Get(ctx context.Context, key string) ([]byte, error)
    Delete(ctx context.Context, key string) error
    Exists(ctx context.Context, key string) (bool, error)
    List(ctx context.Context, prefix string) ([]string, error)
    GetURL(ctx context.Context, key string, expiresIn time.Duration) (string, error)
    Close() error
}

// CacheStore abstracts key/value caching.
type CacheStore interface {
    Get(ctx context.Context, key string) ([]byte, error)
    Set(ctx context.Context, key string, value []byte, ttl time.Duration) error
    Delete(ctx context.Context, key string) error
    Exists(ctx context.Context, key string) (bool, error)
    Increment(ctx context.Context, key string, amount int64) (int64, error)
    GetMany(ctx context.Context, keys []string) (map[string][]byte, error)
    SetMany(ctx context.Context, mapping map[string][]byte, ttl time.Duration) error
    Close() error
}

// StreamMessage represents a single message from a stream.
type StreamMessage struct {
    Topic     string
    Partition int
    Offset    int64
    Key       []byte
    Value     []byte
    Headers   map[string]string
    Timestamp time.Time
}

// StreamProducer abstracts message producers.
type StreamProducer interface {
    Publish(ctx context.Context, topic string, message []byte, opts ...PublishOption) error
    Close() error
}

// StreamConsumer abstracts message consumers.
type StreamConsumer interface {
    Subscribe(ctx context.Context, topics []string) error
    Poll(ctx context.Context, timeout time.Duration) ([]StreamMessage, error)
    Commit(ctx context.Context) error
    Close() error
    Seek(ctx context.Context, topic string, partition int, offset int64) error
}

// DocumentStore abstracts document databases.
type DocumentStore interface {
    InsertOne(ctx context.Context, collection string, document interface{}) (string, error)
    FindOne(ctx context.Context, collection string, filter interface{}) (map[string]interface{}, error)
    Find(ctx context.Context, collection string, filter interface{}, opts ...FindOption) ([]map[string]interface{}, error)
    UpdateOne(ctx context.Context, collection string, filter, update interface{}) (int64, error)
    DeleteOne(ctx context.Context, collection string, filter interface{}) (int64, error)
    Count(ctx context.Context, collection string, filter interface{}) (int64, error)
    CreateIndex(ctx context.Context, collection string, keys []IndexKey, opts ...IndexOption) error
    Close() error
}

// Factory functions
func NewStorageStore(driver string, config map[string]interface{}) (StorageStore, error) { ... }
func NewCacheStore(driver string, config map[string]interface{}) (CacheStore, error) { ... }
func NewStreamProducer(driver string, config map[string]interface{}) (StreamProducer, error) { ... }
func NewStreamConsumer(driver string, config map[string]interface{}) (StreamConsumer, error) { ... }
func NewDocumentStore(driver string, config map[string]interface{}) (DocumentStore, error) { ... }
```

### Example Usage

```go
package main

import (
    "context"
    "fmt"
    "log"

    "github.com/penguintechinc/penguin-libs/packages/go-dal"
)

func main() {
    ctx := context.Background()

    // S3 storage
    storage, err := dal.NewStorageStore("s3", map[string]interface{}{
        "bucket":    "my-bucket",
        "region":    "us-east-1",
        "accessKey": "AKIAIOSFODNN7EXAMPLE",
        "secretKey": "wJalrXUtnFEMI/K7MDENG/...",
    })
    if err != nil {
        log.Fatal(err)
    }
    defer storage.Close()

    err = storage.Put(ctx, "uploads/file.pdf", pdfBytes)
    url, err := storage.GetURL(ctx, "uploads/file.pdf", 1*time.Hour)
    fmt.Println(url)

    // Redis cache
    cache, err := dal.NewCacheStore("redis", map[string]interface{}{
        "host": "localhost",
        "port": 6379,
    })
    if err != nil {
        log.Fatal(err)
    }
    defer cache.Close()

    cache.Set(ctx, "session:user:123", sessionBytes, 1*time.Hour)
    val, _ := cache.Get(ctx, "session:user:123")
    fmt.Println(val)

    // Kafka producer
    producer, err := dal.NewStreamProducer("kafka", map[string]interface{}{
        "bootstrapServers": []string{"kafka:9092"},
    })
    if err != nil {
        log.Fatal(err)
    }
    defer producer.Close()

    err = producer.Publish(ctx, "user.events", []byte(`{"action":"login"}`))
}
```

### go.mod Dependencies

```
module github.com/penguintechinc/penguin-libs/packages/go-dal

go 1.24.2

require (
    github.com/aws/aws-sdk-go-v2 v1.24.1
    github.com/aws/aws-sdk-go-v2/service/s3 v1.47.5
    github.com/redis/go-redis/v9 v9.5.1
    github.com/valkey-io/valkey-go v1.0.0
    github.com/confluentinc/confluent-kafka-go/v2 v2.3.1
    go.mongodb.org/mongo-driver v2.1.0
    gorm.io/gorm v1.25.7
    gorm.io/driver/postgres v1.5.7
    gorm.io/driver/mysql v1.5.7
)
```

All dependencies pinned to exact versions per Go standards (never `@latest`).

---

## Versioning Plan

### Python Package: penguin-dal

| Version | Release | Change |
|---------|---------|--------|
| 0.3.0 | Current | DB-only abstraction; full backwards compat |
| **0.4.0** | **v2 launch** | **Add storage, cache, streams, documents; all existing APIs unchanged** |
| 0.4.1+ | Maintenance | Bug fixes, dependency updates, new backend support |

**Rationale**: Minor version bump (0.3 → 0.4) — new capabilities without breaking existing API.

### Go Package: go-dal

| Version | Release | Change |
|---------|---------|--------|
| **0.1.0** | **v2 launch** | Initial release; full feature parity with Python v0.4 |
| 0.1.1+ | Maintenance | Bug fixes, dependency updates, new backend support |

**Rationale**: New package; version starts at 0.1.0.

### Release Timeline

- **v0.4.0 / 0.1.0 target**: Q2 2026 (after spec approval and implementation)
- **Beta testing**: Internal use in penguin-libs consumers for 2-4 weeks before release
- **Stable release**: Announce in penguin-libs CHANGELOG with migration guide

---

## Appendix: Design Rationale

### Why Protocols Over Inheritance?

Protocols (structural subtyping) allow:
- Implementations without explicit inheritance
- Easy testing via mock/stub objects
- IDE autocomplete without drag of base classes
- Future flexibility if backends diverge

### Why Separate Async Variants?

Python's async/await requires type clarity at callsite. Mixing sync/async in one interface (via `inspect.iscoroutinefunction`) causes runtime confusion. Separate variants are explicit.

### Why Factory Functions?

Factories decouple consumers from backend implementations. Registry-based discovery enables:
- Lazy importing (backend libraries not required unless used)
- Easy testing (inject mock factory)
- Plugin-style backend registration for third-party backends

### Why Keep Existing DB API Unchanged?

Thousands of lines of existing production code use `DB()`, `AsyncDB()`, etc. Breaking changes would require massive refactors across penguin-libs consumers. Keeping the existing API ensures:
- Seamless adoption (zero changes required)
- Gradual migration path (new code uses factory, old code unchanged)
- Two-way compatibility (can mix old and new in same codebase)

---

**Document Version**: 1.0  
**Last Updated**: 2026-04-27  
**Next Review**: 2026-06-01 (post-implementation)
