"""Penguin-DAL: SQLAlchemy runtime wrapper with PyDAL ergonomics."""

from penguin_dal.db import DB, AsyncDB, DatabaseManager
from penguin_dal.exceptions import DALError, TableNotFoundError, ValidationError
from penguin_dal.factory import create_dal
from penguin_dal.field import Field
from penguin_dal.field_proxy import FieldProxy
from penguin_dal.pagination import Cursor, Page
from penguin_dal.protocols import (
    AsyncCacheStore,
    AsyncDocumentStore,
    AsyncStorageStore,
    AsyncStreamConsumer,
    AsyncStreamProducer,
    CacheStore,
    DocumentStore,
    FindOptions,
    PutOptions,
    StorageStore,
    StreamConsumer,
    StreamMessage,
    StreamProducer,
)
from penguin_dal.query import AsyncQuerySet, Query, QuerySet, Row, Rows
from penguin_dal.table_proxy import TableProxy
from penguin_dal.validators import (
    IS_DATETIME,
    IS_EMAIL,
    IS_IN_DB,
    IS_IN_SET,
    IS_INT_IN_RANGE,
    IS_IPADDRESS,
    IS_JSON,
    IS_LENGTH,
    IS_MATCH,
    IS_NOT_EMPTY,
    IS_NOT_IN_DB,
    IS_NULL_OR,
    validated_columns,
)

# Storage backends (lazy import)
try:
    from penguin_dal.storage.s3 import AsyncS3Store, S3Store
except ImportError:
    pass

try:
    from penguin_dal.storage.nfs import NFSStore
except ImportError:
    pass

try:
    from penguin_dal.storage.iscsi import ISCSIStore
except ImportError:
    pass

# Cache backends (lazy import)
try:
    from penguin_dal.cache.redis import AsyncRedisCache, RedisCache
except ImportError:
    pass

try:
    from penguin_dal.cache.valkey import AsyncValkeyCache, ValkeyCache
except ImportError:
    pass

try:
    from penguin_dal.cache.memcache import MemcacheCache
except ImportError:
    pass

# Stream backends (lazy import)
try:
    from penguin_dal.stream.kafka import KafkaConsumer, KafkaProducer
except ImportError:
    pass

try:
    from penguin_dal.stream.redis_streams import (
        RedisStreamConsumer,
        RedisStreamProducer,
    )
except ImportError:
    pass

try:
    from penguin_dal.stream.valkey_streams import (
        ValkeyStreamConsumer,
        ValkeyStreamProducer,
    )
except ImportError:
    pass

# Document backends (lazy import)
try:
    from penguin_dal.document.mongodb import AsyncMongoDAL, MongoDAL
except ImportError:
    pass

# PyDAL compatibility aliases
DAL = DB

__all__ = [
    # Core database
    "DB",
    "DAL",
    "AsyncDB",
    "DatabaseManager",
    # Fields & tables
    "Field",
    "TableProxy",
    "FieldProxy",
    # Query & results
    "Query",
    "QuerySet",
    "AsyncQuerySet",
    "Row",
    "Rows",
    # Pagination
    "Cursor",
    "Page",
    # Exceptions
    "DALError",
    "TableNotFoundError",
    "ValidationError",
    # Protocols & options
    "StorageStore",
    "AsyncStorageStore",
    "CacheStore",
    "AsyncCacheStore",
    "StreamProducer",
    "AsyncStreamProducer",
    "StreamConsumer",
    "AsyncStreamConsumer",
    "DocumentStore",
    "AsyncDocumentStore",
    "PutOptions",
    "StreamMessage",
    "FindOptions",
    # Factory
    "create_dal",
    # Storage backends
    "S3Store",
    "AsyncS3Store",
    "NFSStore",
    "ISCSIStore",
    # Cache backends
    "RedisCache",
    "AsyncRedisCache",
    "ValkeyCache",
    "AsyncValkeyCache",
    "MemcacheCache",
    # Stream backends
    "KafkaProducer",
    "KafkaConsumer",
    "RedisStreamProducer",
    "RedisStreamConsumer",
    "ValkeyStreamProducer",
    "ValkeyStreamConsumer",
    # Document backends
    "MongoDAL",
    "AsyncMongoDAL",
    # Validators
    "validated_columns",
    "IS_NOT_EMPTY",
    "IS_LENGTH",
    "IS_EMAIL",
    "IS_IN_SET",
    "IS_MATCH",
    "IS_NOT_IN_DB",
    "IS_IN_DB",
    "IS_INT_IN_RANGE",
    "IS_IPADDRESS",
    "IS_JSON",
    "IS_DATETIME",
    "IS_NULL_OR",
]
