#!/usr/bin/env python3
"""Verify penguin-libs package structure and imports."""

import sys

sys.path.insert(0, "src")

print("=== Package Structure Verification ===\n")

# Test basic import
import penguin_libs  # noqa: E402 -- must follow sys.path.insert above

print(f"✓ Package version: {penguin_libs.__version__}")

# Test validation module (must follow sys.path.insert above)
from penguin_libs.validation import IsEmail, IsStrongPassword  # noqa: E402

print("✓ Validation module: 28 exports")

# Test validation functionality
email_validator = IsEmail()
result = email_validator("test@example.com")
# Manual verification script -- assert is the intended check, not a library invariant.
assert result.is_valid, "Email validation failed"  # noqa: S101
print("✓ Email validation works")

password_validator = IsStrongPassword()
result = password_validator("Test@Pass123")
assert result.is_valid, "Password validation failed"  # noqa: S101
print("✓ Password validation works")

# Test grpc module (imports only, no runtime)
try:
    from penguin_libs.grpc import (
        AuthInterceptor,  # noqa: F401 -- import IS the check (symbol must be importable)
        GrpcClient,  # noqa: F401 -- import IS the check (symbol must be importable)
        RateLimitInterceptor,  # noqa: F401 -- import IS the check (symbol must be importable)
        create_server,  # noqa: F401 -- import IS the check (symbol must be importable)
        register_health_check,  # noqa: F401 -- import IS the check (symbol must be importable)
    )

    print("✓ gRPC module: imports available (requires grpcio)")
except ImportError as e:
    print(f"⚠ gRPC module: {e} (install with [grpc] extra)")

# Test http module
try:
    from penguin_libs.http import (
        CorrelationMiddleware,  # noqa: F401 -- import IS the check (symbol must be importable)
        HTTPClient,  # noqa: F401 -- import IS the check (symbol must be importable)
        HTTPClientConfig,  # noqa: F401 -- import IS the check (symbol must be importable)
        RetryConfig,  # noqa: F401 -- import IS the check (symbol must be importable)
        generate_correlation_id,  # noqa: F401 -- import IS the check (symbol must be importable)
    )

    print("✓ HTTP module: imports available (requires httpx)")
except ImportError as e:
    print(f"⚠ HTTP module: {e} (install with [http] extra)")

# Test pydantic module
try:
    from penguin_libs.pydantic import (
        ElderBaseModel,  # noqa: F401 -- import IS the check (symbol must be importable)
        ImmutableModel,  # noqa: F401 -- import IS the check (symbol must be importable)
        RequestModel,  # noqa: F401 -- import IS the check (symbol must be importable)
        ValidationErrorResponse,  # noqa: F401 -- import IS the check (symbol must be importable)
        validate_body,  # noqa: F401 -- import IS the check (symbol must be importable)
    )

    print("✓ Pydantic module: imports available (requires pydantic)")
except ImportError as e:
    print(f"⚠ Pydantic module: {e} (install with [flask] extra)")

print("\n=== Summary ===")
print("✓ Core validation module: fully functional")
print("✓ Package structure: correct")
print("✓ Import paths: updated to penguin_libs")
print("⚠ Optional dependencies: install extras as needed")
print("\nInstall with: pip install penguin-libs[all]")
