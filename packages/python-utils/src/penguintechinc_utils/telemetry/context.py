"""structlog processor that stamps the active OTel trace/span id onto each event.

Correlates log lines with distributed traces so a log record can be pivoted
to its trace in the observability backend, without requiring callers to pass
trace context explicitly.
"""

from __future__ import annotations

from opentelemetry import trace
from structlog.types import EventDict, WrappedLogger


def add_trace_context(logger: WrappedLogger, method_name: str, event_dict: EventDict) -> EventDict:
    """Inject `trace_id`/`span_id` (32/16 hex chars) when inside a recording span.

    A genuine no-op otherwise: with no active span, or an invalid/non-recording
    span context, the event dict is returned unmodified rather than stamping
    all-zero ids.
    """
    span = trace.get_current_span()
    ctx = span.get_span_context()
    if ctx.is_valid and span.is_recording():
        event_dict["trace_id"] = format(ctx.trace_id, "032x")
        event_dict["span_id"] = format(ctx.span_id, "016x")
    return event_dict


__all__: list[str] = ["add_trace_context"]
