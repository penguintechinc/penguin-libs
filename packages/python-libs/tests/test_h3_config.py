"""Tests for penguin_libs.h3.config module."""

import os
from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

from penguin_libs.h3.config import (
    ClientConfig,
    RetryConfig,
    ServerConfig,
    TLSConfig,
)


def test_tls_config_defaults():
    """Test TLSConfig construction with cert_path/key_path."""
    tls = TLSConfig(cert_path="/path/to/cert.pem", key_path="/path/to/key.pem")
    assert tls.cert_path == "/path/to/cert.pem"
    assert tls.key_path == "/path/to/key.pem"
    assert tls.ca_cert_path is None
    assert tls.verify_client is False


def test_server_config_defaults():
    """Test ServerConfig default values."""
    config = ServerConfig()
    assert config.h2_host == "0.0.0.0"
    assert config.h2_port == 8080
    assert config.h3_port == 8443
    assert config.h2_enabled is True
    assert config.h3_enabled is True
    assert config.tls is None
    assert config.grace_period == 30.0
    assert config.access_log is True


def test_server_config_from_env(monkeypatch):
    """Test ServerConfig parsing from environment variables."""
    monkeypatch.setenv("H2_PORT", "9090")
    monkeypatch.setenv("H3_PORT", "9443")
    config = ServerConfig.from_env()
    assert config.h2_port == 9090
    assert config.h3_port == 9443


def test_server_config_from_env_disabled(monkeypatch):
    """Test ServerConfig with H2_ENABLED=false."""
    monkeypatch.setenv("H2_ENABLED", "false")
    config = ServerConfig.from_env()
    assert config.h2_enabled is False


def test_server_config_from_env_tls(monkeypatch):
    """Test ServerConfig with TLS environment variables."""
    monkeypatch.setenv("TLS_CERT_PATH", "/path/to/cert.pem")
    monkeypatch.setenv("TLS_KEY_PATH", "/path/to/key.pem")
    config = ServerConfig.from_env()
    assert config.tls is not None
    assert isinstance(config.tls, TLSConfig)
    assert config.tls.cert_path == Path("/path/to/cert.pem")
    assert config.tls.key_path == Path("/path/to/key.pem")


def test_client_config_defaults():
    """Test ClientConfig default values."""
    config = ClientConfig()
    assert config.base_url == ""
    assert config.h3_enabled is True
    assert config.h3_timeout == 5.0
    assert config.h3_retry_interval == 300.0
    assert config.request_timeout == 30.0
    assert config.verify_ssl is True


def test_retry_config_defaults():
    """Test RetryConfig default values."""
    config = RetryConfig()
    assert config.max_retries == 3
    assert config.initial_backoff == 0.1
    assert config.max_backoff == 5.0
    assert config.multiplier == 2.0
    assert config.jitter is True


def test_frozen_immutability():
    """Test that frozen dataclasses cannot be modified."""
    config = ServerConfig()
    with pytest.raises(FrozenInstanceError):
        config.h2_port = 9999
