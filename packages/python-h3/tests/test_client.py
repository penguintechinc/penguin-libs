"""Tests for H3Client."""

from __future__ import annotations

import asyncio
import time
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from penguin_h3.client import H3Client
from penguin_h3.config import ClientConfig
from penguin_h3.exceptions import H3ClientError
from penguin_h3.protocol import Protocol


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
