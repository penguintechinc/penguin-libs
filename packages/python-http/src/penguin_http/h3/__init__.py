"""
HTTP/3 QUIC streaming library for Penguin Tech applications.

Provides HTTP/3 server and client with automatic HTTP/2 fallback.
Built on Hypercorn + aioquic (server) and httpx + aioquic (client).

Status: EXPERIMENTAL - HTTP/3 support relies on alpha-quality libraries.
For production workloads, use the Go implementation (packages/go-h3).
HTTP/2 fallback is always available and production-ready.
"""

from __future__ import annotations

from .config import ClientConfig, ServerConfig
from .exceptions import (
    H3ClientError,
    H3ConfigError,
    H3Error,
    H3ServerError,
    H3TLSError,
    ProtocolFallbackError,
)
from .protocol import Protocol

__all__ = [
    "ClientConfig",
    "ServerConfig",
    "Protocol",
    "H3Error",
    "H3ConfigError",
    "H3TLSError",
    "H3ServerError",
    "H3ClientError",
    "ProtocolFallbackError",
]
