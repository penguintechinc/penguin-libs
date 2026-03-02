"""Audit emitter — fan-out to multiple sinks with error aggregation."""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class AuditSink(Protocol):
    """Protocol that all audit sinks must satisfy."""

    def emit(self, event: dict[str, Any]) -> None:
        """Persist or transmit a single audit event.

        Args:
            event: A plain dictionary representation of an AuditEvent.
        """
        ...

    def flush(self) -> None:
        """Flush any buffered events to the underlying destination."""
        ...

    def close(self) -> None:
        """Release resources held by the sink."""
        ...


class Emitter:
    """Fan-out emitter that dispatches audit events to multiple sinks.

    On ``emit``, each sink is called in registration order. Individual sink
    failures are collected; if every sink fails the aggregate exception list
    is raised as an ``ExceptionGroup``. If at least one sink succeeds, errors
    from failing sinks are silently swallowed — callers can wrap the emitter
    with additional error handling if partial delivery is unacceptable.

    Args:
        *sinks: One or more objects satisfying the AuditSink protocol.
    """

    def __init__(self, *sinks: AuditSink) -> None:
        if not sinks:
            raise ValueError("Emitter requires at least one sink")
        self._sinks = list(sinks)

    def emit(self, event: dict[str, Any]) -> None:
        """Dispatch an event to all registered sinks.

        Args:
            event: Serialized audit event (typically from AuditEvent.to_dict()).

        Raises:
            ExceptionGroup: If every sink raises an exception.
        """
        errors: list[Exception] = []
        for sink in self._sinks:
            try:
                sink.emit(event)
            except Exception as exc:
                errors.append(exc)

        if errors and len(errors) == len(self._sinks):
            raise ExceptionGroup("All audit sinks failed", errors)

    def flush(self) -> None:
        """Flush all sinks, collecting but not raising per-sink errors."""
        for sink in self._sinks:
            try:
                sink.flush()
            except Exception:
                pass

    def close(self) -> None:
        """Close all sinks, collecting but not raising per-sink errors."""
        for sink in self._sinks:
            try:
                sink.close()
            except Exception:
                pass
