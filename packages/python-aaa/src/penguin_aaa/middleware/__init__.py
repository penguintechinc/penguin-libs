"""Middleware — ASGI and gRPC middleware for authentication, authorization, and auditing."""

from penguin_aaa.middleware.asgi import AuditMiddleware, OIDCAuthMiddleware, SPIFFEAuthMiddleware
from penguin_aaa.middleware.tenant import TenantMiddleware

__all__ = [
    "OIDCAuthMiddleware",
    "SPIFFEAuthMiddleware",
    "AuditMiddleware",
    "TenantMiddleware",
]

try:
    from penguin_aaa.middleware.grpc import OIDCAuthInterceptor  # noqa: F401

    __all__.append("OIDCAuthInterceptor")
except ImportError:
    pass
