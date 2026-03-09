"""Tests for penguin_aaa.audit.sinks module."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

from penguin_aaa.audit.sinks import CallbackSink, FileSink, StdoutSink, SyslogSink

# ---------------------------------------------------------------------------
# StdoutSink
# ---------------------------------------------------------------------------


class TestStdoutSink:
    def test_emit_writes_json_to_stdout(self, capsys: Any) -> None:
        sink = StdoutSink()
        event = {"action": "login", "user": "alice"}
        sink.emit(event)
        captured = capsys.readouterr()
        assert json.loads(captured.out.strip()) == event

    def test_emit_handles_non_serializable(self, capsys: Any) -> None:
        sink = StdoutSink()
        from datetime import datetime

        now = datetime(2025, 1, 1, 12, 0, 0)
        sink.emit({"ts": now})
        captured = capsys.readouterr()
        parsed = json.loads(captured.out.strip())
        assert parsed["ts"] == str(now)

    def test_flush(self) -> None:
        sink = StdoutSink()
        # Should not raise.
        sink.flush()

    def test_close(self) -> None:
        sink = StdoutSink()
        # Should not raise.
        sink.close()


# ---------------------------------------------------------------------------
# FileSink
# ---------------------------------------------------------------------------


class TestFileSink:
    def test_emit_writes_json_line(self, tmp_path: Path) -> None:
        fp = tmp_path / "audit.log"
        sink = FileSink(fp)
        try:
            event = {"action": "create", "id": 42}
            sink.emit(event)
            lines = fp.read_text().strip().splitlines()
            assert len(lines) == 1
            assert json.loads(lines[0]) == event
        finally:
            sink.close()

    def test_emit_appends_multiple_events(self, tmp_path: Path) -> None:
        fp = tmp_path / "audit.log"
        sink = FileSink(fp)
        try:
            sink.emit({"a": 1})
            sink.emit({"b": 2})
            lines = fp.read_text().strip().splitlines()
            assert len(lines) == 2
        finally:
            sink.close()

    def test_creates_parent_dirs(self, tmp_path: Path) -> None:
        fp = tmp_path / "sub" / "dir" / "audit.log"
        sink = FileSink(fp)
        try:
            sink.emit({"x": 1})
            assert fp.exists()
        finally:
            sink.close()

    def test_flush(self, tmp_path: Path) -> None:
        fp = tmp_path / "audit.log"
        sink = FileSink(fp)
        try:
            sink.flush()  # should not raise
        finally:
            sink.close()

    def test_close(self, tmp_path: Path) -> None:
        fp = tmp_path / "audit.log"
        sink = FileSink(fp)
        sink.close()
        assert sink._fh.closed

    def test_accepts_string_path(self, tmp_path: Path) -> None:
        fp = str(tmp_path / "audit.log")
        sink = FileSink(fp)
        try:
            sink.emit({"ok": True})
            assert Path(fp).exists()
        finally:
            sink.close()


# ---------------------------------------------------------------------------
# SyslogSink
# ---------------------------------------------------------------------------


class TestSyslogSink:
    def test_emit_sends_udp(self) -> None:
        sink = SyslogSink(host="127.0.0.1", port=5140)
        event = {"action": "delete", "id": 7}
        with patch.object(sink, "_sock") as mock_sock:
            sink.emit(event)
            mock_sock.sendto.assert_called_once()
            data, addr = mock_sock.sendto.call_args[0]
            assert addr == ("127.0.0.1", 5140)
            # Default priority: facility=1, severity=6 => (1*8)+6 = 14
            assert data.startswith(b"<14>")
            body = json.loads(data[4:])
            assert body == event

    def test_custom_facility_severity(self) -> None:
        sink = SyslogSink(host="10.0.0.1", port=1514, facility=4, severity=3)
        # priority = (4*8)+3 = 35
        assert sink._priority == 35
        with patch.object(sink, "_sock") as mock_sock:
            sink.emit({"x": 1})
            data = mock_sock.sendto.call_args[0][0]
            assert data.startswith(b"<35>")

    def test_flush(self) -> None:
        sink = SyslogSink()
        sink.flush()  # no-op, should not raise

    def test_close(self) -> None:
        sink = SyslogSink()
        with patch.object(sink, "_sock") as mock_sock:
            sink.close()
            mock_sock.close.assert_called_once()


# ---------------------------------------------------------------------------
# CallbackSink
# ---------------------------------------------------------------------------


class TestCallbackSink:
    def test_emit_calls_callback(self) -> None:
        cb = MagicMock()
        sink = CallbackSink(cb)
        event = {"action": "test"}
        sink.emit(event)
        cb.assert_called_once_with(event)

    def test_emit_multiple(self) -> None:
        cb = MagicMock()
        sink = CallbackSink(cb)
        sink.emit({"a": 1})
        sink.emit({"b": 2})
        assert cb.call_count == 2

    def test_flush(self) -> None:
        sink = CallbackSink(lambda e: None)
        sink.flush()  # no-op

    def test_close(self) -> None:
        sink = CallbackSink(lambda e: None)
        sink.close()  # no-op
