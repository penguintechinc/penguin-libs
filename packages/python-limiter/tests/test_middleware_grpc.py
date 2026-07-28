"""Tests for GrpcRateLimitInterceptor."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from penguin_limiter.config import RateLimitConfig
from penguin_limiter.middleware.grpc import GrpcRateLimitInterceptor, _peer_to_ip
from penguin_limiter.storage.memory import MemoryStorage


class TestPeerToIp:
    @pytest.mark.parametrize("peer,expected", [
        ("ipv4:1.2.3.4:50051", "1.2.3.4"),
        ("ipv6:[::1]:50051", "::1"),
        ("1.2.3.4:50051", "1.2.3.4"),
        ("1.2.3.4", "1.2.3.4"),
    ])
    def test_extracts_ip(self, peer: str, expected: str) -> None:
        assert _peer_to_ip(peer) == expected


class TestGrpcRateLimitInterceptor:
    def _make_context(
        self,
        peer: str = "ipv4:1.2.3.4:50051",
        metadata: dict | None = None,
    ) -> MagicMock:
        ctx = MagicMock()
        ctx.peer.return_value = peer
        ctx.invocation_metadata.return_value = list((metadata or {}).items())
        return ctx

    def _make_handler(self) -> MagicMock:
        handler = MagicMock()
        handler.unary_unary = MagicMock(return_value="response")
        handler.request_deserializer = None
        handler.response_serializer = None
        return handler

    def test_within_limit_passes_through(self) -> None:
        storage = MemoryStorage()
        interceptor = GrpcRateLimitInterceptor(
            config=RateLimitConfig.from_string("5/minute"),
            storage=storage,
        )
        handler = self._make_handler()
        ctx = self._make_context()

        try:
            import grpc
            wrapped = interceptor.intercept_service(lambda _: handler, MagicMock())
            wrapped.unary_unary(MagicMock(), ctx)
            handler.unary_unary.assert_called_once()
        except ImportError:
            pytest.skip("grpcio not installed")

    def test_private_ip_bypasses_limit(self) -> None:
        storage = MemoryStorage()
        interceptor = GrpcRateLimitInterceptor(
            config=RateLimitConfig.from_string("1/minute"),  # very tight
            storage=storage,
        )
        handler = self._make_handler()
        ctx = self._make_context(peer="ipv4:192.168.1.1:50051")

        try:
            import grpc
            wrapped = interceptor.intercept_service(lambda _: handler, MagicMock())
            # Call 5 times — private IP should always pass
            for _ in range(5):
                wrapped.unary_unary(MagicMock(), ctx)
            assert handler.unary_unary.call_count == 5
        except ImportError:
            pytest.skip("grpcio not installed")

    def test_exceeds_limit_aborts_with_resource_exhausted(self) -> None:
        storage = MemoryStorage()
        interceptor = GrpcRateLimitInterceptor(
            config=RateLimitConfig.from_string("2/minute"),
            storage=storage,
        )
        handler = self._make_handler()

        try:
            import grpc
            wrapped = interceptor.intercept_service(lambda _: handler, MagicMock())

            ctx = self._make_context("ipv4:5.5.5.5:50051")
            wrapped.unary_unary(MagicMock(), ctx)
            wrapped.unary_unary(MagicMock(), ctx)

            ctx3 = self._make_context("ipv4:5.5.5.5:50051")
            wrapped.unary_unary(MagicMock(), ctx3)
            ctx3.abort.assert_called_once_with(grpc.StatusCode.RESOURCE_EXHAUSTED, pytest.approx)
        except ImportError:
            pytest.skip("grpcio not installed")

    def test_xff_metadata_used_for_ip(self) -> None:
        storage = MemoryStorage()
        interceptor = GrpcRateLimitInterceptor(
            config=RateLimitConfig.from_string("2/minute"),
            storage=storage,
        )
        handler = self._make_handler()

        try:
            import grpc
            wrapped = interceptor.intercept_service(lambda _: handler, MagicMock())
            ctx = self._make_context(
                peer="ipv4:10.0.0.1:50051",  # internal peer
                metadata={"x-forwarded-for": "8.8.8.8"},  # real client
            )
            wrapped.unary_unary(MagicMock(), ctx)
            wrapped.unary_unary(MagicMock(), ctx)
            # Third should be denied (public IP 8.8.8.8 counted)
            wrapped.unary_unary(MagicMock(), ctx)
            ctx.abort.assert_called()
        except ImportError:
            pytest.skip("grpcio not installed")

    def test_skip_private_ips_false_counts_internal(self) -> None:
        storage = MemoryStorage()
        interceptor = GrpcRateLimitInterceptor(
            config=RateLimitConfig.from_string("1/minute", skip_private_ips=False),
            storage=storage,
        )
        handler = self._make_handler()

        try:
            import grpc
            wrapped = interceptor.intercept_service(lambda _: handler, MagicMock())
            ctx = self._make_context("ipv4:192.168.1.1:50051")
            wrapped.unary_unary(MagicMock(), ctx)  # first ok
            wrapped.unary_unary(MagicMock(), ctx)  # should abort
            ctx.abort.assert_called_once()
        except ImportError:
            pytest.skip("grpcio not installed")
