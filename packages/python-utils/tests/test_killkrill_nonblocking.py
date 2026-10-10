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


def test_close_closes_client_even_when_worker_is_still_running(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """close() must reclaim the client on every path, including a stuck worker.

    Leaving it open leaks the connection pool. Closing it under a still-running
    worker is safe here because this path drops the batch anyway and
    _deliver_with_retry catches the resulting error. This is the branch that
    failed off-3.13: a zero/short budget leaves the worker alive at join(), and the
    client must still end up closed rather than depending on scheduler timing.
    """
    config = KillKrillConfig(endpoint="http://localhost:1", batch_size=1, api_key="test-key")
    sink = KillKrillSink(config)

    def never_returns(*_args: object, **_kwargs: object) -> None:
        time.sleep(30)

    monkeypatch.setattr(sink, "_flush", never_returns)
    sink.emit({"event": "trigger"})
    time.sleep(0.1)  # let the worker enter the stuck flush so join() times out

    with caplog.at_level(logging.WARNING):
        sink.close(budget=0.2)

    assert sink._client.is_closed, "close() must reclaim the client, not leak it"
    assert any("dropping" in r.message for r in caplog.records)


def test_worker_survives_client_closed_mid_flight() -> None:
    """A real worker mid-delivery must not die with an uncaught traceback when the
    client is closed under it -- it drops the batch and exits cleanly.

    Guards the reconciliation of the 118-121 rationale: reclaiming the client is only
    safe because the delivery path swallows the "client closed" error. localhost:1
    refuses fast, so _deliver_with_retry is cycling through its retry/backoff when
    close() shuts the client.
    """
    config = KillKrillConfig(
        endpoint="http://localhost:1", batch_size=1, max_retries=5, api_key="test-key"
    )
    sink = KillKrillSink(config)
    sink.emit({"event": "trigger"})  # batch full -> worker starts real delivery
    time.sleep(0.1)

    sink.close(budget=0.2)

    assert sink._client.is_closed
    # The worker must have exited rather than crashed or spun; give it a moment.
    sink._flush_thread.join(timeout=2)
    assert not sink._flush_thread.is_alive(), "worker did not exit cleanly after client close"


def test_close_drops_buffered_events_when_budget_is_exhausted(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Past the deadline, remaining events are dropped with a WARN, not retried.

    A zero budget is the hard case: join(timeout=0) returns with the worker's
    liveness scheduler-dependent, yet the contract -- WARN + dropped + client
    reclaimed -- must hold identically on 3.11, 3.12 and 3.13.
    """
    config = KillKrillConfig(
        endpoint="http://localhost:1", batch_size=1000, flush_interval=30.0, api_key="test-key"
    )
    sink = KillKrillSink(config)
    sink.emit({"event": "unsent"})

    with caplog.at_level(logging.WARNING):
        sink.close(budget=0.0)

    assert any("dropping" in r.message for r in caplog.records)
    assert sink._client.is_closed


def test_deliver_drops_without_raising_when_client_closed(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A non-HTTP error (a closed client) drops the batch and never escapes.

    This is what keeps a worker mid-retry from dying with an uncaught traceback when
    close() reclaims the client under it.
    """
    config = KillKrillConfig(endpoint="http://localhost:1", api_key="test-key")
    sink = KillKrillSink(config)
    sink.close(budget=0.2)
    assert sink._client.is_closed

    with caplog.at_level(logging.WARNING):
        sink._deliver_with_retry([{"event": "x"}])  # must not raise

    assert any("no longer usable" in r.message for r in caplog.records)


def test_deliver_stops_retrying_at_the_shutdown_deadline(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """With a deadline already reached, delivery drops before sleeping on backoff.

    This is what makes the caller-thread final flush honour close()'s budget instead
    of running the full retry/backoff against a dead endpoint.
    """
    config = KillKrillConfig(endpoint="http://localhost:1", max_retries=5, api_key="test-key")
    sink = KillKrillSink(config)
    try:
        start = time.monotonic()
        with caplog.at_level(logging.WARNING):
            # deadline = now, so the first backoff would overshoot it -> drop, no sleep.
            sink._deliver_with_retry([{"event": "x"}], deadline=time.monotonic())
        assert time.monotonic() - start < 0.5, "retry slept past the deadline"
        assert any("deadline reached" in r.message for r in caplog.records)
    finally:
        sink.close(budget=0.5)
