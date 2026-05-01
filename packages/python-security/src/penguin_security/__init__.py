"""
Security module - Security utilities for Flask/Quart applications.

Provides:
- sanitize: XSS/HTML sanitization, SQL parameter escaping
- csrf: CSRF token generation and validation
- password: Password hashing and verification
- ratelimit: Rate limiting (in-memory)
- validation: PyDAL-style input validators
- pydantic: Pydantic 2 integration with validation
"""

from .csrf import generate_csrf_token, validate_csrf_token
from .password import hash_password, verify_password
from .pydantic import (
    ConfigurableModel,
    Description1000,
    ElderBaseModel,
    EmailStr,
    HostnameStr,
    ImmutableModel,
    IPAddressStr,
    IPv4Str,
    IPv6Str,
    ModeratePassword,
    Name255,
    NonEmptyStr,
    RequestModel,
    ShortText100,
    SlugStr,
    StrongPassword,
    URLStr,
    ValidationErrorResponse,
    bounded_str,
    model_response,
    strong_password,
    validate_body,
    validate_query_params,
    validated_request,
)
from .ratelimit import check_rate_limit
from .sanitize import escape_shell_arg, escape_sql_string, sanitize_html
from .validation import (
    IsAlphanumeric,
    IsDate,
    IsDateInRange,
    IsDateTime,
    IsEmail,
    IsFloat,
    IsFloatInRange,
    IsHostname,
    IsIn,
    IsInt,
    IsIntInRange,
    IsIPAddress,
    IsLength,
    IsMatch,
    IsNegative,
    IsNotEmpty,
    IsPositive,
    IsSlug,
    IsStrongPassword,
    IsTime,
    IsTrimmed,
    IsURL,
    PasswordOptions,
    ValidationError,
    ValidationResult,
    Validator,
    chain,
)

__all__ = [
    # Sanitization
    "sanitize_html",
    "escape_sql_string",
    "escape_shell_arg",
    # CSRF
    "generate_csrf_token",
    "validate_csrf_token",
    # Password
    "hash_password",
    "verify_password",
    # Rate limiting
    "check_rate_limit",
    # Validation
    "ValidationError",
    "ValidationResult",
    "Validator",
    "chain",
    "IsNotEmpty",
    "IsLength",
    "IsMatch",
    "IsAlphanumeric",
    "IsSlug",
    "IsIn",
    "IsTrimmed",
    "IsInt",
    "IsFloat",
    "IsIntInRange",
    "IsFloatInRange",
    "IsPositive",
    "IsNegative",
    "IsEmail",
    "IsURL",
    "IsIPAddress",
    "IsHostname",
    "IsDate",
    "IsDateTime",
    "IsTime",
    "IsDateInRange",
    "IsStrongPassword",
    "PasswordOptions",
    # Pydantic
    "ElderBaseModel",
    "ImmutableModel",
    "RequestModel",
    "ConfigurableModel",
    "EmailStr",
    "URLStr",
    "IPAddressStr",
    "IPv4Str",
    "IPv6Str",
    "HostnameStr",
    "NonEmptyStr",
    "SlugStr",
    "strong_password",
    "bounded_str",
    "StrongPassword",
    "ModeratePassword",
    "Name255",
    "Description1000",
    "ShortText100",
    "ValidationErrorResponse",
    "validate_body",
    "validate_query_params",
    "validated_request",
    "model_response",
]
