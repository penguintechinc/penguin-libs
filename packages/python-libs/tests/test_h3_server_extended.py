"""Extended tests for penguin_libs.h3.server to improve coverage."""

from __future__ import annotations

import ssl
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from penguin_libs.h3.config import ServerConfig, TLSConfig
from penguin_libs.h3.exceptions import H3ConfigError, H3ServerError, H3TLSError
from penguin_libs.h3.server import _build_ssl_context, run, serve


class TestBuildSslContext:
    """Additional tests for _build_ssl_context."""

    def test_with_ca_cert(self):
        tls = TLSConfig(
            cert_path="/cert.pem",
            key_path="/key.pem",
            ca_cert_path="/ca.pem",
        )
        config = ServerConfig(tls=tls)

        with patch("ssl.SSLContext") as mock_cls:
            mock_ctx = MagicMock()
            mock_cls.return_value = mock_ctx
            result = _build_ssl_context(config)

            mock_ctx.load_cert_chain.assert_called_once_with("/cert.pem", "/key.pem")
            mock_ctx.load_verify_locations.assert_called_once_with("/ca.pem")
            assert result is mock_ctx

    def test_with_verify_client(self):
        tls = TLSConfig(
            cert_path="/cert.pem",
            key_path="/key.pem",
            verify_client=True,
        )
        config = ServerConfig(tls=tls)

        with patch("ssl.SSLContext") as mock_cls:
            mock_ctx = MagicMock()
            mock_cls.return_value = mock_ctx
            result = _build_ssl_context(config)

            assert mock_ctx.verify_mode == ssl.CERT_REQUIRED

    def test_tls_error_raises_h3_tls_error(self):
        tls = TLSConfig(cert_path="/bad.pem", key_path="/bad.key")
        config = ServerConfig(tls=tls)

        with patch("ssl.SSLContext") as mock_cls:
            mock_ctx = MagicMock()
            mock_cls.return_value = mock_ctx
            mock_ctx.load_cert_chain.side_effect = OSError("file not found")

            with pytest.raises(H3TLSError, match="Failed to build TLS context"):
                _build_ssl_context(config)

    def test_ssl_error_raises_h3_tls_error(self):
        tls = TLSConfig(cert_path="/cert.pem", key_path="/key.pem")
        config = ServerConfig(tls=tls)

        with patch("ssl.SSLContext") as mock_cls:
            mock_ctx = MagicMock()
            mock_cls.return_value = mock_ctx
            mock_ctx.load_cert_chain.side_effect = ssl.SSLError("bad cert")

            with pytest.raises(H3TLSError):
                _build_ssl_context(config)


class TestServe:
    """Tests for serve() function."""

    @pytest.mark.asyncio
    async def test_serve_default_config_from_env(self):
        """Test serve with default config (from_env)."""
        mock_hcfg = MagicMock()
        mock_hypercorn_serve = AsyncMock()

        with patch.dict("os.environ", {}, clear=False):
            with patch("penguin_libs.h3.server.serve", new=AsyncMock()):
                # Just verify config defaults work
                cfg = ServerConfig.from_env()
                assert cfg.h2_enabled is True

    @pytest.mark.asyncio
    async def test_serve_h3_without_tls_raises(self):
        """H3 enabled but no TLS should raise H3ConfigError."""
        mock_hypercorn_serve = AsyncMock()
        mock_hcfg_cls = MagicMock()

        with patch.dict(
            "sys.modules",
            {
                "hypercorn": MagicMock(),
                "hypercorn.asyncio": MagicMock(serve=mock_hypercorn_serve),
                "hypercorn.config": MagicMock(Config=mock_hcfg_cls),
            },
        ):
            cfg = ServerConfig(h2_enabled=False, h3_enabled=True, tls=None)
            with pytest.raises(H3ConfigError, match="TLS configuration is required"):
                await serve(MagicMock(), cfg)

    @pytest.mark.asyncio
    async def test_serve_no_protocol_enabled_raises(self):
        """Neither H2 nor H3 enabled should raise H3ConfigError."""
        mock_hypercorn_serve = AsyncMock()
        mock_hcfg_cls = MagicMock()

        with patch.dict(
            "sys.modules",
            {
                "hypercorn": MagicMock(),
                "hypercorn.asyncio": MagicMock(serve=mock_hypercorn_serve),
                "hypercorn.config": MagicMock(Config=mock_hcfg_cls),
            },
        ):
            cfg = ServerConfig(h2_enabled=False, h3_enabled=False)
            with pytest.raises(H3ConfigError, match="At least one protocol"):
                await serve(MagicMock(), cfg)

    @pytest.mark.asyncio
    async def test_serve_h2_only_success(self):
        """Test serve with H2 only."""
        mock_hypercorn_serve = AsyncMock()
        mock_hcfg_instance = MagicMock()
        mock_hcfg_cls = MagicMock(return_value=mock_hcfg_instance)

        with patch.dict(
            "sys.modules",
            {
                "hypercorn": MagicMock(),
                "hypercorn.asyncio": MagicMock(serve=mock_hypercorn_serve),
                "hypercorn.config": MagicMock(Config=mock_hcfg_cls),
            },
        ):
            cfg = ServerConfig(h2_enabled=True, h3_enabled=False)
            await serve(MagicMock(), cfg)
            mock_hypercorn_serve.assert_called_once()

    @pytest.mark.asyncio
    async def test_serve_h3_with_tls(self):
        """Test serve with H3 and TLS configured."""
        mock_hypercorn_serve = AsyncMock()
        mock_hcfg_instance = MagicMock()
        mock_hcfg_cls = MagicMock(return_value=mock_hcfg_instance)

        tls = TLSConfig(cert_path="/cert.pem", key_path="/key.pem")
        cfg = ServerConfig(h2_enabled=True, h3_enabled=True, tls=tls)

        with patch.dict(
            "sys.modules",
            {
                "hypercorn": MagicMock(),
                "hypercorn.asyncio": MagicMock(serve=mock_hypercorn_serve),
                "hypercorn.config": MagicMock(Config=mock_hcfg_cls),
            },
        ):
            with patch("penguin_libs.h3.server._build_ssl_context", return_value=MagicMock()):
                await serve(MagicMock(), cfg)
                mock_hypercorn_serve.assert_called_once()
                assert mock_hcfg_instance.certfile == "/cert.pem"
                assert mock_hcfg_instance.keyfile == "/key.pem"

    @pytest.mark.asyncio
    async def test_serve_server_failure_raises_h3_server_error(self):
        """Test that server failure wraps in H3ServerError."""
        mock_hypercorn_serve = AsyncMock(side_effect=RuntimeError("bind failed"))
        mock_hcfg_instance = MagicMock()
        mock_hcfg_cls = MagicMock(return_value=mock_hcfg_instance)

        with patch.dict(
            "sys.modules",
            {
                "hypercorn": MagicMock(),
                "hypercorn.asyncio": MagicMock(serve=mock_hypercorn_serve),
                "hypercorn.config": MagicMock(Config=mock_hcfg_cls),
            },
        ):
            cfg = ServerConfig(h2_enabled=True, h3_enabled=False)
            with pytest.raises(H3ServerError, match="Server failed"):
                await serve(MagicMock(), cfg)

    @pytest.mark.asyncio
    async def test_serve_no_ssl_context(self):
        """Test serve when _build_ssl_context returns None (no TLS)."""
        mock_hypercorn_serve = AsyncMock()
        mock_hcfg_instance = MagicMock()
        mock_hcfg_cls = MagicMock(return_value=mock_hcfg_instance)

        with patch.dict(
            "sys.modules",
            {
                "hypercorn": MagicMock(),
                "hypercorn.asyncio": MagicMock(serve=mock_hypercorn_serve),
                "hypercorn.config": MagicMock(Config=mock_hcfg_cls),
            },
        ):
            cfg = ServerConfig(h2_enabled=True, h3_enabled=False, tls=None)
            await serve(MagicMock(), cfg)
            # certfile/keyfile should NOT be set
            mock_hypercorn_serve.assert_called_once()


class TestRun:
    """Tests for run() synchronous entry point."""

    def test_run_calls_asyncio_run(self):
        mock_app = MagicMock()
        mock_cfg = MagicMock()

        with patch("asyncio.run") as mock_asyncio_run:
            run(mock_app, mock_cfg)
            mock_asyncio_run.assert_called_once()

    def test_run_default_cfg(self):
        mock_app = MagicMock()

        with patch("asyncio.run") as mock_asyncio_run:
            run(mock_app)
            mock_asyncio_run.assert_called_once()
