"""Abstract base adapter for secrets backends."""

from __future__ import annotations

from abc import ABC, abstractmethod
from types import TracebackType
from typing import Any

from penguin_sal.core.types import ConnectionConfig, Secret, SecretList


class BaseAdapter(ABC):
    """Abstract base class for all secrets backend adapters.

    Adapters must implement all abstract methods to provide a unified
    interface for secrets CRUD operations across different backends.
    """

    def __init__(self, config: ConnectionConfig) -> None:
        self.config = config
        self._connected = False

    @abstractmethod
    def _init_connection(self, **kwargs: Any) -> None:
        """Initialize the backend client connection."""

    @abstractmethod
    def authenticate(self) -> None:
        """Authenticate with the secrets backend.

        Raises:
            AuthenticationError: If authentication fails.
            ConnectionError: If the backend is unreachable.
        """

    @abstractmethod
    def get(self, key: str, version: int | None = None) -> Secret:
        """Retrieve a secret by key.

        Args:
            key: The secret identifier.
            version: Optional specific version to retrieve.

        Returns:
            Secret object with value and metadata.

        Raises:
            SecretNotFoundError: If the secret does not exist.
            BackendError: If the backend request fails.
        """

    @abstractmethod
    def set(
        self,
        key: str,
        value: str | bytes | dict[str, Any],
        metadata: dict[str, Any] | None = None,
    ) -> Secret:
        """Create or update a secret.

        Args:
            key: The secret identifier.
            value: The secret value.
            metadata: Optional metadata to attach.

        Returns:
            Secret object reflecting the stored state.

        Raises:
            BackendError: If the backend request fails.
        """

    @abstractmethod
    def delete(self, key: str) -> bool:
        """Delete a secret.

        Args:
            key: The secret identifier.

        Returns:
            True if the secret was deleted, False if it didn't exist.

        Raises:
            BackendError: If the backend request fails.
        """

    @abstractmethod
    def list(self, prefix: str = "", limit: int | None = None) -> SecretList:
        """List secret keys.

        Args:
            prefix: Filter keys by prefix.
            limit: Maximum number of keys to return.

        Returns:
            SecretList with matching keys.

        Raises:
            BackendError: If the backend request fails.
        """

    @abstractmethod
    def exists(self, key: str) -> bool:
        """Check if a secret exists.

        Args:
            key: The secret identifier.

        Returns:
            True if the secret exists.
        """

    @abstractmethod
    def health_check(self) -> bool:
        """Check if the backend is healthy and reachable.

        Returns:
            True if the backend is healthy.
        """

    @abstractmethod
    def close(self) -> None:
        """Close the backend connection and release resources."""

    def __enter__(self) -> BaseAdapter:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        self.close()
