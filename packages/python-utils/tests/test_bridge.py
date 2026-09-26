"""Tests for the OTel log/span bridge: sanitizing handler + span exporter wrapper."""

import logging

from opentelemetry.sdk._logs import LoggerProvider
from opentelemetry.sdk._logs.export import InMemoryLogRecordExporter, SimpleLogRecordProcessor
from opentelemetry.sdk.trace import Event, ReadableSpan, TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, SpanExportResult
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

import penguintechinc_utils.telemetry.bridge as bridge_mod
from penguintechinc_utils.telemetry.bridge import (
    SanitizingLogHandler,
    SanitizingSpanProcessorFactory,
    _SanitizingSpanExporter,
)


def _record(msg: object, args: object = None, **extra: object) -> logging.LogRecord:
    """Build a bare logging.LogRecord for direct _sanitize_record unit tests."""
    record = logging.LogRecord(
        name="t.bridge.unit",
        level=logging.INFO,
        pathname="test_bridge.py",
        lineno=1,
        msg=msg,
        args=args,
        exc_info=None,
    )
    for key, value in extra.items():
        setattr(record, key, value)
    return record


def _make_log_handler():
    """Build a LoggerProvider + InMemoryLogExporter wired to a SanitizingLogHandler."""
    lp = LoggerProvider()
    exp = InMemoryLogRecordExporter()
    lp.add_log_record_processor(SimpleLogRecordProcessor(exp))
    handler = SanitizingLogHandler(logger_provider=lp)
    return lp, exp, handler


def test_handler_redacts_email_in_message():
    """A plain-string message containing an email is redacted before export."""
    lp, exp, handler = _make_log_handler()
    logger = logging.getLogger("t.bridge.msg")
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    logger.info("login for eve@example.com")
    lp.force_flush()
    bodies = [r.log_record.body for r in exp.get_finished_logs()]
    assert bodies and all("eve@example.com" not in str(b) for b in bodies)


def test_handler_is_not_deprecated_sdk_class():
    """SanitizingLogHandler must subclass the non-deprecated instrumentation handler."""
    import opentelemetry.instrumentation.logging.handler as h

    assert issubclass(SanitizingLogHandler, h.LoggingHandler)


def test_handler_redacts_percent_style_args():
    """%-style positional args containing an email are redacted before formatting."""
    lp, exp, handler = _make_log_handler()
    logger = logging.getLogger("t.bridge.args")
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    logger.info("login for %s", "eve@example.com")
    lp.force_flush()
    bodies = [r.log_record.body for r in exp.get_finished_logs()]
    assert bodies and all("eve@example.com" not in str(b) for b in bodies)


def test_handler_redacts_dict_extra_attribute():
    """A dict passed via extra= is sanitized (sensitive key fully redacted)."""
    lp, exp, handler = _make_log_handler()
    logger = logging.getLogger("t.bridge.extra")
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    logger.info(
        "user context",
        extra={"user_info": {"email": "eve@example.com", "api_key": "sk-live-abc123"}},
    )
    lp.force_flush()
    records = exp.get_finished_logs()
    assert records
    attrs = records[0].log_record.attributes
    user_info = attrs["user_info"]
    assert "eve@example.com" not in str(user_info)
    assert "sk-live-abc123" not in str(user_info)


def test_handler_fails_closed_on_hostile_message(monkeypatch):
    """A sanitizer error on the message must not crash emit or leak the raw message."""

    def _boom(_value):
        raise RuntimeError("sanitizer exploded")

    monkeypatch.setattr(bridge_mod, "redact_text", _boom)

    lp, exp, handler = _make_log_handler()
    logger = logging.getLogger("t.bridge.hostile")
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    logger.info("super secret payload")
    lp.force_flush()
    bodies = [str(r.log_record.body) for r in exp.get_finished_logs()]
    assert bodies
    assert all("super secret payload" not in b for b in bodies)
    assert any("REDACTED" in b for b in bodies)


def test_span_processor_factory_returns_batch_processor():
    """Factory signature matches build_providers' span_processor_factory contract."""
    inner = InMemorySpanExporter()
    processor = SanitizingSpanProcessorFactory(inner)
    assert isinstance(processor, BatchSpanProcessor)


def test_span_exporter_redacts_attribute_email_and_sensitive_key():
    """Span attribute values containing an email, and api_key-named attrs, are redacted."""
    span = ReadableSpan(
        name="test-span",
        attributes={
            "user.email": "contact eve@example.com for access",
            "api_key": "sk-live-should-not-leak",
            "safe.value": "ok",
        },
    )
    inner = InMemorySpanExporter()
    wrapped = _SanitizingSpanExporter(inner)
    wrapped.export([span])
    exported = inner.get_finished_spans()
    assert len(exported) == 1
    attrs = exported[0].attributes
    assert "eve@example.com" not in attrs["user.email"]
    assert attrs["api_key"] == "[REDACTED]"
    assert attrs["safe.value"] == "ok"


def test_span_exporter_redacts_event_attributes():
    """Event attribute values are also redacted, not just top-level span attributes."""
    span = ReadableSpan(
        name="test-span-event",
        attributes={"safe": "ok"},
        events=(Event(name="login", attributes={"email": "bob@example.com"}),),
    )
    inner = InMemorySpanExporter()
    wrapped = _SanitizingSpanExporter(inner)
    wrapped.export([span])
    exported = inner.get_finished_spans()[0]
    assert len(exported.events) == 1
    event_attrs = exported.events[0].attributes
    assert "bob@example.com" not in str(event_attrs["email"])


def test_span_exporter_does_not_mutate_original_span():
    """The wrapper must not mutate the caller's span object in place."""
    original_attrs = {"api_key": "sk-live-should-not-leak"}
    span = ReadableSpan(name="immutable-check", attributes=original_attrs)
    inner = InMemorySpanExporter()
    wrapped = _SanitizingSpanExporter(inner)
    wrapped.export([span])
    # The original span's own attributes must be untouched.
    assert span.attributes["api_key"] == "sk-live-should-not-leak"


def test_span_processor_factory_end_to_end_redacts_via_real_tracer():
    """Full path: TracerProvider -> factory-built processor -> in-memory exporter."""
    inner = InMemorySpanExporter()
    tp = TracerProvider()
    tp.add_span_processor(SanitizingSpanProcessorFactory(inner))
    tracer = tp.get_tracer("t.bridge.e2e")
    with tracer.start_as_current_span("op") as span:
        span.set_attribute("api_key", "sk-live-real-tracer-secret")
        span.set_attribute("note", "reach alice@example.com")
    tp.force_flush()
    exported = inner.get_finished_spans()
    assert len(exported) == 1
    attrs = exported[0].attributes
    assert attrs["api_key"] == "[REDACTED]"
    assert "alice@example.com" not in attrs["note"]


def test_span_exporter_redacts_tuple_valued_attribute():
    """Sequence-valued attributes (stored as tuples by the SDK) are redacted per element."""
    span = ReadableSpan(name="tuple-attrs", attributes={"tags": ("safe", "eve@example.com")})
    inner = InMemorySpanExporter()
    wrapped = _SanitizingSpanExporter(inner)
    wrapped.export([span])
    tags = inner.get_finished_spans()[0].attributes["tags"]
    assert "eve@example.com" not in str(tags)


def test_sanitizing_span_exporter_delegates_shutdown_and_force_flush():
    """shutdown()/force_flush() delegate to the inner exporter (not swallowed/no-op)."""
    inner = InMemorySpanExporter()
    wrapped = _SanitizingSpanExporter(inner)
    assert wrapped.force_flush(1000) is True
    wrapped.shutdown()
    result = wrapped.export([ReadableSpan(name="after-shutdown")])
    assert result == SpanExportResult.FAILURE


def test_sanitize_attributes_fails_closed(monkeypatch):
    """_sanitize_attributes collapses to an error placeholder if sanitize_log_data raises."""

    def _boom(_data):
        raise RuntimeError("sanitizer exploded")

    monkeypatch.setattr(bridge_mod, "sanitize_log_data", _boom)
    result = bridge_mod._sanitize_attributes({"a": "b"})
    assert result == {"error": bridge_mod.SANITIZE_ERROR_PLACEHOLDER}


def test_sanitize_record_leaves_non_string_msg_untouched():
    """A non-string msg (e.g. a lazy/deferred object) is passed through unchanged."""
    record = _record(msg=12345)
    SanitizingLogHandler._sanitize_record(record)
    assert record.msg == 12345


def test_sanitize_record_dict_style_args_are_sanitized():
    """%(key)s-style logging (single dict arg) is sanitized via sanitize_log_data."""
    # LogRecord unwraps a lone dict-in-a-tuple into `.args` being the bare dict
    # (stdlib logging's %(key)s-style dict-arg convention).
    record = _record(msg="%(user)s logged in", args=({"user": "eve@example.com"},))
    assert isinstance(record.args, dict)
    SanitizingLogHandler._sanitize_record(record)
    assert "eve@example.com" not in str(record.args)


def test_sanitize_record_args_failure_fails_closed(monkeypatch):
    """If redact_text raises while sanitizing tuple args, args are cleared, not leaked."""

    def _boom(_value):
        raise RuntimeError("sanitizer exploded")

    monkeypatch.setattr(bridge_mod, "redact_text", _boom)
    record = _record(msg="static message", args=("eve@example.com",))
    SanitizingLogHandler._sanitize_record(record)
    assert record.args == ()


def test_sanitize_record_extras_failure_fails_closed(monkeypatch):
    """If sanitize_log_data raises on a dict extra, that extra is replaced, not left raw."""

    def _boom(_data):
        raise RuntimeError("sanitizer exploded")

    monkeypatch.setattr(bridge_mod, "sanitize_log_data", _boom)
    record = _record(msg="static message", args=None, custom={"a": 1})
    SanitizingLogHandler._sanitize_record(record)
    assert record.custom == {"error": bridge_mod.SANITIZE_ERROR_PLACEHOLDER}
