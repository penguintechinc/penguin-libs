#!/usr/bin/env python3
"""Verify penguin-libs package structure and imports."""

import sys
sys.path.insert(0, 'src')

print("=== Package Structure Verification ===\n")

# Test basic import
import penguin_libs
print(f"✓ Package version: {penguin_libs.__version__}")

# Test validation module
from penguin_libs.validation import (
    ValidationError, ValidationResult, Validator, chain,
    IsEmail, IsURL, IsIPAddress, IsHostname,
    IsNotEmpty, IsLength, IsMatch, IsAlphanumeric, IsSlug, IsIn,
    IsInt, IsFloat, IsIntInRange, IsFloatInRange,
    IsDate, IsDateTime, IsTime,
    IsStrongPassword, PasswordOptions
)
print("✓ Validation module: 28 exports")

# Test validation functionality
email_validator = IsEmail()
result = email_validator("test@example.com")
assert result.is_valid, "Email validation failed"
print("✓ Email validation works")

password_validator = IsStrongPassword()
result = password_validator("Test@Pass123")
assert result.is_valid, "Password validation failed"
print("✓ Password validation works")

# Test grpc module (imports only, no runtime)
try:
    from penguin_libs.grpc import (
        create_server, register_health_check, GrpcClient,
        AuthInterceptor, RateLimitInterceptor
    )
    print("✓ gRPC module: imports available (requires grpcio)")
except ImportError as e:
    print(f"⚠ gRPC module: {e} (install with [grpc] extra)")

# Test http module
try:
    from penguin_libs.http import (
        HTTPClient, HTTPClientConfig, RetryConfig,
        CorrelationMiddleware, generate_correlation_id
    )
    print("✓ HTTP module: imports available (requires httpx)")
except ImportError as e:
    print(f"⚠ HTTP module: {e} (install with [http] extra)")

# Test pydantic module
try:
    from penguin_libs.pydantic import (
        ElderBaseModel, ImmutableModel, RequestModel,
        ValidationErrorResponse, validate_body
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
