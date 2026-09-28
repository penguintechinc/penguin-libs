"""
Sanitized logging utilities for Penguin Tech applications.

Provides logging helpers that automatically sanitize sensitive data
to prevent accidental exposure of passwords, tokens, emails, etc.
Built on structlog for structured, production-ready logging.
"""

import functools
import logging
import re
import sys
import time
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

# Regex for email detection.
#
# The {1,64} / {1,255} bounds are the RFC 5321 4.5.3.1 limits on a local part and
# a domain, so nothing that is actually an address stops matching. They exist for
# cost, not validation: an unbounded greedy local part is retried at every offset
# of a long run of local-part-legal characters, which is quadratic -- a 40KB
# alphanumeric message (a base64 blob, a JWT, a stack trace) cost ~2.2s per
# redact_text call. Bounding the run makes each retry O(64) instead of O(n).
#
# A negative lookbehind looks like the cheaper fix and is NOT safe here: it tests
# the raw string, not "was this character already consumed", so when one address's
# domain runs straight into the next address's local part the second match is
# refused and the address leaks (`a@b.coma.b@x.co` kept `a.b@x.co` in full).
EMAIL_REGEX = re.compile(r"[a-zA-Z0-9._%+-]{1,64}@[a-zA-Z0-9.-]{1,255}\.[a-zA-Z]{2,}")

# Word-boundary splitter for key matching
_KEY_SPLIT = re.compile(r"[^a-z0-9]+")

# key=value / key: value scanner (query string, header, or inline free text).
# Sensitivity is decided by is_sensitive_key -- the SAME function the structured
# dict-field path uses -- so there is exactly one source of truth for what counts
# as sensitive, never a second word list.
#
# The scan is driven from SEPARATORS, not from keys, and that choice is what keeps
# the cost down. A key/value pair always contains a ":" or "=", and a bare
# character-class search for one cannot backtrack, so a message with no separator
# at all -- a stack trace, a base64 blob, ordinary prose -- costs one linear pass
# and nothing more. Searching for the key instead means retrying a greedy
# character class at every offset: with that shape an 80KB message cost ~1s, and
# before the value was also split out of it, ~7.8s.
_SEP_FIND = re.compile(r"[:=]")

# The key, anchored to the END of the short window immediately before a separator.
# Optional surrounding quotes, so a JSON/repr key ('"token":') is seen too;
# is_sensitive_key splits on non-alphanumerics, so the quotes fall out of the
# judgement for free -- no second word list, no stripping. Trailing \s* allows
# "token = x". {1,128} bounds the window work; real keys are far shorter.
_KEY_END = re.compile(r"(['\"]?[A-Za-z0-9_.\-]{1,128}['\"]?)\s*\Z")

# How far back from a separator a key is looked for. Longer than any real key, so
# the only thing the bound costs is that an absurdly long key gets judged on its
# last 160 characters -- which is the end that carries the sensitive word
# ("stripe_api_key"), so the judgement is unaffected in practice.
_MAX_KEY_SPAN = 160

# Characters the separator run may absorb after the ":"/"=" itself: whitespace
# (newlines included, so a value on the next line is still reached) and then any
# run of opening quotes, so replacing the value leaves the quoting intact and
# 'token=""x""' cannot hide x behind the quotes.
_SEP_CHARS = ":="
_QUOTE_CHARS = "'\""

# The value of a SENSITIVE key only. Deliberately permissive -- it stops just at
# whitespace and the , ; & # separators that end a field -- because for a key we
# already judged sensitive, over-redaction is the safe direction and a narrow
# class is how secrets escape: excluding quotes and brackets let
# 'token=""secret""' and an escaped '{"token": "\"secret\""}' slip through whole.
# Allowing =, /, + also means a base64 secret (incl. "==" padding) redacts in full
# rather than as a truncated "token=[REDACTED]Iz==" still exposing part of it.
# A benign key's value is never matched with this at all.
_VALUE = re.compile(
    r"(?:Bearer|Basic|Digest|Token)\s+[^\s&#,;]+|[^\s&#,;]+",
    re.IGNORECASE,
)

# Structural characters trimmed back off the end of a redacted value and re-emitted
# after the placeholder, so redacting inside JSON leaves the JSON parseable.
_VALUE_TRAILING = "'\"})]"


def _end_of_separator(value: str, start: int) -> int:
    """
    Return the index just past the separator run beginning at `start`.

    Scanned by hand rather than with a regex so the caller never has to handle an
    impossible no-match case: `start` always points at a ":" or "=", so the result
    is always greater than `start` and redact_text's scan always advances.
    """
    end = start
    length = len(value)
    while end < length and value[end] in _SEP_CHARS:
        end += 1
    while end < length and value[end].isspace():
        end += 1
    while end < length and value[end] in _QUOTE_CHARS:
        end += 1
    return end


@functools.lru_cache(maxsize=8)
def _sensitive_segments(keys: frozenset[str]) -> tuple[tuple[str, ...], ...]:
    """
    Split each sensitive key into its word segments, once per distinct key set.

    Cached because is_sensitive_key is called for every key in every log event and
    for every key/value pair inside every message: re-splitting the whole word list
    per call dominated redaction cost (~550ms for an 80KB message of "k=" pairs).
    Keyed on the frozenset itself, so replacing SENSITIVE_KEYS is still picked up.
    """
    return tuple(tuple(s for s in _KEY_SPLIT.split(key) if s) for key in keys)


@functools.lru_cache(maxsize=4096)
def _is_sensitive_key(key: str, keys: frozenset[str]) -> bool:
    """
    Decide whether `key` names a secret, memoised per (key, sensitive-key-set).

    The result is a pure function of its inputs and the same handful of field and
    query-parameter names recur constantly, so memoising turns the hot path of both
    the dict and the free-text scanners into a dict lookup. `keys` is part of the
    cache key, so replacing SENSITIVE_KEYS never serves a stale answer.
    """
    key_segments = [s for s in _KEY_SPLIT.split(key.lower()) if s]

    # For each sensitive key, check if its segments appear as a contiguous run
    for sensitive_segments in _sensitive_segments(keys):
        width = len(sensitive_segments)
        for i in range(len(key_segments) - width + 1):
            if tuple(key_segments[i : i + width]) == sensitive_segments:
                return True

    return False


def is_sensitive_key(key: str) -> bool:
    """
    Check if a key names a secret (word-boundary match, not substring).

    Matches on contiguous segment subsequence: "stripe_api_key" contains ["api", "key"].

    Args:
        key: Key name to check

    Returns:
        True if key contains a sensitive segment sequence
    """
    return _is_sensitive_key(key, SENSITIVE_KEYS)


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

    # Scanned with an explicit cursor rather than re.sub for two reasons. A benign
    # key must not consume what follows it ("note: password=hunter2" -- the inner
    # pair needs its own chance to match), and the value is only worth matching
    # once the key is known to be sensitive. Resuming just past the separator on a
    # benign key gives both. Recursing instead, as an earlier revision did, blew
    # CPython's C stack on a long "k=k=...=token=secret" chain. The cursor strictly
    # increases every iteration -- key and separator are both non-empty -- so the
    # loop always terminates.
    parts: list[str] = []
    pos = 0
    while (hit := _SEP_FIND.search(value, pos)) is not None:
        sep_start = hit.start()
        window_start = max(pos, sep_start - _MAX_KEY_SPAN)
        key_match = _KEY_END.search(value[window_start:sep_start])
        if key_match is None:
            # A separator with no key in front of it ("://", "::", a bare ":").
            parts.append(value[pos : sep_start + 1])
            pos = sep_start + 1
            continue
        key = key_match.group(1)
        key_start = window_start + key_match.start(1)
        parts.append(value[pos:key_start])
        pos = _end_of_separator(value, sep_start)
        parts.append(value[key_start:pos])
        if not is_sensitive_key(key):
            continue
        found = _VALUE.match(value, pos)
        if found is None:
            continue
        raw = found.group(0)
        pos = found.end()
        if raw.startswith((SENSITIVE_PLACEHOLDER, SANITIZE_ERROR_PLACEHOLDER)):
            # Already redacted: re-redacting would chip the placeholder's own
            # closing bracket off and append another, so redact_text stays
            # idempotent only by leaving it alone.
            parts.append(raw)
            continue
        kept = raw.rstrip(_VALUE_TRAILING)
        parts.append(SENSITIVE_PLACEHOLDER + raw[len(kept) :])
    parts.append(value[pos:])
    return "".join(parts)


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


class _LegacySinkHandler(logging.Handler):
    """
    Fan a stdlib record out to the 0.3.x sinks, isolating each sink's failures.

    0.3.x dispatched from inside the structlog chain with no try/except, so one
    failing sink raised into the caller's log call and every sink after it was
    skipped. Here a failure is counted per sink class and reported to stderr at most
    once per interval, so a broken sink is visible without flooding the very output
    stream it is failing to write to. Sitting on the root logger also means
    third-party records reach sinks, which the structlog-chain version could not do.

    Args:
        sinks: Sinks to deliver each record to.
        error_interval: Minimum seconds between stderr reports about a given sink.
    """

    def __init__(self, sinks: Sequence["Sink"], error_interval: float = 60.0) -> None:
        super().__init__()
        self._sinks = list(sinks)
        self._error_interval = error_interval
        self.errors: dict[str, int] = {}
        self._last_reported: dict[str, float] = {}

    def emit(self, record: logging.LogRecord) -> None:
        """Deliver a sanitized copy of the record to every sink, isolating failures."""
        event = record.msg
        payload = event if isinstance(event, dict) else {"event": record.getMessage()}
        for sink in self._sinks:
            name = type(sink).__name__
            try:
                sink.emit(sanitize_log_data(dict(payload)))
            except Exception as exc:
                self.errors[name] = self.errors.get(name, 0) + 1
                self._report(name, exc)

    def _report(self, name: str, exc: Exception) -> None:
        """Write a rate-limited note to stderr that a sink is failing."""
        now = time.monotonic()
        if now - self._last_reported.get(name, -self._error_interval) < self._error_interval:
            return
        self._last_reported[name] = now
        print(
            f"penguin-utils: log sink {name} failed ({type(exc).__name__}): {exc}",
            file=sys.stderr,
        )


def _shared_processors() -> list[Processor]:
    """
    Build the processor chain applied to structlog events AND foreign stdlib records.

    Imported lazily rather than at module scope because `telemetry` imports back
    into this module; deferring to call time breaks the cycle. The same list is
    reused as ProcessorFormatter's `foreign_pre_chain`, which is the only thing
    that sanitizes records from third-party libraries -- they never pass through
    structlog's own chain.
    """
    from .telemetry.context import add_trace_context

    return [
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        structlog.processors.TimeStamper(fmt="iso"),
        add_trace_context,
        _sanitize_processor,
    ]


def configure_logging(
    level: int = logging.INFO,
    json_output: bool = False,
    sinks: Sequence["Sink"] | None = None,
) -> None:
    """
    Configure structlog to render through stdlib logging. Logs only; call init() for OTel.

    structlog events are routed to the stdlib root logger via ProcessorFormatter,
    so one handler set (console, the 0.3.x sinks, and -- once init() runs -- the
    OTel bridge) serves both our own events and any third-party library's. `level`
    is applied to the root logger, so unlike 0.3.x it actually filters.

    Replaces any handlers already on the root logger, rather than adding to them:
    this owns the root handler set, so a caller that installed its own handler
    beforehand loses it. Calling this repeatedly is therefore safe and never
    doubles output.

    Network-bound sinks (CloudWatch/GCP/Kafka/KillKrill) are automatically put
    behind a bounded background queue so they cannot block a log call; stdout, file
    and callback sinks stay synchronous.

    Args:
        level: Minimum logging level (default: INFO). Now enforced.
        json_output: Render as JSON lines when True, console format when False.
        sinks: Optional sequence of Sink instances to receive every event.
    """
    from .sinks import wrap_blocking_sinks

    shared = _shared_processors()
    renderer: Processor = (
        structlog.processors.JSONRenderer()
        if json_output
        else structlog.dev.ConsoleRenderer(colors=False)
    )
    formatter = structlog.stdlib.ProcessorFormatter(
        processor=renderer,
        foreign_pre_chain=shared,
    )

    root = logging.getLogger()
    for handler in list(root.handlers):
        root.removeHandler(handler)
    console = logging.StreamHandler()
    console.setFormatter(formatter)
    root.addHandler(console)
    if sinks:
        root.addHandler(_LegacySinkHandler(wrap_blocking_sinks(sinks)))
    root.setLevel(level)

    processors: list[Processor] = list(shared)
    processors.append(structlog.stdlib.ProcessorFormatter.wrap_for_formatter)

    structlog.configure(
        processors=processors,
        wrapper_class=structlog.stdlib.BoundLogger,
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )


def get_logger(name: str | None = None, level: int | None = None) -> structlog.stdlib.BoundLogger:
    """
    Get a structlog BoundLogger routed through stdlib logging.

    `level` defaults to None rather than INFO: forcing a per-logger level here is
    what made 0.3.x print DEBUG regardless of configuration, and it would override
    the root level set by configure_logging.

    Args:
        name: Logger name (usually __name__ or component name).
        level: Optional per-logger level override; left untouched when None.

    Returns:
        Configured structlog BoundLogger instance.
    """
    if level is not None:
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
