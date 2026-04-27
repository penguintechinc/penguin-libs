"""Tests for H3 configuration classes."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pytest

from penguin_h3.config import ClientConfig, RetryConfig, ServerConfig, TLSConfig


class TestTLSConfig:
    """Test TLSConfig dataclass."""

    def test_tls_config_defaults(self) -> None:
        """Test TLSConfig with default values."""
        cert_path = Path("/etc/ssl/certs/server.crt")
        key_path = Path("/etc/ssl/private/server.key")
        cfg = TLSConfig(cert_path=cert_path, key_path=key_path)

        assert cfg.cert_path == cert_path
        assert cfg.key_path == key_path
        assert cfg.ca_cert_path is None
        assert cfg.verify_client is False

    def test_tls_config_with_ca_and_verify(self) -> None:
        """Test TLSConfig with CA cert and client verification."""
        cert_path = Path("/etc/ssl/certs/server.crt")
        key_path = Path("/etc/ssl/private/server.key")
        ca_path = Path("/etc/ssl/certs/ca.crt")
        cfg = TLSConfig(
            cert_path=cert_path,
            key_path=key_path,
            ca_cert_path=ca_path,
            verify_client=True,
        )

        assert cfg.cert_path == cert_path
        assert cfg.key_path == key_path
        assert cfg.ca_cert_path == ca_path
        assert cfg.verify_client is True

    def test_tls_config_is_frozen(self) -> None:
        """Test that TLSConfig is immutable."""
        cfg = TLSConfig(
            cert_path=Path("/etc/ssl/certs/server.crt"),
            key_path=Path("/etc/ssl/private/server.key"),
        )
        with pytest.raises(AttributeError):
            cfg.verify_client = True


class TestServerConfig:
    """Test ServerConfig dataclass."""

    def test_server_config_defaults(self) -> None:
        """Test ServerConfig with default values."""
        cfg = ServerConfig()

        assert cfg.h2_host == "0.0.0.0"
        assert cfg.h2_port == 8080
        assert cfg.h3_host == "0.0.0.0"
        assert cfg.h3_port == 8443
        assert cfg.h2_enabled is True
        assert cfg.h3_enabled is True
        assert cfg.tls is None
        assert cfg.grace_period == 30.0
        assert cfg.access_log is True

    def test_server_config_custom_values(self) -> None:
        """Test ServerConfig with custom values."""
        cert_path = Path("/tmp/server.crt")
        key_path = Path("/tmp/server.key")
        tls_cfg = TLSConfig(cert_path=cert_path, key_path=key_path)

        cfg = ServerConfig(
            h2_host="127.0.0.1",
            h2_port=9000,
            h3_host="127.0.0.1",
            h3_port=9443,
            h2_enabled=False,
            h3_enabled=True,
            tls=tls_cfg,
            grace_period=60.0,
            access_log=False,
        )

        assert cfg.h2_host == "127.0.0.1"
        assert cfg.h2_port == 9000
        assert cfg.h3_host == "127.0.0.1"
        assert cfg.h3_port == 9443
        assert cfg.h2_enabled is False
        assert cfg.h3_enabled is True
        assert cfg.tls == tls_cfg
        assert cfg.grace_period == 60.0
        assert cfg.access_log is False

    def test_server_config_is_frozen(self) -> None:
        """Test that ServerConfig is immutable."""
        cfg = ServerConfig()
        with pytest.raises(AttributeError):
            cfg.h2_port = 9000

    def test_server_config_from_env_defaults(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test ServerConfig.from_env() with no env vars set."""
        monkeypatch.delenv("H2_PORT", raising=False)
        monkeypatch.delenv("H3_PORT", raising=False)
        monkeypatch.delenv("H2_ENABLED", raising=False)
        monkeypatch.delenv("H3_ENABLED", raising=False)
        monkeypatch.delenv("TLS_CERT_PATH", raising=False)
        monkeypatch.delenv("TLS_KEY_PATH", raising=False)

        cfg = ServerConfig.from_env()

        assert cfg.h2_port == 8080
        assert cfg.h3_port == 8443
        assert cfg.h2_enabled is True
        assert cfg.h3_enabled is True
        assert cfg.tls is None

    def test_server_config_from_env_custom_ports(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test ServerConfig.from_env() with custom port env vars."""
        monkeypatch.setenv("H2_PORT", "9000")
        monkeypatch.setenv("H3_PORT", "9443")

        cfg = ServerConfig.from_env()

        assert cfg.h2_port == 9000
        assert cfg.h3_port == 9443

    def test_server_config_from_env_disabled_protocols(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test ServerConfig.from_env() with disabled protocols."""
        monkeypatch.setenv("H2_ENABLED", "false")
        monkeypatch.setenv("H3_ENABLED", "false")

        cfg = ServerConfig.from_env()

        assert cfg.h2_enabled is False
        assert cfg.h3_enabled is False

    def test_server_config_from_env_with_tls(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test ServerConfig.from_env() with TLS env vars."""
        with tempfile.TemporaryDirectory() as tmpdir:
            cert_path = Path(tmpdir) / "server.crt"
            key_path = Path(tmpdir) / "server.key"
            ca_path = Path(tmpdir) / "ca.crt"

            cert_path.touch()
            key_path.touch()
            ca_path.touch()

            monkeypatch.setenv("TLS_CERT_PATH", str(cert_path))
            monkeypatch.setenv("TLS_KEY_PATH", str(key_path))
            monkeypatch.setenv("TLS_CA_CERT_PATH", str(ca_path))

            cfg = ServerConfig.from_env()

            assert cfg.tls is not None
            assert cfg.tls.cert_path == cert_path
            assert cfg.tls.key_path == key_path
            assert cfg.tls.ca_cert_path == ca_path

    def test_server_config_from_env_tls_partial(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test ServerConfig.from_env() with only cert_path (no TLS config)."""
        monkeypatch.setenv("TLS_CERT_PATH", "/tmp/server.crt")
        monkeypatch.delenv("TLS_KEY_PATH", raising=False)

        cfg = ServerConfig.from_env()

        assert cfg.tls is None


class TestRetryConfig:
    """Test RetryConfig dataclass."""

    def test_retry_config_defaults(self) -> None:
        """Test RetryConfig with default values."""
        cfg = RetryConfig()

        assert cfg.max_retries == 3
        assert cfg.initial_backoff == 0.1
        assert cfg.max_backoff == 5.0
        assert cfg.multiplier == 2.0
        assert cfg.jitter is True

    def test_retry_config_custom_values(self) -> None:
        """Test RetryConfig with custom values."""
        cfg = RetryConfig(
            max_retries=5,
            initial_backoff=0.5,
            max_backoff=10.0,
            multiplier=3.0,
            jitter=False,
        )

        assert cfg.max_retries == 5
        assert cfg.initial_backoff == 0.5
        assert cfg.max_backoff == 10.0
        assert cfg.multiplier == 3.0
        assert cfg.jitter is False

    def test_retry_config_is_frozen(self) -> None:
        """Test that RetryConfig is immutable."""
        cfg = RetryConfig()
        with pytest.raises(AttributeError):
            cfg.max_retries = 10


class TestClientConfig:
    """Test ClientConfig dataclass."""

    def test_client_config_defaults(self) -> None:
        """Test ClientConfig with default values."""
        cfg = ClientConfig()

        assert cfg.base_url == ""
        assert cfg.tls is None
        assert cfg.h3_enabled is True
        assert cfg.h3_timeout == 5.0
        assert cfg.h3_retry_interval == 300.0
        assert cfg.request_timeout == 30.0
        assert cfg.verify_ssl is True
        assert isinstance(cfg.retry, RetryConfig)
        assert cfg.retry.max_retries == 3
        assert cfg.headers == {}

    def test_client_config_custom_values(self) -> None:
        """Test ClientConfig with custom values."""
        cert_path = Path("/tmp/client.crt")
        key_path = Path("/tmp/client.key")
        tls_cfg = TLSConfig(cert_path=cert_path, key_path=key_path)
        retry_cfg = RetryConfig(max_retries=5, initial_backoff=0.2)
        headers = {"X-Custom": "value"}

        cfg = ClientConfig(
            base_url="https://example.com",
            tls=tls_cfg,
            h3_enabled=False,
            h3_timeout=10.0,
            h3_retry_interval=600.0,
            request_timeout=60.0,
            verify_ssl=False,
            retry=retry_cfg,
            headers=headers,
        )

        assert cfg.base_url == "https://example.com"
        assert cfg.tls == tls_cfg
        assert cfg.h3_enabled is False
        assert cfg.h3_timeout == 10.0
        assert cfg.h3_retry_interval == 600.0
        assert cfg.request_timeout == 60.0
        assert cfg.verify_ssl is False
        assert cfg.retry == retry_cfg
        assert cfg.headers == headers

    def test_client_config_is_frozen(self) -> None:
        """Test that ClientConfig is immutable."""
        cfg = ClientConfig()
        with pytest.raises(AttributeError):
            cfg.base_url = "https://example.com"

    def test_client_config_retry_default_factory(self) -> None:
        """Test that retry field uses default_factory for each instance."""
        cfg1 = ClientConfig()
        cfg2 = ClientConfig()

        # Both should have RetryConfig instances but not the same object
        assert isinstance(cfg1.retry, RetryConfig)
        assert isinstance(cfg2.retry, RetryConfig)
        assert cfg1.retry is not cfg2.retry

    def test_client_config_headers_default_factory(self) -> None:
        """Test that headers field uses default_factory for each instance."""
        cfg1 = ClientConfig()
        cfg2 = ClientConfig()

        # Both should have dict instances but not the same object
        assert isinstance(cfg1.headers, dict)
        assert isinstance(cfg2.headers, dict)
        assert cfg1.headers is not cfg2.headers
