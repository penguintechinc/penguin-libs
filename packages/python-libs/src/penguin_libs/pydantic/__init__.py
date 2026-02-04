"""Pydantic 2 integration module for penguin_libs.

Provides custom base models for Penguin Tech applications and custom Annotated
types that integrate with penguin_libs.validation validators for seamless
Pydantic model validation.

Features:
- Base models with standard configuration (ElderBaseModel,
  ImmutableModel, RequestModel, ConfigurableModel)
- Pre-built Annotated types for common use cases (email, URL, IP, hostname)
- Factory functions for customizable types (strong_password, bounded_str)
- Full integration with penguin_libs.validation IS_* validators
- No breaking changes to existing validation code

Usage:
    from pydantic import BaseModel
    from penguin_libs.pydantic import (
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
from penguin_libs.pydantic.base import (
    ConfigurableModel,
    ElderBaseModel,
    ImmutableModel,
    RequestModel,
)

# Flask Integration
from penguin_libs.pydantic.flask_integration import (
    ValidationErrorResponse,
    model_response,
    validate_body,
    validate_query_params,
    validated_request,
)

# Type Aliases
from penguin_libs.pydantic.types import (
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
