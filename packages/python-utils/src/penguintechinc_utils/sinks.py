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
