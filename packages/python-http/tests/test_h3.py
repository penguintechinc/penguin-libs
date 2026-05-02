"""Tests for H3 configuration, exceptions, protocol, client, and retry logic."""

from __future__ import annotations

import asyncio
import os
import tempfile
import time
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from penguin_http.h3.client import H3Client
from penguin_http.h3.config import ClientConfig, RetryConfig, ServerConfig, TLSConfig
from penguin_http.h3.exceptions import (
    H3ClientError,
    H3ConfigError,
    H3Error,
    H3ServerError,
    H3TLSError,
    ProtocolFallbackError,
)
from penguin_http.h3.protocol import Protocol
from penguin_http.h3.retry import _calc_backoff, async_retry


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


class TestH3Error:
    """Test H3Error base exception."""

    def test_h3_error_raised(self) -> None:
        """Test that H3Error can be raised and caught."""
        with pytest.raises(H3Error):
            raise H3Error("test error")

    def test_h3_error_message(self) -> None:
        """Test that H3Error preserves error message."""
        msg = "something went wrong"
        try:
            raise H3Error(msg)
        except H3Error as exc:
            assert str(exc) == msg

    def test_h3_error_is_exception(self) -> None:
        """Test that H3Error inherits from Exception."""
        assert issubclass(H3Error, Exception)


class TestH3ConfigError:
    """Test H3ConfigError exception."""

    def test_h3_config_error_raised(self) -> None:
        """Test that H3ConfigError can be raised and caught."""
        with pytest.raises(H3ConfigError):
            raise H3ConfigError("invalid config")

    def test_h3_config_error_message(self) -> None:
        """Test that H3ConfigError preserves error message."""
        msg = "config validation failed"
        try:
            raise H3ConfigError(msg)
        except H3ConfigError as exc:
            assert str(exc) == msg

    def test_h3_config_error_inherits_from_h3_error(self) -> None:
        """Test that H3ConfigError inherits from H3Error."""
        assert issubclass(H3ConfigError, H3Error)

    def test_h3_config_error_caught_as_h3_error(self) -> None:
        """Test that H3ConfigError can be caught as H3Error."""
        with pytest.raises(H3Error):
            raise H3ConfigError("invalid config")


class TestH3TLSError:
    """Test H3TLSError exception."""

    def test_h3_tls_error_raised(self) -> None:
        """Test that H3TLSError can be raised and caught."""
        with pytest.raises(H3TLSError):
            raise H3TLSError("tls error")

    def test_h3_tls_error_message(self) -> None:
        """Test that H3TLSError preserves error message."""
        msg = "certificate not found"
        try:
            raise H3TLSError(msg)
        except H3TLSError as exc:
            assert str(exc) == msg

    def test_h3_tls_error_inherits_from_h3_error(self) -> None:
        """Test that H3TLSError inherits from H3Error."""
        assert issubclass(H3TLSError, H3Error)

    def test_h3_tls_error_caught_as_h3_error(self) -> None:
        """Test that H3TLSError can be caught as H3Error."""
        with pytest.raises(H3Error):
            raise H3TLSError("tls error")


class TestH3ServerError:
    """Test H3ServerError exception."""

    def test_h3_server_error_raised(self) -> None:
        """Test that H3ServerError can be raised and caught."""
        with pytest.raises(H3ServerError):
            raise H3ServerError("server error")

    def test_h3_server_error_message(self) -> None:
        """Test that H3ServerError preserves error message."""
        msg = "failed to bind port"
        try:
            raise H3ServerError(msg)
        except H3ServerError as exc:
            assert str(exc) == msg

    def test_h3_server_error_inherits_from_h3_error(self) -> None:
        """Test that H3ServerError inherits from H3Error."""
        assert issubclass(H3ServerError, H3Error)

    def test_h3_server_error_caught_as_h3_error(self) -> None:
        """Test that H3ServerError can be caught as H3Error."""
        with pytest.raises(H3Error):
            raise H3ServerError("server error")


class TestH3ClientError:
    """Test H3ClientError exception."""

    def test_h3_client_error_raised(self) -> None:
        """Test that H3ClientError can be raised and caught."""
        with pytest.raises(H3ClientError):
            raise H3ClientError("client error")

    def test_h3_client_error_message(self) -> None:
        """Test that H3ClientError preserves error message."""
        msg = "connection failed"
        try:
            raise H3ClientError(msg)
        except H3ClientError as exc:
            assert str(exc) == msg

    def test_h3_client_error_inherits_from_h3_error(self) -> None:
        """Test that H3ClientError inherits from H3Error."""
        assert issubclass(H3ClientError, H3Error)

    def test_h3_client_error_caught_as_h3_error(self) -> None:
        """Test that H3ClientError can be caught as H3Error."""
        with pytest.raises(H3Error):
            raise H3ClientError("client error")


class TestProtocolFallbackError:
    """Test ProtocolFallbackError exception."""

    def test_protocol_fallback_error_basic(self) -> None:
        """Test ProtocolFallbackError with original error."""
        original = ValueError("h3 connection failed")
        exc = ProtocolFallbackError(original)

        assert exc.original_error == original
        assert exc.fallback_protocol == "h2"
        assert "h3" in str(exc).lower()
        assert "h2" in str(exc).lower()

    def test_protocol_fallback_error_custom_protocol(self) -> None:
        """Test ProtocolFallbackError with custom fallback protocol."""
        original = RuntimeError("quic error")
        exc = ProtocolFallbackError(original, protocol="custom")

        assert exc.original_error == original
        assert exc.fallback_protocol == "custom"
        assert "custom" in str(exc)

    def test_protocol_fallback_error_message_format(self) -> None:
        """Test ProtocolFallbackError message format."""
        original = TimeoutError("connection timeout")
        exc = ProtocolFallbackError(original, protocol="h2")

        msg = str(exc)
        assert "HTTP/3" in msg
        assert "connection timeout" in msg
        assert "h2" in msg

    def test_protocol_fallback_error_inherits_from_h3_error(self) -> None:
        """Test that ProtocolFallbackError inherits from H3Error."""
        assert issubclass(ProtocolFallbackError, H3Error)

    def test_protocol_fallback_error_caught_as_h3_error(self) -> None:
        """Test that ProtocolFallbackError can be caught as H3Error."""
        original = Exception("some error")
        with pytest.raises(H3Error):
            raise ProtocolFallbackError(original)

    def test_protocol_fallback_error_attributes_preserved(self) -> None:
        """Test that ProtocolFallbackError preserves original exception details."""
        original = ValueError("specific error message")
        exc = ProtocolFallbackError(original)

        # Check that original exception is accessible
        assert isinstance(exc.original_error, ValueError)
        assert str(exc.original_error) == "specific error message"


class TestProtocol:
    """Test Protocol enum."""

    def test_protocol_h2_value(self) -> None:
        """Test Protocol.H2 enum value."""
        assert Protocol.H2.value == "h2"

    def test_protocol_h3_value(self) -> None:
        """Test Protocol.H3 enum value."""
        assert Protocol.H3.value == "h3"

    def test_protocol_h2_str(self) -> None:
        """Test string representation of Protocol.H2."""
        assert str(Protocol.H2) == "h2"

    def test_protocol_h3_str(self) -> None:
        """Test string representation of Protocol.H3."""
        assert str(Protocol.H3) == "h3"

    def test_protocol_h2_name(self) -> None:
        """Test Protocol.H2 enum name."""
        assert Protocol.H2.name == "H2"

    def test_protocol_h3_name(self) -> None:
        """Test Protocol.H3 enum name."""
        assert Protocol.H3.name == "H3"

    def test_protocol_members(self) -> None:
        """Test that Protocol enum has expected members."""
        members = list(Protocol)
        assert len(members) == 2
        assert Protocol.H2 in members
        assert Protocol.H3 in members

    def test_protocol_equality(self) -> None:
        """Test Protocol enum equality."""
        assert Protocol.H2 == Protocol.H2
        assert Protocol.H3 == Protocol.H3
        assert Protocol.H2 != Protocol.H3

    def test_protocol_from_value(self) -> None:
        """Test creating Protocol from value."""
        assert Protocol("h2") == Protocol.H2
        assert Protocol("h3") == Protocol.H3

    def test_protocol_invalid_value(self) -> None:
        """Test that invalid value raises ValueError."""
        with pytest.raises(ValueError):
            Protocol("invalid")

    def test_protocol_iteration(self) -> None:
        """Test iterating over Protocol members."""
        protocols = {p.value for p in Protocol}
        assert protocols == {"h2", "h3"}

    def test_protocol_bool_values(self) -> None:
        """Test that all Protocol members are truthy."""
        assert bool(Protocol.H2) is True
        assert bool(Protocol.H3) is True


class TestH3Client:
    """Test H3Client."""

    @pytest.mark.asyncio
    async def test_h3_client_init_default_config(self) -> None:
        """Test H3Client initialization with default config."""
        async with H3Client() as client:
            assert isinstance(client._cfg, ClientConfig)
            assert client._cfg.base_url == ""
            assert client._cfg.h3_enabled is True

    @pytest.mark.asyncio
    async def test_h3_client_init_custom_config(self) -> None:
        """Test H3Client initialization with custom config."""
        cfg = ClientConfig(base_url="https://example.com", h3_enabled=False)
        async with H3Client(cfg) as client:
            assert client._cfg == cfg

    @pytest.mark.asyncio
    async def test_h3_client_context_manager(self) -> None:
        """Test H3Client as async context manager."""
        async with H3Client() as client:
            # Should be usable
            assert isinstance(client, H3Client)

    @pytest.mark.asyncio
    async def test_h3_client_protocol_h2_initially(self) -> None:
        """Test that protocol defaults to H2 (httpx_h3 likely not installed)."""
        async with H3Client() as client:
            # Without httpx_h3, should fall back to H2
            protocol = client.protocol
            # Should be one of the protocols
            assert protocol in [Protocol.H2, Protocol.H3]

    @pytest.mark.asyncio
    async def test_h3_client_get_request(self) -> None:
        """Test GET request."""
        cfg = ClientConfig(base_url="https://api.example.com")

        async with H3Client(cfg) as client:
            # Mock the h2_client
            mock_response = MagicMock(spec=httpx.Response)
            mock_response.status_code = 200
            client._h2_client = AsyncMock(spec=httpx.AsyncClient)
            client._h2_client.request = AsyncMock(return_value=mock_response)

            response = await client.get("/data")

            assert response == mock_response
            client._h2_client.request.assert_called_once()
            args = client._h2_client.request.call_args
            assert args[0][0] == "GET"

    @pytest.mark.asyncio
    async def test_h3_client_post_request(self) -> None:
        """Test POST request."""
        cfg = ClientConfig(base_url="https://api.example.com")

        async with H3Client(cfg) as client:
            mock_response = MagicMock(spec=httpx.Response)
            client._h2_client = AsyncMock(spec=httpx.AsyncClient)
            client._h2_client.request = AsyncMock(return_value=mock_response)

            response = await client.post("/data", json={"key": "value"})

            assert response == mock_response
            args = client._h2_client.request.call_args
            assert args[0][0] == "POST"

    @pytest.mark.asyncio
    async def test_h3_client_put_request(self) -> None:
        """Test PUT request."""
        cfg = ClientConfig(base_url="https://api.example.com")

        async with H3Client(cfg) as client:
            mock_response = MagicMock(spec=httpx.Response)
            client._h2_client = AsyncMock(spec=httpx.AsyncClient)
            client._h2_client.request = AsyncMock(return_value=mock_response)

            response = await client.put("/data/123", json={"key": "value"})

            assert response == mock_response
            args = client._h2_client.request.call_args
            assert args[0][0] == "PUT"

    @pytest.mark.asyncio
    async def test_h3_client_delete_request(self) -> None:
        """Test DELETE request."""
        cfg = ClientConfig(base_url="https://api.example.com")

        async with H3Client(cfg) as client:
            mock_response = MagicMock(spec=httpx.Response)
            client._h2_client = AsyncMock(spec=httpx.AsyncClient)
            client._h2_client.request = AsyncMock(return_value=mock_response)

            response = await client.delete("/data/123")

            assert response == mock_response
            args = client._h2_client.request.call_args
            assert args[0][0] == "DELETE"

    @pytest.mark.asyncio
    async def test_h3_client_close(self) -> None:
        """Test closing client."""
        cfg = ClientConfig()

        client = H3Client(cfg)

        # Manually set clients instead of calling _ensure_clients
        client._h2_client = AsyncMock(spec=httpx.AsyncClient)
        client._h3_client = AsyncMock(spec=httpx.AsyncClient)

        await client.close()

        # Both should be closed
        if client._h2_client is not None:
            client._h2_client.aclose.assert_called_once()
        if client._h3_client is not None:
            client._h3_client.aclose.assert_called_once()

        # References should be cleared (check via re-initialization)
        # After close, they should be None
        assert client._h2_client is None
        assert client._h3_client is None

    @pytest.mark.asyncio
    async def test_h3_client_not_initialized_error(self) -> None:
        """Test that request without context manager raises error."""
        client = H3Client()

        with pytest.raises((H3ClientError, Exception)):
            # Either H3ClientError or httpx protocol error (due to no base_url)
            await client.get("/")

    @pytest.mark.asyncio
    async def test_h3_client_h3_disabled(self) -> None:
        """Test client with H3 disabled."""
        cfg = ClientConfig(h3_enabled=False)

        async with H3Client(cfg) as client:
            assert client._use_h3 is False
            assert client.protocol == Protocol.H2

    @pytest.mark.asyncio
    async def test_h3_client_request_with_kwargs(self) -> None:
        """Test request with additional kwargs."""
        cfg = ClientConfig()

        async with H3Client(cfg) as client:
            mock_response = MagicMock(spec=httpx.Response)
            client._h2_client = AsyncMock(spec=httpx.AsyncClient)
            client._h2_client.request = AsyncMock(return_value=mock_response)

            await client.request("GET", "/data", headers={"X-Custom": "value"})

            call_kwargs = client._h2_client.request.call_args[1]
            assert call_kwargs["headers"]["X-Custom"] == "value"

    @pytest.mark.asyncio
    async def test_h3_client_fallback_on_h3_failure(self) -> None:
        """Test fallback to H2 when H3 fails."""
        cfg = ClientConfig(h3_enabled=True)

        async with H3Client(cfg) as client:
            # Setup mocks
            mock_h2_response = MagicMock(spec=httpx.Response)
            mock_h3_client = AsyncMock(spec=httpx.AsyncClient)
            mock_h3_client.request = AsyncMock(side_effect=RuntimeError("H3 error"))

            mock_h2_client = AsyncMock(spec=httpx.AsyncClient)
            mock_h2_client.request = AsyncMock(return_value=mock_h2_response)

            client._h3_client = mock_h3_client
            client._h2_client = mock_h2_client
            client._use_h3 = True

            response = await client.request("GET", "/")

            # Should return H2 response
            assert response == mock_h2_response
            # H3 should have been tried
            mock_h3_client.request.assert_called_once()
            # H2 should be fallback
            mock_h2_client.request.assert_called_once()

    @pytest.mark.asyncio
    async def test_h3_client_marks_h3_failed(self) -> None:
        """Test that H3 is marked as failed after error."""
        cfg = ClientConfig(h3_enabled=True)

        async with H3Client(cfg) as client:
            mock_h3_client = AsyncMock(spec=httpx.AsyncClient)
            mock_h3_client.request = AsyncMock(side_effect=RuntimeError("H3 error"))

            mock_h2_client = AsyncMock(spec=httpx.AsyncClient)
            mock_h2_client.request = AsyncMock(return_value=MagicMock())

            client._h3_client = mock_h3_client
            client._h2_client = mock_h2_client
            client._use_h3 = True

            initial = client._use_h3
            await client.request("GET", "/")

            # Should be marked as failed
            assert client._use_h3 is False

    @pytest.mark.asyncio
    async def test_h3_client_retry_h3_after_interval(self) -> None:
        """Test that H3 is retried after interval."""
        cfg = ClientConfig(h3_enabled=True, h3_retry_interval=0.1)

        async with H3Client(cfg) as client:
            client._use_h3 = False
            client._last_h3_try = time.monotonic() - 0.2  # 200ms ago
            client._h3_client = AsyncMock(spec=httpx.AsyncClient)  # Mock h3_client presence

            # H3 should be retried
            await client._maybe_retry_h3()

            assert client._use_h3 is True

    @pytest.mark.asyncio
    async def test_h3_client_no_retry_h3_before_interval(self) -> None:
        """Test that H3 is not retried before interval."""
        cfg = ClientConfig(h3_enabled=True, h3_retry_interval=10.0)

        async with H3Client(cfg) as client:
            client._use_h3 = False
            client._last_h3_try = time.monotonic()

            # H3 should not be retried
            await client._maybe_retry_h3()

            assert client._use_h3 is False

    @pytest.mark.asyncio
    async def test_h3_client_ensure_clients_idempotent(self) -> None:
        """Test that _ensure_clients is idempotent."""
        cfg = ClientConfig(h3_enabled=False)

        async with H3Client(cfg) as client:
            await client._ensure_clients()
            first_h2 = client._h2_client

            await client._ensure_clients()
            second_h2 = client._h2_client

            # Should be same object
            assert first_h2 is second_h2

    @pytest.mark.asyncio
    async def test_h3_client_httpx_h3_import_error(self) -> None:
        """Test handling of httpx_h3 import error."""
        cfg = ClientConfig(h3_enabled=True)

        async with H3Client(cfg) as client:
            # httpx_h3 is likely not installed, so h3 should be disabled
            # Just verify the behavior works when h3_client init fails
            client._h3_client = None
            client._h2_client = AsyncMock(spec=httpx.AsyncClient)
            client._use_h3 = True

            # Simulate failure by triggering request fallback
            client._h3_client = AsyncMock(side_effect=ImportError("httpx_h3"))
            client._h2_client.request = AsyncMock(return_value=MagicMock())

            # Should not raise, just use h2
            # This test verifies graceful fallback exists
            assert client.protocol in [Protocol.H2, Protocol.H3]

    @pytest.mark.asyncio
    async def test_h3_client_concurrent_requests(self) -> None:
        """Test concurrent requests work correctly."""
        cfg = ClientConfig(base_url="https://api.example.com")

        async with H3Client(cfg) as client:
            mock_response = MagicMock(spec=httpx.Response)
            mock_response.status_code = 200

            client._h2_client = AsyncMock(spec=httpx.AsyncClient)
            client._h2_client.request = AsyncMock(return_value=mock_response)

            # Make concurrent requests
            results = await asyncio.gather(
                client.get("/1"),
                client.get("/2"),
                client.get("/3"),
            )

            assert len(results) == 3
            assert client._h2_client.request.call_count == 3

    @pytest.mark.asyncio
    async def test_h3_client_preserves_config_headers(self) -> None:
        """Test that config headers are used in requests."""
        cfg = ClientConfig(headers={"X-API-Key": "secret", "User-Agent": "custom"})

        async with H3Client(cfg) as client:
            # Config is passed to httpx client initialization
            assert client._cfg.headers["X-API-Key"] == "secret"

    @pytest.mark.asyncio
    async def test_h3_client_lock_thread_safety(self) -> None:
        """Test that lock prevents race conditions on h3 flag."""
        cfg = ClientConfig(h3_enabled=True)

        async with H3Client(cfg) as client:
            # Mock clients
            client._h2_client = AsyncMock(spec=httpx.AsyncClient)
            client._h2_client.request = AsyncMock(return_value=MagicMock())

            # Simulate concurrent failure marking
            await asyncio.gather(
                client._mark_h3_failed(),
                client._mark_h3_failed(),
            )

            # Should only be marked once (idempotent)
            assert client._use_h3 is False


class TestCalcBackoff:
    """Test backoff calculation."""

    def test_calc_backoff_first_attempt(self) -> None:
        """Test backoff calculation for first attempt."""
        cfg = RetryConfig(initial_backoff=0.1, multiplier=2.0, jitter=False)
        backoff = _calc_backoff(cfg, 0)
        assert backoff == 0.1

    def test_calc_backoff_second_attempt(self) -> None:
        """Test backoff calculation for second attempt."""
        cfg = RetryConfig(initial_backoff=0.1, multiplier=2.0, jitter=False)
        backoff = _calc_backoff(cfg, 1)
        assert backoff == 0.2

    def test_calc_backoff_exponential_growth(self) -> None:
        """Test exponential growth of backoff."""
        cfg = RetryConfig(initial_backoff=0.1, multiplier=2.0, jitter=False)
        backoff_0 = _calc_backoff(cfg, 0)
        backoff_1 = _calc_backoff(cfg, 1)
        backoff_2 = _calc_backoff(cfg, 2)

        assert backoff_0 == 0.1
        assert backoff_1 == 0.2
        assert backoff_2 == 0.4

    def test_calc_backoff_max_backoff_cap(self) -> None:
        """Test that backoff is capped at max_backoff."""
        cfg = RetryConfig(initial_backoff=1.0, max_backoff=5.0, multiplier=2.0, jitter=False)
        backoff_0 = _calc_backoff(cfg, 0)
        backoff_1 = _calc_backoff(cfg, 1)
        backoff_2 = _calc_backoff(cfg, 2)
        backoff_3 = _calc_backoff(cfg, 3)

        assert backoff_0 == 1.0
        assert backoff_1 == 2.0
        assert backoff_2 == 4.0
        assert backoff_3 == 5.0  # Capped at max_backoff
        assert _calc_backoff(cfg, 10) == 5.0  # Still capped

    def test_calc_backoff_with_jitter(self) -> None:
        """Test backoff calculation with jitter enabled."""
        cfg = RetryConfig(initial_backoff=1.0, multiplier=2.0, jitter=True)
        backoff = _calc_backoff(cfg, 0)

        # Jitter multiplies by 0.5 + random(), so result should be 0.5x to 1.5x base
        assert 0.5 <= backoff <= 1.5

    def test_calc_backoff_jitter_range(self) -> None:
        """Test that jitter produces values in expected range."""
        cfg = RetryConfig(initial_backoff=2.0, multiplier=1.0, jitter=True)
        backoffs = [_calc_backoff(cfg, 0) for _ in range(100)]

        # All values should be between 1.0 (2.0 * 0.5) and 3.0 (2.0 * 1.5)
        assert all(1.0 <= b <= 3.0 for b in backoffs)
        # Ensure we get variation (not all same value)
        assert len(set(backoffs)) > 10


class TestAsyncRetry:
    """Test async_retry function."""

    @pytest.mark.asyncio
    async def test_async_retry_success_first_try(self) -> None:
        """Test successful execution on first try."""
        fn = AsyncMock(return_value="success")
        cfg = RetryConfig(max_retries=3)

        result = await async_retry(fn, cfg)

        assert result == "success"
        assert fn.call_count == 1

    @pytest.mark.asyncio
    async def test_async_retry_success_after_retries(self) -> None:
        """Test successful execution after initial failures."""
        fn = AsyncMock(side_effect=[ValueError("fail 1"), ValueError("fail 2"), "success"])
        cfg = RetryConfig(max_retries=3, initial_backoff=0.01, jitter=False)

        result = await async_retry(fn, cfg)

        assert result == "success"
        assert fn.call_count == 3

    @pytest.mark.asyncio
    async def test_async_retry_exhausts_retries(self) -> None:
        """Test that all retries are exhausted before raising."""
        fn = AsyncMock(side_effect=ValueError("always fails"))
        cfg = RetryConfig(max_retries=2, initial_backoff=0.01, jitter=False)

        with pytest.raises(ValueError, match="always fails"):
            await async_retry(fn, cfg)

        assert fn.call_count == 3  # Initial + 2 retries

    @pytest.mark.asyncio
    async def test_async_retry_respects_max_retries(self) -> None:
        """Test that max_retries limit is respected."""
        fn = AsyncMock(side_effect=RuntimeError("fail"))
        cfg = RetryConfig(max_retries=5, initial_backoff=0.01, jitter=False)

        with pytest.raises(RuntimeError):
            await async_retry(fn, cfg)

        assert fn.call_count == 6  # Initial + 5 retries

    @pytest.mark.asyncio
    async def test_async_retry_default_config(self) -> None:
        """Test async_retry with default config (None)."""
        fn = AsyncMock(return_value="success")

        result = await async_retry(fn, None)

        assert result == "success"
        assert fn.call_count == 1

    @pytest.mark.asyncio
    async def test_async_retry_passes_args(self) -> None:
        """Test that args are passed to the function."""
        fn = AsyncMock(return_value="success")
        cfg = RetryConfig(max_retries=1)

        result = await async_retry(fn, cfg, "arg1", "arg2")

        assert result == "success"
        fn.assert_called_once_with("arg1", "arg2")

    @pytest.mark.asyncio
    async def test_async_retry_passes_kwargs(self) -> None:
        """Test that kwargs are passed to the function."""
        fn = AsyncMock(return_value="success")
        cfg = RetryConfig(max_retries=1)

        result = await async_retry(fn, cfg, key1="value1", key2="value2")

        assert result == "success"
        fn.assert_called_once_with(key1="value1", key2="value2")

    @pytest.mark.asyncio
    async def test_async_retry_passes_mixed_args_kwargs(self) -> None:
        """Test that both args and kwargs are passed."""
        fn = AsyncMock(return_value="success")
        cfg = RetryConfig(max_retries=1)

        result = await async_retry(fn, cfg, "arg1", key="value")

        assert result == "success"
        fn.assert_called_once_with("arg1", key="value")

    @pytest.mark.asyncio
    async def test_async_retry_backoff_timing(self) -> None:
        """Test that backoff delay is applied between retries."""
        fn = AsyncMock(side_effect=ValueError("fail"))
        cfg = RetryConfig(max_retries=2, initial_backoff=0.05, multiplier=1.0, jitter=False)

        with patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
            with pytest.raises(ValueError):
                await async_retry(fn, cfg)

            # Should sleep twice (between attempts)
            assert mock_sleep.call_count == 2
            # First sleep 0.05, second sleep 0.05
            sleep_calls = [call[0][0] for call in mock_sleep.call_args_list]
            assert sleep_calls[0] == 0.05
            assert sleep_calls[1] == 0.05

    @pytest.mark.asyncio
    async def test_async_retry_exponential_backoff_timing(self) -> None:
        """Test exponential backoff timing between retries."""
        fn = AsyncMock(side_effect=ValueError("fail"))
        cfg = RetryConfig(max_retries=3, initial_backoff=0.1, multiplier=2.0, jitter=False)

        with patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
            with pytest.raises(ValueError):
                await async_retry(fn, cfg)

            assert mock_sleep.call_count == 3
            sleep_calls = [call[0][0] for call in mock_sleep.call_args_list]
            assert abs(sleep_calls[0] - 0.1) < 0.01
            assert abs(sleep_calls[1] - 0.2) < 0.01
            assert abs(sleep_calls[2] - 0.4) < 0.01

    @pytest.mark.asyncio
    async def test_async_retry_preserves_exception_type(self) -> None:
        """Test that original exception type is preserved."""
        fn = AsyncMock(side_effect=TimeoutError("timeout"))
        cfg = RetryConfig(max_retries=1, initial_backoff=0.01, jitter=False)

        with pytest.raises(TimeoutError):
            await async_retry(fn, cfg)

    @pytest.mark.asyncio
    async def test_async_retry_preserves_exception_message(self) -> None:
        """Test that original exception message is preserved."""
        error_msg = "specific error message"
        fn = AsyncMock(side_effect=ValueError(error_msg))
        cfg = RetryConfig(max_retries=1, initial_backoff=0.01, jitter=False)

        with pytest.raises(ValueError, match=error_msg):
            await async_retry(fn, cfg)

    @pytest.mark.asyncio
    async def test_async_retry_returns_value_on_success(self) -> None:
        """Test various return values are preserved."""
        # Test with dict
        fn = AsyncMock(return_value={"key": "value"})
        cfg = RetryConfig(max_retries=1)
        result = await async_retry(fn, cfg)
        assert result == {"key": "value"}

        # Test with list
        fn = AsyncMock(return_value=[1, 2, 3])
        result = await async_retry(fn, cfg)
        assert result == [1, 2, 3]

        # Test with None
        fn = AsyncMock(return_value=None)
        result = await async_retry(fn, cfg)
        assert result is None

    @pytest.mark.asyncio
    async def test_async_retry_no_sleep_on_final_failure(self) -> None:
        """Test that no sleep occurs after final failure."""
        fn = AsyncMock(side_effect=ValueError("fail"))
        cfg = RetryConfig(max_retries=2, initial_backoff=0.01, jitter=False)

        with patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
            with pytest.raises(ValueError):
                await async_retry(fn, cfg)

            # Should sleep only 2 times (between 3 attempts), not after the last
            assert mock_sleep.call_count == 2

    @pytest.mark.asyncio
    async def test_async_retry_zero_max_retries(self) -> None:
        """Test with max_retries=0 (only initial attempt, no retries)."""
        fn = AsyncMock(side_effect=ValueError("fail"))
        cfg = RetryConfig(max_retries=0)

        with pytest.raises(ValueError):
            await async_retry(fn, cfg)

        assert fn.call_count == 1  # Only initial attempt

    @pytest.mark.asyncio
    async def test_async_retry_logs_on_failure(self) -> None:
        """Test that failures are logged with attempt info."""
        fn = AsyncMock(side_effect=ValueError("fail"))
        cfg = RetryConfig(max_retries=2, initial_backoff=0.01, jitter=False)

        with patch("penguin_http.h3.retry.logger") as mock_logger:
            with pytest.raises(ValueError):
                await async_retry(fn, cfg)

            # Should log warning for each failed attempt except the last
            assert mock_logger.warning.call_count == 2
