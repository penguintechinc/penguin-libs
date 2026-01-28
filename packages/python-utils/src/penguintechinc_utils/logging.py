"""
Sanitized logging utilities for Penguin Tech applications.

Provides logging helpers that automatically sanitize sensitive data
to prevent accidental exposure of passwords, tokens, emails, etc.
"""

import logging
import re
from typing import Any

# Keys that should never be logged
SENSITIVE_KEYS = frozenset({
    "password",
    "passwd",
    "secret",
    "token",
    "api_key",
    "apikey",
    "auth_token",
    "authtoken",
    "access_token",
    "refresh_token",
    "credential",
    "credentials",
    "mfa_code",
    "totp_code",
    "otp",
    "captcha_token",
    "session_id",
    "sessionid",
    "cookie",
    "authorization",
})

# Regex for email detection
EMAIL_REGEX = re.compile(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}")


def sanitize_log_data(data: dict[str, Any]) -> dict[str, Any]:
    """
    Sanitize a dictionary for safe logging.

    Removes or redacts sensitive values like passwords, tokens, and emails.

    Args:
        data: Dictionary to sanitize

    Returns:
        Sanitized copy of the dictionary
    """
    if not isinstance(data, dict):
        return data

    sanitized = {}
    for key, value in data.items():
        key_lower = key.lower()

        # Check if key is sensitive
        if key_lower in SENSITIVE_KEYS or any(s in key_lower for s in SENSITIVE_KEYS):
            sanitized[key] = "[REDACTED]"
        elif isinstance(value, str):
            # Check for email addresses - only log domain
            if "@" in value and EMAIL_REGEX.match(value):
                parts = value.split("@")
                if len(parts) == 2:
                    sanitized[key] = f"[email]@{parts[1]}"
                else:
                    sanitized[key] = "[REDACTED_EMAIL]"
            else:
                sanitized[key] = value
        elif isinstance(value, dict):
            sanitized[key] = sanitize_log_data(value)
        elif isinstance(value, list):
            sanitized[key] = [
                sanitize_log_data(item) if isinstance(item, dict) else item
                for item in value
            ]
        else:
            sanitized[key] = value

    return sanitized


def get_logger(name: str, level: int = logging.INFO) -> logging.Logger:
    """
    Get a logger with Penguin Tech standard formatting.

    Args:
        name: Logger name (usually __name__ or component name)
        level: Logging level (default: INFO)

    Returns:
        Configured logger instance
    """
    logger = logging.getLogger(name)

    if not logger.handlers:
        handler = logging.StreamHandler()
        formatter = logging.Formatter(
            fmt="[%(name)s] %(levelname)s: %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
        handler.setFormatter(formatter)
        logger.addHandler(handler)

    logger.setLevel(level)
    return logger


class SanitizedLogger:
    """
    A logger wrapper that automatically sanitizes data before logging.

    Usage:
        log = SanitizedLogger("MyComponent")
        log.info("User login", {"email": "user@example.com", "password": "secret"})
        # Logs: [MyComponent] INFO: User login {'email': '[email]@example.com', 'password': '[REDACTED]'}
    """

    def __init__(self, name: str, level: int = logging.INFO) -> None:
        self._logger = get_logger(name, level)

    def _log(self, level: int, message: str, data: dict[str, Any] | None = None) -> None:
        if data:
            sanitized = sanitize_log_data(data)
            self._logger.log(level, f"{message} {sanitized}")
        else:
            self._logger.log(level, message)

    def debug(self, message: str, data: dict[str, Any] | None = None) -> None:
        """Log a debug message with optional sanitized data."""
        self._log(logging.DEBUG, message, data)

    def info(self, message: str, data: dict[str, Any] | None = None) -> None:
        """Log an info message with optional sanitized data."""
        self._log(logging.INFO, message, data)

    def warning(self, message: str, data: dict[str, Any] | None = None) -> None:
        """Log a warning message with optional sanitized data."""
        self._log(logging.WARNING, message, data)

    def error(self, message: str, data: dict[str, Any] | None = None) -> None:
        """Log an error message with optional sanitized data."""
        self._log(logging.ERROR, message, data)

    def critical(self, message: str, data: dict[str, Any] | None = None) -> None:
        """Log a critical message with optional sanitized data."""
        self._log(logging.CRITICAL, message, data)
