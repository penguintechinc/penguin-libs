"""Tests for structlog rendering through stdlib logging.

The rewire is what lets a sanitizing OTel handler, the console handler and the
0.3.x sinks all hang off one root logger, and it is what finally makes `level`
actually filter.
"""

from __future__ import annotations

import json
import logging

import pytest
import structlog

from penguintechinc_utils.logging import configure_logging, get_logger


def _captured(capsys: pytest.CaptureFixture[str]) -> str:
    """Return everything written to stdout+stderr so far, as one string."""
    out = capsys.readouterr()
    return out.out + out.err


def test_get_logger_returns_bound_logger() -> None:
    """get_logger still hands back structlog's lazy proxy over a stdlib BoundLogger.

    The proxy type is the published 0.3.x return value; `.bind()` resolves it to
    the configured wrapper class, which is what must now be the stdlib one.
    """
    configure_logging(level=logging.INFO, json_output=True)
    log = get_logger("x")
    assert isinstance(log.bind(), structlog.stdlib.BoundLogger)


def test_records_reach_stdlib_root() -> None:
    """configure_logging must attach a stdlib handler, not print past logging."""
    configure_logging(level=logging.INFO, json_output=True)
    assert logging.getLogger().handlers


def test_level_is_enforced(capsys: pytest.CaptureFixture[str]) -> None:
    """A DEBUG line is dropped at INFO -- the 0.3.x bug was that it always printed."""
    configure_logging(level=logging.INFO, json_output=True)
    log = get_logger("lvl")
    log.debug("should_be_filtered")
    log.info("should_appear")
    text = _captured(capsys)
    assert "should_be_filtered" not in text
    assert "should_appear" in text


def test_debug_level_lets_debug_through(capsys: pytest.CaptureFixture[str]) -> None:
    """Enforcement cuts both ways: at DEBUG the same line must appear."""
    configure_logging(level=logging.DEBUG, json_output=True)
    get_logger("lvl2").debug("debug_visible")
    assert "debug_visible" in _captured(capsys)


def test_json_output_is_parseable_json(capsys: pytest.CaptureFixture[str]) -> None:
    """json_output=True renders one JSON object per line with the standard fields."""
    configure_logging(level=logging.INFO, json_output=True)
    get_logger("jsonlog").info("hello")
    line = [ln for ln in _captured(capsys).splitlines() if "hello" in ln][-1]
    payload = json.loads(line)
    assert payload["event"] == "hello"
    assert payload["level"] == "info"
    assert payload["logger"] == "jsonlog"
    assert payload["timestamp"]


def test_console_output_is_not_json(capsys: pytest.CaptureFixture[str]) -> None:
    """json_output=False renders the human console format instead."""
    configure_logging(level=logging.INFO, json_output=False)
    get_logger("consolelog").info("hello_console")
    assert "hello_console" in _captured(capsys)


def test_structlog_event_is_sanitized(capsys: pytest.CaptureFixture[str]) -> None:
    """The structlog path still redacts sensitive fields after the rewire."""
    configure_logging(level=logging.INFO, json_output=True)
    get_logger("san").info("login", password="hunter2", email="alice@example.com")
    text = _captured(capsys)
    assert "hunter2" not in text
    assert "alice@example.com" not in text
    assert "[REDACTED]" in text


def test_foreign_stdlib_record_is_rendered_and_sanitized(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A third-party library logging via stdlib is rendered AND redacted.

    Third-party records never pass through structlog's chain, so the
    ProcessorFormatter's foreign_pre_chain is the only thing that redacts them.
    """
    configure_logging(level=logging.INFO, json_output=True)
    logging.getLogger("thirdparty").warning("call ?token=sk-FOREIGNLEAK for bob@example.com")
    text = _captured(capsys)
    assert "sk-FOREIGNLEAK" not in text
    assert "bob@example.com" not in text
    assert "thirdparty" in text


def test_trace_context_is_added_inside_span(capsys: pytest.CaptureFixture[str]) -> None:
    """Log lines emitted inside a recording span carry trace_id/span_id."""
    from opentelemetry import trace
    from opentelemetry.sdk.trace import TracerProvider

    configure_logging(level=logging.INFO, json_output=True)
    span = TracerProvider().get_tracer("t").start_span("s")
    with trace.use_span(span, end_on_exit=True):
        get_logger("traced").info("in_span")
    line = [ln for ln in _captured(capsys).splitlines() if "in_span" in ln][-1]
    payload = json.loads(line)
    assert len(payload["trace_id"]) == 32
    assert len(payload["span_id"]) == 16


def test_reconfiguring_does_not_stack_console_handlers() -> None:
    """Calling configure_logging twice must not double every log line."""
    configure_logging(level=logging.INFO, json_output=True)
    first = len(logging.getLogger().handlers)
    configure_logging(level=logging.INFO, json_output=True)
    assert len(logging.getLogger().handlers) == first


def test_exception_logging_still_renders_a_traceback(capsys: pytest.CaptureFixture[str]) -> None:
    """log.exception must still produce a traceback after the rewire."""
    configure_logging(level=logging.INFO, json_output=False)
    try:
        raise ZeroDivisionError("boom")
    except ZeroDivisionError:
        get_logger("exc").exception("failed_op")
    text = _captured(capsys)
    assert "failed_op" in text
    assert "ZeroDivisionError" in text
