"""MongoDB document store backend for penguin-dal."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(slots=True)
class FindOptions:
    """Options for find operations."""

    limit: int = 0
    skip: int = 0
    sort: list[tuple[str, int]] | None = None


@dataclass(slots=True)
class MongoConfig:
    """Configuration for MongoDB backend."""

    uri: str
    db_name: str
    server_selection_timeout_ms: int = 5000
    connect_timeout_ms: int = 10000
    max_pool_size: int = 100
    tls: bool = False


class MongoDAL:
    """Synchronous MongoDB document store using pymongo."""

    def __init__(self, config: MongoConfig) -> None:
        """Initialize MongoDB backend with given config."""
        try:
            from pymongo import MongoClient
        except ImportError as e:
            raise ImportError(
                "Install pymongo: pip install penguin-dal[mongodb]"
            ) from e

        self.config = config
        self.client = MongoClient(
            config.uri,
            serverSelectionTimeoutMS=config.server_selection_timeout_ms,
            connectTimeoutMS=config.connect_timeout_ms,
            maxPoolSize=config.max_pool_size,
            tls=config.tls,
        )
        self.db = self.client[config.db_name]

    def _objectid_to_str(self, doc: dict[str, Any]) -> dict[str, Any]:
        """Convert ObjectId to string in document."""
        if "_id" in doc:
            from bson import ObjectId

            if isinstance(doc["_id"], ObjectId):
                doc = dict(doc)
                doc["_id"] = str(doc["_id"])
        return doc

    def insert_one(self, collection: str, document: dict[str, Any]) -> str:
        """Insert document into collection, return str(_id)."""
        coll = self.db[collection]
        result = coll.insert_one(document)
        return str(result.inserted_id)

    def find_one(
        self, collection: str, filter: dict[str, Any]
    ) -> dict[str, Any] | None:
        """Find single document matching filter."""
        coll = self.db[collection]
        doc = coll.find_one(filter)
        if doc is None:
            return None
        return self._objectid_to_str(doc)

    def find(
        self,
        collection: str,
        filter: dict[str, Any],
        opts: FindOptions | None = None,
    ) -> list[dict[str, Any]]:
        """Find documents matching filter with options."""
        coll = self.db[collection]
        opts = opts or FindOptions()

        query = coll.find(filter)
        if opts.skip > 0:
            query = query.skip(opts.skip)
        if opts.limit > 0:
            query = query.limit(opts.limit)
        if opts.sort:
            query = query.sort(opts.sort)

        return [self._objectid_to_str(doc) for doc in query]

    def update_one(
        self,
        collection: str,
        filter: dict[str, Any],
        update: dict[str, Any],
        upsert: bool = False,
    ) -> int:
        """Update single document, return modified count."""
        coll = self.db[collection]
        result = coll.update_one(filter, update, upsert=upsert)
        return result.modified_count

    def delete_one(self, collection: str, filter: dict[str, Any]) -> int:
        """Delete single document, return deleted count."""
        coll = self.db[collection]
        result = coll.delete_one(filter)
        return result.deleted_count

    def count(
        self, collection: str, filter: dict[str, Any] | None = None
    ) -> int:
        """Count documents matching filter."""
        coll = self.db[collection]
        filter = filter or {}
        return coll.count_documents(filter)

    def create_index(
        self,
        collection: str,
        keys: list[tuple[str, int]],
        unique: bool = False,
    ) -> None:
        """Create index on collection."""
        coll = self.db[collection]
        coll.create_index(keys, unique=unique)

    def close(self) -> None:
        """Close MongoDB connection."""
        self.client.close()


class AsyncMongoDAL:
    """Async MongoDB document store using motor."""

    def __init__(self, config: MongoConfig) -> None:
        """Initialize async MongoDB backend with given config."""
        try:
            import motor.motor_asyncio
        except ImportError as e:
            raise ImportError(
                "Install motor: pip install penguin-dal[motor]"
            ) from e

        self.config = config
        self.client = motor.motor_asyncio.AsyncMongoClient(
            config.uri,
            serverSelectionTimeoutMS=config.server_selection_timeout_ms,
            connectTimeoutMS=config.connect_timeout_ms,
            maxPoolSize=config.max_pool_size,
            tls=config.tls,
        )
        self.db = self.client[config.db_name]

    def _objectid_to_str(self, doc: dict[str, Any]) -> dict[str, Any]:
        """Convert ObjectId to string in document."""
        if "_id" in doc:
            from bson import ObjectId

            if isinstance(doc["_id"], ObjectId):
                doc = dict(doc)
                doc["_id"] = str(doc["_id"])
        return doc

    async def insert_one(self, collection: str, document: dict[str, Any]) -> str:
        """Insert document into collection, return str(_id)."""
        coll = self.db[collection]
        result = await coll.insert_one(document)
        return str(result.inserted_id)

    async def find_one(
        self, collection: str, filter: dict[str, Any]
    ) -> dict[str, Any] | None:
        """Find single document matching filter."""
        coll = self.db[collection]
        doc = await coll.find_one(filter)
        if doc is None:
            return None
        return self._objectid_to_str(doc)

    async def find(
        self,
        collection: str,
        filter: dict[str, Any],
        opts: FindOptions | None = None,
    ) -> list[dict[str, Any]]:
        """Find documents matching filter with options."""
        coll = self.db[collection]
        opts = opts or FindOptions()

        query = coll.find(filter)
        if opts.skip > 0:
            query = query.skip(opts.skip)
        if opts.limit > 0:
            query = query.limit(opts.limit)
        if opts.sort:
            query = query.sort(opts.sort)

        docs = await query.to_list(None)
        return [self._objectid_to_str(doc) for doc in docs]

    async def update_one(
        self,
        collection: str,
        filter: dict[str, Any],
        update: dict[str, Any],
        upsert: bool = False,
    ) -> int:
        """Update single document, return modified count."""
        coll = self.db[collection]
        result = await coll.update_one(filter, update, upsert=upsert)
        return result.modified_count

    async def delete_one(self, collection: str, filter: dict[str, Any]) -> int:
        """Delete single document, return deleted count."""
        coll = self.db[collection]
        result = await coll.delete_one(filter)
        return result.deleted_count

    async def count(
        self, collection: str, filter: dict[str, Any] | None = None
    ) -> int:
        """Count documents matching filter."""
        coll = self.db[collection]
        filter = filter or {}
        return await coll.count_documents(filter)

    async def create_index(
        self,
        collection: str,
        keys: list[tuple[str, int]],
        unique: bool = False,
    ) -> None:
        """Create index on collection."""
        coll = self.db[collection]
        await coll.create_index(keys, unique=unique)

    async def close(self) -> None:
        """Close MongoDB connection."""
        self.client.close()
