"""gRPC server interceptor for rate limiting.

Compatible with ``grpcio >= 1.60``.  Add to your server::

    from grpc import server as grpc_server
    from penguin_limiter.middleware.grpc import GrpcRateLimitInterceptor
    from penguin_limiter.config import RateLimitConfig
    from penguin_limiter.storage.memory import MemoryStorage

    interceptor = GrpcRateLimitInterceptor(
        config=RateLimitConfig.from_string("500/minute"),
        storage=MemoryStorage(),
    )
    srv = grpc_server(futures.ThreadPoolExecutor(), interceptors=[interceptor])

IP extraction
-------------
gRPC metadata does not automatically propagate HTTP headers.  The interceptor
reads them in this priority order:

1. ``x-forwarded-for`` metadata key (set by an ingress / envoy proxy)
2. ``x-real-ip`` metadata key
3. ``servicer_context.peer()`` — the TCP peer address (``ipv4:1.2.3.4:port``
   or ``ipv6:[::1]:port``)

The ``skip_private_ips`` flag in :class:`~penguin_limiter.config.RateLimitConfig`
controls whether internal IPs bypass rate limiting (default: ``True``).
Set ``skip_private_ips=False`` to enforce limits regardless of source.
"""

from __future__ import annotations

import re
from typing import Any, Callable

from ..algorithms.fixed_window import FixedWindow
from ..algorithms.sliding_window import SlidingWindow
from ..algorithms.token_bucket import TokenBucket
from ..config import Algorithm, RateLimitConfig
from ..ip import should_rate_limit
from ..storage import RateLimitStorage

_PEER_RE = re.compile(r"^(?:ipv[46]:)?\[?([^\]]+)\]?(?::\d+)?$")


def _peer_to_ip(peer: str) -> str:
    """Extract bare IP from a gRPC peer string like ``ipv4:1.2.3.4:50051``."""
    m = _PEER_RE.match(peer)
    if m:
        return m.group(1)
    return peer


def _build_algorithm(
    config: RateLimitConfig, storage: RateLimitStorage
) -> FixedWindow | SlidingWindow | TokenBucket:
    if config.algorithm == Algorithm.FIXED_WINDOW:
        return FixedWindow(storage, config.limit, config.window)
    if config.algorithm == Algorithm.TOKEN_BUCKET:
        return TokenBucket(storage, config.limit, config.window)
    return SlidingWindow(storage, config.limit, config.window)


class GrpcRateLimitInterceptor:
    """gRPC ``ServerInterceptor`` that enforces rate limits per client IP.

    Parameters
    ----------
    config:
        Rate-limit configuration.  ``skip_private_ips=True`` (default) means
        intra-cluster gRPC calls are never counted.
    storage:
        Storage backend.
    """

    def __init__(
        self,
        config: RateLimitConfig,
        storage: RateLimitStorage | None = None,
    ) -> None:
        if storage is None:
            from ..storage.memory import MemoryStorage
            storage = MemoryStorage()
        self._config = config
        self._algo = _build_algorithm(config, storage)

    def intercept_service(
        self,
        continuation: Callable[..., Any],
        handler_call_details: Any,
    ) -> Any:
        """Wrap each RPC handler with the rate-limit check."""
        handler = continuation(handler_call_details)
        if handler is None:
            return handler

        config = self._config
        algo = self._algo

        def rate_limit_wrapper(request: Any, context: Any) -> Any:
            # Extract IP from metadata then peer address
            metadata = dict(context.invocation_metadata())
            xff = metadata.get("x-forwarded-for")
            xri = metadata.get("x-real-ip")
            peer_ip = _peer_to_ip(context.peer()) if hasattr(context, "peer") else None

            if config.skip_private_ips:
                do_limit, client_ip = should_rate_limit(xff, xri, peer_ip)
                if not do_limit:
                    # Internal caller — pass through without counting
                    return handler.unary_unary(request, context)
            else:
                _, client_ip = should_rate_limit(xff, xri, peer_ip)
                do_limit = True

            key = f"{config.key_prefix}:{client_ip or peer_ip or 'unknown'}"

            try:
                result = algo.is_allowed(key)
            except Exception:
                if config.fail_open:
                    return handler.unary_unary(request, context)
                import grpc
                context.abort(grpc.StatusCode.UNAVAILABLE, "Rate limit service unavailable")
                return None

            if not result.allowed:
                import grpc
                context.abort(
                    grpc.StatusCode.RESOURCE_EXHAUSTED,
                    f"Rate limit exceeded. Try again in {int(result.reset_after)}s.",
                )
                return None

            return handler.unary_unary(request, context)

        try:
            import grpc
            return grpc.unary_unary_rpc_method_handler(
                rate_limit_wrapper,
                request_deserializer=getattr(handler, "request_deserializer", None),
                response_serializer=getattr(handler, "response_serializer", None),
            )
        except ImportError:
            return handler
