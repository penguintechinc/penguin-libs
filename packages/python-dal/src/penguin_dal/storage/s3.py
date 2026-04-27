"""S3-compatible object storage backend."""
from __future__ import annotations

import asyncio
from dataclasses import dataclass

from penguin_dal.protocols import PutOptions, StorageStore


@dataclass(slots=True)
class S3Config:
    """Configuration for S3-compatible storage."""

    bucket: str
    region: str = "us-east-1"
    access_key: str | None = None
    secret_key: str | None = None
    endpoint_url: str | None = None
    prefix: str = ""


class S3Store:
    """Synchronous S3-compatible object store using boto3."""

    def __init__(self, config: S3Config) -> None:
        """Initialize S3 store with configuration."""
        try:
            import boto3
        except ImportError as e:
            raise ImportError(
                "boto3 is required for S3 storage. Install with: pip install penguin-dal[s3]"
            ) from e

        self._config = config
        self._boto3 = boto3

        session_kwargs: dict[str, str | None] = {}
        if config.access_key:
            session_kwargs["aws_access_key_id"] = config.access_key
        if config.secret_key:
            session_kwargs["aws_secret_access_key"] = config.secret_key

        session = boto3.Session(**{k: v for k, v in session_kwargs.items() if v})
        client_kwargs: dict[str, str] = {"region_name": config.region}
        if config.endpoint_url:
            client_kwargs["endpoint_url"] = config.endpoint_url

        self._client = session.client("s3", **client_kwargs)

    def _make_key(self, key: str) -> str:
        """Build full S3 key with prefix."""
        if self._config.prefix:
            return f"{self._config.prefix}/{key}"
        return key

    def _strip_prefix(self, key: str) -> str:
        """Remove prefix from key for listing results."""
        if self._config.prefix and key.startswith(f"{self._config.prefix}/"):
            return key[len(self._config.prefix) + 1 :]
        return key

    def put(
        self, key: str, data: bytes, opts: PutOptions | None = None
    ) -> None:
        """Store object at key."""
        opts = opts or PutOptions()
        s3_key = self._make_key(key)

        put_kwargs: dict[str, str | dict[str, str]] = {
            "ContentType": opts.content_type,
        }

        if opts.metadata:
            put_kwargs["Metadata"] = opts.metadata

        if opts.cache_control:
            put_kwargs["CacheControl"] = opts.cache_control

        self._client.put_object(
            Bucket=self._config.bucket,
            Key=s3_key,
            Body=data,
            **put_kwargs,
        )

    def get(self, key: str) -> bytes:
        """Retrieve object at key. Raises KeyError if not found."""
        s3_key = self._make_key(key)
        try:
            response = self._client.get_object(
                Bucket=self._config.bucket,
                Key=s3_key,
            )
            return response["Body"].read()
        except self._client.exceptions.NoSuchKey:
            raise KeyError(key)
        except Exception as e:
            if "NoSuchKey" in str(e) or "404" in str(e):
                raise KeyError(key)
            raise

    def delete(self, key: str) -> None:
        """Delete object at key."""
        s3_key = self._make_key(key)
        self._client.delete_object(
            Bucket=self._config.bucket,
            Key=s3_key,
        )

    def exists(self, key: str) -> bool:
        """Check if object exists at key."""
        s3_key = self._make_key(key)
        try:
            self._client.head_object(
                Bucket=self._config.bucket,
                Key=s3_key,
            )
            return True
        except self._client.exceptions.NoSuchKey:
            return False
        except Exception as e:
            if "NoSuchKey" in str(e) or "404" in str(e):
                return False
            raise

    def list(self, prefix: str = "") -> list[str]:
        """List all keys with given prefix."""
        s3_prefix = self._make_key(prefix)
        keys: list[str] = []

        paginator = self._client.get_paginator("list_objects_v2")
        pages = paginator.paginate(
            Bucket=self._config.bucket,
            Prefix=s3_prefix,
        )

        for page in pages:
            if "Contents" in page:
                for obj in page["Contents"]:
                    full_key = obj["Key"]
                    stripped_key = self._strip_prefix(full_key)

                    if prefix:
                        if prefix in full_key:
                            relative = full_key[len(s3_prefix) + 1 :]
                            if relative:
                                keys.append(relative)
                    else:
                        if stripped_key:
                            keys.append(stripped_key)

        return sorted(keys)

    def get_url(self, key: str, expires_in: int = 3600) -> str:
        """Get a presigned URL to access object at key."""
        s3_key = self._make_key(key)
        return self._client.generate_presigned_url(
            "get_object",
            Params={"Bucket": self._config.bucket, "Key": s3_key},
            ExpiresIn=expires_in,
        )


class AsyncS3Store:
    """Asynchronous S3 store wrapping S3Store via asyncio.to_thread."""

    def __init__(self, config: S3Config) -> None:
        """Initialize async S3 store."""
        self._sync_store = S3Store(config)

    async def put(
        self, key: str, data: bytes, opts: PutOptions | None = None
    ) -> None:
        """Store object at key."""
        await asyncio.to_thread(self._sync_store.put, key, data, opts)

    async def get(self, key: str) -> bytes:
        """Retrieve object at key. Raises KeyError if not found."""
        return await asyncio.to_thread(self._sync_store.get, key)

    async def delete(self, key: str) -> None:
        """Delete object at key."""
        await asyncio.to_thread(self._sync_store.delete, key)

    async def exists(self, key: str) -> bool:
        """Check if object exists at key."""
        return await asyncio.to_thread(self._sync_store.exists, key)

    async def list(self, prefix: str = "") -> list[str]:
        """List all keys with given prefix."""
        return await asyncio.to_thread(self._sync_store.list, prefix)

    async def get_url(self, key: str, expires_in: int = 3600) -> str:
        """Get a presigned URL to access object at key."""
        return await asyncio.to_thread(self._sync_store.get_url, key, expires_in)
