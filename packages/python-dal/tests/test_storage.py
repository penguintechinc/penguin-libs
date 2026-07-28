"""Tests for storage layer backends."""
from __future__ import annotations

import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from penguin_dal.protocols import PutOptions, StorageStore
from penguin_dal.storage.iscsi import ISCSIConfig, ISCSIStore
from penguin_dal.storage.nfs import NFSConfig, NFSStore
from penguin_dal.storage.s3 import AsyncS3Store, S3Config, S3Store


class TestPutOptions:
    """Tests for PutOptions dataclass."""

    def test_default_values(self) -> None:
        """Test default values for PutOptions."""
        opts = PutOptions()
        assert opts.content_type == "application/octet-stream"
        assert opts.metadata == {}
        assert opts.cache_control is None

    def test_custom_values(self) -> None:
        """Test custom values for PutOptions."""
        opts = PutOptions(
            content_type="text/plain",
            metadata={"key": "value"},
            cache_control="max-age=3600",
        )
        assert opts.content_type == "text/plain"
        assert opts.metadata == {"key": "value"}
        assert opts.cache_control == "max-age=3600"


class TestNFSStore:
    """Tests for NFS file storage backend."""

    def test_init_with_valid_mount(self, tmp_path: Path) -> None:
        """Test initialization with valid mount path."""
        config = NFSConfig(mount_path=str(tmp_path))
        store = NFSStore(config)
        assert store._base_path == tmp_path

    def test_init_with_missing_mount(self) -> None:
        """Test initialization with missing mount path."""
        config = NFSConfig(mount_path="/nonexistent/path")
        with pytest.raises(ValueError, match="Mount path does not exist"):
            NFSStore(config)

    def test_init_with_file_not_directory(self, tmp_path: Path) -> None:
        """Test initialization with file instead of directory."""
        file_path = tmp_path / "file.txt"
        file_path.write_text("test")
        config = NFSConfig(mount_path=str(file_path))
        with pytest.raises(ValueError, match="is not a directory"):
            NFSStore(config)

    def test_put_and_get(self, tmp_path: Path) -> None:
        """Test put and get operations."""
        config = NFSConfig(mount_path=str(tmp_path))
        store = NFSStore(config)

        data = b"hello world"
        store.put("test.txt", data)

        result = store.get("test.txt")
        assert result == data

    def test_put_creates_nested_directories(self, tmp_path: Path) -> None:
        """Test put creates nested directories when create_dirs=True."""
        config = NFSConfig(mount_path=str(tmp_path), create_dirs=True)
        store = NFSStore(config)

        data = b"nested content"
        store.put("foo/bar/baz/file.txt", data)

        file_path = tmp_path / "foo" / "bar" / "baz" / "file.txt"
        assert file_path.exists()
        assert file_path.read_bytes() == data

    def test_put_without_create_dirs_raises(self, tmp_path: Path) -> None:
        """Test put raises when create_dirs=False and directory missing."""
        config = NFSConfig(mount_path=str(tmp_path), create_dirs=False)
        store = NFSStore(config)

        data = b"content"
        with pytest.raises(FileNotFoundError):
            store.put("foo/bar/file.txt", data)

    def test_get_missing_key_raises_keyerror(self, tmp_path: Path) -> None:
        """Test get raises KeyError for missing key."""
        config = NFSConfig(mount_path=str(tmp_path))
        store = NFSStore(config)

        with pytest.raises(KeyError):
            store.get("nonexistent.txt")

    def test_delete(self, tmp_path: Path) -> None:
        """Test delete operation."""
        config = NFSConfig(mount_path=str(tmp_path))
        store = NFSStore(config)

        store.put("test.txt", b"data")
        assert store.exists("test.txt")

        store.delete("test.txt")
        assert not store.exists("test.txt")

    def test_delete_missing_key_is_noop(self, tmp_path: Path) -> None:
        """Test delete on missing key is no-op."""
        config = NFSConfig(mount_path=str(tmp_path))
        store = NFSStore(config)

        store.delete("nonexistent.txt")

    def test_exists(self, tmp_path: Path) -> None:
        """Test exists operation."""
        config = NFSConfig(mount_path=str(tmp_path))
        store = NFSStore(config)

        assert not store.exists("test.txt")

        store.put("test.txt", b"data")
        assert store.exists("test.txt")

    def test_list_empty(self, tmp_path: Path) -> None:
        """Test list on empty store."""
        config = NFSConfig(mount_path=str(tmp_path))
        store = NFSStore(config)

        result = store.list()
        assert result == []

    def test_list_all_files(self, tmp_path: Path) -> None:
        """Test list returns all files."""
        config = NFSConfig(mount_path=str(tmp_path))
        store = NFSStore(config)

        store.put("file1.txt", b"data1")
        store.put("file2.txt", b"data2")
        store.put("nested/file3.txt", b"data3")

        result = store.list()
        assert sorted(result) == [
            "file1.txt",
            "file2.txt",
            "nested/file3.txt",
        ]

    def test_list_with_prefix(self, tmp_path: Path) -> None:
        """Test list with prefix filter."""
        config = NFSConfig(mount_path=str(tmp_path))
        store = NFSStore(config)

        store.put("data/file1.txt", b"data1")
        store.put("data/file2.txt", b"data2")
        store.put("other/file3.txt", b"data3")

        result = store.list("data")
        assert sorted(result) == ["file1.txt", "file2.txt"]

    def test_list_with_missing_prefix(self, tmp_path: Path) -> None:
        """Test list with non-existent prefix returns empty."""
        config = NFSConfig(mount_path=str(tmp_path))
        store = NFSStore(config)

        result = store.list("nonexistent")
        assert result == []

    def test_get_url(self, tmp_path: Path) -> None:
        """Test get_url returns file URI."""
        config = NFSConfig(mount_path=str(tmp_path))
        store = NFSStore(config)

        store.put("test.txt", b"data")
        url = store.get_url("test.txt")

        assert url.startswith("file://")
        assert "test.txt" in url

    def test_protocol_compliance(self, tmp_path: Path) -> None:
        """Test NFSStore complies with StorageStore protocol."""
        config = NFSConfig(mount_path=str(tmp_path))
        store = NFSStore(config)

        assert isinstance(store, StorageStore)

    def test_put_with_options(self, tmp_path: Path) -> None:
        """Test put respects PutOptions (though NFS doesn't use them)."""
        config = NFSConfig(mount_path=str(tmp_path))
        store = NFSStore(config)

        opts = PutOptions(
            content_type="text/plain",
            metadata={"author": "test"},
        )
        data = b"content"

        store.put("file.txt", data, opts)
        assert store.get("file.txt") == data


class TestISCSIStore:
    """Tests for iSCSI block device storage backend."""

    def test_init(self, tmp_path: Path) -> None:
        """Test initialization."""
        config = ISCSIConfig(
            mount_path=str(tmp_path),
            target="iqn.2024-04.io.penguintech:storage1",
            lun=0,
        )
        store = ISCSIStore(config)
        assert store._config.target == "iqn.2024-04.io.penguintech:storage1"

    def test_put_and_get(self, tmp_path: Path) -> None:
        """Test put and get via delegation."""
        config = ISCSIConfig(
            mount_path=str(tmp_path),
            target="iqn.2024-04.io.penguintech:storage1",
        )
        store = ISCSIStore(config)

        data = b"iscsi data"
        store.put("file.bin", data)
        assert store.get("file.bin") == data

    def test_delete(self, tmp_path: Path) -> None:
        """Test delete via delegation."""
        config = ISCSIConfig(
            mount_path=str(tmp_path),
            target="iqn.2024-04.io.penguintech:storage1",
        )
        store = ISCSIStore(config)

        store.put("file.bin", b"data")
        store.delete("file.bin")
        assert not store.exists("file.bin")

    def test_exists(self, tmp_path: Path) -> None:
        """Test exists via delegation."""
        config = ISCSIConfig(
            mount_path=str(tmp_path),
            target="iqn.2024-04.io.penguintech:storage1",
        )
        store = ISCSIStore(config)

        assert not store.exists("file.bin")
        store.put("file.bin", b"data")
        assert store.exists("file.bin")

    def test_list(self, tmp_path: Path) -> None:
        """Test list via delegation."""
        config = ISCSIConfig(
            mount_path=str(tmp_path),
            target="iqn.2024-04.io.penguintech:storage1",
        )
        store = ISCSIStore(config)

        store.put("file1.bin", b"data1")
        store.put("file2.bin", b"data2")

        result = store.list()
        assert sorted(result) == ["file1.bin", "file2.bin"]

    def test_list_with_prefix(self, tmp_path: Path) -> None:
        """Test list with prefix via delegation."""
        config = ISCSIConfig(
            mount_path=str(tmp_path),
            target="iqn.2024-04.io.penguintech:storage1",
        )
        store = ISCSIStore(config)

        store.put("block/file1.bin", b"data1")
        store.put("block/file2.bin", b"data2")

        result = store.list("block")
        assert sorted(result) == ["file1.bin", "file2.bin"]

    def test_get_url(self, tmp_path: Path) -> None:
        """Test get_url via delegation."""
        config = ISCSIConfig(
            mount_path=str(tmp_path),
            target="iqn.2024-04.io.penguintech:storage1",
        )
        store = ISCSIStore(config)

        store.put("file.bin", b"data")
        url = store.get_url("file.bin")

        assert url.startswith("file://")


class TestS3Store:
    """Tests for S3 object storage backend (mocked)."""

    def test_boto3_import_error(self) -> None:
        """Test helpful error when boto3 not installed."""
        with patch.dict("sys.modules", {"boto3": None}):
            config = S3Config(bucket="test-bucket")
            with pytest.raises(ImportError, match="Install with: pip install"):
                S3Store(config)

    def test_init_with_defaults(self) -> None:
        """Test initialization with default config."""
        with patch("boto3.Session") as mock_session_cls:
            mock_session = MagicMock()
            mock_session_cls.return_value = mock_session

            config = S3Config(bucket="test-bucket")
            store = S3Store(config)

            assert store._config.bucket == "test-bucket"
            mock_session.client.assert_called_once()

    def test_init_with_credentials(self) -> None:
        """Test initialization with explicit credentials."""
        with patch("boto3.Session") as mock_session_cls:
            mock_session = MagicMock()
            mock_session_cls.return_value = mock_session

            config = S3Config(
                bucket="test-bucket",
                access_key="AKIAIOSFODNN7EXAMPLE",
                secret_key="wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY",
            )
            store = S3Store(config)

            call_kwargs = mock_session_cls.call_args[1]
            assert call_kwargs["aws_access_key_id"] == "AKIAIOSFODNN7EXAMPLE"
            assert call_kwargs["aws_secret_access_key"] == "wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY"

    def test_put(self) -> None:
        """Test put operation."""
        with patch("boto3.Session") as mock_session_cls:
            mock_session = MagicMock()
            mock_client = MagicMock()
            mock_session.client.return_value = mock_client
            mock_session_cls.return_value = mock_session

            config = S3Config(bucket="test-bucket")
            store = S3Store(config)

            data = b"test data"
            store.put("key.txt", data)

            mock_client.put_object.assert_called_once()
            call_kwargs = mock_client.put_object.call_args[1]
            assert call_kwargs["Bucket"] == "test-bucket"
            assert call_kwargs["Key"] == "key.txt"
            assert call_kwargs["Body"] == data

    def test_put_with_options(self) -> None:
        """Test put respects PutOptions."""
        with patch("boto3.Session") as mock_session_cls:
            mock_session = MagicMock()
            mock_client = MagicMock()
            mock_session.client.return_value = mock_client
            mock_session_cls.return_value = mock_session

            config = S3Config(bucket="test-bucket")
            store = S3Store(config)

            opts = PutOptions(
                content_type="text/plain",
                metadata={"author": "test"},
                cache_control="max-age=3600",
            )
            store.put("key.txt", b"data", opts)

            call_kwargs = mock_client.put_object.call_args[1]
            assert call_kwargs["ContentType"] == "text/plain"
            assert call_kwargs["Metadata"] == {"author": "test"}
            assert call_kwargs["CacheControl"] == "max-age=3600"

    def test_put_with_prefix(self) -> None:
        """Test put respects key prefix."""
        with patch("boto3.Session") as mock_session_cls:
            mock_session = MagicMock()
            mock_client = MagicMock()
            mock_session.client.return_value = mock_client
            mock_session_cls.return_value = mock_session

            config = S3Config(bucket="test-bucket", prefix="app-data")
            store = S3Store(config)

            store.put("key.txt", b"data")

            call_kwargs = mock_client.put_object.call_args[1]
            assert call_kwargs["Key"] == "app-data/key.txt"

    def test_get(self) -> None:
        """Test get operation."""
        with patch("boto3.Session") as mock_session_cls:
            mock_session = MagicMock()
            mock_client = MagicMock()
            mock_response = MagicMock()
            mock_response["Body"].read.return_value = b"test data"
            mock_client.get_object.return_value = mock_response
            mock_session.client.return_value = mock_client
            mock_session_cls.return_value = mock_session

            config = S3Config(bucket="test-bucket")
            store = S3Store(config)

            result = store.get("key.txt")
            assert result == b"test data"

    def test_get_missing_raises_keyerror(self) -> None:
        """Test get raises KeyError for missing key."""
        with patch("boto3.Session") as mock_session_cls:
            mock_session = MagicMock()
            mock_client = MagicMock()
            mock_client.exceptions.NoSuchKey = type("NoSuchKey", (Exception,), {})
            mock_client.get_object.side_effect = mock_client.exceptions.NoSuchKey()
            mock_session.client.return_value = mock_client
            mock_session_cls.return_value = mock_session

            config = S3Config(bucket="test-bucket")
            store = S3Store(config)

            with pytest.raises(KeyError):
                store.get("missing.txt")

    def test_delete(self) -> None:
        """Test delete operation."""
        with patch("boto3.Session") as mock_session_cls:
            mock_session = MagicMock()
            mock_client = MagicMock()
            mock_session.client.return_value = mock_client
            mock_session_cls.return_value = mock_session

            config = S3Config(bucket="test-bucket")
            store = S3Store(config)

            store.delete("key.txt")

            mock_client.delete_object.assert_called_once()
            call_kwargs = mock_client.delete_object.call_args[1]
            assert call_kwargs["Key"] == "key.txt"

    def test_exists_true(self) -> None:
        """Test exists returns True when object exists."""
        with patch("boto3.Session") as mock_session_cls:
            mock_session = MagicMock()
            mock_client = MagicMock()
            mock_client.head_object.return_value = {}
            mock_session.client.return_value = mock_client
            mock_session_cls.return_value = mock_session

            config = S3Config(bucket="test-bucket")
            store = S3Store(config)

            assert store.exists("key.txt") is True

    def test_exists_false(self) -> None:
        """Test exists returns False when object missing."""
        with patch("boto3.Session") as mock_session_cls:
            mock_session = MagicMock()
            mock_client = MagicMock()
            mock_client.exceptions.NoSuchKey = type("NoSuchKey", (Exception,), {})
            mock_client.head_object.side_effect = mock_client.exceptions.NoSuchKey()
            mock_session.client.return_value = mock_client
            mock_session_cls.return_value = mock_session

            config = S3Config(bucket="test-bucket")
            store = S3Store(config)

            assert store.exists("missing.txt") is False

    def test_list(self) -> None:
        """Test list operation."""
        with patch("boto3.Session") as mock_session_cls:
            mock_session = MagicMock()
            mock_client = MagicMock()
            mock_paginator = MagicMock()
            mock_client.get_paginator.return_value = mock_paginator
            mock_paginator.paginate.return_value = [
                {
                    "Contents": [
                        {"Key": "key1.txt"},
                        {"Key": "key2.txt"},
                    ]
                }
            ]
            mock_session.client.return_value = mock_client
            mock_session_cls.return_value = mock_session

            config = S3Config(bucket="test-bucket")
            store = S3Store(config)

            result = store.list()
            assert sorted(result) == ["key1.txt", "key2.txt"]

    def test_list_with_prefix(self) -> None:
        """Test list with prefix."""
        with patch("boto3.Session") as mock_session_cls:
            mock_session = MagicMock()
            mock_client = MagicMock()
            mock_paginator = MagicMock()
            mock_client.get_paginator.return_value = mock_paginator
            mock_paginator.paginate.return_value = [
                {
                    "Contents": [
                        {"Key": "data/key1.txt"},
                        {"Key": "data/key2.txt"},
                    ]
                }
            ]
            mock_session.client.return_value = mock_client
            mock_session_cls.return_value = mock_session

            config = S3Config(bucket="test-bucket")
            store = S3Store(config)

            result = store.list("data")
            assert sorted(result) == ["key1.txt", "key2.txt"]

    def test_get_url(self) -> None:
        """Test get_url returns presigned URL."""
        with patch("boto3.Session") as mock_session_cls:
            mock_session = MagicMock()
            mock_client = MagicMock()
            mock_client.generate_presigned_url.return_value = "https://s3.amazonaws.com/presigned"
            mock_session.client.return_value = mock_client
            mock_session_cls.return_value = mock_session

            config = S3Config(bucket="test-bucket")
            store = S3Store(config)

            url = store.get_url("key.txt", expires_in=7200)
            assert url == "https://s3.amazonaws.com/presigned"

    def test_protocol_compliance(self) -> None:
        """Test S3Store complies with StorageStore protocol."""
        with patch("boto3.Session") as mock_session_cls:
            mock_session = MagicMock()
            mock_session_cls.return_value = mock_session

            config = S3Config(bucket="test-bucket")
            store = S3Store(config)

            assert isinstance(store, StorageStore)


class TestAsyncS3Store:
    """Tests for async S3 storage backend."""

    @pytest.mark.asyncio
    async def test_async_put(self) -> None:
        """Test async put delegates to sync store."""
        with patch("boto3.Session"):
            config = S3Config(bucket="test-bucket")
            store = AsyncS3Store(config)

            with patch.object(store._sync_store, "put") as mock_put:
                await store.put("key.txt", b"data")
                mock_put.assert_called_once_with("key.txt", b"data", None)

    @pytest.mark.asyncio
    async def test_async_get(self) -> None:
        """Test async get delegates to sync store."""
        with patch("boto3.Session"):
            config = S3Config(bucket="test-bucket")
            store = AsyncS3Store(config)

            with patch.object(store._sync_store, "get", return_value=b"data"):
                result = await store.get("key.txt")
                assert result == b"data"

    @pytest.mark.asyncio
    async def test_async_delete(self) -> None:
        """Test async delete delegates to sync store."""
        with patch("boto3.Session"):
            config = S3Config(bucket="test-bucket")
            store = AsyncS3Store(config)

            with patch.object(store._sync_store, "delete") as mock_delete:
                await store.delete("key.txt")
                mock_delete.assert_called_once_with("key.txt")

    @pytest.mark.asyncio
    async def test_async_exists(self) -> None:
        """Test async exists delegates to sync store."""
        with patch("boto3.Session"):
            config = S3Config(bucket="test-bucket")
            store = AsyncS3Store(config)

            with patch.object(store._sync_store, "exists", return_value=True):
                result = await store.exists("key.txt")
                assert result is True

    @pytest.mark.asyncio
    async def test_async_list(self) -> None:
        """Test async list delegates to sync store."""
        with patch("boto3.Session"):
            config = S3Config(bucket="test-bucket")
            store = AsyncS3Store(config)

            with patch.object(store._sync_store, "list", return_value=["key1.txt"]):
                result = await store.list()
                assert result == ["key1.txt"]

    @pytest.mark.asyncio
    async def test_async_get_url(self) -> None:
        """Test async get_url delegates to sync store."""
        with patch("boto3.Session"):
            config = S3Config(bucket="test-bucket")
            store = AsyncS3Store(config)

            with patch.object(store._sync_store, "get_url", return_value="https://s3.amazonaws.com/url"):
                result = await store.get_url("key.txt", 7200)
                assert result == "https://s3.amazonaws.com/url"
