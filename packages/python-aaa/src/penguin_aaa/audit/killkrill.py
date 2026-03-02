"""KillKrill audit sink — batched HTTP delivery to the KillKrill audit service."""

from __future__ import annotations

import json
import logging
import threading
import time
from dataclasses import dataclass
from typing import Any

import httpx

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class KillKrillConfig:
    """Configuration for the KillKrill audit sink.

    Args:
        endpoint: Base URL of the KillKrill service (e.g. ``https://audit.example.io``).
        api_key: API key used in the ``X-API-Key`` request header.
        batch_size: Maximum events per POST request before a flush is triggered.
        flush_interval: Maximum seconds between automatic background flushes.
        timeout: HTTP request timeout in seconds.
        max_retries: Number of additional attempts after the initial POST failure.
    """

    endpoint: str
    api_key: str
    batch_size: int = 100
    flush_interval: float = 5.0
    timeout: float = 10.0
    max_retries: int = 3


class KillKrillSink:
    """Buffered audit sink that delivers batches of events to KillKrill.

    Events are accumulated in memory and flushed either when the buffer
    reaches ``config.batch_size`` or when the background flush thread fires
    after ``config.flush_interval`` seconds.

    The background thread is a daemon thread; it will stop automatically
    when the process exits. Call :meth:`close` to perform a final flush
    and stop the thread cleanly.

    Args:
        config: KillKrill connection and batching configuration.
    """

    _EVENTS_PATH = "/api/v1/events"

    def __init__(self, config: KillKrillConfig) -> None:
        self._config = config
        self._buffer: list[dict[str, Any]] = []
        self._lock = threading.Lock()
        self._stopped = threading.Event()

        self._thread = threading.Thread(
            target=self._background_flush,
            name="killkrill-flush",
            daemon=True,
        )
        self._thread.start()

    # ------------------------------------------------------------------
    # AuditSink interface
    # ------------------------------------------------------------------

    def emit(self, event: dict[str, Any]) -> None:
        """Buffer an event and flush eagerly when batch_size is reached.

        Args:
            event: Serialized audit event dictionary.
        """
        with self._lock:
            self._buffer.append(event)
            should_flush = len(self._buffer) >= self._config.batch_size

        if should_flush:
            self._flush_now()

    def flush(self) -> None:
        """Flush all buffered events to KillKrill immediately."""
        self._flush_now()

    def close(self) -> None:
        """Stop the background thread and perform a final flush."""
        self._stopped.set()
        self._thread.join(timeout=self._config.flush_interval + self._config.timeout + 1)
        self._flush_now()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _background_flush(self) -> None:
        """Periodic flush loop — runs in the background daemon thread."""
        while not self._stopped.wait(timeout=self._config.flush_interval):
            self._flush_now()

    def _flush_now(self) -> None:
        """Drain the buffer and POST events to KillKrill, with retries."""
        with self._lock:
            if not self._buffer:
                return
            batch = self._buffer[:]
            self._buffer.clear()

        url = self._config.endpoint.rstrip("/") + self._EVENTS_PATH
        headers = {
            "Content-Type": "application/json",
            "X-API-Key": self._config.api_key,
        }
        payload = json.dumps(batch, default=str).encode()

        last_error: Exception | None = None
        for attempt in range(1 + self._config.max_retries):
            try:
                with httpx.Client(timeout=self._config.timeout) as client:
                    response = client.post(url, content=payload, headers=headers)
                    response.raise_for_status()
                return
            except Exception as exc:
                last_error = exc
                if attempt < self._config.max_retries:
                    backoff = 2**attempt
                    logger.warning(
                        "KillKrill flush attempt %d/%d failed, retrying in %ds: %s",
                        attempt + 1,
                        1 + self._config.max_retries,
                        backoff,
                        exc,
                    )
                    time.sleep(backoff)

        logger.error(
            "KillKrill flush failed after %d attempts, %d events dropped: %s",
            1 + self._config.max_retries,
            len(batch),
            last_error,
        )
