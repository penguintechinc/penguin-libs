"""Tests for penguin_grpc package exports and integration."""

import pytest

import penguin_grpc


class TestPackageExports:
    """Test package __all__ exports."""

    def test_all_exports_are_available(self) -> None:
        """Test all items in __all__ are importable."""
        expected_exports = {
            "create_server",
            "register_health_check",
            "GrpcClient",
            "AuthInterceptor",
            "RateLimitInterceptor",
            "AuditInterceptor",
            "CorrelationInterceptor",
            "RecoveryInterceptor",
        }

        for export in expected_exports:
            assert hasattr(penguin_grpc, export), f"Missing export: {export}"

    def test_create_server_is_callable(self) -> None:
        """Test create_server is callable."""
        assert callable(penguin_grpc.create_server)

    def test_register_health_check_is_callable(self) -> None:
        """Test register_health_check is callable."""
        assert callable(penguin_grpc.register_health_check)

    def test_grpc_client_is_class(self) -> None:
        """Test GrpcClient is a class."""
        assert isinstance(penguin_grpc.GrpcClient, type)

    def test_auth_interceptor_is_class(self) -> None:
        """Test AuthInterceptor is a class."""
        assert isinstance(penguin_grpc.AuthInterceptor, type)

    def test_rate_limit_interceptor_is_class(self) -> None:
        """Test RateLimitInterceptor is a class."""
        assert isinstance(penguin_grpc.RateLimitInterceptor, type)

    def test_audit_interceptor_is_class(self) -> None:
        """Test AuditInterceptor is a class."""
        assert isinstance(penguin_grpc.AuditInterceptor, type)

    def test_correlation_interceptor_is_class(self) -> None:
        """Test CorrelationInterceptor is a class."""
        assert isinstance(penguin_grpc.CorrelationInterceptor, type)

    def test_recovery_interceptor_is_class(self) -> None:
        """Test RecoveryInterceptor is a class."""
        assert isinstance(penguin_grpc.RecoveryInterceptor, type)


class TestPackageIntegration:
    """Test package integration."""

    def test_import_from_package_root(self) -> None:
        """Test importing from package root works."""
        from penguin_grpc import (
            AuditInterceptor,
            AuthInterceptor,
            CorrelationInterceptor,
            GrpcClient,
            RateLimitInterceptor,
            RecoveryInterceptor,
            create_server,
            register_health_check,
        )

        assert create_server is not None
        assert register_health_check is not None
        assert GrpcClient is not None
        assert AuthInterceptor is not None
        assert RateLimitInterceptor is not None
        assert AuditInterceptor is not None
        assert CorrelationInterceptor is not None
        assert RecoveryInterceptor is not None

    def test_import_from_submodules(self) -> None:
        """Test importing from submodules works."""
        from penguin_grpc.client import GrpcClient
        from penguin_grpc.interceptors import (
            AuditInterceptor,
            AuthInterceptor,
            CorrelationInterceptor,
            RateLimitInterceptor,
            RecoveryInterceptor,
        )
        from penguin_grpc.server import create_server, register_health_check

        assert create_server is not None
        assert register_health_check is not None
        assert GrpcClient is not None
        assert AuthInterceptor is not None
        assert RateLimitInterceptor is not None
        assert AuditInterceptor is not None
        assert CorrelationInterceptor is not None
        assert RecoveryInterceptor is not None
