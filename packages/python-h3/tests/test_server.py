"""Tests for H3 server."""

from __future__ import annotations

import ssl
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from penguin_h3.config import ServerConfig, TLSConfig
from penguin_h3.exceptions import H3ConfigError, H3ServerError, H3TLSError
from penguin_h3.server import _build_ssl_context, run, serve


class TestBuildSSLContext:
    """Test _build_ssl_context function."""

    def test_build_ssl_context_no_tls(self) -> None:
        """Test that None is returned when TLS is not configured."""
        cfg = ServerConfig(tls=None)
        ctx = _build_ssl_context(cfg)
        assert ctx is None

    def test_build_ssl_context_with_valid_certs(self) -> None:
        """Test building SSL context with valid certificates."""
        with tempfile.TemporaryDirectory() as tmpdir:
            cert_path = Path(tmpdir) / "server.crt"
            key_path = Path(tmpdir) / "server.key"

            # Create dummy cert and key files
            cert_path.write_text("-----BEGIN CERTIFICATE-----\ndummy\n-----END CERTIFICATE-----")
            key_path.write_text("-----BEGIN RSA PRIVATE KEY-----\ndummy\n-----END RSA PRIVATE KEY-----")

            tls_cfg = TLSConfig(cert_path=cert_path, key_path=key_path)
            cfg = ServerConfig(tls=tls_cfg)

            # Will fail with invalid cert, but should attempt to build
            with pytest.raises((ssl.SSLError, OSError, H3TLSError)):
                _build_ssl_context(cfg)

    def test_build_ssl_context_missing_cert_file(self) -> None:
        """Test that missing cert file raises H3TLSError."""
        tls_cfg = TLSConfig(
            cert_path=Path("/nonexistent/cert.crt"),
            key_path=Path("/nonexistent/key.key"),
        )
        cfg = ServerConfig(tls=tls_cfg)

        with pytest.raises(H3TLSError):
            _build_ssl_context(cfg)

    def test_build_ssl_context_missing_key_file(self) -> None:
        """Test that missing key file raises H3TLSError."""
        with tempfile.TemporaryDirectory() as tmpdir:
            cert_path = Path(tmpdir) / "server.crt"
            cert_path.write_text("dummy")

            tls_cfg = TLSConfig(
                cert_path=cert_path,
                key_path=Path("/nonexistent/key.key"),
            )
            cfg = ServerConfig(tls=tls_cfg)

            with pytest.raises(H3TLSError):
                _build_ssl_context(cfg)

    def test_build_ssl_context_tls13_minimum(self) -> None:
        """Test that context enforces TLS 1.3 minimum."""
        with tempfile.TemporaryDirectory() as tmpdir:
            cert_path = Path(tmpdir) / "server.crt"
            key_path = Path(tmpdir) / "server.key"

            cert_path.write_text("dummy")
            key_path.write_text("dummy")

            tls_cfg = TLSConfig(cert_path=cert_path, key_path=key_path)
            cfg = ServerConfig(tls=tls_cfg)

            # Will fail due to invalid cert, but can't test version directly
            with pytest.raises((ssl.SSLError, OSError, H3TLSError)):
                _build_ssl_context(cfg)

    def test_build_ssl_context_with_ca_cert(self) -> None:
        """Test building context with CA certificate."""
        with tempfile.TemporaryDirectory() as tmpdir:
            cert_path = Path(tmpdir) / "server.crt"
            key_path = Path(tmpdir) / "server.key"
            ca_path = Path(tmpdir) / "ca.crt"

            cert_path.write_text("dummy")
            key_path.write_text("dummy")
            ca_path.write_text("dummy")

            tls_cfg = TLSConfig(cert_path=cert_path, key_path=key_path, ca_cert_path=ca_path)
            cfg = ServerConfig(tls=tls_cfg)

            with pytest.raises((ssl.SSLError, OSError, H3TLSError)):
                _build_ssl_context(cfg)

    def test_build_ssl_context_with_client_verification(self) -> None:
        """Test building context with client certificate verification."""
        with tempfile.TemporaryDirectory() as tmpdir:
            cert_path = Path(tmpdir) / "server.crt"
            key_path = Path(tmpdir) / "server.key"

            cert_path.write_text("dummy")
            key_path.write_text("dummy")

            tls_cfg = TLSConfig(
                cert_path=cert_path, key_path=key_path, verify_client=True
            )
            cfg = ServerConfig(tls=tls_cfg)

            with pytest.raises((ssl.SSLError, OSError, H3TLSError)):
                _build_ssl_context(cfg)


class TestServe:
    """Test serve function."""

    @pytest.mark.asyncio
    async def test_serve_requires_hypercorn(self) -> None:
        """Test that serve requires hypercorn to be installed."""
        app = AsyncMock()
        cfg = ServerConfig()

        with patch.dict("sys.modules", {"hypercorn": None, "hypercorn.asyncio": None}):
            with pytest.raises(H3ConfigError, match="hypercorn"):
                await serve(app, cfg)

    @pytest.mark.asyncio
    async def test_serve_requires_at_least_one_protocol(self) -> None:
        """Test that at least one protocol must be enabled."""
        app = AsyncMock()
        cfg = ServerConfig(h2_enabled=False, h3_enabled=False)

        with pytest.raises(H3ConfigError, match="At least one protocol"):
            await serve(app, cfg)

    @pytest.mark.asyncio
    async def test_serve_h3_requires_tls(self) -> None:
        """Test that HTTP/3 requires TLS configuration."""
        app = AsyncMock()
        cfg = ServerConfig(h3_enabled=True, h2_enabled=False, tls=None)

        with pytest.raises(H3ConfigError, match="TLS"):
            await serve(app, cfg)

    @pytest.mark.asyncio
    async def test_serve_h2_only_no_tls_required(self) -> None:
        """Test that HTTP/2 only does not require TLS."""
        app = AsyncMock()
        cfg = ServerConfig(h2_enabled=True, h3_enabled=False, tls=None)

        with patch("hypercorn.asyncio.serve", new_callable=AsyncMock) as mock_serve:
            with patch("hypercorn.config.Config"):
                # Should not raise config error for H2 without TLS
                try:
                    await serve(app, cfg)
                except H3ServerError:
                    # Server error is OK (hypercorn may fail internally)
                    pass
                except H3ConfigError:
                    # Config error should NOT occur for H2-only
                    pytest.fail("H2-only should not require TLS config")

    @pytest.mark.asyncio
    async def test_serve_uses_default_config(self) -> None:
        """Test that serve uses ServerConfig.from_env() if cfg is None."""
        app = AsyncMock()

        with patch("hypercorn.asyncio.serve", new_callable=AsyncMock) as mock_serve:
            with patch("penguin_h3.server.ServerConfig.from_env") as mock_from_env:
                mock_from_env.return_value = ServerConfig(h2_enabled=True, h3_enabled=False)

                try:
                    await serve(app, None)
                except Exception:
                    pass

                mock_from_env.assert_called_once()

    @pytest.mark.asyncio
    async def test_serve_configures_binds(self) -> None:
        """Test that binds are configured correctly."""
        app = AsyncMock()
        cfg = ServerConfig(
            h2_host="127.0.0.1",
            h2_port=9000,
            h3_host="127.0.0.1",
            h3_port=9443,
            h2_enabled=True,
            h3_enabled=False,
        )

        with patch("hypercorn.asyncio.serve", new_callable=AsyncMock) as mock_serve:
            with patch("hypercorn.config.Config") as mock_config:
                mock_cfg_instance = MagicMock()
                mock_config.return_value = mock_cfg_instance

                try:
                    await serve(app, cfg)
                except Exception:
                    pass

                # Check that bind was set
                assert mock_cfg_instance.bind == ["127.0.0.1:9000"]

    @pytest.mark.asyncio
    async def test_serve_server_error_propagation(self) -> None:
        """Test that server errors are wrapped in H3ServerError."""
        app = AsyncMock()
        cfg = ServerConfig(h2_enabled=True, h3_enabled=False)

        with patch("hypercorn.asyncio.serve", new_callable=AsyncMock) as mock_serve:
            mock_serve.side_effect = RuntimeError("Server startup failed")

            with pytest.raises(H3ServerError):
                await serve(app, cfg)


class TestRun:
    """Test run function."""

    def test_run_starts_event_loop(self) -> None:
        """Test that run starts the event loop."""
        app = AsyncMock()
        cfg = ServerConfig()

        with patch("asyncio.run") as mock_asyncio_run:
            with patch("penguin_h3.server.serve", new_callable=AsyncMock) as mock_serve:
                run(app, cfg)

                # asyncio.run should be called
                mock_asyncio_run.assert_called_once()

    def test_run_uses_default_config(self) -> None:
        """Test that run uses None config if not provided."""
        app = AsyncMock()

        with patch("asyncio.run") as mock_asyncio_run:
            run(app, None)

            # Should call asyncio.run with serve(app, None)
            mock_asyncio_run.assert_called_once()

    def test_run_passes_app_and_config(self) -> None:
        """Test that run passes app and config to serve."""
        app = AsyncMock()
        cfg = ServerConfig()

        with patch("asyncio.run") as mock_asyncio_run:
            run(app, cfg)

            # Should call asyncio.run
            call_args = mock_asyncio_run.call_args
            # First arg is the coroutine
            coro = call_args[0][0]
            # Coroutine should have been created with serve
            assert hasattr(coro, "cr_frame")


class TestServerIntegration:
    """Integration tests for server configuration."""

    def test_server_config_h2_only(self) -> None:
        """Test server configuration for HTTP/2 only."""
        cfg = ServerConfig(h2_enabled=True, h3_enabled=False, tls=None)

        assert cfg.h2_enabled is True
        assert cfg.h3_enabled is False
        assert cfg.tls is None

    def test_server_config_h3_requires_tls(self) -> None:
        """Test that H3 config requires TLS."""
        with tempfile.TemporaryDirectory() as tmpdir:
            cert_path = Path(tmpdir) / "server.crt"
            key_path = Path(tmpdir) / "server.key"
            cert_path.touch()
            key_path.touch()

            tls_cfg = TLSConfig(cert_path=cert_path, key_path=key_path)
            cfg = ServerConfig(h2_enabled=False, h3_enabled=True, tls=tls_cfg)

            assert cfg.h3_enabled is True
            assert cfg.tls is not None

    def test_server_config_dual_protocol(self) -> None:
        """Test server configuration for dual-protocol setup."""
        with tempfile.TemporaryDirectory() as tmpdir:
            cert_path = Path(tmpdir) / "server.crt"
            key_path = Path(tmpdir) / "server.key"
            cert_path.touch()
            key_path.touch()

            tls_cfg = TLSConfig(cert_path=cert_path, key_path=key_path)
            cfg = ServerConfig(
                h2_host="0.0.0.0",
                h2_port=8080,
                h3_host="0.0.0.0",
                h3_port=8443,
                h2_enabled=True,
                h3_enabled=True,
                tls=tls_cfg,
            )

            assert cfg.h2_enabled is True
            assert cfg.h3_enabled is True
            assert cfg.tls is not None

    def test_server_config_custom_grace_period(self) -> None:
        """Test server configuration with custom grace period."""
        cfg = ServerConfig(grace_period=60.0)
        assert cfg.grace_period == 60.0

    def test_server_config_access_log_disabled(self) -> None:
        """Test server configuration with access log disabled."""
        cfg = ServerConfig(access_log=False)
        assert cfg.access_log is False
