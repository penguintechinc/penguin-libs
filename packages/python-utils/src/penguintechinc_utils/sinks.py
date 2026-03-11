"""
Log sink implementations for Penguin Tech applications.

A Sink receives structured log events (plain dicts) and writes them to a
destination — stdout, a rotating file, syslog, or any user-supplied callback.
All sinks implement the Sink Protocol so they can be composed freely.
"""

import json
import logging
import logging.handlers
import socket
import sys
from collections.abc import Callable
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
            import boto3  # type: ignore[import]
        except ImportError as exc:
            raise ImportError(
                "CloudWatchSink requires boto3. Install with: pip install penguin-utils[cloudwatch]"
            ) from exc
        self._client = boto3.client("logs", region_name=region)
        self._log_group = log_group
        self._log_stream = log_stream
        self._batch_size = batch_size
        self._buffer: list[dict] = []
        self._sequence_token: str | None = None

    def __call__(self, logger: Any, method: str, event_dict: dict) -> dict:
        """Buffer log event and flush when batch_size is reached."""
        import time

        self._buffer.append(
            {
                "timestamp": int(time.time() * 1000),
                "message": str(event_dict),
            }
        )
        if len(self._buffer) >= self._batch_size:
            self.flush()
        return event_dict

    def flush(self) -> None:
        """Send buffered events to CloudWatch."""
        if not self._buffer:
            return
        kwargs: dict = {
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


class GCPCloudLoggingSink:
    """Sends log events to Google Cloud Logging.

    Requires: pip install penguin-utils[gcp]

    Args:
        project_id: GCP project ID.
        log_name: Cloud Logging log name.
    """

    def __init__(self, project_id: str, log_name: str) -> None:
        try:
            from google.cloud import logging as gcp_logging  # type: ignore[import]
        except ImportError as exc:
            raise ImportError(
                "GCPCloudLoggingSink requires google-cloud-logging. "
                "Install with: pip install penguin-utils[gcp]"
            ) from exc
        client = gcp_logging.Client(project=project_id)
        self._logger = client.logger(log_name)

    def __call__(self, logger: Any, method: str, event_dict: dict) -> dict:
        """Send log event as structured JSON payload to GCP."""
        severity = method.upper()
        self._logger.log_struct(event_dict, severity=severity)
        return event_dict


class KafkaSink:
    """Sends log events as JSON messages to a Kafka topic.

    Requires: pip install penguin-utils[kafka]

    Args:
        bootstrap_servers: Comma-separated Kafka broker addresses.
        topic: Kafka topic to produce messages to.
    """

    def __init__(self, bootstrap_servers: str, topic: str) -> None:
        try:
            from kafka import KafkaProducer  # type: ignore[import]
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

    def __call__(self, logger: Any, method: str, event_dict: dict) -> dict:
        """Send log event as JSON to Kafka topic."""
        self._producer.send(self._topic, value=event_dict)
        return event_dict

    def flush(self) -> None:
        """Flush pending Kafka messages."""
        self._producer.flush()
