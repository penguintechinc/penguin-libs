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
        """Buffer an event, flushing immediately if the batch is full."""
        with self._buffer.lock:
            self._buffer.events.append(event)
            should_flush = len(self._buffer.events) >= self._config.batch_size

        if should_flush:
            self._flush()

    def flush(self) -> None:
        """Flush all buffered events to the remote service."""
        self._flush()

    def close(self) -> None:
        """Stop the background thread and flush remaining events."""
        self._stop_event.set()
        self._flush_thread.join(timeout=self._config.timeout + 1)
        self._flush()
        self._client.close()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _flush_loop(self) -> None:
        """Background thread: flush on interval until stop is signalled."""
        while not self._stop_event.wait(timeout=self._config.flush_interval):
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
