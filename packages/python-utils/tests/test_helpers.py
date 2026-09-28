"""Tests for get_tracer/get_meter passthroughs and the timed decorator/CM helper."""

from __future__ import annotations

import time
from collections.abc import Iterator

import pytest
from opentelemetry import metrics, trace
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import InMemoryMetricReader
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from opentelemetry.trace import StatusCode

from penguintechinc_utils.telemetry.helpers import get_meter, get_tracer, timed


@pytest.fixture
def traced() -> Iterator[tuple[TracerProvider, InMemorySpanExporter]]:
    """Fresh SDK TracerProvider + in-memory exporter, restoring the global after."""
    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    yield provider, exporter


@pytest.fixture
def metered() -> Iterator[tuple[MeterProvider, InMemoryMetricReader]]:
    """Fresh SDK MeterProvider + in-memory reader for asserting recorded histograms."""
    reader = InMemoryMetricReader()
    provider = MeterProvider(metric_readers=[reader])
    yield provider, reader


def _histogram_data_points(reader: InMemoryMetricReader, name: str) -> list[object]:
    """Flatten every HistogramDataPoint recorded under `name` across all scopes."""
    data = reader.get_metrics_data()
    points: list[object] = []
    if data is None:
        return points
    for resource_metrics in data.resource_metrics:
        for scope_metrics in resource_metrics.scope_metrics:
            for metric in scope_metrics.metrics:
                if metric.name == name:
                    points.extend(metric.data.data_points)
    return points


def test_timed_context_manager_runs_body() -> None:
    """The wrapped block actually executes under a plain, un-configured timed()."""
    ran = {}
    with timed("op.test"):
        ran["yes"] = True
    assert ran["yes"]


def test_timed_decorator_returns_value() -> None:
    """Decorator usage preserves the wrapped function's return value."""

    @timed("op.dec")
    def add(a: int, b: int) -> int:
        return a + b

    assert add(2, 3) == 5


def test_get_tracer_and_meter_return_usable_objects() -> None:
    """The passthroughs must return something actually usable, not merely non-None."""
    assert get_tracer("t").start_span("s") is not None
    assert get_meter("m").create_histogram("h", unit="ms") is not None


def test_get_tracer_is_thin_passthrough_to_otel_api(monkeypatch: pytest.MonkeyPatch) -> None:
    """get_tracer delegates straight to `opentelemetry.trace.get_tracer`, uncached.

    Verified via monkeypatch on the real `opentelemetry.trace` module rather than
    `trace.set_tracer_provider()`, which can only succeed once per process — calling
    it here would permanently clobber the provider for every other test module.
    """
    sentinel = object()
    calls: list[str] = []

    def fake_get_tracer(name: str) -> object:
        calls.append(name)
        return sentinel

    monkeypatch.setattr(trace, "get_tracer", fake_get_tracer)
    assert get_tracer("my-tracer") is sentinel
    assert calls == ["my-tracer"]


def test_get_meter_is_thin_passthrough_to_otel_api(monkeypatch: pytest.MonkeyPatch) -> None:
    """get_meter delegates straight to `opentelemetry.metrics.get_meter`, uncached.

    Verified via monkeypatch rather than `metrics.set_meter_provider()`, which can
    only succeed once per process — calling it here would permanently clobber the
    provider for every other test module.
    """
    sentinel = object()
    calls: list[str] = []

    def fake_get_meter(name: str) -> object:
        calls.append(name)
        return sentinel

    monkeypatch.setattr(metrics, "get_meter", fake_get_meter)
    assert get_meter("my-meter") is sentinel
    assert calls == ["my-meter"]


def test_timed_records_span(
    traced: tuple[TracerProvider, InMemorySpanExporter],
) -> None:
    """A span named after the timed() block is created and ended."""
    provider, exporter = traced
    tracer = provider.get_tracer("test")
    with timed("op.span", tracer=tracer):
        pass
    spans = exporter.get_finished_spans()
    assert len(spans) == 1
    assert spans[0].name == "op.span"
    assert spans[0].end_time is not None


def test_timed_records_duration_histogram_in_ms(
    metered: tuple[MeterProvider, InMemoryMetricReader],
) -> None:
    """A `<name>.duration` histogram in milliseconds is recorded with one data point."""
    provider, reader = metered
    meter = provider.get_meter("test")
    with timed("op.hist", meter=meter):
        pass
    points = _histogram_data_points(reader, "op.hist.duration")
    assert len(points) == 1
    data = reader.get_metrics_data()
    assert data is not None
    found_unit = None
    for resource_metrics in data.resource_metrics:
        for scope_metrics in resource_metrics.scope_metrics:
            for metric in scope_metrics.metrics:
                if metric.name == "op.hist.duration":
                    found_unit = metric.unit
    assert found_unit == "ms"
    assert points[0].count == 1  # type: ignore[attr-defined]
    assert points[0].sum >= 0.0  # type: ignore[attr-defined]


def test_timed_exception_still_records_duration_and_propagates(
    traced: tuple[TracerProvider, InMemorySpanExporter],
    metered: tuple[MeterProvider, InMemoryMetricReader],
) -> None:
    """An exception in the block is not swallowed, the span errors, duration is recorded."""
    tracer_provider, exporter = traced
    meter_provider, reader = metered
    tracer = tracer_provider.get_tracer("test")
    meter = meter_provider.get_meter("test")

    with pytest.raises(ValueError, match="boom"):
        with timed("op.err", meter=meter, tracer=tracer):
            raise ValueError("boom")

    spans = exporter.get_finished_spans()
    assert len(spans) == 1
    assert spans[0].status.status_code == StatusCode.ERROR
    assert any(event.name == "exception" for event in spans[0].events)

    points = _histogram_data_points(reader, "op.err.duration")
    assert len(points) == 1
    assert points[0].count == 1  # type: ignore[attr-defined]


def test_timed_decorator_reused_across_calls_records_each_invocation(
    metered: tuple[MeterProvider, InMemoryMetricReader],
) -> None:
    """One timed() instance used as a decorator is not single-use.

    `_recreate_cm` hands each call its own fresh, unshared instance, so calling the
    decorated function twice records two separate histogram measurements rather than
    corrupting shared `_start`/span state on the decorator instance itself.
    """
    provider, reader = metered
    meter = provider.get_meter("test")
    instance = timed("op.reuse", meter=meter)

    @instance
    def work(x: int) -> int:
        return x * 2

    assert work(1) == 2
    assert work(2) == 4

    points = _histogram_data_points(reader, "op.reuse.duration")
    assert len(points) == 1
    assert points[0].count == 2  # type: ignore[attr-defined]


def test_timed_recreate_cm_returns_independent_instance() -> None:
    """`_recreate_cm()` yields a distinct object, never the shared decorator instance.

    This is what makes decorator reuse safe under recursion/concurrency: each call
    gets private `_start`/span state instead of racing on the same attributes.
    """
    instance = timed("op.identity")
    fresh = instance._recreate_cm()
    assert fresh is not instance
    assert isinstance(fresh, timed)


async def test_timed_decorator_times_the_awaited_work_not_coroutine_creation(
    metered: tuple[MeterProvider, InMemoryMetricReader],
) -> None:
    """@timed on an async def must measure the await, not the coroutine construction.

    ContextDecorator's own __call__ wraps only the call that builds the coroutine, so
    without an async-aware override a 200ms coroutine reported ~0ms -- silently wrong
    latency data, which is worse than no data.
    """
    import asyncio

    provider, reader = metered

    @timed("op.async", meter=provider.get_meter("t"))
    async def work() -> str:
        await asyncio.sleep(0.05)
        return "done"

    assert await work() == "done"

    points = _histogram_data_points(reader, "op.async.duration")
    assert len(points) == 1
    recorded = points[0].sum  # type: ignore[attr-defined]
    assert recorded >= 40, f"recorded {recorded}ms for a 50ms await"


async def test_timed_supports_async_with(
    metered: tuple[MeterProvider, InMemoryMetricReader],
) -> None:
    """`async with timed(...)` must work rather than raising TypeError."""
    import asyncio

    provider, reader = metered

    async with timed("op.awith", meter=provider.get_meter("t")):
        await asyncio.sleep(0.02)

    points = _histogram_data_points(reader, "op.awith.duration")
    assert len(points) == 1
    assert points[0].sum >= 10  # type: ignore[attr-defined]


async def test_timed_async_decorator_propagates_exceptions(
    metered: tuple[MeterProvider, InMemoryMetricReader],
) -> None:
    """An exception from an awaited body still records a duration and propagates."""
    provider, reader = metered

    @timed("op.async.boom", meter=provider.get_meter("t"))
    async def explode() -> None:
        raise ValueError("boom")

    with pytest.raises(ValueError, match="boom"):
        await explode()

    assert len(_histogram_data_points(reader, "op.async.boom.duration")) == 1


def test_timed_decorator_preserves_function_metadata() -> None:
    """Decoration must not rename the function or drop its docstring/signature."""
    import inspect

    @timed("op.meta")
    def documented(a: int, b: int = 2) -> int:
        """Add two numbers."""
        return a + b

    assert documented.__name__ == "documented"
    assert documented.__doc__ == "Add two numbers."
    assert list(inspect.signature(documented).parameters) == ["a", "b"]

    @timed("op.meta.async")
    async def documented_async(a: int) -> int:
        """Async add."""
        return a

    assert documented_async.__name__ == "documented_async"
    assert documented_async.__doc__ == "Async add."


def test_timed_decorator_is_thread_safe(
    metered: tuple[MeterProvider, InMemoryMetricReader],
) -> None:
    """N concurrent calls through one decorated function record N data points.

    The class docstring claims concurrent calls are safe because _recreate_cm hands
    each invocation its own instance; that claim needs a test, not just prose.
    """
    import threading

    provider, reader = metered
    threads_count = 20

    @timed("op.threads", meter=provider.get_meter("t"))
    def work() -> None:
        time.sleep(0.01)

    threads = [threading.Thread(target=work) for _ in range(threads_count)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    points = _histogram_data_points(reader, "op.threads.duration")
    assert len(points) == 1, "all recordings aggregate into one stream"
    assert points[0].count == threads_count  # type: ignore[attr-defined]


def test_timed_exit_without_enter_is_safe() -> None:
    """__exit__ with no matching __enter__ must not raise (defensive path)."""
    assert timed("op.bare").__exit__(None, None, None) is None
