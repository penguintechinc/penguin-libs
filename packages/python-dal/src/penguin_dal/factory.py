"""Unified factory for all penguin-dal backends."""
from __future__ import annotations

from typing import Any


def create_dal(backend: str, **config: Any) -> Any:
    """
    Factory for all penguin-dal backends.

    Database backends (existing):
      "postgresql", "mysql", "sqlite", "mssql", "firebird"
      → returns DB(**config) with appropriate dialect

    Storage backends:
      "s3"    → S3Store(**config)  (or AsyncS3Store if async_=True in config)
      "nfs"   → NFSStore(**config)
      "iscsi" → ISCSIStore(**config)

    Cache backends:
      "redis"    → RedisCache(**config)  (or AsyncRedisCache if async_=True)
      "valkey"   → ValkeyCache(**config) (or AsyncValkeyCache if async_=True)
      "memcache" → MemcacheCache(**config)

    Stream backends:
      "kafka"         → KafkaProducer or KafkaConsumer (role="producer"|"consumer" in config)
      "redis-streams" → RedisStreamProducer or RedisStreamConsumer
      "valkey-streams"→ ValkeyStreamProducer or ValkeyStreamConsumer

    Document backends:
      "mongodb" → MongoDAL(**config)  (or AsyncMongoDAL if async_=True)

    Args:
        backend: Backend type (database, storage, cache, stream, or document)
        **config: Configuration parameters
            async_ (bool): Return async variant if supported (default: False)
            role (str): For stream backends, "producer" or "consumer" (default: "producer")

    Returns:
        Configured backend instance

    Raises:
        ValueError: If backend is unknown or required dependencies are missing
    """
    # Pop optional config keys
    is_async = config.pop("async_", False)
    role = config.pop("role", "producer")

    # Database backends
    if backend in ("postgresql", "mysql", "sqlite", "mssql", "firebird"):
        from penguin_dal.db import DB

        return DB(backend=backend, **config)

    # Storage backends
    if backend == "s3":
        from penguin_dal.storage.s3 import AsyncS3Store, S3Store

        return AsyncS3Store(**config) if is_async else S3Store(**config)

    if backend == "nfs":
        from penguin_dal.storage.nfs import NFSStore

        return NFSStore(**config)

    if backend == "iscsi":
        from penguin_dal.storage.iscsi import ISCSIStore

        return ISCSIStore(**config)

    # Cache backends
    if backend == "redis":
        from penguin_dal.cache.redis import AsyncRedisCache, RedisCache

        return AsyncRedisCache(**config) if is_async else RedisCache(**config)

    if backend == "valkey":
        from penguin_dal.cache.valkey import AsyncValkeyCache, ValkeyCache

        return AsyncValkeyCache(**config) if is_async else ValkeyCache(**config)

    if backend == "memcache":
        from penguin_dal.cache.memcache import MemcacheCache

        return MemcacheCache(**config)

    # Stream backends
    if backend == "kafka":
        from penguin_dal.stream.kafka import KafkaConsumer, KafkaProducer

        if role == "consumer":
            return KafkaConsumer(**config)
        else:
            return KafkaProducer(**config)

    if backend == "redis-streams":
        from penguin_dal.stream.redis_streams import (
            RedisStreamConsumer,
            RedisStreamProducer,
        )

        if role == "consumer":
            return RedisStreamConsumer(**config)
        else:
            return RedisStreamProducer(**config)

    if backend == "valkey-streams":
        from penguin_dal.stream.valkey_streams import (
            ValkeyStreamConsumer,
            ValkeyStreamProducer,
        )

        if role == "consumer":
            return ValkeyStreamConsumer(**config)
        else:
            return ValkeyStreamProducer(**config)

    # Document backends
    if backend == "mongodb":
        from penguin_dal.document.mongodb import AsyncMongoDAL, MongoDAL

        return AsyncMongoDAL(**config) if is_async else MongoDAL(**config)

    # Unknown backend
    valid_backends = [
        "postgresql",
        "mysql",
        "sqlite",
        "mssql",
        "firebird",
        "s3",
        "nfs",
        "iscsi",
        "redis",
        "valkey",
        "memcache",
        "kafka",
        "redis-streams",
        "valkey-streams",
        "mongodb",
    ]
    raise ValueError(
        f"Unknown backend: {backend!r}. Valid backends: {', '.join(valid_backends)}"
    )
