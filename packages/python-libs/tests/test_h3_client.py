"""Tests for penguin_libs.h3.client module."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from penguin_libs.h3.client import H3Client
from penguin_libs.h3.config import ClientConfig
from penguin_libs.h3.protocol import Protocol


def test_client_default_protocol():
    """Test that H3Client defaults to HTTP/3 when enabled."""
    client = H3Client()
    assert client.protocol == Protocol.H3


def test_client_h2_only():
    """Test that H3Client uses HTTP/2 when H3 is disabled."""
    config = ClientConfig(h3_enabled=False)
    client = H3Client(config)
    assert client.protocol == Protocol.H2


@pytest.mark.asyncio
async def test_client_context_manager():
    """Test that H3Client works as async context manager."""
    config = ClientConfig(h3_enabled=False, base_url="http://localhost")
    client = H3Client(config)

    # Mock _ensure_clients to avoid real HTTP connections
    with patch.object(client, '_ensure_clients', new_callable=AsyncMock):
        # Mock close to track it was called
        with patch.object(client, 'close', new_callable=AsyncMock) as mock_close:
            async with client as c:
                assert c is client
            mock_close.assert_called_once()


@pytest.mark.asyncio
async def test_client_fallback_on_h3_import_error():
    """Test that H3Client falls back to HTTP/2 if httpx_h3 import fails."""
    config = ClientConfig(h3_enabled=True, base_url="http://localhost")
    client = H3Client(config)

    # Simulate the _ensure_clients path where httpx_h3 import fails
    # by directly calling the method with a patched import
    with patch.dict('sys.modules', {'httpx_h3': None}):
        with patch('httpx.AsyncClient') as mock_async_client:
            mock_async_client.return_value = AsyncMock()
            await client._ensure_clients()

    # After import failure, h3 should be disabled
    assert client._use_h3 is False
    assert client.protocol == Protocol.H2
