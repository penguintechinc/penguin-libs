"""Thin passthroughs to the OTel API plus a span+histogram timing helper.

`get_tracer`/`get_meter` intentionally do no caching so callers always observe
whatever `TracerProvider`/`MeterProvider` is globally installed at call time
(including the SDK no-op default before `init()` runs). `timed` builds on top
of them to record a span and a millisecond duration histogram around a block
of code, usable as either a decorator or a context manager.
"""

from __future__ import annotations

import functools
import inspect
import time
from contextlib import AbstractContextManager, ContextDecorator
from typing import TYPE_CHECKING, Any, TypeVar, cast

from opentelemetry import metrics, trace

if TYPE_CHECKING:
    from collections.abc import Callable
    from types import TracebackType

    from opentelemetry.metrics import Meter
    from opentelemetry.trace import Span, Tracer

_INSTRUMENTATION_NAME = "penguintechinc_utils"

# Mirrors contextlib.ContextDecorator's own TypeVar so overriding __call__ keeps the
# "decorating a function returns that same function type" contract mypy checks.
_F = TypeVar("_F", bound="Callable[..., Any]")


def get_tracer(name: str) -> Tracer:
    """Return a `Tracer` for `name` from whichever `TracerProvider` is global now.

    A thin, uncached passthrough to `opentelemetry.trace.get_tracer` — never binds
    to a provider at import/construction time, so it also works before `init()`
    installs a real SDK provider (falling back to the OTel no-op implementation).
    """
    return trace.get_tracer(name)


def get_meter(name: str) -> Meter:
    """Return a `Meter` for `name` from whichever `MeterProvider` is global now.

    A thin, uncached passthrough to `opentelemetry.metrics.get_meter` — never binds
    to a provider at import/construction time, so it also works before `init()`
    installs a real SDK provider (falling back to the OTel no-op implementation).
    """
    return metrics.get_meter(name)


class timed(ContextDecorator):  # noqa: N801 -- mandated lowercase public decorator name
    """Time a block or function as a span plus a `<name>.duration` ms histogram.

    Usable as `@timed("op")` or `with timed("op"):`. `meter`/`tracer` default to
    `get_meter`/`get_tracer` resolved fresh on every entry (never cached on the
    instance), so a `timed(...)` built at import time still picks up the real
    provider once `init()` installs one later.

    Works on `async def` too, as `@timed(...)`, `with timed(...)` and
    `async with timed(...)`: the plain `ContextDecorator.__call__` would wrap only
    the *call* that builds the coroutine, reporting ~0ms for work that awaited for
    200ms, so `__call__` detects a coroutine function and times the await instead.

    Decorator reuse, recursion, and concurrent calls through the same decorated
    function are safe: `ContextDecorator` calls `_recreate_cm()` once per wrapped
    call, and this override hands back a brand-new `timed` instance each time, so
    no invocation ever shares `_start`/span state with another. Reusing the same
    instance directly as a context manager for *nested* or concurrent `with` /
    `async with` blocks is the one unsupported pattern — construct a separate
    `timed(...)` per nesting level (the decorator path does this for you).
    """

    __slots__ = ("_name", "_meter", "_tracer", "_start", "_span_cm")

    def __init__(
        self,
        name: str,
        meter: Meter | None = None,
        tracer: Tracer | None = None,
    ) -> None:
        """Configure the span/histogram name and optional explicit meter/tracer."""
        self._name = name
        self._meter = meter
        self._tracer = tracer
        self._start: float | None = None
        self._span_cm: AbstractContextManager[Span] | None = None

    def _recreate_cm(self) -> timed:
        """Return a fresh, unshared instance for each decorator-wrapped call.

        Keeps recursive and concurrent invocations of a decorated function from
        racing on shared `_start`/span attributes — each call gets its own object.
        """
        return timed(self._name, meter=self._meter, tracer=self._tracer)

    def __call__(self, func: _F) -> _F:
        """Decorate `func`, timing the awaited work when it is a coroutine function.

        `ContextDecorator.__call__` would wrap only the call that *builds* the
        coroutine, so an `async def` would report the microseconds spent creating it
        instead of the time it actually ran — wrong latency data, silently. Sync
        functions keep the inherited behaviour.
        """
        if not inspect.iscoroutinefunction(func):
            return super().__call__(func)

        @functools.wraps(func)
        async def _timed_async(*args: Any, **kwargs: Any) -> Any:
            with self._recreate_cm():
                return await func(*args, **kwargs)

        return cast("_F", _timed_async)

    async def __aenter__(self) -> timed:
        """Enter as an async context manager, so `async with timed(...)` works.

        The span is held across awaits via contextvars, which propagate within a
        task; without this, `async with` would simply raise TypeError.
        """
        return self.__enter__()

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> bool | None:
        """Exit the async context manager, recording duration and ending the span."""
        return self.__exit__(exc_type, exc_val, exc_tb)

    def __enter__(self) -> timed:
        """Start the span and the wall-clock timer for this invocation."""
        tracer = self._tracer or get_tracer(_INSTRUMENTATION_NAME)
        span_cm = cast("AbstractContextManager[Span]", tracer.start_as_current_span(self._name))
        span_cm.__enter__()
        self._span_cm = span_cm
        self._start = time.perf_counter()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> bool | None:
        """Record the duration histogram, then end the span (marking errors)."""
        start = self._start
        span_cm = self._span_cm
        self._start = None
        self._span_cm = None
        elapsed_ms = (time.perf_counter() - start) * 1000.0 if start is not None else 0.0
        meter = self._meter or get_meter(_INSTRUMENTATION_NAME)
        histogram = meter.create_histogram(
            f"{self._name}.duration",
            unit="ms",
            description=f"Duration of {self._name} in milliseconds",
        )
        histogram.record(elapsed_ms)
        if span_cm is None:
            return None
        # start_as_current_span defaults to record_exception=True and
        # set_status_on_exception=True, so propagating exc_info here is what marks
        # the span as errored and attaches the exception event.
        return span_cm.__exit__(exc_type, exc_val, exc_tb)


__all__: list[str] = ["get_tracer", "get_meter", "timed"]
