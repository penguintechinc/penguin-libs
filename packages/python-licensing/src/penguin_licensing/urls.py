"""Shared URL validation for license server endpoints.

Single source of truth for the transport rules both client implementations
apply, so the TLS posture cannot drift between them.
"""

from urllib.parse import urlparse

# Loopback hosts are exempt from the HTTPS requirement so a developer can point
# a client at a local license server stub without terminating TLS.
_LOOPBACK_HOSTS = frozenset({"localhost", "127.0.0.1", "::1"})


def require_https_url(url: str) -> str:
    """Return ``url`` unchanged if it is safe to send license traffic to.

    Enforces HTTPS for every non-loopback host; license keys travel in the
    Authorization header, so plaintext to a remote host is never acceptable.

    Raises:
        ValueError: If a non-loopback URL does not use the https scheme.
    """
    parsed = urlparse(url)
    if parsed.scheme == "https":
        return url
    if parsed.hostname in _LOOPBACK_HOSTS:
        return url
    raise ValueError(f"License server URL must use HTTPS: {url}")


__all__ = ["require_https_url"]
