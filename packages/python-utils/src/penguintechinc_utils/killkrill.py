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
        """Stop the background thread, deliver what the budget allows, and close the client.

        Bounded by one deadline for the whole call, because this runs on the
        process's exit path: with default config an unreachable endpoint costs
        10+1+10+2+10s per delivery attempt, so an unbounded join plus a final flush
        could hang exit for ~44s. Past the deadline the remaining batch is dropped
        with a WARN rather than retried, and the caller-thread final flush is itself
        deadline-bounded so it cannot overrun the budget either.

        The client is ALWAYS closed before returning, on every path -- a close() that
        left it open would leak the connection pool and its sockets. Closing it out
        from under a still-running worker is safe here precisely because it only
        happens on the budget-exhausted path, where the batch is being dropped
        anyway; `_deliver_with_retry` catches the resulting "client closed" error, so
        the worker exits cleanly rather than dying with an uncaught traceback. (That
        is the silent-thread-death the earlier revision avoided by leaking the client
        instead -- the broadened catch lets us reclaim the client without it.)

        Args:
            budget: Total seconds allowed for draining and stopping.
        """
        deadline = time.monotonic() + budget
        self._stop_event.set()
        self._flush_now.set()
        self._flush_thread.join(timeout=max(0.0, deadline - time.monotonic()))

        try:
            if self._flush_thread.is_alive():
                # Budget spent with the worker still draining (typically an
                # unreachable endpoint mid-retry). Give up on the buffered batch
                # rather than block the caller, and reclaim the client below.
                with self._buffer.lock:
                    dropped = len(self._buffer.events)
                    self._buffer.events = []
                logger.warning(
                    "KillKrillSink: flush thread still running after %.1fs; "
                    "dropping %d buffered events and closing the client",
                    budget,
                    dropped,
                )
            elif time.monotonic() < deadline:
                # Worker has exited; deliver the final partial batch on this thread,
                # bounded by the same deadline so a dead endpoint cannot overrun it.
                self._flush(deadline=deadline)
            else:
                with self._buffer.lock:
                    dropped = len(self._buffer.events)
                    self._buffer.events = []
                if dropped:
                    logger.warning(
                        "KillKrillSink: shutdown budget exhausted; dropping %d events", dropped
                    )
        finally:
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

    def _flush(self, deadline: float | None = None) -> None:
        """Drain the buffer and deliver events with retry/backoff.

        `deadline` (a `time.monotonic()` value) bounds the retry/backoff when the
        caller is shutting down, so a final flush to a dead endpoint cannot overrun
        close()'s budget. The background loop calls it with no deadline.
        """
        with self._buffer.lock:
            if not self._buffer.events:
                return
            batch = self._buffer.events
            self._buffer.events = []

        self._deliver_with_retry(batch, deadline)

    def _deliver_with_retry(
        self, batch: list[dict[str, Any]], deadline: float | None = None
    ) -> None:
        """Attempt delivery up to max_retries times with exponential backoff.

        Never lets an exception escape to the background thread: an HTTP error
        retries then drops, and any other error (most importantly a "client has been
        closed" RuntimeError when close() reclaims the client mid-shutdown) drops
        immediately without retrying -- retrying a closed client cannot succeed, and
        an uncaught exception here would kill the worker thread.
        """
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
                if deadline is not None and time.monotonic() + backoff >= deadline:
                    logger.warning(
                        "KillKrillSink: dropping %d events; shutdown deadline reached",
                        len(batch),
                    )
                    return
                logger.debug(
                    "KillKrillSink: attempt %d failed, retrying in %.1fs: %s",
                    attempt,
                    backoff,
                    exc,
                )
                time.sleep(backoff)
            except Exception as exc:
                logger.warning(
                    "KillKrillSink: dropping %d events; client no longer usable: %s",
                    len(batch),
                    exc,
                )
                return
