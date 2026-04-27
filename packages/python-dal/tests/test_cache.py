"""Tests for cache backends."""
from __future__ import annotations

import pytest
from unittest.mock import MagicMock, AsyncMock

from penguin_dal.cache.redis import RedisCache, AsyncRedisCache, RedisConfig
from penguin_dal.cache.valkey import ValkeyCache, AsyncValkeyCache, ValkeyConfig
from penguin_dal.cache.memcache import (
    MemcacheCache,
    MemcacheConfig,
    UnsupportedOperationError,
)


class TestRedisCache:
    """Tests for synchronous Redis cache."""

    def test_init_creates_client(self):
        """Test initialization creates Redis client."""
        import redis
        mock_client = MagicMock()
        redis.Redis = MagicMock(return_value=mock_client)

        config = RedisConfig(host="localhost", port=6379)
        cache = RedisCache(config)

        assert cache.client == mock_client
        redis.Redis.assert_called_once()

    def test_get_returns_value(self):
        """Test get returns value from Redis."""
        import redis
        mock_client = MagicMock()
        mock_client.get.return_value = b"value"
        redis.Redis = MagicMock(return_value=mock_client)

        cache = RedisCache(RedisConfig())
        result = cache.get("key")

        assert result == b"value"
        mock_client.get.assert_called_once_with("key")

    def test_get_returns_none_for_missing(self):
        """Test get returns None for missing key."""
        import redis
        mock_client = MagicMock()
        mock_client.get.return_value = None
        redis.Redis = MagicMock(return_value=mock_client)

        cache = RedisCache(RedisConfig())
        result = cache.get("missing")

        assert result is None

    def test_set_without_ttl(self):
        """Test set without TTL."""
        import redis
        mock_client = MagicMock()
        redis.Redis = MagicMock(return_value=mock_client)

        cache = RedisCache(RedisConfig())
        cache.set("key", b"value")

        mock_client.set.assert_called_once_with("key", b"value")

    def test_set_with_ttl(self):
        """Test set with TTL."""
        import redis
        mock_client = MagicMock()
        redis.Redis = MagicMock(return_value=mock_client)

        cache = RedisCache(RedisConfig())
        cache.set("key", b"value", ttl=60)

        mock_client.setex.assert_called_once_with("key", 60, b"value")

    def test_delete(self):
        """Test delete removes key."""
        import redis
        mock_client = MagicMock()
        redis.Redis = MagicMock(return_value=mock_client)

        cache = RedisCache(RedisConfig())
        cache.delete("key")

        mock_client.delete.assert_called_once_with("key")

    def test_exists_true(self):
        """Test exists returns True when key present."""
        import redis
        mock_client = MagicMock()
        mock_client.exists.return_value = 1
        redis.Redis = MagicMock(return_value=mock_client)

        cache = RedisCache(RedisConfig())
        result = cache.exists("key")

        assert result is True

    def test_exists_false(self):
        """Test exists returns False when key missing."""
        import redis
        mock_client = MagicMock()
        mock_client.exists.return_value = 0
        redis.Redis = MagicMock(return_value=mock_client)

        cache = RedisCache(RedisConfig())
        result = cache.exists("missing")

        assert result is False

    def test_increment(self):
        """Test increment returns new value."""
        import redis
        mock_client = MagicMock()
        mock_client.incrby.return_value = 5
        redis.Redis = MagicMock(return_value=mock_client)

        cache = RedisCache(RedisConfig())
        result = cache.increment("counter", 5)

        assert result == 5
        mock_client.incrby.assert_called_once_with("counter", 5)

    def test_flush_without_prefix(self):
        """Test flush without prefix calls flushdb."""
        import redis
        mock_client = MagicMock()
        redis.Redis = MagicMock(return_value=mock_client)

        cache = RedisCache(RedisConfig())
        cache.flush()

        mock_client.flushdb.assert_called_once()

    def test_flush_with_prefix(self):
        """Test flush with prefix scans and deletes."""
        import redis
        mock_client = MagicMock()
        mock_client.scan.return_value = (0, [b"app:key1", b"app:key2"])
        redis.Redis = MagicMock(return_value=mock_client)

        cache = RedisCache(RedisConfig(prefix="app:"))
        cache.flush(prefix="temp")

        mock_client.scan.assert_called_once()
        mock_client.delete.assert_called_once_with(b"app:key1", b"app:key2")

    def test_get_many(self):
        """Test get_many uses MGET and returns dict."""
        import redis
        mock_client = MagicMock()
        mock_client.mget.return_value = [b"val1", b"val2", None]
        redis.Redis = MagicMock(return_value=mock_client)

        cache = RedisCache(RedisConfig())
        result = cache.get_many(["key1", "key2", "key3"])

        assert result == {"key1": b"val1", "key2": b"val2", "key3": None}
        mock_client.mget.assert_called_once_with(["key1", "key2", "key3"])

    def test_get_many_empty(self):
        """Test get_many with empty list."""
        import redis
        redis.Redis = MagicMock(return_value=MagicMock())

        cache = RedisCache(RedisConfig())
        result = cache.get_many([])

        assert result == {}

    def test_set_many_without_ttl(self):
        """Test set_many without TTL uses pipeline."""
        import redis
        mock_client = MagicMock()
        mock_pipe = MagicMock()
        mock_client.pipeline.return_value = mock_pipe
        redis.Redis = MagicMock(return_value=mock_client)

        cache = RedisCache(RedisConfig())
        cache.set_many({"key1": b"val1", "key2": b"val2"})

        assert mock_pipe.set.call_count == 2
        mock_pipe.execute.assert_called_once()

    def test_set_many_with_ttl(self):
        """Test set_many with TTL uses setex."""
        import redis
        mock_client = MagicMock()
        mock_pipe = MagicMock()
        mock_client.pipeline.return_value = mock_pipe
        redis.Redis = MagicMock(return_value=mock_client)

        cache = RedisCache(RedisConfig())
        cache.set_many({"key1": b"val1", "key2": b"val2"}, ttl=60)

        assert mock_pipe.setex.call_count == 2
        mock_pipe.execute.assert_called_once()

    def test_close(self):
        """Test close closes connection."""
        import redis
        mock_client = MagicMock()
        redis.Redis = MagicMock(return_value=mock_client)

        cache = RedisCache(RedisConfig())
        cache.close()

        mock_client.close.assert_called_once()

    def test_key_prefix_applied(self):
        """Test that key prefix is applied to all operations."""
        import redis
        mock_client = MagicMock()
        redis.Redis = MagicMock(return_value=mock_client)

        cache = RedisCache(RedisConfig(prefix="myapp:"))
        cache.get("user:123")

        mock_client.get.assert_called_once_with("myapp:user:123")


@pytest.mark.asyncio
class TestAsyncRedisCache:
    """Tests for async Redis cache."""

    async def test_async_get(self):
        """Test async get."""
        import redis.asyncio
        mock_client = AsyncMock()
        mock_client.get.return_value = b"value"
        redis.asyncio.Redis = MagicMock(return_value=mock_client)

        cache = AsyncRedisCache(RedisConfig())
        result = await cache.get("key")

        assert result == b"value"

    async def test_async_set_with_ttl(self):
        """Test async set with TTL."""
        import redis.asyncio
        mock_client = AsyncMock()
        redis.asyncio.Redis = MagicMock(return_value=mock_client)

        cache = AsyncRedisCache(RedisConfig())
        await cache.set("key", b"value", ttl=60)

        mock_client.setex.assert_called_once_with("key", 60, b"value")

    async def test_async_close(self):
        """Test async close."""
        import redis.asyncio
        mock_client = AsyncMock()
        redis.asyncio.Redis = MagicMock(return_value=mock_client)

        cache = AsyncRedisCache(RedisConfig())
        await cache.close()

        mock_client.close.assert_called_once()


class TestValkeyCache:
    """Tests for synchronous Valkey cache."""

    def test_init_creates_client(self):
        """Test initialization creates Valkey client."""
        import valkey
        mock_client = MagicMock()
        valkey.Valkey = MagicMock(return_value=mock_client)

        config = ValkeyConfig(host="localhost", port=6379)
        cache = ValkeyCache(config)

        assert cache.client == mock_client
        valkey.Valkey.assert_called_once()

    def test_get_returns_value(self):
        """Test get returns value from Valkey."""
        import valkey
        mock_client = MagicMock()
        mock_client.get.return_value = b"value"
        valkey.Valkey = MagicMock(return_value=mock_client)

        cache = ValkeyCache(ValkeyConfig())
        result = cache.get("key")

        assert result == b"value"

    def test_close(self):
        """Test close closes connection."""
        import valkey
        mock_client = MagicMock()
        valkey.Valkey = MagicMock(return_value=mock_client)

        cache = ValkeyCache(ValkeyConfig())
        cache.close()

        mock_client.close.assert_called_once()


@pytest.mark.asyncio
class TestAsyncValkeyCache:
    """Tests for async Valkey cache."""

    async def test_async_get(self):
        """Test async get."""
        import valkey.asyncio
        mock_client = AsyncMock()
        mock_client.get.return_value = b"value"
        valkey.asyncio.Valkey = MagicMock(return_value=mock_client)

        cache = AsyncValkeyCache(ValkeyConfig())
        result = await cache.get("key")

        assert result == b"value"

    async def test_async_close(self):
        """Test async close."""
        import valkey.asyncio
        mock_client = AsyncMock()
        valkey.asyncio.Valkey = MagicMock(return_value=mock_client)

        cache = AsyncValkeyCache(ValkeyConfig())
        await cache.close()

        mock_client.close.assert_called_once()


class TestMemcacheCache:
    """Tests for Memcache backend."""

    def test_init_creates_pooled_client(self):
        """Test initialization creates pooled client."""
        from pymemcache.client.pool import ObjectPooledClient
        mock_client = MagicMock()
        ObjectPooledClient = MagicMock(return_value=mock_client)

        config = MemcacheConfig(servers=["localhost:11211"])
        import pymemcache.client.pool
        pymemcache.client.pool.ObjectPooledClient = ObjectPooledClient
        cache = MemcacheCache(config)

        assert cache.client == mock_client
        ObjectPooledClient.assert_called_once()

    def test_parse_server_with_port(self):
        """Test server parsing with port."""
        from pymemcache.client.pool import ObjectPooledClient
        mock_pooled = MagicMock(return_value=MagicMock())
        import pymemcache.client.pool
        pymemcache.client.pool.ObjectPooledClient = mock_pooled

        config = MemcacheConfig(servers=["cache.example.com:11211"])
        cache = MemcacheCache(config)

        assert cache._parse_server("cache.example.com:11211") == (
            "cache.example.com",
            11211,
        )

    def test_get_returns_value(self):
        """Test get returns value."""
        mock_client = MagicMock()
        mock_client.get.return_value = b"value"
        import pymemcache.client.pool
        pymemcache.client.pool.ObjectPooledClient = MagicMock(return_value=mock_client)

        cache = MemcacheCache(MemcacheConfig(servers=["localhost:11211"]))
        result = cache.get("key")

        assert result == b"value"

    def test_set_without_ttl(self):
        """Test set without TTL."""
        mock_client = MagicMock()
        import pymemcache.client.pool
        pymemcache.client.pool.ObjectPooledClient = MagicMock(return_value=mock_client)

        cache = MemcacheCache(MemcacheConfig(servers=["localhost:11211"]))
        cache.set("key", b"value")

        mock_client.set.assert_called_once()
        call_args = mock_client.set.call_args
        assert call_args[1]["expire"] == 0

    def test_set_with_ttl(self):
        """Test set with TTL."""
        mock_client = MagicMock()
        import pymemcache.client.pool
        pymemcache.client.pool.ObjectPooledClient = MagicMock(return_value=mock_client)

        cache = MemcacheCache(MemcacheConfig(servers=["localhost:11211"]))
        cache.set("key", b"value", ttl=60)

        call_args = mock_client.set.call_args
        assert call_args[1]["expire"] == 60

    def test_delete(self):
        """Test delete."""
        mock_client = MagicMock()
        import pymemcache.client.pool
        pymemcache.client.pool.ObjectPooledClient = MagicMock(return_value=mock_client)

        cache = MemcacheCache(MemcacheConfig(servers=["localhost:11211"]))
        cache.delete("key")

        mock_client.delete.assert_called_once()

    def test_exists_true(self):
        """Test exists when key present."""
        mock_client = MagicMock()
        mock_client.get.return_value = b"value"
        import pymemcache.client.pool
        pymemcache.client.pool.ObjectPooledClient = MagicMock(return_value=mock_client)

        cache = MemcacheCache(MemcacheConfig(servers=["localhost:11211"]))
        result = cache.exists("key")

        assert result is True

    def test_exists_false(self):
        """Test exists when key missing."""
        mock_client = MagicMock()
        mock_client.get.return_value = None
        import pymemcache.client.pool
        pymemcache.client.pool.ObjectPooledClient = MagicMock(return_value=mock_client)

        cache = MemcacheCache(MemcacheConfig(servers=["localhost:11211"]))
        result = cache.exists("missing")

        assert result is False

    def test_increment(self):
        """Test increment."""
        mock_client = MagicMock()
        mock_client.incr.return_value = 5
        import pymemcache.client.pool
        pymemcache.client.pool.ObjectPooledClient = MagicMock(return_value=mock_client)

        cache = MemcacheCache(MemcacheConfig(servers=["localhost:11211"]))
        result = cache.increment("counter", 5)

        assert result == 5

    def test_flush_without_prefix(self):
        """Test flush without prefix calls flush_all."""
        mock_client = MagicMock()
        import pymemcache.client.pool
        pymemcache.client.pool.ObjectPooledClient = MagicMock(return_value=mock_client)

        cache = MemcacheCache(MemcacheConfig(servers=["localhost:11211"]))
        cache.flush()

        mock_client.flush_all.assert_called_once()

    def test_flush_with_prefix_raises(self):
        """Test flush with prefix raises UnsupportedOperationError."""
        import pymemcache.client.pool
        pymemcache.client.pool.ObjectPooledClient = MagicMock(return_value=MagicMock())

        cache = MemcacheCache(MemcacheConfig(servers=["localhost:11211"]))

        with pytest.raises(UnsupportedOperationError):
            cache.flush(prefix="temp")

    def test_get_many(self):
        """Test get_many."""
        mock_client = MagicMock()
        mock_client.get_many.return_value = {b"key1": b"val1", b"key2": b"val2"}
        import pymemcache.client.pool
        pymemcache.client.pool.ObjectPooledClient = MagicMock(return_value=mock_client)

        cache = MemcacheCache(MemcacheConfig(servers=["localhost:11211"]))
        result = cache.get_many(["key1", "key2"])

        assert len(result) == 2

    def test_set_many(self):
        """Test set_many."""
        mock_client = MagicMock()
        import pymemcache.client.pool
        pymemcache.client.pool.ObjectPooledClient = MagicMock(return_value=mock_client)

        cache = MemcacheCache(MemcacheConfig(servers=["localhost:11211"]))
        cache.set_many({"key1": b"val1", "key2": b"val2"}, ttl=60)

        assert mock_client.set.call_count == 2

    def test_close(self):
        """Test close."""
        mock_client = MagicMock()
        import pymemcache.client.pool
        pymemcache.client.pool.ObjectPooledClient = MagicMock(return_value=mock_client)

        cache = MemcacheCache(MemcacheConfig(servers=["localhost:11211"]))
        cache.close()

        mock_client.close.assert_called_once()
