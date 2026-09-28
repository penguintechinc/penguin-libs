"""Pydantic 2 integration module for penguin_libs.

Provides custom base models for Penguin Tech applications and custom Annotated
types that integrate with penguin_security.validation validators for seamless
Pydantic model validation.

Features:
- Base models with standard configuration (ElderBaseModel,
  ImmutableModel, RequestModel, ConfigurableModel)
- Pre-built Annotated types for common use cases (email, URL, IP, hostname)
- Factory functions for customizable types (strong_password, bounded_str)
- Full integration with penguin_security.validation IS_* validators
- No breaking changes to existing validation code

Usage:
    from pydantic import BaseModel
    from penguin_security.pydantic import (
        ElderBaseModel,
        RequestModel,
        EmailStr,
        StrongPassword,
        Name255,
    )

    class UserRequest(RequestModel):
        email: EmailStr
        password: StrongPassword
        name: Name255

    user = UserRequest(
        email="user@example.com",
        password="SecureP@ss123",
        name="John Doe"
    )
"""

# flake8: noqa: E501

# Base Models
from .base import (
    ConfigurableModel,
    ElderBaseModel,
    ImmutableModel,
    RequestModel,
)

# Note: ValidationErrorResponse, model_response, validate_body, validate_query_params,
# and validated_request are NOT imported here — flask_integration.py imports Flask at
# module level, and Flask is an optional dependency. They are lazily loaded via
# __getattr__ below (PEP 562) so `import penguin_security.pydantic` succeeds without
# Flask installed. See __getattr__ for the deferred-import/clear-error contract.
# Type Aliases
from .types import (
    Description1000,
    EmailStr,
    HostnameStr,
    IPAddressStr,
    IPv4Str,
    IPv6Str,
    ModeratePassword,
    Name255,
    NonEmptyStr,
    ShortText100,
    SlugStr,
    StrongPassword,
    URLStr,
    bounded_str,
    strong_password,
)

__all__ = [
    # Base Models
    "ElderBaseModel",
    "ImmutableModel",
    "RequestModel",
    "ConfigurableModel",
    # Basic types
    "EmailStr",
    "URLStr",
    "IPAddressStr",
    "IPv4Str",
    "IPv6Str",
    "HostnameStr",
    "NonEmptyStr",
    "SlugStr",
    # Factory functions
    "strong_password",
    "bounded_str",
    # Pre-built password types
    "StrongPassword",
    "ModeratePassword",
    # Pre-built text length types
    "Name255",
    "Description1000",
    "ShortText100",
    # Flask Integration
    "ValidationErrorResponse",
    "validate_body",
    "validate_query_params",
    "validated_request",
    "model_response",
]

_FLASK_INTEGRATION_NAMES = frozenset(
    {
        "ValidationErrorResponse",
        "model_response",
        "validate_body",
        "validate_query_params",
        "validated_request",
    }
)


def __getattr__(name: str) -> object:
    """Lazily import Flask-dependent request/response helpers (optional dependency).

    Defers the Flask import in flask_integration.py until one of its symbols is
    actually accessed, so `import penguin_security.pydantic` succeeds without Flask
    installed (gh-security-lazy-flask; precedent: penguin_aaa 11c4e19).
    """
    if name in _FLASK_INTEGRATION_NAMES:
        try:
            from . import flask_integration
        except ImportError as e:
            raise ImportError(
                f"{name} requires the 'flask' extra: pip install penguin-security[flask]"
            ) from e
        return getattr(flask_integration, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
