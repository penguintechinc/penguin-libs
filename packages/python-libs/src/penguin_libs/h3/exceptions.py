"""Exception hierarchy for the H3 package."""

from __future__ import annotations


class H3Error(Exception):
    """Base exception for all H3 package errors."""


class H3ConfigError(H3Error):
    """Raised for configuration errors."""


class H3TLSError(H3Error):
    """Raised for TLS-related errors."""


class H3ServerError(H3Error):
    """Raised for server-side errors."""


class H3ClientError(H3Error):
    """Raised for client-side errors."""


class ProtocolFallbackError(H3Error):
    """Raised when HTTP/3 fails and client falls back to HTTP/2."""

    def __init__(self, original_error: Exception, protocol: str = "h2") -> None:
        self.original_error = original_error
        self.fallback_protocol = protocol
        super().__init__(
            f"HTTP/3 failed ({original_error}), fell back to {protocol}"
        )
