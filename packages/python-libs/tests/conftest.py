"""Pytest configuration for penguin-libs tests.

This conftest adds the src directory and split package directories to sys.path
so that penguin_libs and all split packages are importable. This enables both:
- Direct imports from split packages: from penguin_crypto import ...
- Legacy imports via penguin_libs: from penguin_libs.crypto import ...

The legacy imports work because _compat.py registers sys.modules aliases.

It also pre-mocks grpc dependencies so that grpc-dependent tests can load.
"""

import sys
from pathlib import Path
from unittest.mock import MagicMock

# Add src directory to sys.path FIRST
src_dir = Path(__file__).parent.parent / "src"
if str(src_dir) not in sys.path:
    sys.path.insert(0, str(src_dir))

# Add all split package directories to sys.path so they're importable
# They're sibling directories: ../python-crypto, ../python-flask, etc.
packages_dir = Path(__file__).parent.parent.parent
split_packages = [
    "python-crypto",
    "python-flask",
    "python-grpc",
    "python-h3",
    "python-http",
    "python-pydantic",
    "python-security",
    "python-validation",
    "python-aaa",
    "python-dal",
    "python-email",
    "python-licensing",
    "python-limiter",
    "python-secrets",
    "python-utils",
]

for pkg_name in split_packages:
    pkg_path = packages_dir / pkg_name / "src"
    if pkg_path.exists() and str(pkg_path) not in sys.path:
        sys.path.insert(0, str(pkg_path))

# Pre-mock grpc dependencies BEFORE any imports that might use them
# This allows grpc-dependent code to import without requiring the full grpc stack
if "grpc" not in sys.modules:
    _mock_grpc = MagicMock()
    _mock_grpc.__version__ = "1.80.0"  # Required: grpc_health imports try to access this
    _mock_grpc.StatusCode.UNAUTHENTICATED = "UNAUTHENTICATED"
    _mock_grpc.StatusCode.PERMISSION_DENIED = "PERMISSION_DENIED"
    _mock_grpc.StatusCode.INVALID_ARGUMENT = "INVALID_ARGUMENT"
    _mock_grpc.StatusCode.NOT_FOUND = "NOT_FOUND"
    _mock_grpc.StatusCode.ALREADY_EXISTS = "ALREADY_EXISTS"
    _mock_grpc.StatusCode.RESOURCE_EXHAUSTED = "RESOURCE_EXHAUSTED"
    _mock_grpc.StatusCode.INTERNAL = "INTERNAL"
    _mock_grpc.RpcError = type("RpcError", (Exception,), {"code": lambda self: self._code})
    _mock_grpc.ServerInterceptor = type("ServerInterceptor", (), {})
    _mock_grpc.Channel = MagicMock
    _mock_grpc.HandlerCallDetails = MagicMock

    _mock_jwt = MagicMock()
    _mock_jwt.ExpiredSignatureError = type("ExpiredSignatureError", (Exception,), {})
    _mock_jwt.InvalidTokenError = type("InvalidTokenError", (Exception,), {})

    _mock_health = MagicMock()
    _mock_health.SERVICE_NAME = "grpc.health.v1.Health"
    _mock_health_pb2 = MagicMock()
    _mock_health_pb2.HealthCheckResponse.SERVING = 1
    _mock_health_pb2_grpc = MagicMock()
    _mock_reflection = MagicMock()
    _mock_reflection.SERVICE_NAME = "grpc.reflection.v1alpha.ServerReflection"

    sys.modules["grpc"] = _mock_grpc
    sys.modules["jwt"] = _mock_jwt
    sys.modules["grpc_health"] = MagicMock()
    sys.modules["grpc_health.v1"] = MagicMock()
    sys.modules["grpc_health.v1.health"] = _mock_health
    sys.modules["grpc_health.v1.health_pb2"] = _mock_health_pb2
    sys.modules["grpc_health.v1.health_pb2_grpc"] = _mock_health_pb2_grpc
    sys.modules["grpc_reflection"] = MagicMock()
    sys.modules["grpc_reflection.v1alpha"] = MagicMock()
    sys.modules["grpc_reflection.v1alpha.reflection"] = _mock_reflection

# CRITICAL: Import penguin_libs EARLY to register sys.modules aliases.
# This enables legacy imports like: from penguin_libs.grpc import ...
# test_grpc.py will delete and reimport these modules, so conftest must import
# them first to ensure they're available in sys.modules.
import penguin_libs  # noqa: F401


__all__ = []
