"""gRPC server interceptors for OIDC authentication."""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

try:
    import grpc

    _GRPC_AVAILABLE = True
except ImportError:
    grpc = None  # type: ignore[assignment]
    _GRPC_AVAILABLE = False

logger = logging.getLogger(__name__)

_ServerInterceptorBase = grpc.ServerInterceptor if _GRPC_AVAILABLE else object


class OIDCAuthInterceptor(_ServerInterceptorBase):  # type: ignore[misc]
    """Validate OIDC Bearer tokens on incoming gRPC calls.

    Token validation is performed synchronously via the relying party's
    ``verify_token_sync`` method (or ``verify_token`` if the RP exposes
    it; callers should provide an adapter if only async verification is
    available).

    On success the interceptor delegates to the continuation. On failure
    it returns an UNAUTHENTICATED error handler without invoking the
    service implementation.

    Args:
        rp: An OIDC Relying Party object with a ``verify_token_sync(token)``
            method that raises on invalid tokens.
        public_methods: Fully-qualified gRPC method names (e.g.
            ``"/grpc.health.v1.Health/Check"``) that bypass authentication.
    """

    def __init__(self, rp: Any, public_methods: set[str] | None = None) -> None:
        self._rp = rp
        self._public_methods = public_methods or set()

    def intercept_service(
        self,
        continuation: Callable[[grpc.HandlerCallDetails], grpc.RpcMethodHandler],
        handler_call_details: grpc.HandlerCallDetails,
    ) -> grpc.RpcMethodHandler:
        """Intercept an incoming call and enforce token authentication."""
        method = handler_call_details.method
        if method in self._public_methods:
            return continuation(handler_call_details)

        metadata = dict(handler_call_details.invocation_metadata)
        auth_header = metadata.get("authorization", "")

        if not auth_header.startswith("Bearer "):
            logger.warning("gRPC call to %s rejected: missing Bearer token", method)
            return self._abort_handler(
                grpc.StatusCode.UNAUTHENTICATED,
                "Missing or invalid Authorization header",
            )

        token = auth_header[7:]
        try:
            self._rp.verify_token_sync(token)
        except Exception as exc:
            logger.warning("gRPC call to %s rejected: token invalid (%s)", method, exc)
            return self._abort_handler(
                grpc.StatusCode.UNAUTHENTICATED,
                "Token verification failed",
            )

        return continuation(handler_call_details)

    @staticmethod
    def _abort_handler(
        code: grpc.StatusCode,
        details: str,
    ) -> grpc.RpcMethodHandler:
        """Return an RPC handler that aborts the call with the given status."""

        def abort(request: Any, context: grpc.ServicerContext) -> None:
            context.abort(code, details)

        return grpc.unary_unary_rpc_method_handler(
            abort,
            request_deserializer=lambda x: x,
            response_serializer=lambda x: x,
        )
