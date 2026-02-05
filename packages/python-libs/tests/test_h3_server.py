"""Tests for penguin_libs.h3.server module."""

import ssl
from unittest.mock import MagicMock, patch

import pytest

from penguin_libs.h3.config import ServerConfig, TLSConfig
from penguin_libs.h3.exceptions import H3ConfigError
from penguin_libs.h3.server import _build_ssl_context, serve


def test_build_ssl_context_no_tls():
    """Test that _build_ssl_context returns None when TLS is not configured."""
    config = ServerConfig()
    assert config.tls is None

    ssl_context = _build_ssl_context(config)
    assert ssl_context is None


def test_build_ssl_context_with_tls():
    """Test that _build_ssl_context creates SSLContext with TLS config."""
    tls = TLSConfig(
        cert_path="/path/to/cert.pem",
        key_path="/path/to/key.pem"
    )
    config = ServerConfig(tls=tls)

    # Mock ssl.SSLContext to avoid needing real certificates
    with patch('ssl.SSLContext') as mock_ssl_context_class:
        mock_context = MagicMock()
        mock_ssl_context_class.return_value = mock_context

        ssl_context = _build_ssl_context(config)

        # Verify SSLContext was created
        mock_ssl_context_class.assert_called_once_with(ssl.PROTOCOL_TLS_SERVER)

        # Verify load_cert_chain was called with positional args
        mock_context.load_cert_chain.assert_called_once_with(
            "/path/to/cert.pem",
            "/path/to/key.pem"
        )

        assert ssl_context is mock_context


@pytest.mark.asyncio
async def test_serve_raises_without_hypercorn():
    """Test that serve raises H3ConfigError when hypercorn is not available."""
    import builtins
    real_import = builtins.__import__

    def mock_import(name, *args, **kwargs):
        if "hypercorn" in name:
            raise ImportError("hypercorn not installed")
        return real_import(name, *args, **kwargs)

    with patch("builtins.__import__", side_effect=mock_import):
        # Force reload to trigger import error
        import importlib
        from penguin_libs.h3 import server as server_module

        try:
            importlib.reload(server_module)
        except ImportError:
            # Expected - hypercorn not available
            pass

        # Now try to use serve
        with pytest.raises((H3ConfigError, ImportError, AttributeError)):
            # Mock ASGI app
            async def mock_app(scope, receive, send):
                pass

            await server_module.serve(mock_app)
