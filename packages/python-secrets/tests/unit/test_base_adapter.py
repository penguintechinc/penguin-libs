"""Tests for BaseAdapter abstract base class."""

from __future__ import annotations

from typing import Any

import pytest

from penguin_sal.core.base_adapter import BaseAdapter
from penguin_sal.core.types import ConnectionConfig, Secret, SecretList


class ConcreteAdapter(BaseAdapter):
    """Minimal concrete implementation for testing the ABC."""

    def _init_connection(self, **kwargs: Any) -> None:
        self._connected = True

    def authenticate(self) -> None:
        pass

    def get(self, key: str, version: int | None = None) -> Secret:
        return Secret(key=key, value="test-value", version=version)

    def set(
        self,
        key: str,
        value: str | bytes | dict[str, Any],
        metadata: dict[str, Any] | None = None,
    ) -> Secret:
        return Secret(key=key, value=value, metadata=metadata)

    def delete(self, key: str) -> bool:
        return True

    def list(self, prefix: str = "", limit: int | None = None) -> SecretList:
        return SecretList(keys=["key1", "key2"])

    def exists(self, key: str) -> bool:
        return True

    def health_check(self) -> bool:
        return True

    def close(self) -> None:
        self._connected = False


class TestBaseAdapterInit:
    """Test BaseAdapter initialization."""

    def test_stores_config(self) -> None:
        config = ConnectionConfig(scheme="vault", host="localhost", port=8200)
        adapter = ConcreteAdapter(config)
        assert adapter.config is config

    def test_connected_starts_false(self) -> None:
        config = ConnectionConfig(scheme="vault", host="localhost")
        adapter = ConcreteAdapter(config)
        assert adapter._connected is False


class TestBaseAdapterContextManager:
    """Test BaseAdapter context manager protocol."""

    def test_enter_returns_self(self) -> None:
        config = ConnectionConfig(scheme="vault", host="localhost")
        adapter = ConcreteAdapter(config)
        result = adapter.__enter__()
        assert result is adapter

    def test_exit_calls_close(self) -> None:
        config = ConnectionConfig(scheme="vault", host="localhost")
        adapter = ConcreteAdapter(config)
        adapter._connected = True
        adapter.__exit__(None, None, None)
        assert adapter._connected is False

    def test_with_statement(self) -> None:
        config = ConnectionConfig(scheme="vault", host="localhost")
        with ConcreteAdapter(config) as adapter:
            adapter._connected = True
            assert isinstance(adapter, BaseAdapter)
        assert adapter._connected is False

    def test_exit_called_on_exception(self) -> None:
        config = ConnectionConfig(scheme="vault", host="localhost")
        adapter = ConcreteAdapter(config)
        adapter._connected = True
        try:
            with adapter:
                raise ValueError("test error")
        except ValueError:
            pass
        assert adapter._connected is False


class TestBaseAdapterAbstract:
    """Test that BaseAdapter cannot be instantiated directly."""

    def test_cannot_instantiate_directly(self) -> None:
        config = ConnectionConfig(scheme="vault", host="localhost")
        with pytest.raises(TypeError, match="abstract"):
            BaseAdapter(config)  # type: ignore[abstract]

    def test_partial_implementation_raises(self) -> None:
        """Subclass missing some abstract methods cannot be instantiated."""

        class PartialAdapter(BaseAdapter):
            def _init_connection(self, **kwargs: Any) -> None:
                pass

            def authenticate(self) -> None:
                pass

        config = ConnectionConfig(scheme="vault", host="localhost")
        with pytest.raises(TypeError):
            PartialAdapter(config)  # type: ignore[abstract]


class TestConcreteAdapterMethods:
    """Test that concrete implementations work through the ABC interface."""

    def test_get_returns_secret(self) -> None:
        config = ConnectionConfig(scheme="vault", host="localhost")
        adapter = ConcreteAdapter(config)
        result = adapter.get("my-key")
        assert isinstance(result, Secret)
        assert result.key == "my-key"

    def test_set_returns_secret(self) -> None:
        config = ConnectionConfig(scheme="vault", host="localhost")
        adapter = ConcreteAdapter(config)
        result = adapter.set("my-key", "my-value")
        assert isinstance(result, Secret)
        assert result.value == "my-value"

    def test_delete_returns_bool(self) -> None:
        config = ConnectionConfig(scheme="vault", host="localhost")
        adapter = ConcreteAdapter(config)
        assert adapter.delete("my-key") is True

    def test_list_returns_secret_list(self) -> None:
        config = ConnectionConfig(scheme="vault", host="localhost")
        adapter = ConcreteAdapter(config)
        result = adapter.list()
        assert isinstance(result, SecretList)

    def test_exists_returns_bool(self) -> None:
        config = ConnectionConfig(scheme="vault", host="localhost")
        adapter = ConcreteAdapter(config)
        assert adapter.exists("my-key") is True

    def test_health_check_returns_bool(self) -> None:
        config = ConnectionConfig(scheme="vault", host="localhost")
        adapter = ConcreteAdapter(config)
        assert adapter.health_check() is True

    def test_init_connection(self) -> None:
        config = ConnectionConfig(scheme="vault", host="localhost")
        adapter = ConcreteAdapter(config)
        adapter._init_connection()
        assert adapter._connected is True
