"""Configuration dataclasses for H3 server and client."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path


@dataclass(slots=True, frozen=True)
class TLSConfig:
    """TLS configuration for HTTP/3 (TLS 1.3 required by QUIC)."""

    cert_path: Path
    key_path: Path
    ca_cert_path: Path | None = None
    verify_client: bool = False


@dataclass(slots=True, frozen=True)
class ServerConfig:
    """Configuration for the dual-protocol HTTP/2 + HTTP/3 server.

    HTTP/3 requires TLS. If tls is None, only HTTP/2 (plaintext) will be served.
    """

    h2_host: str = "0.0.0.0"
    h2_port: int = 8080
    h3_host: str = "0.0.0.0"
    h3_port: int = 8443
    h2_enabled: bool = True
    h3_enabled: bool = True
    tls: TLSConfig | None = None
    grace_period: float = 30.0
    access_log: bool = True

    @staticmethod
    def from_env() -> ServerConfig:
        """Create ServerConfig from environment variables.

        Recognized vars: H2_PORT, H3_PORT, H2_ENABLED, H3_ENABLED,
        TLS_CERT_PATH, TLS_KEY_PATH, TLS_CA_CERT_PATH.
        """
        tls_cfg = None
        cert_path = os.environ.get("TLS_CERT_PATH")
        key_path = os.environ.get("TLS_KEY_PATH")
        if cert_path and key_path:
            tls_cfg = TLSConfig(
                cert_path=Path(cert_path),
                key_path=Path(key_path),
                ca_cert_path=(
                    Path(v) if (v := os.environ.get("TLS_CA_CERT_PATH")) else None
                ),
            )

        return ServerConfig(
            h2_port=int(os.environ.get("H2_PORT", "8080")),
            h3_port=int(os.environ.get("H3_PORT", "8443")),
            h2_enabled=os.environ.get("H2_ENABLED", "true").lower() != "false",
            h3_enabled=os.environ.get("H3_ENABLED", "true").lower() != "false",
            tls=tls_cfg,
        )


@dataclass(slots=True, frozen=True)
class RetryConfig:
    """Retry configuration with exponential backoff."""

    max_retries: int = 3
    initial_backoff: float = 0.1
    max_backoff: float = 5.0
    multiplier: float = 2.0
    jitter: bool = True


@dataclass(slots=True, frozen=True)
class ClientConfig:
    """Configuration for the HTTP/3 client with HTTP/2 fallback.

    The client tries HTTP/3 first. If it fails, it falls back to HTTP/2
    and periodically re-attempts HTTP/3 after h3_retry_interval seconds.
    """

    base_url: str = ""
    tls: TLSConfig | None = None
    h3_enabled: bool = True
    h3_timeout: float = 5.0
    h3_retry_interval: float = 300.0
    request_timeout: float = 30.0
    verify_ssl: bool = True
    retry: RetryConfig = field(default_factory=RetryConfig)
    headers: dict[str, str] = field(default_factory=dict)
