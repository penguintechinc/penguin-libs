"""
Sanitized logging utilities for Penguin Tech applications.

Provides logging helpers that automatically sanitize sensitive data
to prevent accidental exposure of passwords, tokens, emails, etc.
Built on structlog for structured, production-ready logging.
"""

import logging
import re
from collections.abc import Sequence
from typing import TYPE_CHECKING, Any

import structlog
from structlog.types import EventDict, Processor

if TYPE_CHECKING:
    from .sinks import Sink

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
            # Check for email addresses — only log domain
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


def _sanitize_processor(logger: Any, method: str, event_dict: EventDict) -> EventDict:
    """structlog processor that sanitizes all dict values in the event."""
    return sanitize_log_data(event_dict)  # type: ignore[return-value]


class _SinkProcessor:
    """structlog processor that forwards events to registered sinks."""

    def __init__(self, sinks: Sequence["Sink"]) -> None:
        self._sinks = list(sinks)

    def __call__(self, logger: Any, method: str, event_dict: EventDict) -> EventDict:
        for sink in self._sinks:
            sink.emit(dict(event_dict))
        return event_dict


def configure_logging(
    level: int = logging.INFO,
    json_output: bool = False,
    sinks: Sequence["Sink"] | None = None,
) -> None:
    """
    Configure structlog for the application.

    Sets up a processor chain that adds log level, ISO timestamps, sanitizes
    sensitive fields, and renders output as JSON or a human-readable console
    format. Optionally forwards events to additional sinks.

    Args:
        level: Minimum logging level (default: INFO).
        json_output: Render as JSON lines when True, console format when False.
        sinks: Optional sequence of Sink instances to receive every event.
    """
    processors: list[Processor] = [
        structlog.stdlib.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        _sanitize_processor,
    ]

    if sinks:
        processors.append(_SinkProcessor(sinks))

    if json_output:
        processors.append(structlog.processors.JSONRenderer())
    else:
        processors.append(structlog.dev.ConsoleRenderer())

    structlog.configure(
        processors=processors,
        wrapper_class=structlog.stdlib.BoundLogger,
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )

    logging.basicConfig(level=level)


def get_logger(name: str, level: int = logging.INFO) -> structlog.stdlib.BoundLogger:
    """
    Get a structlog BoundLogger with Penguin Tech standard configuration.

    Args:
        name: Logger name (usually __name__ or component name).
        level: Logging level (default: INFO).

    Returns:
        Configured structlog BoundLogger instance.
    """
    logging.getLogger(name).setLevel(level)
    return structlog.get_logger(name)


class SanitizedLogger:
    """
    A logger that automatically sanitizes data before emitting log events.

    Delegates to a structlog BoundLogger internally while preserving the
    original (msg, data) method signature for backward compatibility.

    Usage:
        log = SanitizedLogger("MyComponent")
        log.info("User login", {"email": "user@example.com", "password": "secret"})
    """

    def __init__(self, name: str, level: int = logging.INFO) -> None:
        self._logger = get_logger(name, level)

    def _log(self, method: str, message: str, data: dict[str, Any] | None = None) -> None:
        sanitized = sanitize_log_data(data) if data else {}
        getattr(self._logger, method)(message, **sanitized)

    def debug(self, message: str, data: dict[str, Any] | None = None) -> None:
        """Log a debug message with optional sanitized data."""
        self._log("debug", message, data)

    def info(self, message: str, data: dict[str, Any] | None = None) -> None:
        """Log an info message with optional sanitized data."""
        self._log("info", message, data)

    def warning(self, message: str, data: dict[str, Any] | None = None) -> None:
        """Log a warning message with optional sanitized data."""
        self._log("warning", message, data)

    def error(self, message: str, data: dict[str, Any] | None = None) -> None:
        """Log an error message with optional sanitized data."""
        self._log("error", message, data)

    def critical(self, message: str, data: dict[str, Any] | None = None) -> None:
        """Log a critical message with optional sanitized data."""
        self._log("critical", message, data)
