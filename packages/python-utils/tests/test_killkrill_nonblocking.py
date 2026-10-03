"""
Regression tests: KillKrillSink.emit must never perform network I/O on the
caller's thread, and close() must respect a hard shutdown budget.
"""

import logging
import threading
import time

import pytest

from penguintechinc_utils.killkrill import KillKrillConfig, KillKrillSink


def test_emit_returns_immediately_when_batch_full(monkeypatch: pytest.MonkeyPatch) -> None:
    """A full batch must signal the background thread, not block the caller."""
    config = KillKrillConfig(endpoint="http://localhost:1", batch_size=1, api_key="test-key")
    sink = KillKrillSink(config)

    def slow_flush(*_args: object, **_kwargs: object) -> None:
        time.sleep(0.3)

    monkeypatch.setattr(sink, "_flush", slow_flush)

    start = time.monotonic()
    sink.emit({"event": "a"})
    sink.emit({"event": "b"})
    elapsed = time.monotonic() - start

    assert elapsed < 0.1, "emit must not block on flush"

    sink.close(budget=1.0)


def test_emit_does_not_block_while_worker_is_mid_retry_backoff(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """emit stays instant even while the worker sits in a retry backoff sleep."""
    config = KillKrillConfig(endpoint="http://localhost:1", batch_size=1, api_key="test-key")
    sink = KillKrillSink(config)
    in_flush = threading.Event()

    def stuck_flush(*_args: object, **_kwargs: object) -> None:
        in_flush.set()
        time.sleep(0.5)

    monkeypatch.setattr(sink, "_flush", stuck_flush)
    sink.emit({"event": "trigger"})
    assert in_flush.wait(timeout=2), "worker never entered flush"

    start = time.monotonic()
    for i in range(50):
        sink.emit({"event": f"e{i}"})
    elapsed = time.monotonic() - start

    assert elapsed < 0.1, f"emit blocked for {elapsed:.3f}s while the worker was busy"
    sink.close(budget=1.0)


def test_close_respects_its_shutdown_budget(monkeypatch: pytest.MonkeyPatch) -> None:
    """close() must return within its budget even when flushing never completes.

    The exit path has to stay bounded: with default config an unreachable endpoint
    costs ~33s per delivery attempt, which would otherwise hang process exit.
    """
    config = KillKrillConfig(endpoint="http://localhost:1", batch_size=1, api_key="test-key")
    sink = KillKrillSink(config)

    def never_returns(*_args: object, **_kwargs: object) -> None:
        time.sleep(30)

    monkeypatch.setattr(sink, "_flush", never_returns)
    sink.emit({"event": "trigger"})
    time.sleep(0.1)  # let the worker enter the stuck flush

    start = time.monotonic()
    sink.close(budget=0.5)
    elapsed = time.monotonic() - start

    assert elapsed < 2.0, f"close took {elapsed:.2f}s despite a 0.5s budget"


def test_close_leaves_client_open_if_worker_is_still_running(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """The shared HTTP client must not be closed under a still-running worker.

    Closing it mid-request raises an error `_deliver_with_retry` does not catch,
    which kills the worker thread silently and loses the batch.
    """
    config = KillKrillConfig(endpoint="http://localhost:1", batch_size=1, api_key="test-key")
    sink = KillKrillSink(config)

    def never_returns(*_args: object, **_kwargs: object) -> None:
        time.sleep(30)

    monkeypatch.setattr(sink, "_flush", never_returns)
    sink.emit({"event": "trigger"})
    time.sleep(0.1)

    with caplog.at_level(logging.WARNING):
        sink.close(budget=0.2)

    assert not sink._client.is_closed, "client closed while the worker was still using it"
    assert any("still running" in r.message for r in caplog.records)


def test_close_drops_buffered_events_when_budget_is_exhausted(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Past the deadline, remaining events are dropped with a WARN, not retried."""
    config = KillKrillConfig(
        endpoint="http://localhost:1", batch_size=1000, flush_interval=30.0, api_key="test-key"
    )
    sink = KillKrillSink(config)
    sink.emit({"event": "unsent"})

    with caplog.at_level(logging.WARNING):
        sink.close(budget=0.0)

    assert any("dropping" in r.message for r in caplog.records)
    assert sink._client.is_closed
