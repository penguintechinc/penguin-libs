"""NFS file storage backend."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from penguin_dal.protocols import PutOptions, StorageStore


@dataclass(slots=True)
class NFSConfig:
    """Configuration for NFS file storage."""

    mount_path: str
    create_dirs: bool = True


class NFSStore:
    """File-based store over a pre-mounted NFS path."""

    def __init__(self, config: NFSConfig) -> None:
        """Initialize NFS store with configuration."""
        self._config = config
        self._base_path = Path(config.mount_path)

        if not self._base_path.exists():
            raise ValueError(
                f"Mount path does not exist: {config.mount_path}"
            )

        if not self._base_path.is_dir():
            raise ValueError(
                f"Mount path is not a directory: {config.mount_path}"
            )

    def _get_file_path(self, key: str) -> Path:
        """Build full file path from key."""
        return self._base_path / key

    def put(
        self, key: str, data: bytes, opts: PutOptions | None = None
    ) -> None:
        """Store object at key."""
        file_path = self._get_file_path(key)

        if self._config.create_dirs:
            file_path.parent.mkdir(parents=True, exist_ok=True)

        file_path.write_bytes(data)

    def get(self, key: str) -> bytes:
        """Retrieve object at key. Raises KeyError if not found."""
        file_path = self._get_file_path(key)

        if not file_path.exists():
            raise KeyError(key)

        return file_path.read_bytes()

    def delete(self, key: str) -> None:
        """Delete object at key."""
        file_path = self._get_file_path(key)

        if file_path.exists():
            file_path.unlink()

    def exists(self, key: str) -> bool:
        """Check if object exists at key."""
        file_path = self._get_file_path(key)
        return file_path.exists() and file_path.is_file()

    def list(self, prefix: str = "") -> list[str]:
        """List all keys with given prefix."""
        if prefix:
            search_path = self._get_file_path(prefix)
        else:
            search_path = self._base_path

        if not search_path.exists():
            return []

        keys: list[str] = []

        for file_path in sorted(search_path.rglob("*")):
            if file_path.is_file():
                if prefix:
                    relative_path = file_path.relative_to(search_path)
                else:
                    relative_path = file_path.relative_to(self._base_path)
                keys.append(str(relative_path))

        return keys

    def get_url(self, key: str, expires_in: int = 3600) -> str:
        """Get a file:// URI to access object at key."""
        file_path = self._get_file_path(key)
        return file_path.as_uri()
