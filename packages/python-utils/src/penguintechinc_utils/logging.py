"""
Sanitized logging utilities for Penguin Tech applications.

Provides logging helpers that automatically sanitize sensitive data
to prevent accidental exposure of passwords, tokens, emails, etc.
Built on structlog for structured, production-ready logging.
"""

import logging
import re
from collections.abc import Sequence
from typing import TYPE_CHECKING, Any, cast

import structlog
from structlog.types import EventDict, Processor

if TYPE_CHECKING:
    from .sinks import Sink

# Redaction placeholders
SENSITIVE_PLACEHOLDER = "[REDACTED]"
SANITIZE_ERROR_PLACEHOLDER = "[REDACTED:sanitize-error]"

# Keys that should never be logged
SENSITIVE_KEYS = frozenset(
    {
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
    }
)

# Regex for email detection
EMAIL_REGEX = re.compile(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}")

# Word-boundary splitter for key matching
_KEY_SPLIT = re.compile(r"[^a-z0-9]+")

# key=value / key: value scanner (query string, header, or inline free text).
# Sensitivity is decided by is_sensitive_key -- the SAME function the structured
# dict-field path uses -- so there is exactly one source of truth for what counts
# as sensitive, never a second word list.
#
# The value's second alternative is guarded by a negative lookahead that refuses to
# start consuming where the upcoming text itself looks like a new key=/key: pair.
# Without that guard, a non-sensitive outer key (e.g. "note:") greedily swallows an
# inner sensitive one (e.g. "password=hunter2") whole as its own opaque value, and
# the inner pair never gets a chance to be scanned on its own.
_KV = re.compile(
    r"([A-Za-z0-9_.\-]+)(\s*[:=]\s*)"
    r"((?:Bearer|Basic|Digest|Token)\s+[^\s&#,;?/]+"
    r"|(?:(?![A-Za-z0-9_.\-]+\s*[:=])[^\s&#,;?/])+)",
    re.IGNORECASE,
)


def _redact_kv(m: "re.Match[str]") -> str:
    """Redact a _KV match's value when its key is sensitive; otherwise pass through."""
    return f"{m.group(1)}{m.group(2)}[REDACTED]" if is_sensitive_key(m.group(1)) else m.group(0)


def is_sensitive_key(key: str) -> bool:
    """
    Check if a key names a secret (word-boundary match, not substring).

    Matches on contiguous segment subsequence: "stripe_api_key" contains ["api", "key"].

    Args:
        key: Key name to check

    Returns:
        True if key contains a sensitive segment sequence
    """
    key_lower = key.lower()
    key_segments = [s for s in _KEY_SPLIT.split(key_lower) if s]

    # For each sensitive key, check if its segments appear as contiguous subsequence
    for sensitive in SENSITIVE_KEYS:
        sensitive_segments = [s for s in _KEY_SPLIT.split(sensitive) if s]

        # Check if sensitive_segments appears as contiguous run in key_segments
        for i in range(len(key_segments) - len(sensitive_segments) + 1):
            if key_segments[i : i + len(sensitive_segments)] == sensitive_segments:
                return True

    return False


def redact_text(value: str) -> str:
    """
    Redact emails, and the value of any sensitive key=value / key: value pair.

    Scans query strings, headers, and inline free text alike -- anywhere in the
    string, not just query strings. Sensitivity is judged by is_sensitive_key, the
    same function used for structured dict fields, so there is one source of truth
    for what counts as sensitive rather than a second word list.

    Args:
        value: String to redact

    Returns:
        String with emails replaced by [email] and sensitive key/value pairs'
        values replaced by [REDACTED] (key and separator preserved).
    """
    value = EMAIL_REGEX.sub("[email]", value)
    value = _KV.sub(_redact_kv, value)
    return value


def _sanitize_value(value: Any) -> Any:
    """
    Recursively sanitize a value: dicts, lists/tuples/sets, strings, or convert others to strings.

    Args:
        value: Value to sanitize

    Returns:
        Sanitized value (list/tuple/set input is always returned as a list)

    Raises:
        Any exception from converting non-standard types to strings (e.g., broken __repr__).
    """
    if isinstance(value, dict):
        return sanitize_log_data(value)
    if isinstance(value, (list, tuple, set)):
        return [_sanitize_value(v) for v in value]
    if isinstance(value, str):
        return redact_text(value)
    # For non-standard types, try to convert to string (may raise if __repr__/__str__ broken)
    # This allows fail-closed behavior to catch the exception
    _ = str(value)
    return value


def sanitize_log_data(data: dict[str, Any]) -> dict[str, Any]:
    """
    Sanitize a dictionary for safe logging.

    Removes or redacts sensitive values like passwords, tokens, and emails.
    Fails closed: if sanitizing a value raises, returns SANITIZE_ERROR_PLACEHOLDER.

    Args:
        data: Dictionary to sanitize

    Returns:
        Sanitized copy of the dictionary
    """
    if not isinstance(data, dict):
        return data

    sanitized: dict[str, Any] = {}
    for key, value in data.items():
        try:
            # If key is sensitive, redact entirely
            if is_sensitive_key(key):
                sanitized[key] = SENSITIVE_PLACEHOLDER
            else:
                # Otherwise, scan the value for emails/tokens and recurse
                sanitized[key] = _sanitize_value(value)
        except Exception:
            # Fail closed: if anything raises during sanitization, use error placeholder
            sanitized[key] = SANITIZE_ERROR_PLACEHOLDER

    return sanitized


def _sanitize_processor(logger: Any, method: str, event_dict: EventDict) -> EventDict:
    """structlog processor that sanitizes all dict values in the event."""
    return cast(EventDict, sanitize_log_data(cast(dict[str, Any], event_dict)))


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
    return cast(structlog.stdlib.BoundLogger, structlog.get_logger(name))


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


def configure_logging_from_env() -> list["Sink"]:
    """Build log sinks from environment variables.

    Checks for the following env vars:
    - LOG_CLOUDWATCH_GROUP + LOG_CLOUDWATCH_STREAM: enables CloudWatchSink
    - LOG_GCP_PROJECT + LOG_GCP_LOG_NAME: enables GCPCloudLoggingSink
    - LOG_KAFKA_SERVERS + LOG_KAFKA_TOPIC: enables KafkaSink

    Returns:
        List of configured sink instances. Empty list if no env vars set.
    """
    import os

    from penguintechinc_utils.sinks import CloudWatchSink, GCPCloudLoggingSink, KafkaSink

    sinks: list[Sink] = []

    cw_group = os.environ.get("LOG_CLOUDWATCH_GROUP")
    cw_stream = os.environ.get("LOG_CLOUDWATCH_STREAM")
    if cw_group and cw_stream:
        sinks.append(CloudWatchSink(log_group=cw_group, log_stream=cw_stream))

    gcp_project = os.environ.get("LOG_GCP_PROJECT")
    gcp_log_name = os.environ.get("LOG_GCP_LOG_NAME")
    if gcp_project and gcp_log_name:
        sinks.append(GCPCloudLoggingSink(project_id=gcp_project, log_name=gcp_log_name))

    kafka_servers = os.environ.get("LOG_KAFKA_SERVERS")
    kafka_topic = os.environ.get("LOG_KAFKA_TOPIC")
    if kafka_servers and kafka_topic:
        sinks.append(KafkaSink(bootstrap_servers=kafka_servers, topic=kafka_topic))

    return sinks
