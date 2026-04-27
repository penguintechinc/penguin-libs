"""sys.modules aliases for backwards-compatible submodule imports."""

import sys
from unittest.mock import MagicMock

# Pre-mock grpc dependencies if not available
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

# Import split packages with graceful fallback
_PACKAGES = {}

_package_specs = [
    ("penguin_crypto", "penguin_libs.crypto"),
    ("penguin_flask", "penguin_libs.flask"),
    ("penguin_grpc", "penguin_libs.grpc"),
    ("penguin_h3", "penguin_libs.h3"),
    ("penguin_http", "penguin_libs.http"),
    ("penguin_pydantic", "penguin_libs.pydantic"),
    ("penguin_security", "penguin_libs.security"),
    ("penguin_validation", "penguin_libs.validation"),
]

for pkg_name, legacy_name in _package_specs:
    try:
        _PACKAGES[pkg_name] = __import__(pkg_name)
        # Try to re-export everything from the submodule
        try:
            _mod = sys.modules[pkg_name]
            if hasattr(_mod, "__all__"):
                for _name in _mod.__all__:
                    globals()[_name] = getattr(_mod, _name)
        except Exception:
            pass  # Skip re-export if it fails
    except ImportError as _import_err:
        # Package not available; skip it
        # Note: silently skipping failed imports - this is intentional for optional split packages
        pass

__all__ = list(_PACKAGES.keys())

# Register sys.modules aliases for backwards-compatible submodule imports
# Allows: from penguin_libs.crypto import ... (legacy) -> from penguin_crypto import ... (new)
for pkg_name, legacy_name in _package_specs:
    if pkg_name in _PACKAGES:
        _module = _PACKAGES[pkg_name]
        if legacy_name not in sys.modules:
            sys.modules[legacy_name] = _module
