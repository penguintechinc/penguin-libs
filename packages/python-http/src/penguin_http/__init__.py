"""
HTTP module - HTTP utilities.

Provides:
- correlation: Request ID/correlation middleware
- client: Resilient HTTP client with retries
- flask: Flask utilities (response envelopes, pagination)
- grpc: gRPC utilities (server, client, interceptors)
- h3: HTTP/3 QUIC streaming support
"""

from .client import (
    CircuitBreakerConfig,
    CircuitState,
    HTTPClient,
    HTTPClientConfig,
    RetryConfig,
)
from .correlation import (
    CorrelationMiddleware,
    generate_correlation_id,
    get_correlation_id,
)
from .flask import (
    error_response,
    get_pagination_params,
    paginate,
    success_response,
)
from .grpc import (
    create_server,
    register_health_check,
    GrpcClient,
    AuthInterceptor,
    RateLimitInterceptor,
    AuditInterceptor,
    CorrelationInterceptor,
    RecoveryInterceptor,
)
from .h3 import (
    ClientConfig,
    ServerConfig,
    Protocol,
    H3Error,
    H3ConfigError,
    H3TLSError,
    H3ServerError,
    H3ClientError,
    ProtocolFallbackError,
)

__all__ = [
    # Correlation ID utilities
    "CorrelationMiddleware",
    "generate_correlation_id",
    "get_correlation_id",
    # HTTP client
    "HTTPClient",
    "HTTPClientConfig",
    "RetryConfig",
    "CircuitBreakerConfig",
    "CircuitState",
    # Flask utilities
    "error_response",
    "get_pagination_params",
    "paginate",
    "success_response",
    # gRPC utilities
    "create_server",
    "register_health_check",
    "GrpcClient",
    "AuthInterceptor",
    "RateLimitInterceptor",
    "AuditInterceptor",
    "CorrelationInterceptor",
    "RecoveryInterceptor",
    # H3 utilities
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
