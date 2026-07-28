"""
penguin-libs — transition library.

All functionality has moved to focused packages. This package re-exports
everything for backwards compatibility. Install the focused package directly
for new projects.

Packages:
- penguin-crypto: Cryptographic utilities
- penguin-flask: Flask utilities
- penguin-grpc: gRPC utilities
- penguin-h3: HTTP/3 QUIC utilities
- penguin-http: HTTP utilities
- penguin-pydantic: Pydantic utilities
- penguin-security: Security utilities
- penguin-validation: Validation utilities
"""

import penguin_libs._compat  # noqa: F401

__version__ = "0.3.0"

__all__ = ["__version__"]
