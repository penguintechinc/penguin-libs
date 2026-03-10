"""Extended tests for penguin_libs.h3.client to improve coverage."""

from __future__ import annotations

import time
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from penguin_libs.h3.client import H3Client
from penguin_libs.h3.config import ClientConfig
from penguin_libs.h3.exceptions import H3ClientError


class TestH3ClientEnsureClients:
    """Tests for _ensure_clients."""

    @pytest.mark.asyncio
    async def test_creates_h2_client(self):
        cfg = ClientConfig(h3_enabled=False, base_url="http://localhost:8080")
        client = H3Client(cfg)

        assert client._h2_client is None
        with patch("httpx.AsyncClient") as mock_cls:
            mock_cls.return_value = MagicMock()
            await client._ensure_clients()
            assert client._h2_client is not None
            mock_cls.assert_called_once()

    @pytest.mark.asyncio
    async def test_idempotent(self):
        cfg = ClientConfig(h3_enabled=False, base_url="http://localhost:8080")
        client = H3Client(cfg)

        with patch("httpx.AsyncClient") as mock_cls:
            mock_cls.return_value = MagicMock()
            await client._ensure_clients()
            await client._ensure_clients()
            # Should only create once
            mock_cls.assert_called_once()


class TestH3ClientProtocolFallback:
    """Tests for HTTP/3 -> HTTP/2 fallback behavior."""

    @pytest.mark.asyncio
    async def test_mark_h3_failed(self):
        cfg = ClientConfig(h3_enabled=True, base_url="http://localhost")
        client = H3Client(cfg)
        assert client._use_h3 is True

        await client._mark_h3_failed()
        assert client._use_h3 is False
        assert client._last_h3_try > 0

    @pytest.mark.asyncio
    async def test_mark_h3_failed_idempotent(self):
        cfg = ClientConfig(h3_enabled=True, base_url="http://localhost")
        client = H3Client(cfg)

        await client._mark_h3_failed()
        first_time = client._last_h3_try
        await client._mark_h3_failed()
        # Should not update since _use_h3 is already False
        assert client._last_h3_try == first_time

    @pytest.mark.asyncio
    async def test_maybe_retry_h3_too_soon(self):
        cfg = ClientConfig(
            h3_enabled=True,
            h3_retry_interval=300.0,
            base_url="http://localhost",
        )
        client = H3Client(cfg)
        client._h3_client = MagicMock()
        client._use_h3 = False
        client._last_h3_try = time.monotonic()

        await client._maybe_retry_h3()
        assert client._use_h3 is False  # Too soon

    @pytest.mark.asyncio
    async def test_maybe_retry_h3_after_interval(self):
        cfg = ClientConfig(
            h3_enabled=True,
            h3_retry_interval=1.0,
            base_url="http://localhost",
        )
        client = H3Client(cfg)
        client._h3_client = MagicMock()
        client._use_h3 = False
        client._last_h3_try = time.monotonic() - 2.0  # 2 seconds ago

        await client._maybe_retry_h3()
        assert client._use_h3 is True

    @pytest.mark.asyncio
    async def test_maybe_retry_h3_disabled(self):
        cfg = ClientConfig(h3_enabled=False, base_url="http://localhost")
        client = H3Client(cfg)
        client._use_h3 = False

        await client._maybe_retry_h3()
        assert client._use_h3 is False  # Should stay disabled

    @pytest.mark.asyncio
    async def test_maybe_retry_h3_no_client(self):
        cfg = ClientConfig(h3_enabled=True, base_url="http://localhost")
        client = H3Client(cfg)
        client._h3_client = None
        client._use_h3 = False

        await client._maybe_retry_h3()
        assert client._use_h3 is False  # No h3 client to retry with


class TestH3ClientActiveClient:
    """Tests for _active_client."""

    def test_returns_h3_when_available(self):
        cfg = ClientConfig(h3_enabled=True, base_url="http://localhost")
        client = H3Client(cfg)
        mock_h3 = MagicMock()
        client._h3_client = mock_h3
        client._use_h3 = True

        assert client._active_client() is mock_h3

    def test_returns_h2_when_h3_disabled(self):
        cfg = ClientConfig(h3_enabled=False, base_url="http://localhost")
        client = H3Client(cfg)
        mock_h2 = MagicMock()
        client._h2_client = mock_h2

        assert client._active_client() is mock_h2

    def test_raises_when_not_initialized(self):
        cfg = ClientConfig(h3_enabled=False, base_url="http://localhost")
        client = H3Client(cfg)

        with pytest.raises(H3ClientError, match="Client not initialized"):
            client._active_client()

    def test_returns_h2_when_h3_none(self):
        cfg = ClientConfig(h3_enabled=True, base_url="http://localhost")
        client = H3Client(cfg)
        client._use_h3 = True
        client._h3_client = None
        mock_h2 = MagicMock()
        client._h2_client = mock_h2

        assert client._active_client() is mock_h2


class TestH3ClientRequest:
    """Tests for request method and HTTP verb helpers."""

    @pytest.mark.asyncio
    async def test_request_h2_only(self):
        cfg = ClientConfig(h3_enabled=False, base_url="http://localhost")
        client = H3Client(cfg)

        mock_h2 = AsyncMock()
        mock_response = MagicMock(spec=httpx.Response)
        mock_h2.request = AsyncMock(return_value=mock_response)
        client._h2_client = mock_h2

        with patch.object(client, "_ensure_clients", new_callable=AsyncMock):
            with patch.object(client, "_maybe_retry_h3", new_callable=AsyncMock):
                result = await client.request("GET", "/test")
                assert result is mock_response
                mock_h2.request.assert_called_once_with("GET", "/test")

    @pytest.mark.asyncio
    async def test_request_h3_fallback_on_error(self):
        cfg = ClientConfig(h3_enabled=True, base_url="http://localhost")
        client = H3Client(cfg)
        client._use_h3 = True

        mock_h3 = AsyncMock()
        mock_h3.request = AsyncMock(side_effect=ConnectionError("h3 fail"))
        client._h3_client = mock_h3

        mock_h2 = AsyncMock()
        mock_response = MagicMock(spec=httpx.Response)
        mock_h2.request = AsyncMock(return_value=mock_response)
        client._h2_client = mock_h2

        with patch.object(client, "_ensure_clients", new_callable=AsyncMock):
            with patch.object(client, "_maybe_retry_h3", new_callable=AsyncMock):
                result = await client.request("GET", "/test")
                assert result is mock_response
                assert client._use_h3 is False

    @pytest.mark.asyncio
    async def test_request_no_client_raises(self):
        cfg = ClientConfig(h3_enabled=False, base_url="http://localhost")
        client = H3Client(cfg)
        client._h2_client = None

        with patch.object(client, "_ensure_clients", new_callable=AsyncMock):
            with patch.object(client, "_maybe_retry_h3", new_callable=AsyncMock):
                with pytest.raises(H3ClientError, match="No HTTP client available"):
                    await client.request("GET", "/test")

    @pytest.mark.asyncio
    async def test_get(self):
        cfg = ClientConfig(h3_enabled=False, base_url="http://localhost")
        client = H3Client(cfg)

        mock_response = MagicMock(spec=httpx.Response)
        with patch.object(client, "request", new_callable=AsyncMock, return_value=mock_response):
            result = await client.get("/test")
            client.request.assert_called_once_with("GET", "/test")
            assert result is mock_response

    @pytest.mark.asyncio
    async def test_post(self):
        cfg = ClientConfig(h3_enabled=False, base_url="http://localhost")
        client = H3Client(cfg)

        mock_response = MagicMock(spec=httpx.Response)
        with patch.object(client, "request", new_callable=AsyncMock, return_value=mock_response):
            result = await client.post("/test", json={"key": "val"})
            client.request.assert_called_once_with("POST", "/test", json={"key": "val"})

    @pytest.mark.asyncio
    async def test_put(self):
        cfg = ClientConfig(h3_enabled=False, base_url="http://localhost")
        client = H3Client(cfg)

        mock_response = MagicMock(spec=httpx.Response)
        with patch.object(client, "request", new_callable=AsyncMock, return_value=mock_response):
            result = await client.put("/test")
            client.request.assert_called_once_with("PUT", "/test")

    @pytest.mark.asyncio
    async def test_delete(self):
        cfg = ClientConfig(h3_enabled=False, base_url="http://localhost")
        client = H3Client(cfg)

        mock_response = MagicMock(spec=httpx.Response)
        with patch.object(client, "request", new_callable=AsyncMock, return_value=mock_response):
            result = await client.delete("/test")
            client.request.assert_called_once_with("DELETE", "/test")

    @pytest.mark.asyncio
    async def test_request_h3_success(self):
        """Test that H3 is used when available and working."""
        cfg = ClientConfig(h3_enabled=True, base_url="http://localhost")
        client = H3Client(cfg)
        client._use_h3 = True

        mock_h3 = AsyncMock()
        mock_response = MagicMock(spec=httpx.Response)
        mock_h3.request = AsyncMock(return_value=mock_response)
        client._h3_client = mock_h3
        client._h2_client = AsyncMock()

        with patch.object(client, "_ensure_clients", new_callable=AsyncMock):
            with patch.object(client, "_maybe_retry_h3", new_callable=AsyncMock):
                result = await client.request("GET", "/data")
                assert result is mock_response
                mock_h3.request.assert_called_once()


class TestH3ClientClose:
    """Tests for close method."""

    @pytest.mark.asyncio
    async def test_close_both_clients(self):
        cfg = ClientConfig(h3_enabled=True, base_url="http://localhost")
        client = H3Client(cfg)

        mock_h2 = AsyncMock()
        mock_h3 = AsyncMock()
        client._h2_client = mock_h2
        client._h3_client = mock_h3

        await client.close()
        mock_h2.aclose.assert_called_once()
        mock_h3.aclose.assert_called_once()
        assert client._h2_client is None
        assert client._h3_client is None

    @pytest.mark.asyncio
    async def test_close_none_clients(self):
        cfg = ClientConfig(base_url="http://localhost")
        client = H3Client(cfg)

        await client.close()  # Should not raise

    @pytest.mark.asyncio
    async def test_close_h2_only(self):
        cfg = ClientConfig(h3_enabled=False, base_url="http://localhost")
        client = H3Client(cfg)

        mock_h2 = AsyncMock()
        client._h2_client = mock_h2
        client._h3_client = None

        await client.close()
        mock_h2.aclose.assert_called_once()


class TestH3ClientContextManager:
    """Tests for async context manager."""

    @pytest.mark.asyncio
    async def test_aenter_aexit(self):
        cfg = ClientConfig(h3_enabled=False, base_url="http://localhost")
        client = H3Client(cfg)

        with patch.object(client, "_ensure_clients", new_callable=AsyncMock):
            with patch.object(client, "close", new_callable=AsyncMock) as mock_close:
                async with client as c:
                    assert c is client
                mock_close.assert_called_once()
