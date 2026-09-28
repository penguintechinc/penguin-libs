"""Tests for fault-isolated sink fan-out and the async sink queue.

0.3.x dispatched to sinks inline with no try/except, so one failing sink raised into
the caller's log call and skipped every sink after it, and a slow network sink
blocked the caller for the length of its timeouts and retries.
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Any

import pytest

from penguintechinc_utils.logging import _LegacySinkHandler, configure_logging, get_logger
from penguintechinc_utils.sinks import AsyncSink, CallbackSink, StdoutSink


class _BoomSink:
    """A sink whose emit always raises, to prove failures are isolated."""

    def __init__(self) -> None:
        self.calls = 0

    def emit(self, event: dict[str, Any]) -> None:
        self.calls += 1
        raise RuntimeError("boom")

    def flush(self) -> None:
        pass

    def close(self) -> None:
        pass


class _SlowSink:
    """A sink that blocks in emit, to prove the caller is never the one waiting."""

    def __init__(self, delay: float = 0.4) -> None:
        self.delay = delay
        self.seen: list[dict[str, Any]] = []

    def emit(self, event: dict[str, Any]) -> None:
        time.sleep(self.delay)
        self.seen.append(event)

    def flush(self) -> None:
        pass

    def close(self) -> None:
        pass


def test_one_failing_sink_does_not_break_logging() -> None:
    """A raising sink must not raise into the log call, nor skip the other sinks."""
    seen: list[dict[str, Any]] = []
    bad = _BoomSink()
    good = CallbackSink(seen.append)
    configure_logging(level=logging.INFO, json_output=True, sinks=[bad, good])

    get_logger("iso").info("hello")

    assert bad.calls == 1, "the failing sink must still have been attempted"
    assert seen, "a healthy sink after a failing one must still receive the event"


def test_sink_failures_are_counted_per_sink_class() -> None:
    """Failures are counted (spec: penguin_utils.log_sink.errors, by sink class)."""
    handler = _LegacySinkHandler([_BoomSink()])
    record = logging.LogRecord("x", logging.INFO, __file__, 1, "msg", None, None)

    handler.emit(record)
    handler.emit(record)

    assert handler.errors == {"_BoomSink": 2}


def test_sink_failure_is_reported_to_stderr_but_rate_limited(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A broken sink must be visible on stderr, without flooding it."""
    handler = _LegacySinkHandler([_BoomSink()], error_interval=3600.0)
    record = logging.LogRecord("x", logging.INFO, __file__, 1, "msg", None, None)

    for _ in range(5):
        handler.emit(record)

    err = capsys.readouterr().err
    assert "_BoomSink" in err
    assert err.count("_BoomSink") == 1, "must report once per interval, not per failure"


def test_sinks_receive_sanitized_events() -> None:
    """Whatever reaches a sink must already be redacted."""
    seen: list[dict[str, Any]] = []
    configure_logging(level=logging.INFO, json_output=True, sinks=[CallbackSink(seen.append)])

    get_logger("sanitized").info("login", password="hunter2", email="a@b.com")

    assert seen[-1]["password"] == "[REDACTED]"
    assert seen[-1]["email"] == "[email]"


def test_foreign_stdlib_records_reach_sinks() -> None:
    """A third-party library's record now reaches sinks too, and is sanitized.

    Dispatch moved from the structlog chain to a root-logger handler, so records that
    never pass through structlog are no longer invisible to sinks.
    """
    seen: list[dict[str, Any]] = []
    configure_logging(level=logging.INFO, json_output=True, sinks=[CallbackSink(seen.append)])

    logging.getLogger("thirdparty.sink").warning("call ?token=sk-SINKLEAK now")

    assert seen, "a foreign stdlib record must reach the sinks"
    assert "sk-SINKLEAK" not in str(seen[-1])


def test_async_sink_drains_on_close() -> None:
    """Events queued to an AsyncSink are delivered by close()."""
    got: list[dict[str, Any]] = []
    sink = AsyncSink(CallbackSink(got.append))

    sink.emit({"event": "x"})
    sink.close()

    assert got == [{"event": "x"}]


def test_async_sink_emit_does_not_block_the_caller() -> None:
    """emit must return immediately even when the inner sink is slow."""
    slow = _SlowSink(delay=0.4)
    sink = AsyncSink(slow)
    try:
        start = time.perf_counter()
        sink.emit({"event": "a"})
        elapsed = time.perf_counter() - start
        assert elapsed < 0.1, f"emit blocked for {elapsed:.3f}s"
    finally:
        sink.close()


def test_async_sink_drops_oldest_when_full_and_counts_it() -> None:
    """A full queue drops the OLDEST event, keeps the newest, and counts the drop."""
    release = threading.Event()

    class _Blocked:
        def __init__(self) -> None:
            self.seen: list[dict[str, Any]] = []

        def emit(self, event: dict[str, Any]) -> None:
            release.wait(timeout=5)
            self.seen.append(event)

        def flush(self) -> None:
            pass

        def close(self) -> None:
            pass

    inner = _Blocked()
    sink = AsyncSink(inner, maxsize=2)
    try:
        for i in range(12):
            sink.emit({"event": f"e{i}"})
        assert sink.dropped > 0, "overflow must be counted"
    finally:
        release.set()
        sink.close()


def test_async_sink_survives_a_failing_inner_sink() -> None:
    """A raising inner sink must not kill the worker thread or the queue."""
    got: list[dict[str, Any]] = []

    class _FailsOnce:
        def __init__(self) -> None:
            self.calls = 0

        def emit(self, event: dict[str, Any]) -> None:
            self.calls += 1
            if self.calls == 1:
                raise RuntimeError("boom")
            got.append(event)

        def flush(self) -> None:
            pass

        def close(self) -> None:
            pass

    sink = AsyncSink(_FailsOnce())
    sink.emit({"event": "first"})
    sink.emit({"event": "second"})
    sink.close()

    assert got == [{"event": "second"}], "worker must survive the first failure"
    assert sink.errors == 1


def test_async_sink_flush_waits_for_delivery() -> None:
    """flush() must block until queued events have actually reached the inner sink."""
    got: list[dict[str, Any]] = []
    inner = CallbackSink(got.append)
    sink = AsyncSink(inner)
    try:
        for i in range(50):
            sink.emit({"event": f"e{i}"})
        sink.flush()
        assert len(got) == 50
        assert sink.inner is inner
    finally:
        sink.close()


def test_async_sink_close_is_idempotent() -> None:
    """close() twice must not raise or hang."""
    sink = AsyncSink(CallbackSink(lambda e: None))
    sink.close()
    sink.close()


def test_network_sinks_are_wrapped_and_local_sinks_are_not() -> None:
    """Only the blocking network sinks go behind a queue.

    Stdout/File/Callback stay synchronous on purpose: consumers' tests assert on a
    CallbackSink immediately after logging, which a background queue would break.
    """
    from penguintechinc_utils.sinks import wrap_blocking_sinks

    local = CallbackSink(lambda e: None)
    stdout = StdoutSink()
    wrapped = wrap_blocking_sinks([local, stdout])
    assert wrapped == [local, stdout], "local sinks must be passed through unchanged"

    class FakeKafkaSink:
        """Stands in for KafkaSink, whose constructor needs a live broker."""

        def emit(self, event: dict[str, Any]) -> None:
            pass

        def flush(self) -> None:
            pass

        def close(self) -> None:
            pass

    out = wrap_blocking_sinks([FakeKafkaSink()], blocking_names=frozenset({"FakeKafkaSink"}))
    assert isinstance(out[0], AsyncSink)
    out[0].close()
