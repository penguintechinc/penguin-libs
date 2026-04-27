"""CSRF token generation and validation."""

import hmac
import os
import secrets
from typing import Any


def generate_csrf_token() -> str:
    """
    Generate a cryptographically secure CSRF token.

    Returns:
        str: A random token suitable for CSRF protection (hex-encoded)
    """
    # Generate 32 random bytes and encode as hex (64 hex characters)
    return secrets.token_hex(32)


def validate_csrf_token(token: str, session_token: str) -> bool:
    """
    Validate CSRF token using constant-time comparison.

    Args:
        token: Token from request (form/header)
        session_token: Token stored in session

    Returns:
        bool: True if tokens match, False otherwise

    Raises:
        TypeError: If either argument is not a string
    """
    if not isinstance(token, str):
        raise TypeError(f"Expected str for token, got {type(token).__name__}")
    if not isinstance(session_token, str):
        raise TypeError(f"Expected str for session_token, got {type(session_token).__name__}")

    # Reject if either token is empty
    if not token or not session_token:
        return False

    # Use constant-time comparison to prevent timing attacks
    return hmac.compare_digest(token, session_token)
