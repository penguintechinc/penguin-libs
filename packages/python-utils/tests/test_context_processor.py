"""Tests for the OTel trace-context structlog processor."""

from __future__ import annotations

from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.trace import NonRecordingSpan, SpanContext, TraceFlags

from penguintechinc_utils.telemetry.context import add_trace_context


def test_injects_ids_inside_span() -> None:
    """Inside a recording span, trace_id/span_id are stamped as 32/16 hex chars."""
    # A local provider, never trace.set_tracer_provider(): the global provider can
    # only be set once per process, so claiming it here would silently break any
    # later test (notably init()'s) that needs to install its own.
    tracer = TracerProvider().get_tracer("t")
    span = tracer.start_span("s")
    with trace.use_span(span, end_on_exit=True):
        out = add_trace_context(None, "info", {"event": "x"})
    assert len(out["trace_id"]) == 32
    assert len(out["span_id"]) == 16


def test_noop_without_span() -> None:
    """With no active span, the event dict passes through unmodified."""
    out = add_trace_context(None, "info", {"event": "x"})
    assert "trace_id" not in out
    assert "span_id" not in out


def test_noop_for_valid_but_non_recording_span() -> None:
    """A sampled-out span carries a valid context but must not stamp ids.

    Recording is the gate, not validity: ids that point at a trace the backend
    never received would be dangling links.
    """
    ctx = SpanContext(
        trace_id=0x000000000000000000000000DEADBEEF,
        span_id=0x00000000DEADBEEF,
        is_remote=True,
        trace_flags=TraceFlags(TraceFlags.DEFAULT),
    )
    with trace.use_span(NonRecordingSpan(ctx), end_on_exit=False):
        out = add_trace_context(None, "info", {"event": "x"})
    assert "trace_id" not in out
    assert "span_id" not in out
