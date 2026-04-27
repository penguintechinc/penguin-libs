"""iSCSI block device storage backend."""
from __future__ import annotations

from dataclasses import dataclass

from penguin_dal.storage.nfs import NFSConfig, NFSStore


@dataclass(slots=True)
class ISCSIConfig:
    """Configuration for iSCSI block device storage."""

    mount_path: str
    target: str
    lun: int = 0


class ISCSIStore:
    """
    File-based store over an iSCSI-mounted block device filesystem.

    Behaves identically to NFSStore—the difference is the underlying
    transport (iSCSI block device vs NFS network share). Connection
    and mounting must be managed externally (iscsiadm + mount).
    """

    def __init__(self, config: ISCSIConfig) -> None:
        """Initialize iSCSI store by delegating to NFSStore."""
        nfs_config = NFSConfig(
            mount_path=config.mount_path,
            create_dirs=True,
        )
        self._nfs_store = NFSStore(nfs_config)
        self._config = config

    def put(self, key: str, data: bytes, opts=None) -> None:
        """Store object at key."""
        self._nfs_store.put(key, data, opts)

    def get(self, key: str) -> bytes:
        """Retrieve object at key. Raises KeyError if not found."""
        return self._nfs_store.get(key)

    def delete(self, key: str) -> None:
        """Delete object at key."""
        self._nfs_store.delete(key)

    def exists(self, key: str) -> bool:
        """Check if object exists at key."""
        return self._nfs_store.exists(key)

    def list(self, prefix: str = "") -> list[str]:
        """List all keys with given prefix."""
        return self._nfs_store.list(prefix)

    def get_url(self, key: str, expires_in: int = 3600) -> str:
        """Get a file:// URI to access object at key."""
        return self._nfs_store.get_url(key, expires_in)
