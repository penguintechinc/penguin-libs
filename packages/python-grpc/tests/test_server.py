"""Tests for gRPC server functions and ServerOptions."""

import signal
from unittest.mock import MagicMock, Mock, call, patch

import grpc
import pytest
from grpc_health.v1 import health_pb2

from penguin_grpc.server import (
    ServerOptions,
    _enable_reflection,
    create_server,
    register_health_check,
    start_server_with_graceful_shutdown,
)


class TestServerOptions:
    """Test ServerOptions dataclass."""

    def test_default_values(self) -> None:
        """Test ServerOptions has correct defaults."""
        opts = ServerOptions()
        assert opts.max_workers == 10
        assert opts.max_concurrent_rpcs == 100
        assert opts.enable_reflection is True
        assert opts.enable_health_check is True
        assert opts.port == 50051
        assert opts.max_connection_idle_ms == 300000
        assert opts.max_connection_age_ms == 600000
        assert opts.keepalive_time_ms == 60000
        assert opts.keepalive_timeout_ms == 20000

    def test_custom_values(self) -> None:
        """Test ServerOptions with custom values."""
        opts = ServerOptions(
            max_workers=20,
            port=9999,
            enable_reflection=False,
        )
        assert opts.max_workers == 20
        assert opts.port == 9999
        assert opts.enable_reflection is False
        assert opts.enable_health_check is True  # Still default

    def test_frozen_dataclass(self) -> None:
        """Test ServerOptions is frozen."""
        opts = ServerOptions()
        with pytest.raises(AttributeError):
            opts.max_workers = 50  # type: ignore


class TestCreateServer:
    """Test create_server function."""

    def test_create_server_with_defaults(self) -> None:
        """Test server creation with default options."""
        server = create_server()
        assert isinstance(server, grpc.Server)
        server.stop(0)

    def test_create_server_with_custom_options(self) -> None:
        """Test server creation with custom options."""
        opts = ServerOptions(max_workers=5, port=9000)
        server = create_server(options=opts)
        assert isinstance(server, grpc.Server)
        server.stop(0)

    def test_create_server_with_interceptors(self) -> None:
        """Test server creation with interceptors."""
        mock_interceptor = MagicMock(spec=grpc.ServerInterceptor)
        server = create_server(interceptors=[mock_interceptor])
        assert isinstance(server, grpc.Server)
        server.stop(0)

    def test_create_server_reflection_enabled(self) -> None:
        """Test server creation with reflection enabled."""
        opts = ServerOptions(enable_reflection=True)
        with patch("penguin_grpc.server._enable_reflection") as mock_reflect:
            server = create_server(options=opts)
            mock_reflect.assert_called_once_with(server)
            server.stop(0)

    def test_create_server_reflection_disabled(self) -> None:
        """Test server creation with reflection disabled."""
        opts = ServerOptions(enable_reflection=False)
        with patch("penguin_grpc.server._enable_reflection") as mock_reflect:
            server = create_server(options=opts)
            mock_reflect.assert_not_called()
            server.stop(0)

    def test_create_server_health_check_enabled(self) -> None:
        """Test server creation with health check enabled."""
        opts = ServerOptions(enable_health_check=True)
        with patch("penguin_grpc.server.register_health_check") as mock_health:
            server = create_server(options=opts)
            mock_health.assert_called_once_with(server)
            server.stop(0)

    def test_create_server_health_check_disabled(self) -> None:
        """Test server creation with health check disabled."""
        opts = ServerOptions(enable_health_check=False)
        with patch("penguin_grpc.server.register_health_check") as mock_health:
            server = create_server(options=opts)
            mock_health.assert_not_called()
            server.stop(0)

    def test_create_server_with_all_interceptors(self) -> None:
        """Test server with multiple interceptors."""
        mock_int1 = MagicMock(spec=grpc.ServerInterceptor)
        mock_int2 = MagicMock(spec=grpc.ServerInterceptor)
        server = create_server(interceptors=[mock_int1, mock_int2])
        assert isinstance(server, grpc.Server)
        server.stop(0)

    def test_create_server_applies_channel_options(self) -> None:
        """Test that server applies channel options."""
        opts = ServerOptions(
            max_concurrent_rpcs=50,
            max_connection_idle_ms=100000,
            keepalive_time_ms=30000,
        )
        server = create_server(options=opts)
        assert isinstance(server, grpc.Server)
        server.stop(0)


class TestRegisterHealthCheck:
    """Test register_health_check function."""

    def test_register_health_check(self) -> None:
        """Test health check registration."""
        server = create_server(options=ServerOptions(enable_health_check=False))
        health_servicer = register_health_check(server)
        assert health_servicer is not None
        server.stop(0)

    def test_health_servicer_is_health_class(self) -> None:
        """Test returned servicer is HealthServicer."""
        server = create_server(options=ServerOptions(enable_health_check=False))
        health_servicer = register_health_check(server)
        assert isinstance(health_servicer, type(health.HealthServicer()))
        server.stop(0)

    def test_health_check_sets_serving_status(self) -> None:
        """Test health check sets SERVING status."""
        server = create_server(options=ServerOptions(enable_health_check=False))
        health_servicer = register_health_check(server)
        # Verify the servicer can set status
        health_servicer.set("test_service", health_pb2.HealthCheckResponse.SERVING)
        server.stop(0)


class TestEnableReflection:
    """Test _enable_reflection function."""

    def test_enable_reflection(self) -> None:
        """Test reflection is enabled on server."""
        server = create_server(options=ServerOptions(enable_reflection=False))
        # Should not raise
        _enable_reflection(server)
        server.stop(0)


class TestStartServerWithGracefulShutdown:
    """Test start_server_with_graceful_shutdown function."""

    def test_graceful_shutdown_sigterm(self) -> None:
        """Test server graceful shutdown on SIGTERM."""
        server = MagicMock(spec=grpc.Server)

        def mock_wait_for_termination() -> None:
            # Simulate SIGTERM signal
            raise KeyboardInterrupt()

        server.wait_for_termination = mock_wait_for_termination

        with patch("signal.signal") as mock_signal:
            with pytest.raises(KeyboardInterrupt):
                start_server_with_graceful_shutdown(server, port=50051, grace_period=30.0)

            # Verify signal handlers were registered
            assert mock_signal.call_count == 2
            calls = mock_signal.call_args_list
            assert calls[0][0][0] == signal.SIGTERM
            assert calls[1][0][0] == signal.SIGINT

    def test_graceful_shutdown_calls_server_methods(self) -> None:
        """Test graceful shutdown calls required server methods."""
        server = MagicMock(spec=grpc.Server)

        def mock_wait_for_termination() -> None:
            raise KeyboardInterrupt()

        server.wait_for_termination = mock_wait_for_termination

        with patch("signal.signal"):
            with pytest.raises(KeyboardInterrupt):
                start_server_with_graceful_shutdown(server, port=50051, grace_period=30.0)

        server.add_insecure_port.assert_called_once_with("[::]:50051")
        server.start.assert_called_once()

    def test_graceful_shutdown_custom_port(self) -> None:
        """Test graceful shutdown with custom port."""
        server = MagicMock(spec=grpc.Server)

        def mock_wait_for_termination() -> None:
            raise KeyboardInterrupt()

        server.wait_for_termination = mock_wait_for_termination

        with patch("signal.signal"):
            with pytest.raises(KeyboardInterrupt):
                start_server_with_graceful_shutdown(server, port=9999)

        server.add_insecure_port.assert_called_once_with("[::]:9999")

    def test_graceful_shutdown_custom_grace_period(self) -> None:
        """Test graceful shutdown with custom grace period."""
        server = MagicMock(spec=grpc.Server)

        def mock_wait_for_termination() -> None:
            raise KeyboardInterrupt()

        server.wait_for_termination = mock_wait_for_termination

        with patch("signal.signal") as mock_signal:
            with pytest.raises(KeyboardInterrupt):
                start_server_with_graceful_shutdown(server, grace_period=15.0)

            # Extract the signal handler function
            handler_func = mock_signal.call_args_list[0][0][1]
            # Call the handler
            handler_func(signal.SIGTERM, None)
            # Verify stop was called with grace period
            server.stop.assert_called_once_with(15.0)


# Import health after other imports to avoid circular dependencies
from grpc_health.v1 import health
