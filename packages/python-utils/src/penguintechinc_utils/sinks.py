"""
Log sink implementations for Penguin Tech applications.

A Sink receives structured log events (plain dicts) and writes them to a
destination — stdout, a rotating file, syslog, or any user-supplied callback.
All sinks implement the Sink Protocol so they can be composed freely.
"""

import json
import logging
import logging.handlers
import queue
import socket
import sys
import threading
import time
from collections.abc import Callable, Sequence
from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class Sink(Protocol):
    """Protocol that all log sinks must satisfy."""

    def emit(self, event: dict[str, Any]) -> None:
        """Write a single structured log event."""
        ...

    def flush(self) -> None:
        """Flush any buffered output."""
        ...

    def close(self) -> None:
        """Release resources held by the sink."""
        ...


class StdoutSink:
    """Writes each log event as a JSON line to stdout."""

    def emit(self, event: dict[str, Any]) -> None:
        print(json.dumps(event), file=sys.stdout)

    def flush(self) -> None:
        sys.stdout.flush()

    def close(self) -> None:
        pass


class FileSink:
    """
    Writes log events as JSON lines to a size-rotating file.

    Args:
        path: Destination file path.
        max_size_mb: Maximum file size in megabytes before rotation (default: 100).
        backup_count: Number of rotated backup files to retain (default: 5).
    """

    def __init__(self, path: str, max_size_mb: int = 100, backup_count: int = 5) -> None:
        self._handler = logging.handlers.RotatingFileHandler(
            filename=path,
            maxBytes=max_size_mb * 1024 * 1024,
            backupCount=backup_count,
            encoding="utf-8",
        )

    def emit(self, event: dict[str, Any]) -> None:
        record = logging.LogRecord(
            name="penguintech",
            level=logging.INFO,
            pathname="",
            lineno=0,
            msg=json.dumps(event),
            args=(),
            exc_info=None,
        )
        self._handler.emit(record)

    def flush(self) -> None:
        self._handler.flush()

    def close(self) -> None:
        self._handler.close()


class SyslogSink:
    """
    Sends log events as JSON over UDP syslog.

    Args:
        host: Syslog server hostname or IP address.
        port: UDP port (default: 514).
        facility: Syslog facility code (default: 1 = USER).
    """

    _SEVERITY_MAP = {
        "debug": 7,
        "info": 6,
        "warning": 4,
        "error": 3,
        "critical": 2,
    }

    def __init__(self, host: str, port: int = 514, facility: int = 1) -> None:
        self._host = host
        self._port = port
        self._facility = facility
        self._socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

    def _priority(self, level: str) -> int:
        severity = self._SEVERITY_MAP.get(level.lower(), 6)
        return (self._facility << 3) | severity

    def emit(self, event: dict[str, Any]) -> None:
        level = str(event.get("level", "info"))
        priority = self._priority(level)
        message = f"<{priority}>{json.dumps(event)}"
        self._socket.sendto(message.encode("utf-8"), (self._host, self._port))

    def flush(self) -> None:
        pass

    def close(self) -> None:
        self._socket.close()


class CallbackSink:
    """
    Forwards each log event to a user-supplied callable.

    Args:
        callback: Function that accepts a single dict argument.
    """

    def __init__(self, callback: Callable[[dict[str, Any]], None]) -> None:
        self._callback = callback

    def emit(self, event: dict[str, Any]) -> None:
        self._callback(dict(event))

    def flush(self) -> None:
        pass

    def close(self) -> None:
        pass


class CloudWatchSink:
    """Sends log events to AWS CloudWatch Logs.

    Requires: pip install penguin-utils[cloudwatch]

    Args:
        log_group: CloudWatch log group name.
        log_stream: CloudWatch log stream name.
        region: AWS region (default: us-east-1).
        batch_size: Max events per PutLogEvents call (default: 100).
    """

    def __init__(
        self,
        log_group: str,
        log_stream: str,
        region: str = "us-east-1",
        batch_size: int = 100,
    ) -> None:
        try:
            import boto3  # type: ignore[import-untyped]
        except ImportError as exc:
            raise ImportError(
                "CloudWatchSink requires boto3. Install with: pip install penguin-utils[cloudwatch]"
            ) from exc
        self._client = boto3.client("logs", region_name=region)
        self._log_group = log_group
        self._log_stream = log_stream
        self._batch_size = batch_size
        self._buffer: list[dict[str, Any]] = []
        self._sequence_token: str | None = None

    def emit(self, event: dict[str, Any]) -> None:
        """Emit a log event to CloudWatch."""
        import time

        self._buffer.append(
            {
                "timestamp": int(time.time() * 1000),
                "message": json.dumps(event),
            }
        )
        if len(self._buffer) >= self._batch_size:
            self.flush()

    def __call__(self, logger: Any, method: str, event_dict: dict[str, Any]) -> dict[str, Any]:
        """Buffer log event and flush when batch_size is reached (structlog processor)."""
        self.emit(event_dict)
        return event_dict

    def flush(self) -> None:
        """Send buffered events to CloudWatch."""
        if not self._buffer:
            return
        kwargs: dict[str, Any] = {
            "logGroupName": self._log_group,
            "logStreamName": self._log_stream,
            "logEvents": self._buffer,
        }
        if self._sequence_token:
            kwargs["sequenceToken"] = self._sequence_token
        try:
            response = self._client.put_log_events(**kwargs)
            self._sequence_token = response.get("nextSequenceToken")
        finally:
            self._buffer = []

    def close(self) -> None:
        """Close the CloudWatch sink."""
        self.flush()


class GCPCloudLoggingSink:
    """Sends log events to Google Cloud Logging.

    Requires: pip install penguin-utils[gcp]

    Args:
        project_id: GCP project ID.
        log_name: Cloud Logging log name.
    """

    def __init__(self, project_id: str, log_name: str) -> None:
        try:
            from google.cloud import logging as gcp_logging  # type: ignore[import-untyped]
        except ImportError as exc:
            raise ImportError(
                "GCPCloudLoggingSink requires google-cloud-logging. "
                "Install with: pip install penguin-utils[gcp]"
            ) from exc
        client = gcp_logging.Client(project=project_id)
        self._logger = client.logger(log_name)

    def emit(self, event: dict[str, Any]) -> None:
        """Emit a log event to GCP Cloud Logging."""
        self._logger.log_struct(event)

    def __call__(self, logger: Any, method: str, event_dict: dict[str, Any]) -> dict[str, Any]:
        """Send log event as structured JSON payload to GCP (structlog processor)."""
        severity = method.upper()
        self._logger.log_struct(event_dict, severity=severity)
        return event_dict

    def flush(self) -> None:
        """Flush GCP Cloud Logging (no-op)."""
        pass

    def close(self) -> None:
        """Close the GCP sink."""
        pass


class KafkaSink:
    """Sends log events as JSON messages to a Kafka topic.

    Requires: pip install penguin-utils[kafka]

    Args:
        bootstrap_servers: Comma-separated Kafka broker addresses.
        topic: Kafka topic to produce messages to.
    """

    def __init__(self, bootstrap_servers: str, topic: str) -> None:
        try:
            from kafka import KafkaProducer  # type: ignore[import-not-found]
        except ImportError as exc:
            raise ImportError(
                "KafkaSink requires kafka-python. Install with: pip install penguin-utils[kafka]"
            ) from exc
        import json as _json

        self._topic = topic
        self._producer = KafkaProducer(
            bootstrap_servers=bootstrap_servers.split(","),
            value_serializer=lambda v: _json.dumps(v).encode("utf-8"),
        )

    def emit(self, event: dict[str, Any]) -> None:
        """Emit a log event to Kafka."""
        self._producer.send(self._topic, value=event)

    def __call__(self, logger: Any, method: str, event_dict: dict[str, Any]) -> dict[str, Any]:
        """Send log event as JSON to Kafka topic (structlog processor)."""
        self.emit(event_dict)
        return event_dict

    def flush(self) -> None:
        """Flush pending Kafka messages."""
        self._producer.flush()

    def close(self) -> None:
        """Close the Kafka sink."""
        self._producer.close()


# Sinks that talk to the network on the caller's thread and therefore need a queue in
# front of them. Named explicitly rather than guessed at. KillKrillSink is deliberately
# NOT here: it buffers and flushes on its own background thread, so wrapping it would
# add a redundant thread and queue, and a consumer holding its own reference to call
# close() would bypass the outer queue entirely. StdoutSink, FileSink, SyslogSink (a UDP
# sendto does not block) and CallbackSink stay synchronous, because consumers' tests
# assert on a CallbackSink immediately after logging.
BLOCKING_SINK_NAMES = frozenset({"CloudWatchSink", "GCPCloudLoggingSink", "KafkaSink"})

# Total seconds AsyncSink.close() may spend draining, matching KillKrillSink's budget:
# shutdown must stay bounded even when the inner sink's network call never returns.
SHUTDOWN_BUDGET = 5.0


class AsyncSink:
    """
    Wrap a blocking sink with a bounded queue drained by a background thread.

    Keeps a slow or unreachable network sink off the caller's thread entirely. When
    the queue is full the OLDEST event is dropped, so the newest -- usually the most
    relevant -- still gets through, and the drop is counted rather than hidden.

    Args:
        inner: The sink to deliver to.
        maxsize: Queue capacity; beyond it, the oldest queued event is dropped.
    """

    _SENTINEL = object()

    def __init__(self, inner: "Sink", maxsize: int = 10000) -> None:
        self._inner = inner
        self._queue: queue.Queue[Any] = queue.Queue(maxsize=maxsize)
        self._dropped = 0
        self._errors = 0
        self._closed = False
        self._lock = threading.Lock()
        self._thread = threading.Thread(
            target=self._run,
            name=f"penguin-asyncsink-{type(inner).__name__}",
            daemon=True,
        )
        self._thread.start()

    @property
    def inner(self) -> "Sink":
        """The wrapped sink."""
        return self._inner

    @property
    def dropped(self) -> int:
        """Events discarded because the queue was full."""
        return self._dropped

    @property
    def errors(self) -> int:
        """Deliveries the inner sink raised on."""
        return self._errors

    def emit(self, event: dict[str, Any]) -> None:
        """Queue an event for background delivery; never blocks and never raises."""
        try:
            self._queue.put_nowait(event)
            return
        except queue.Full:
            pass
        # Full: discard the head to make room, then retry. A log call must never wait
        # on queue space, so dropping the oldest is the only acceptable answer.
        try:
            self._queue.get_nowait()
            self._queue.task_done()
        except queue.Empty:  # pragma: no cover - needs an exact producer/consumer race
            pass
        self._dropped += 1
        try:
            self._queue.put_nowait(event)
        except queue.Full:  # pragma: no cover - needs an exact producer/consumer race
            self._dropped += 1

    def _run(self) -> None:
        """Background worker: deliver queued events until the sentinel arrives."""
        while True:
            item = self._queue.get()
            if item is self._SENTINEL:
                self._queue.task_done()
                return
            try:
                self._inner.emit(item)
            except Exception:
                # A failing sink must never kill the worker: the next event, and
                # every event after it, still has to be delivered.
                self._errors += 1
            finally:
                self._queue.task_done()

    def flush(self, timeout: float = SHUTDOWN_BUDGET) -> None:
        """Wait up to `timeout` for queued events to be delivered, then flush inner."""
        self._drain(timeout)
        try:
            self._inner.flush()
        except Exception:
            self._errors += 1

    def close(self, timeout: float = SHUTDOWN_BUDGET) -> None:
        """Drain, stop the worker and close the inner sink within `timeout`. Idempotent.

        Bounded, because this runs on the exit path: `Queue.join()` alone waits forever,
        so one unreachable CloudWatch/GCP/Kafka endpoint would hang process shutdown
        indefinitely. Past the deadline the undelivered remainder is counted as dropped.
        """
        with self._lock:
            if self._closed:
                return
            self._closed = True
        deadline = time.monotonic() + timeout
        self._drain(timeout)
        self._queue.put(self._SENTINEL)
        self._thread.join(timeout=max(0.0, deadline - time.monotonic()))
        try:
            self._inner.close()
        except Exception:
            self._errors += 1

    def _drain(self, timeout: float) -> None:
        """Wait for the queue to empty, giving up after `timeout` seconds."""
        deadline = time.monotonic() + timeout
        while not self._queue.empty() and time.monotonic() < deadline:
            time.sleep(0.01)
        remaining = self._queue.qsize()
        if remaining:
            self._dropped += remaining


def wrap_blocking_sinks(
    sinks: Sequence["Sink"],
    blocking_names: frozenset[str] = BLOCKING_SINK_NAMES,
) -> list["Sink"]:
    """
    Put each network-bound sink behind an AsyncSink, passing local sinks through.

    Selection is by class name so an already-wrapped sink, or a caller's own custom
    sink, is left exactly as given -- this must never silently make a synchronous
    sink asynchronous for a consumer who was relying on it being synchronous.
    """
    return [AsyncSink(s) if type(s).__name__ in blocking_names else s for s in sinks]
