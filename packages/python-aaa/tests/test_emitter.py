"""Tests for penguin_aaa.audit.emitter — Emitter and AuditSink protocol."""

import pytest

from penguin_aaa.audit.emitter import AuditSink, Emitter


class _CollectingSink:
    """Test sink that records emitted events in a list."""

    def __init__(self):
        self.events: list[dict] = []
        self.flushed: bool = False
        self.closed: bool = False

    def emit(self, event: dict) -> None:
        self.events.append(event)

    def flush(self) -> None:
        self.flushed = True

    def close(self) -> None:
        self.closed = True


class _FailingSink:
    """Test sink that always raises on emit."""

    def emit(self, event: dict) -> None:
        raise RuntimeError("sink unavailable")

    def flush(self) -> None:
        pass

    def close(self) -> None:
        pass


class TestAuditSinkProtocol:
    def test_collecting_sink_satisfies_protocol(self):
        sink = _CollectingSink()
        assert isinstance(sink, AuditSink)

    def test_failing_sink_satisfies_protocol(self):
        sink = _FailingSink()
        assert isinstance(sink, AuditSink)


class TestEmitter:
    def test_requires_at_least_one_sink(self):
        with pytest.raises(ValueError, match="at least one sink"):
            Emitter()

    def test_emit_dispatches_to_single_sink(self):
        sink = _CollectingSink()
        emitter = Emitter(sink)
        event = {"type": "auth.success", "subject": "u1"}
        emitter.emit(event)
        assert sink.events == [event]

    def test_emit_dispatches_to_multiple_sinks(self):
        sink_a = _CollectingSink()
        sink_b = _CollectingSink()
        emitter = Emitter(sink_a, sink_b)
        event = {"type": "auth.success", "subject": "u1"}
        emitter.emit(event)
        assert sink_a.events == [event]
        assert sink_b.events == [event]

    def test_emit_raises_when_all_sinks_fail(self):
        fail_a = _FailingSink()
        fail_b = _FailingSink()
        emitter = Emitter(fail_a, fail_b)
        with pytest.raises(ExceptionGroup):
            emitter.emit({"type": "auth.failure"})

    def test_emit_succeeds_when_at_least_one_sink_works(self):
        good = _CollectingSink()
        bad = _FailingSink()
        emitter = Emitter(bad, good)
        event = {"type": "auth.success"}
        emitter.emit(event)  # should not raise
        assert good.events == [event]

    def test_flush_calls_all_sinks(self):
        sink_a = _CollectingSink()
        sink_b = _CollectingSink()
        emitter = Emitter(sink_a, sink_b)
        emitter.flush()
        assert sink_a.flushed is True
        assert sink_b.flushed is True

    def test_close_calls_all_sinks(self):
        sink_a = _CollectingSink()
        sink_b = _CollectingSink()
        emitter = Emitter(sink_a, sink_b)
        emitter.close()
        assert sink_a.closed is True
        assert sink_b.closed is True

    def test_flush_does_not_raise_on_sink_error(self):
        class BrokenFlushSink(_CollectingSink):
            def flush(self) -> None:
                raise RuntimeError("flush broken")

        emitter = Emitter(BrokenFlushSink())
        emitter.flush()  # should not raise

    def test_close_does_not_raise_on_sink_error(self):
        class BrokenCloseSink(_CollectingSink):
            def close(self) -> None:
                raise RuntimeError("close broken")

        emitter = Emitter(BrokenCloseSink())
        emitter.close()  # should not raise

    def test_multiple_events_emitted_in_order(self):
        sink = _CollectingSink()
        emitter = Emitter(sink)
        events = [{"type": "auth.success", "n": i} for i in range(5)]
        for e in events:
            emitter.emit(e)
        assert sink.events == events
