"""Bridge stdlib log records and spans into OTel, sanitizing before export.

Wraps the non-deprecated OTel logging handler and a SpanExporter so that PII
and secrets are redacted before anything reaches an OTLP pipeline, reusing the
single sanitizer in `penguintechinc_utils.logging` (never reimplemented here).
"""

from __future__ import annotations

import logging
from collections.abc import Mapping, Sequence

from opentelemetry.instrumentation.logging.handler import LoggingHandler
from opentelemetry.sdk.trace import Event, ReadableSpan
from opentelemetry.sdk.trace.export import BatchSpanProcessor, SpanExporter, SpanExportResult

from ..logging import SANITIZE_ERROR_PLACEHOLDER, redact_text, sanitize_log_data


class SanitizingLogHandler(LoggingHandler):
    """OTel LoggingHandler that scrubs PII/secrets from a record before export.

    Subclasses the non-deprecated `opentelemetry.instrumentation.logging.handler.
    LoggingHandler` (never the deprecated `opentelemetry.sdk._logs.LoggingHandler`).
    Sanitizes `record.msg`, `record.args`, and any dict-valued extra attribute on
    the record in place before delegating to the parent's emit/translate pipeline.
    Fails closed per-field on any sanitize error so a broken sanitizer can never
    leak raw data or crash logging.
    """

    def emit(self, record: logging.LogRecord) -> None:
        """Sanitize the record in place, then delegate to LoggingHandler.emit."""
        self._sanitize_record(record)
        super().emit(record)

    @staticmethod
    def _sanitize_record(record: logging.LogRecord) -> None:
        """Redact record.msg, record.args, and dict-valued extras; fail closed per field."""
        try:
            if isinstance(record.msg, str):
                record.msg = redact_text(record.msg)
        except Exception:
            record.msg = SANITIZE_ERROR_PLACEHOLDER

        try:
            if isinstance(record.args, dict):
                record.args = sanitize_log_data(record.args)
            elif record.args:
                record.args = tuple(
                    redact_text(a) if isinstance(a, str) else a for a in record.args
                )
        except Exception:
            record.args = ()

        for key, value in list(vars(record).items()):
            if key in ("msg", "args") or not isinstance(value, dict):
                continue
            try:
                setattr(record, key, sanitize_log_data(value))
            except Exception:
                setattr(record, key, {"error": SANITIZE_ERROR_PLACEHOLDER})


def _normalize_attribute_value(value: object) -> object:
    """Convert tuple-shaped OTel attribute values to lists.

    OTel span/event attribute values are primitives or homogeneous sequences of
    primitives, stored as tuples by the SDK. `sanitize_log_data` only recurses
    into `list`, not `tuple` -- converting here lets its existing per-element
    string redaction apply to sequence-valued attributes without touching the
    sanitizer itself.
    """
    if isinstance(value, tuple):
        return list(value)
    return value


def _sanitize_attributes(attributes: Mapping[str, object] | None) -> dict[str, object]:
    """Redact sensitive keys/values in a span or event attribute mapping.

    Reuses `sanitize_log_data` (the same sanitizer used for logs) so span/event
    attribute redaction never drifts from the one sanitizer implementation.
    Fails closed: any error while sanitizing collapses the whole mapping to a
    single error placeholder rather than risking a partially-sanitized leak.
    """
    try:
        normalized = {k: _normalize_attribute_value(v) for k, v in (attributes or {}).items()}
        return sanitize_log_data(normalized)
    except Exception:
        return {"error": SANITIZE_ERROR_PLACEHOLDER}


class _SanitizingSpanExporter(SpanExporter):
    """Wraps a SpanExporter, redacting span + event attribute values before delegating.

    Builds sanitized *copies* of each span (via the public `ReadableSpan`/`Event`
    constructors) rather than mutating the caller's span objects in place -- spans
    may be shared across multiple registered SpanProcessors, so in-place mutation
    of `span._attributes` would leak into any other processor on the same provider.
    """

    def __init__(self, inner: SpanExporter) -> None:
        """Wrap `inner`; all export/shutdown/force_flush calls delegate to it."""
        self._inner = inner

    def export(self, spans: Sequence[ReadableSpan]) -> SpanExportResult:
        """Export sanitized copies of `spans` via the inner exporter."""
        return self._inner.export([self._sanitize_span(span) for span in spans])

    def shutdown(self) -> None:
        """Delegate shutdown to the inner exporter."""
        self._inner.shutdown()

    def force_flush(self, timeout_millis: int = 30000) -> bool:
        """Delegate force_flush to the inner exporter."""
        return self._inner.force_flush(timeout_millis)

    @staticmethod
    def _sanitize_span(span: ReadableSpan) -> ReadableSpan:
        """Return a new ReadableSpan with sanitized attributes and event attributes."""
        sanitized_events = tuple(
            Event(
                name=event.name,
                attributes=_sanitize_attributes(event.attributes),
                timestamp=event.timestamp,
            )
            for event in span.events
        )
        return ReadableSpan(
            name=span.name,
            context=span.context,
            parent=span.parent,
            resource=span.resource,
            attributes=_sanitize_attributes(span.attributes),
            events=sanitized_events,
            links=span.links,
            kind=span.kind,
            status=span.status,
            start_time=span.start_time,
            end_time=span.end_time,
            instrumentation_scope=span.instrumentation_scope,
        )


def SanitizingSpanProcessorFactory(inner_exporter: SpanExporter) -> BatchSpanProcessor:  # noqa: N802
    """Build a BatchSpanProcessor whose export path redacts span/event attributes first.

    PascalCase name is the mandated public interface consumed by downstream wiring
    (matches the `span_processor_factory` kwarg of `telemetry.providers.build_providers`:
    one SpanExporter argument in, one SpanProcessor out).
    """
    return BatchSpanProcessor(_SanitizingSpanExporter(inner_exporter))
