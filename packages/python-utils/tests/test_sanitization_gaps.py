"""Regression tests for sanitization gaps only the assembled system exposes.

Each of these passed every per-task test suite in isolation and only surfaced when a
realistic logging idiom met a live OTel pipeline. They are kept together so the class
of bug -- "sanitized in one place, not in the place that actually ships the bytes" --
stays visible.
"""

from __future__ import annotations

import logging
import sys

from penguintechinc_utils.logging import sanitize_log_data
from penguintechinc_utils.telemetry.bridge import SanitizingLogHandler

SECRET = "sk-GAP-9999"


def _record(msg: object, args: object = None, exc_info: object = None) -> logging.LogRecord:
    """Build a bare stdlib record the way a third-party library's log call would."""
    return logging.LogRecord(
        "gaps",
        logging.ERROR,
        __file__,
        1,
        msg,
        args,
        exc_info,  # type: ignore[arg-type]
    )


def test_percent_style_arg_beside_a_sensitive_key_does_not_raise() -> None:
    """`log.warning("token=%s", val)` must not blow up in the caller's log call.

    Redacting `msg` and `args` as independent pieces deleted the only `%s` from the
    format string -- redaction matched it as the value of `token=` -- while `args`
    kept its element. `record.getMessage()` then raised TypeError out of the original
    caller, and neither emit() catches it.
    """
    record = _record("token=%s rejected", ("abc123XYZ",))

    SanitizingLogHandler._sanitize_record(record)

    rendered = record.getMessage()  # must not raise
    assert "abc123XYZ" not in rendered
    assert "[REDACTED]" in rendered


def test_percent_style_args_are_still_redacted_and_rendered() -> None:
    """Interpolating before redacting must not lose the argument values."""
    record = _record("user %s hit %s", ("bob", "https://x/y?token=" + SECRET))

    SanitizingLogHandler._sanitize_record(record)

    rendered = record.getMessage()
    assert "bob" in rendered
    assert SECRET not in rendered


def test_multiple_percent_args_survive() -> None:
    """A benign multi-argument format string must render exactly as before."""
    record = _record("%s took %d ms", ("op", 12))

    SanitizingLogHandler._sanitize_record(record)

    assert record.getMessage() == "op took 12 ms"


def test_exception_message_is_redacted_before_otel_sees_it() -> None:
    """A secret in an exception message must not reach OTLP attributes.

    OTel's LoggingHandler reads `record.exc_info` straight into
    exception.message/exception.stacktrace, which nothing was sanitizing.
    """
    try:
        raise ValueError(f"db connect failed with password={SECRET}")
    except ValueError:
        record = _record("operation failed", None, sys.exc_info())

    SanitizingLogHandler._sanitize_record(record)

    assert record.exc_info is None, "raw exc_info must not survive into the OTel path"
    assert SECRET not in (record.exc_text or "")
    assert "[REDACTED]" in (record.exc_text or "")
    assert "ValueError" in (record.exc_text or ""), "the exception type must survive"


def test_exception_object_in_a_field_is_redacted() -> None:
    """An exception instance reaching the sanitizer must be rendered and redacted.

    structlog's ProcessorFormatter injects raw `exc_info` into the event dict for
    foreign records, and `sanitize_log_data` only redacted `str` leaves -- so the
    exception passed through as an opaque object and was stringified, secret and all,
    at render time after sanitization had already run.
    """
    exc = ValueError(f"boom password={SECRET}")
    out = sanitize_log_data({"error": exc})
    assert SECRET not in str(out["error"])

    try:
        raise ValueError(f"boom token={SECRET}")
    except ValueError:
        out = sanitize_log_data({"exc_info": sys.exc_info()})
    assert SECRET not in str(out["exc_info"])


def test_sanitize_log_data_still_reports_the_exception_type() -> None:
    """Redacting an exception must not reduce it to an opaque placeholder."""
    out = sanitize_log_data({"error": ValueError("plain message")})
    assert "ValueError" in str(out["error"])
    assert "plain message" in str(out["error"])


def test_exception_sanitization_fails_closed(monkeypatch: object) -> None:
    """If rendering or redacting the exception raises, nothing raw survives.

    Fail-closed matters most here: this is the path that would otherwise hand a raw
    traceback straight to the exporter.
    """
    import penguintechinc_utils.telemetry.bridge as bridge_mod

    def _boom(_value: object) -> str:
        raise RuntimeError("renderer exploded")

    monkeypatch.setattr(bridge_mod, "format_exception_text", _boom)  # type: ignore[attr-defined]
    try:
        raise ValueError(f"boom password={SECRET}")
    except ValueError:
        record = _record("failed", None, sys.exc_info())

    SanitizingLogHandler._sanitize_record(record)

    assert record.exc_info is None
    assert record.exc_text == "[REDACTED:sanitize-error]"
    assert SECRET not in str(vars(record))


def test_structlog_dict_record_args_failure_fails_closed(monkeypatch: object) -> None:
    """A dict-msg (structlog) record whose args cannot be sanitized loses them."""
    import penguintechinc_utils.telemetry.bridge as bridge_mod

    def _boom(_value: object) -> str:
        raise RuntimeError("sanitizer exploded")

    monkeypatch.setattr(bridge_mod, "redact_text", _boom)  # type: ignore[attr-defined]
    record = _record({"event": "hi"}, ("eve@example.com",))

    SanitizingLogHandler._sanitize_record(record)

    assert record.args == ()
    assert "eve@example.com" not in str(vars(record))


def test_structlog_dict_record_keeps_its_event_dict() -> None:
    """A structlog record's dict msg must never be stringified by the sanitizer."""
    record = _record({"event": "hi", "password": "p"}, None)

    SanitizingLogHandler._sanitize_record(record)

    assert isinstance(record.msg, dict), "the event dict must stay a dict"
