"""Tests for penguin-sal core data types."""

from datetime import datetime

import pytest

from penguin_sal.core.types import Secret, SecretList, ConnectionConfig


class TestSecret:
    """Test Secret data type."""

    def test_secret_required_fields(self) -> None:
        """Secret with required fields key and value."""
        secret = Secret(key="k", value="v")
        assert secret.key == "k"
        assert secret.value == "v"

    def test_secret_optional_fields_default(self) -> None:
        """Secret optional fields default to None."""
        secret = Secret(key="k", value="v")
        assert secret.version is None
        assert secret.created_at is None
        assert secret.updated_at is None
        assert secret.metadata is None

    def test_secret_all_fields(self) -> None:
        """Secret with all fields set."""
        now = datetime.now()
        metadata = {"tag": "prod"}
        secret = Secret(
            key="k",
            value="v",
            version=1,
            created_at=now,
            updated_at=now,
            metadata=metadata,
        )
        assert secret.key == "k"
        assert secret.value == "v"
        assert secret.version == 1
        assert secret.created_at is now
        assert secret.updated_at is now
        assert secret.metadata is metadata

    def test_secret_dict_value(self) -> None:
        """Secret can store dict value."""
        value = {"user": "admin", "pass": "x"}
        secret = Secret(key="k", value=value)
        assert secret.value == value

    def test_secret_bytes_value(self) -> None:
        """Secret can store bytes value."""
        value = b"binary-data"
        secret = Secret(key="k", value=value)
        assert secret.value == value

    def test_secret_has_slots(self) -> None:
        """Secret uses slots for memory efficiency."""
        secret = Secret(key="k", value="v")
        assert hasattr(Secret, "__slots__")


class TestSecretList:
    """Test SecretList data type."""

    def test_secret_list_basic(self) -> None:
        """SecretList with keys stores keys and cursor is None."""
        secret_list = SecretList(keys=["a", "b"])
        assert secret_list.keys == ["a", "b"]
        assert secret_list.cursor is None

    def test_secret_list_with_cursor(self) -> None:
        """SecretList with cursor stores cursor."""
        secret_list = SecretList(keys=["a"], cursor="next-page")
        assert secret_list.keys == ["a"]
        assert secret_list.cursor == "next-page"


class TestConnectionConfig:
    """Test ConnectionConfig data type."""

    def test_connection_config_required(self) -> None:
        """ConnectionConfig with required fields scheme and host."""
        config = ConnectionConfig(scheme="vault", host="localhost")
        assert config.scheme == "vault"
        assert config.host == "localhost"

    def test_connection_config_defaults(self) -> None:
        """ConnectionConfig optional fields have correct defaults."""
        config = ConnectionConfig(scheme="vault", host="localhost")
        assert config.port is None
        assert config.path == ""
        assert config.username is None
        assert config.password is None
        assert config.params == {}

    def test_connection_config_all_fields(self) -> None:
        """ConnectionConfig with all fields set."""
        params = {"timeout": "30"}
        config = ConnectionConfig(
            scheme="vault",
            host="localhost",
            port=8200,
            path="/v1",
            username="admin",
            password="secret",
            params=params,
        )
        assert config.scheme == "vault"
        assert config.host == "localhost"
        assert config.port == 8200
        assert config.path == "/v1"
        assert config.username == "admin"
        assert config.password == "secret"
        assert config.params is params

    def test_connection_config_has_slots(self) -> None:
        """ConnectionConfig uses slots for memory efficiency."""
        config = ConnectionConfig(scheme="vault", host="localhost")
        assert hasattr(ConnectionConfig, "__slots__")
