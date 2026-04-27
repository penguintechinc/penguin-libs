"""Tests for document store backends."""
from __future__ import annotations

import pytest
from unittest.mock import MagicMock, AsyncMock

from bson import ObjectId

from penguin_dal.document.mongodb import (
    MongoDAL,
    AsyncMongoDAL,
    MongoConfig,
    FindOptions,
)


class TestMongoDAL:
    """Tests for synchronous MongoDB backend."""

    def test_init_creates_client(self):
        """Test initialization creates MongoDB client."""
        import pymongo
        mock_client = MagicMock()
        pymongo.MongoClient = MagicMock(return_value=mock_client)
        mock_client.__getitem__ = MagicMock(return_value=MagicMock())

        config = MongoConfig(uri="mongodb://localhost:27017", db_name="testdb")
        dal = MongoDAL(config)

        assert dal.client == mock_client
        pymongo.MongoClient.assert_called_once()

    def test_insert_one_returns_str_id(self):
        """Test insert_one returns string _id."""
        import pymongo
        mock_client = MagicMock()
        mock_db = MagicMock()
        mock_coll = MagicMock()
        mock_result = MagicMock()
        mock_result.inserted_id = ObjectId("507f1f77bcf86cd799439011")
        mock_coll.insert_one.return_value = mock_result

        mock_client.__getitem__.return_value = mock_db
        mock_db.__getitem__.return_value = mock_coll
        pymongo.MongoClient = MagicMock(return_value=mock_client)

        dal = MongoDAL(MongoConfig(uri="mongodb://localhost", db_name="testdb"))
        result = dal.insert_one("users", {"name": "Alice"})

        assert result == "507f1f77bcf86cd799439011"
        assert isinstance(result, str)

    def test_find_one_returns_dict_with_str_id(self):
        """Test find_one returns dict with ObjectId converted to str."""
        import pymongo
        mock_client = MagicMock()
        mock_db = MagicMock()
        mock_coll = MagicMock()
        oid = ObjectId("507f1f77bcf86cd799439011")
        mock_coll.find_one.return_value = {"_id": oid, "name": "Alice"}

        mock_client.__getitem__.return_value = mock_db
        mock_db.__getitem__.return_value = mock_coll
        pymongo.MongoClient = MagicMock(return_value=mock_client)

        dal = MongoDAL(MongoConfig(uri="mongodb://localhost", db_name="testdb"))
        result = dal.find_one("users", {"name": "Alice"})

        assert result is not None
        assert result["_id"] == "507f1f77bcf86cd799439011"
        assert result["name"] == "Alice"

    def test_find_one_returns_none(self):
        """Test find_one returns None when not found."""
        import pymongo
        mock_client = MagicMock()
        mock_db = MagicMock()
        mock_coll = MagicMock()
        mock_coll.find_one.return_value = None

        mock_client.__getitem__.return_value = mock_db
        mock_db.__getitem__.return_value = mock_coll
        pymongo.MongoClient = MagicMock(return_value=mock_client)

        dal = MongoDAL(MongoConfig(uri="mongodb://localhost", db_name="testdb"))
        result = dal.find_one("users", {"name": "NoOne"})

        assert result is None

    def test_find_with_limit_and_skip(self):
        """Test find applies limit and skip."""
        import pymongo
        mock_client = MagicMock()
        mock_db = MagicMock()
        mock_coll = MagicMock()
        mock_cursor = MagicMock()
        mock_cursor.skip.return_value = mock_cursor
        mock_cursor.limit.return_value = mock_cursor
        mock_cursor.__iter__ = MagicMock(return_value=iter([]))
        mock_coll.find.return_value = mock_cursor

        mock_client.__getitem__.return_value = mock_db
        mock_db.__getitem__.return_value = mock_coll
        pymongo.MongoClient = MagicMock(return_value=mock_client)

        dal = MongoDAL(MongoConfig(uri="mongodb://localhost", db_name="testdb"))
        dal.find("users", {}, FindOptions(skip=10, limit=20))

        mock_cursor.skip.assert_called_once_with(10)
        mock_cursor.limit.assert_called_once_with(20)

    def test_find_with_sort(self):
        """Test find applies sort."""
        import pymongo
        mock_client = MagicMock()
        mock_db = MagicMock()
        mock_coll = MagicMock()
        mock_cursor = MagicMock()
        mock_cursor.skip.return_value = mock_cursor
        mock_cursor.limit.return_value = mock_cursor
        mock_cursor.sort.return_value = mock_cursor
        mock_cursor.__iter__ = MagicMock(return_value=iter([]))
        mock_coll.find.return_value = mock_cursor

        mock_client.__getitem__.return_value = mock_db
        mock_db.__getitem__.return_value = mock_coll
        pymongo.MongoClient = MagicMock(return_value=mock_client)

        dal = MongoDAL(MongoConfig(uri="mongodb://localhost", db_name="testdb"))
        dal.find("users", {}, FindOptions(sort=[("name", 1), ("age", -1)]))

        mock_cursor.sort.assert_called_once_with([("name", 1), ("age", -1)])

    def test_find_returns_list_of_dicts(self):
        """Test find returns list of dicts with str _id."""
        import pymongo
        mock_client = MagicMock()
        mock_db = MagicMock()
        mock_coll = MagicMock()
        mock_cursor = MagicMock()

        oid1 = ObjectId("507f1f77bcf86cd799439011")
        oid2 = ObjectId("507f1f77bcf86cd799439012")
        docs = [
            {"_id": oid1, "name": "Alice"},
            {"_id": oid2, "name": "Bob"},
        ]
        mock_cursor.__iter__ = MagicMock(return_value=iter(docs))
        mock_coll.find.return_value = mock_cursor

        mock_client.__getitem__.return_value = mock_db
        mock_db.__getitem__.return_value = mock_coll
        pymongo.MongoClient = MagicMock(return_value=mock_client)

        dal = MongoDAL(MongoConfig(uri="mongodb://localhost", db_name="testdb"))
        result = dal.find("users", {})

        assert len(result) == 2
        assert result[0]["_id"] == "507f1f77bcf86cd799439011"
        assert result[1]["_id"] == "507f1f77bcf86cd799439012"
        assert result[0]["name"] == "Alice"

    def test_update_one_returns_modified_count(self):
        """Test update_one returns modified count."""
        import pymongo
        mock_client = MagicMock()
        mock_db = MagicMock()
        mock_coll = MagicMock()
        mock_result = MagicMock()
        mock_result.modified_count = 1
        mock_coll.update_one.return_value = mock_result

        mock_client.__getitem__.return_value = mock_db
        mock_db.__getitem__.return_value = mock_coll
        pymongo.MongoClient = MagicMock(return_value=mock_client)

        dal = MongoDAL(MongoConfig(uri="mongodb://localhost", db_name="testdb"))
        count = dal.update_one("users", {"name": "Alice"}, {"$set": {"age": 30}})

        assert count == 1
        mock_coll.update_one.assert_called_once()

    def test_delete_one_returns_deleted_count(self):
        """Test delete_one returns deleted count."""
        import pymongo
        mock_client = MagicMock()
        mock_db = MagicMock()
        mock_coll = MagicMock()
        mock_result = MagicMock()
        mock_result.deleted_count = 1
        mock_coll.delete_one.return_value = mock_result

        mock_client.__getitem__.return_value = mock_db
        mock_db.__getitem__.return_value = mock_coll
        pymongo.MongoClient = MagicMock(return_value=mock_client)

        dal = MongoDAL(MongoConfig(uri="mongodb://localhost", db_name="testdb"))
        count = dal.delete_one("users", {"name": "Alice"})

        assert count == 1

    def test_count_with_filter(self):
        """Test count with filter."""
        import pymongo
        mock_client = MagicMock()
        mock_db = MagicMock()
        mock_coll = MagicMock()
        mock_coll.count_documents.return_value = 5

        mock_client.__getitem__.return_value = mock_db
        mock_db.__getitem__.return_value = mock_coll
        pymongo.MongoClient = MagicMock(return_value=mock_client)

        dal = MongoDAL(MongoConfig(uri="mongodb://localhost", db_name="testdb"))
        count = dal.count("users", {"active": True})

        assert count == 5
        mock_coll.count_documents.assert_called_once_with({"active": True})

    def test_count_without_filter(self):
        """Test count without filter counts all."""
        import pymongo
        mock_client = MagicMock()
        mock_db = MagicMock()
        mock_coll = MagicMock()
        mock_coll.count_documents.return_value = 10

        mock_client.__getitem__.return_value = mock_db
        mock_db.__getitem__.return_value = mock_coll
        pymongo.MongoClient = MagicMock(return_value=mock_client)

        dal = MongoDAL(MongoConfig(uri="mongodb://localhost", db_name="testdb"))
        count = dal.count("users")

        assert count == 10
        mock_coll.count_documents.assert_called_once_with({})

    def test_create_index(self):
        """Test create_index."""
        import pymongo
        mock_client = MagicMock()
        mock_db = MagicMock()
        mock_coll = MagicMock()

        mock_client.__getitem__.return_value = mock_db
        mock_db.__getitem__.return_value = mock_coll
        pymongo.MongoClient = MagicMock(return_value=mock_client)

        dal = MongoDAL(MongoConfig(uri="mongodb://localhost", db_name="testdb"))
        dal.create_index("users", [("email", 1)], unique=True)

        mock_coll.create_index.assert_called_once_with([("email", 1)], unique=True)

    def test_close(self):
        """Test close closes connection."""
        import pymongo
        mock_client = MagicMock()
        pymongo.MongoClient = MagicMock(return_value=mock_client)
        mock_client.__getitem__ = MagicMock(return_value=MagicMock())

        dal = MongoDAL(MongoConfig(uri="mongodb://localhost", db_name="testdb"))
        dal.close()

        mock_client.close.assert_called_once()


@pytest.mark.asyncio
class TestAsyncMongoDAL:
    """Tests for async MongoDB backend."""

    async def test_async_init(self):
        """Test async initialization."""
        import motor.motor_asyncio
        mock_client = MagicMock()
        motor.motor_asyncio.AsyncMongoClient = MagicMock(return_value=mock_client)
        mock_client.__getitem__ = MagicMock(return_value=MagicMock())

        config = MongoConfig(uri="mongodb://localhost:27017", db_name="testdb")
        dal = AsyncMongoDAL(config)

        assert dal.client == mock_client

    async def test_async_insert_one(self):
        """Test async insert_one."""
        import motor.motor_asyncio
        mock_client = MagicMock()
        mock_db = MagicMock()
        mock_coll = MagicMock()
        mock_result = AsyncMock()
        mock_result.inserted_id = ObjectId("507f1f77bcf86cd799439011")
        mock_coll.insert_one = AsyncMock(return_value=mock_result)

        mock_client.__getitem__.return_value = mock_db
        mock_db.__getitem__.return_value = mock_coll
        motor.motor_asyncio.AsyncMongoClient = MagicMock(return_value=mock_client)

        dal = AsyncMongoDAL(MongoConfig(uri="mongodb://localhost", db_name="testdb"))
        result = await dal.insert_one("users", {"name": "Alice"})

        assert result == "507f1f77bcf86cd799439011"

    async def test_async_find_one(self):
        """Test async find_one."""
        import motor.motor_asyncio
        mock_client = MagicMock()
        mock_db = MagicMock()
        mock_coll = MagicMock()
        oid = ObjectId("507f1f77bcf86cd799439011")
        mock_coll.find_one = AsyncMock(return_value={"_id": oid, "name": "Alice"})

        mock_client.__getitem__.return_value = mock_db
        mock_db.__getitem__.return_value = mock_coll
        motor.motor_asyncio.AsyncMongoClient = MagicMock(return_value=mock_client)

        dal = AsyncMongoDAL(MongoConfig(uri="mongodb://localhost", db_name="testdb"))
        result = await dal.find_one("users", {"name": "Alice"})

        assert result is not None
        assert result["_id"] == "507f1f77bcf86cd799439011"

    async def test_async_find(self):
        """Test async find."""
        import motor.motor_asyncio
        mock_client = MagicMock()
        mock_db = MagicMock()
        mock_coll = MagicMock()
        mock_cursor = MagicMock()

        oid1 = ObjectId("507f1f77bcf86cd799439011")
        oid2 = ObjectId("507f1f77bcf86cd799439012")
        docs = [
            {"_id": oid1, "name": "Alice"},
            {"_id": oid2, "name": "Bob"},
        ]
        mock_cursor.to_list = AsyncMock(return_value=docs)
        mock_coll.find.return_value = mock_cursor

        mock_client.__getitem__.return_value = mock_db
        mock_db.__getitem__.return_value = mock_coll
        motor.motor_asyncio.AsyncMongoClient = MagicMock(return_value=mock_client)

        dal = AsyncMongoDAL(MongoConfig(uri="mongodb://localhost", db_name="testdb"))
        result = await dal.find("users", {})

        assert len(result) == 2
        assert result[0]["_id"] == "507f1f77bcf86cd799439011"

    async def test_async_update_one(self):
        """Test async update_one."""
        import motor.motor_asyncio
        mock_client = MagicMock()
        mock_db = MagicMock()
        mock_coll = MagicMock()
        mock_result = AsyncMock()
        mock_result.modified_count = 1
        mock_coll.update_one = AsyncMock(return_value=mock_result)

        mock_client.__getitem__.return_value = mock_db
        mock_db.__getitem__.return_value = mock_coll
        motor.motor_asyncio.AsyncMongoClient = MagicMock(return_value=mock_client)

        dal = AsyncMongoDAL(MongoConfig(uri="mongodb://localhost", db_name="testdb"))
        count = await dal.update_one(
            "users", {"name": "Alice"}, {"$set": {"age": 30}}
        )

        assert count == 1

    async def test_async_delete_one(self):
        """Test async delete_one."""
        import motor.motor_asyncio
        mock_client = MagicMock()
        mock_db = MagicMock()
        mock_coll = MagicMock()
        mock_result = AsyncMock()
        mock_result.deleted_count = 1
        mock_coll.delete_one = AsyncMock(return_value=mock_result)

        mock_client.__getitem__.return_value = mock_db
        mock_db.__getitem__.return_value = mock_coll
        motor.motor_asyncio.AsyncMongoClient = MagicMock(return_value=mock_client)

        dal = AsyncMongoDAL(MongoConfig(uri="mongodb://localhost", db_name="testdb"))
        count = await dal.delete_one("users", {"name": "Alice"})

        assert count == 1

    async def test_async_count(self):
        """Test async count."""
        import motor.motor_asyncio
        mock_client = MagicMock()
        mock_db = MagicMock()
        mock_coll = MagicMock()
        mock_coll.count_documents = AsyncMock(return_value=5)

        mock_client.__getitem__.return_value = mock_db
        mock_db.__getitem__.return_value = mock_coll
        motor.motor_asyncio.AsyncMongoClient = MagicMock(return_value=mock_client)

        dal = AsyncMongoDAL(MongoConfig(uri="mongodb://localhost", db_name="testdb"))
        count = await dal.count("users", {"active": True})

        assert count == 5

    async def test_async_create_index(self):
        """Test async create_index."""
        import motor.motor_asyncio
        mock_client = MagicMock()
        mock_db = MagicMock()
        mock_coll = MagicMock()
        mock_coll.create_index = AsyncMock()

        mock_client.__getitem__.return_value = mock_db
        mock_db.__getitem__.return_value = mock_coll
        motor.motor_asyncio.AsyncMongoClient = MagicMock(return_value=mock_client)

        dal = AsyncMongoDAL(MongoConfig(uri="mongodb://localhost", db_name="testdb"))
        await dal.create_index("users", [("email", 1)], unique=True)

        mock_coll.create_index.assert_called_once()

    async def test_async_close(self):
        """Test async close."""
        import motor.motor_asyncio
        mock_client = MagicMock()
        motor.motor_asyncio.AsyncMongoClient = MagicMock(return_value=mock_client)
        mock_client.__getitem__ = MagicMock(return_value=MagicMock())

        dal = AsyncMongoDAL(MongoConfig(uri="mongodb://localhost", db_name="testdb"))
        await dal.close()

        mock_client.close.assert_called_once()
