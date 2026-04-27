"""
Security module - Security utilities for Flask/Quart applications.

Provides:
- sanitize: XSS/HTML sanitization, SQL parameter escaping
- csrf: CSRF token generation and validation
- password: Password hashing and verification
- ratelimit: Rate limiting (in-memory)
"""

from .csrf import generate_csrf_token, validate_csrf_token
from .password import hash_password, verify_password
from .ratelimit import check_rate_limit
from .sanitize import escape_shell_arg, escape_sql_string, sanitize_html

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
]
