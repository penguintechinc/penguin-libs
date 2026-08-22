"""Security module - Security utilities for Flask/Quart applications.

Provides:
- sanitize: XSS/HTML sanitization, SQL parameter escaping
- csrf: CSRF token generation and validation
- password: Password hashing and verification (Argon2id, with legacy PBKDF2
  verification support -- see penguin_security.password module docstring)
- ratelimit: Rate limiting (in-memory)
- validation: PyDAL-style input validators
- pydantic: Pydantic 2 integration with validation
- crypto: Symmetric/hybrid encryption, key derivation, ECC, hashing
  (formerly the standalone penguin-crypto package; also importable as
  penguin_security.crypto.{ecc,hashing,hybrid,kdf,symmetric})
"""

from .crypto import (
    blake2b,
    decrypt,
    derive_key,
    derive_key_argon2id,
    derive_key_hkdf,
    ed25519_sign,
    ed25519_verify,
    encrypt,
    generate_ed25519_keypair,
    generate_key,
    generate_salt,
    generate_x25519_keypair,
    hmac_sha256,
    hybrid_decrypt,
    hybrid_encrypt,
    load_ed25519_public_key,
    load_x25519_public_key,
    serialize_private_key,
    serialize_public_key,
    sha256,
    sha512,
    x25519_exchange,
)
from .csrf import generate_csrf_token, validate_csrf_token
from .password import hash_password, needs_rehash, verify_password
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
    "needs_rehash",
    # Rate limiting
    "check_rate_limit",
    # Crypto: symmetric (AES-256-GCM)
    "encrypt",
    "decrypt",
    "generate_key",
    # Crypto: key derivation
    "generate_salt",
    "derive_key",
    "derive_key_argon2id",
    "derive_key_hkdf",
    # Crypto: elliptic curve (X25519, Ed25519)
    "generate_x25519_keypair",
    "x25519_exchange",
    "generate_ed25519_keypair",
    "ed25519_sign",
    "ed25519_verify",
    "serialize_public_key",
    "serialize_private_key",
    "load_x25519_public_key",
    "load_ed25519_public_key",
    # Crypto: hybrid encryption
    "hybrid_encrypt",
    "hybrid_decrypt",
    # Crypto: hashing
    "sha256",
    "sha512",
    "blake2b",
    "hmac_sha256",
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
