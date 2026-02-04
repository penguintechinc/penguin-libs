"""ASGI server wrapper with HTTP/2 + HTTP/3 dual-protocol support.

Uses Hypercorn with aioquic for HTTP/3 transport.
Serves any ASGI application (Quart, FastAPI, Starlette, etc.).

Status: EXPERIMENTAL. Hypercorn HTTP/3 support is alpha-quality.
HTTP/2 serving is production-ready.
"""

from __future__ import annotations

import asyncio
import logging
import ssl
from typing import Any

from .config import ServerConfig
from .exceptions import H3ConfigError, H3ServerError, H3TLSError

logger = logging.getLogger(__name__)


def _build_ssl_context(cfg: ServerConfig) -> ssl.SSLContext | None:
    """Build an SSL context from server config."""
    if cfg.tls is None:
        return None
    try:
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        ctx.minimum_version = ssl.TLSVersion.TLSv1_3
        ctx.load_cert_chain(str(cfg.tls.cert_path), str(cfg.tls.key_path))
        if cfg.tls.ca_cert_path:
            ctx.load_verify_locations(str(cfg.tls.ca_cert_path))
        if cfg.tls.verify_client:
            ctx.verify_mode = ssl.CERT_REQUIRED
        return ctx
    except (OSError, ssl.SSLError) as exc:
        raise H3TLSError(f"Failed to build TLS context: {exc}") from exc


async def serve(app: Any, cfg: ServerConfig | None = None) -> None:
    """Start a dual-protocol ASGI server.

    Args:
        app: An ASGI application (Quart, FastAPI, etc.).
        cfg: Server configuration. Defaults to ServerConfig.from_env().

    Raises:
        H3ConfigError: If the configuration is invalid.
        H3ServerError: If the server fails to start.
    """
    try:
        from hypercorn.asyncio import serve as hypercorn_serve
        from hypercorn.config import Config as HypercornConfig
    except ImportError as exc:
        raise H3ConfigError(
            "hypercorn is required for H3 server. "
            "Install with: pip install 'penguin-libs[h3]'"
        ) from exc

    if cfg is None:
        cfg = ServerConfig.from_env()

    hcfg = HypercornConfig()
    binds: list[str] = []
    if cfg.h2_enabled:
        binds.append(f"{cfg.h2_host}:{cfg.h2_port}")
    if cfg.h3_enabled:
        if cfg.tls is None:
            raise H3ConfigError("TLS configuration is required for HTTP/3")
        binds.append(f"{cfg.h3_host}:{cfg.h3_port}")
        hcfg.quic_bind = [f"{cfg.h3_host}:{cfg.h3_port}"]

    if not binds:
        raise H3ConfigError("At least one protocol (H2 or H3) must be enabled")

    hcfg.bind = binds
    hcfg.graceful_timeout = cfg.grace_period
    hcfg.accesslog = logger if cfg.access_log else None

    ssl_ctx = _build_ssl_context(cfg)
    if ssl_ctx is not None:
        hcfg.certfile = str(cfg.tls.cert_path)  # type: ignore[union-attr]
        hcfg.keyfile = str(cfg.tls.key_path)  # type: ignore[union-attr]

    logger.info(
        "Starting H3 server",
        extra={"binds": binds, "h2": cfg.h2_enabled, "h3": cfg.h3_enabled},
    )

    try:
        await hypercorn_serve(app, hcfg)  # type: ignore[arg-type]
    except Exception as exc:
        raise H3ServerError(f"Server failed: {exc}") from exc


def run(app: Any, cfg: ServerConfig | None = None) -> None:
    """Synchronous entry point for serve(). Runs the event loop.

    Args:
        app: An ASGI application.
        cfg: Server configuration.
    """
    asyncio.run(serve(app, cfg))
