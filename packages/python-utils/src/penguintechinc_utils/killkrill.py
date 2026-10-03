"""
KillKrill sink — ships structured log events to the KillKrill log aggregation service.

Events are buffered in memory and flushed by a background thread either when
the batch fills up or the flush interval elapses. Failed flushes are retried
with exponential backoff up to max_retries times before the batch is dropped.
"""

import json
import logging
import threading
import time
from dataclasses import dataclass, field
from typing import Any

import httpx

logger = logging.getLogger(__name__)

# Total seconds close() may spend draining. Matches the design spec's hard 5s
# atexit flush budget: process exit must never hang on an unreachable collector.
SHUTDOWN_BUDGET = 5.0


@dataclass(slots=True)
class KillKrillConfig:
    """
    Configuration for the KillKrill log aggregation sink.

    Attributes:
        endpoint: Base URL of the KillKrill service (e.g. "https://logs.example.io").
        api_key: Bearer token used to authenticate with the service.
        batch_size: Maximum number of events per HTTP request (default: 100).
        flush_interval: Seconds between automatic flushes (default: 5.0).
        use_grpc: Reserved for future gRPC transport support (default: False).
        timeout: HTTP request timeout in seconds (default: 10.0).
        max_retries: Maximum delivery attempts per batch before dropping (default: 3).
    """

    endpoint: str
    api_key: str
    batch_size: int = 100
    flush_interval: float = 5.0
    use_grpc: bool = False
    timeout: float = 10.0
    max_retries: int = 3


@dataclass
class _Buffer:
    """Thread-safe event buffer."""

    events: list[dict[str, Any]] = field(default_factory=list)
    lock: threading.Lock = field(default_factory=threading.Lock)


class KillKrillSink:
    """
    Buffers log events and ships them in batches to the KillKrill service.

    A background daemon thread wakes every flush_interval seconds and sends
    any buffered events. The buffer is also flushed eagerly when it reaches
    batch_size. Call close() for a clean shutdown that flushes remaining events.

    Args:
        config: KillKrillConfig describing the remote endpoint and tuning knobs.
    """

    def __init__(self, config: KillKrillConfig) -> None:
        self._config = config
        self._buffer = _Buffer()
        self._client = httpx.Client(
            headers={
                "Authorization": f"Bearer {config.api_key}",
                "Content-Type": "application/json",
            },
            timeout=config.timeout,
        )
        self._stop_event = threading.Event()
        self._flush_now = threading.Event()
        self._flush_thread = threading.Thread(
            target=self._flush_loop,
            name="killkrill-flush",
            daemon=True,
        )
        self._flush_thread.start()

    # ------------------------------------------------------------------
    # Sink Protocol
    # ------------------------------------------------------------------

    def emit(self, event: dict[str, Any]) -> None:
        """Buffer an event, signalling the background thread if the batch is full.

        Never performs network I/O on the caller's thread — a full batch only
        sets an Event that the background flush loop wakes up on.
        """
        with self._buffer.lock:
            self._buffer.events.append(event)
            should_flush = len(self._buffer.events) >= self._config.batch_size

        if should_flush:
            self._flush_now.set()

    def flush(self) -> None:
        """Flush all buffered events to the remote service."""
        self._flush()

    def close(self, budget: float = SHUTDOWN_BUDGET) -> None:
        """Stop the background thread and flush remaining events within `budget`.

        Bounded by one deadline for the whole call, because this runs on the
        process's exit path: with default config an unreachable endpoint costs
        10+1+10+2+10s per delivery attempt, so an unbounded join plus a final flush
        could hang exit for ~44s. Past the deadline the remaining batch is dropped
        with a WARN rather than retried.

        The client is only closed once the worker has actually exited. Closing it
        while the worker is mid-request would fail that request with an error
        `_deliver_with_retry` does not catch, killing the thread silently.

        Args:
            budget: Total seconds allowed for draining and stopping.
        """
        deadline = time.monotonic() + budget
        self._stop_event.set()
        self._flush_now.set()
        self._flush_thread.join(timeout=max(0.0, deadline - time.monotonic()))

        if self._flush_thread.is_alive():
            logger.warning(
                "KillKrillSink: flush thread still running after %.1fs; "
                "leaving the client open and dropping any buffered events",
                budget,
            )
            return

        remaining = max(0.0, deadline - time.monotonic())
        if remaining > 0:
            self._flush()
        else:
            with self._buffer.lock:
                dropped = len(self._buffer.events)
                self._buffer.events = []
            if dropped:
                logger.warning(
                    "KillKrillSink: shutdown budget exhausted; dropping %d events", dropped
                )
        self._client.close()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _flush_loop(self) -> None:
        """Background thread: flush when signalled full or on interval, until stop."""
        while not self._stop_event.is_set():
            self._flush_now.wait(timeout=self._config.flush_interval)
            self._flush_now.clear()
            if self._stop_event.is_set():
                break
            self._flush()

    def _flush(self) -> None:
        """Drain the buffer and deliver events with retry/backoff."""
        with self._buffer.lock:
            if not self._buffer.events:
                return
            batch = self._buffer.events
            self._buffer.events = []

        self._deliver_with_retry(batch)

    def _deliver_with_retry(self, batch: list[dict[str, Any]]) -> None:
        """Attempt delivery up to max_retries times with exponential backoff."""
        url = f"{self._config.endpoint}/api/v1/events"
        payload = json.dumps(batch)

        for attempt in range(1, self._config.max_retries + 1):
            try:
                response = self._client.post(url, content=payload)
                response.raise_for_status()
                return
            except httpx.HTTPError as exc:
                if attempt == self._config.max_retries:
                    logger.warning(
                        "KillKrillSink: dropping %d events after %d failed attempts: %s",
                        len(batch),
                        attempt,
                        exc,
                    )
                    return

                backoff = 2 ** (attempt - 1)
                logger.debug(
                    "KillKrillSink: attempt %d failed, retrying in %.1fs: %s",
                    attempt,
                    backoff,
                    exc,
                )
                time.sleep(backoff)
