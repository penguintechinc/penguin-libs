"""Concrete AuditSink implementations for common delivery destinations."""

from __future__ import annotations

import json
import logging
import socket
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class StdoutSink:
    """Write JSON-encoded audit events to standard output, one line per event."""

    def emit(self, event: dict[str, Any]) -> None:
        """Serialize event as JSON and write to stdout."""
        print(json.dumps(event, default=str), file=sys.stdout, flush=True)

    def flush(self) -> None:
        sys.stdout.flush()

    def close(self) -> None:
        pass


class FileSink:
    """Append JSON-encoded audit events to a file, one line per event.

    Args:
        path: Destination file path. Created if it does not exist.
    """

    def __init__(self, path: str | Path) -> None:
        self._path = Path(path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._fh = self._path.open("a", encoding="utf-8")

    def emit(self, event: dict[str, Any]) -> None:
        """Serialize event as JSON and append to the file."""
        self._fh.write(json.dumps(event, default=str) + "\n")
        self._fh.flush()

    def flush(self) -> None:
        self._fh.flush()

    def close(self) -> None:
        self._fh.close()


class SyslogSink:
    """Send JSON-encoded audit events to a syslog server over UDP.

    Args:
        host: Syslog server hostname or IP address.
        port: Syslog server UDP port (default 514).
        facility: Syslog facility code (default 1 = user-level messages).
        severity: Syslog severity code (default 6 = informational).
    """

    def __init__(
        self,
        host: str = "localhost",
        port: int = 514,
        facility: int = 1,
        severity: int = 6,
    ) -> None:
        self._host = host
        self._port = port
        self._priority = (facility * 8) + severity
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

    def emit(self, event: dict[str, Any]) -> None:
        """Format and send an event as a syslog UDP datagram."""
        body = json.dumps(event, default=str)
        message = f"<{self._priority}>{body}"
        self._sock.sendto(message.encode("utf-8"), (self._host, self._port))

    def flush(self) -> None:
        pass

    def close(self) -> None:
        self._sock.close()


class CallbackSink:
    """Deliver audit events to an arbitrary callable.

    Useful for testing and for integrating with application-specific
    event pipelines without subclassing.

    Args:
        callback: A callable that accepts a single ``dict[str, Any]`` argument.
    """

    def __init__(self, callback: Callable[[dict[str, Any]], None]) -> None:
        self._callback = callback

    def emit(self, event: dict[str, Any]) -> None:
        """Invoke the callback with the event dictionary."""
        self._callback(event)

    def flush(self) -> None:
        pass

    def close(self) -> None:
        pass
