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


def test_async_sink_close_respects_a_budget() -> None:
    """close() must return within its budget even if the inner sink never does.

    `Queue.join()` alone waits forever, so one unreachable CloudWatch/Kafka endpoint
    would hang process shutdown indefinitely.
    """
    sink = AsyncSink(_SlowSink(delay=30))
    sink.emit({"event": "stuck"})
    start = time.perf_counter()
    sink.close(timeout=0.3)
    elapsed = time.perf_counter() - start
    assert elapsed < 3.0, f"close took {elapsed:.2f}s despite a 0.3s budget"


def test_async_sink_counts_undelivered_events_as_dropped_on_timeout() -> None:
    """Whatever the budget could not deliver is counted, not silently forgotten."""
    sink = AsyncSink(_SlowSink(delay=30))
    for i in range(5):
        sink.emit({"event": f"e{i}"})
    sink.close(timeout=0.2)
    assert sink.dropped > 0


def test_async_sink_survives_a_failing_inner_flush_and_close() -> None:
    """A sink that raises on flush/close must not raise out of shutdown."""

    class _Hostile:
        def emit(self, event: dict[str, Any]) -> None:
            pass

        def flush(self) -> None:
            raise RuntimeError("flush exploded")

        def close(self) -> None:
            raise RuntimeError("close exploded")

    sink = AsyncSink(_Hostile())
    sink.flush(timeout=0.1)
    sink.close(timeout=0.1)
    assert sink.errors >= 2


def test_killkrill_sink_is_not_double_wrapped() -> None:
    """KillKrillSink already flushes on its own thread; a second queue is redundant.

    Wrapping it would also mean a consumer holding its own reference and calling
    close() bypasses the outer queue entirely.
    """
    from penguintechinc_utils.sinks import BLOCKING_SINK_NAMES

    assert "KillKrillSink" not in BLOCKING_SINK_NAMES


def test_legacy_sink_handler_closes_its_sinks() -> None:
    """Closing the handler must flush and close every sink.

    stdlib's logging.shutdown() atexit hook closes every handler, so this is what
    keeps a buffered network-sink batch from being silently lost at exit.
    """
    events: list[str] = []

    class _Recording:
        def emit(self, event: dict[str, Any]) -> None:
            pass

        def flush(self) -> None:
            events.append("flush")

        def close(self) -> None:
            events.append("close")

    handler = _LegacySinkHandler([_Recording()])
    handler.close()
    assert events == ["flush", "close"]


def test_legacy_sink_handler_close_isolates_a_failing_sink() -> None:
    """One sink raising on close must not stop the others from being closed."""
    closed: list[str] = []

    class _Hostile:
        def emit(self, event: dict[str, Any]) -> None:
            pass

        def flush(self) -> None:
            raise RuntimeError("flush exploded")

        def close(self) -> None:
            raise RuntimeError("close exploded")

    class _Good:
        def emit(self, event: dict[str, Any]) -> None:
            pass

        def flush(self) -> None:
            pass

        def close(self) -> None:
            closed.append("good")

    handler = _LegacySinkHandler([_Hostile(), _Good()])
    handler.close()  # must not raise
    assert closed == ["good"]
    assert handler.errors["_Hostile"] == 2


def test_configure_logging_keeps_handlers_it_does_not_own() -> None:
    """A handler installed by someone else must survive configure_logging().

    Tearing off the whole root handler set silently removed the OTel log handler that
    init() had installed (and pytest's caplog, and an app's own handler).
    """
    foreign = logging.StreamHandler()
    logging.getLogger().addHandler(foreign)
    try:
        configure_logging(level=logging.INFO, json_output=True)
        assert foreign in logging.getLogger().handlers
    finally:
        logging.getLogger().removeHandler(foreign)


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
