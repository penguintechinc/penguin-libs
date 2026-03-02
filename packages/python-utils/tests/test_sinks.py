"""
Tests for log sink implementations and backward-compatible logging API.
"""

import json
import logging
import os
import tempfile
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from penguintechinc_utils import (
    CallbackSink,
    FileSink,
    SanitizedLogger,
    Sink,
    StdoutSink,
    SyslogSink,
    configure_logging,
    get_logger,
    sanitize_log_data,
)
from penguintechinc_utils.logging import SENSITIVE_KEYS


# ---------------------------------------------------------------------------
# sanitize_log_data — backward compatibility
# ---------------------------------------------------------------------------


class TestSanitizeLogData:
    def test_redacts_sensitive_keys(self) -> None:
        data = {"password": "hunter2", "username": "alice"}
        result = sanitize_log_data(data)
        assert result["password"] == "[REDACTED]"
        assert result["username"] == "alice"

    def test_redacts_partial_key_match(self) -> None:
        data = {"user_password_hash": "abc123"}
        result = sanitize_log_data(data)
        assert result["user_password_hash"] == "[REDACTED]"

    def test_redacts_email_to_domain(self) -> None:
        data = {"contact": "alice@example.com"}
        result = sanitize_log_data(data)
        assert result["contact"] == "[email]@example.com"

    def test_preserves_non_sensitive_strings(self) -> None:
        data = {"action": "login", "status": "ok"}
        result = sanitize_log_data(data)
        assert result == data

    def test_recurses_into_nested_dicts(self) -> None:
        data = {"user": {"password": "secret", "name": "bob"}}
        result = sanitize_log_data(data)
        assert result["user"]["password"] == "[REDACTED]"
        assert result["user"]["name"] == "bob"

    def test_recurses_into_list_of_dicts(self) -> None:
        data = {"items": [{"token": "abc"}, {"value": 1}]}
        result = sanitize_log_data(data)
        assert result["items"][0]["token"] == "[REDACTED]"
        assert result["items"][1]["value"] == 1

    def test_passes_through_non_dict_argument(self) -> None:
        assert sanitize_log_data("not a dict") == "not a dict"  # type: ignore[arg-type]

    def test_sensitive_keys_frozenset(self) -> None:
        assert isinstance(SENSITIVE_KEYS, frozenset)
        assert "password" in SENSITIVE_KEYS
        assert "api_key" in SENSITIVE_KEYS


# ---------------------------------------------------------------------------
# get_logger — backward compatibility
# ---------------------------------------------------------------------------


class TestGetLogger:
    def test_returns_bound_logger(self) -> None:
        import structlog

        log = get_logger("test.component")
        from structlog._config import BoundLoggerLazyProxy
        assert isinstance(log, BoundLoggerLazyProxy)

    def test_accepts_level_parameter(self) -> None:
        log = get_logger("test.level", level=logging.DEBUG)
        assert log is not None


# ---------------------------------------------------------------------------
# configure_logging
# ---------------------------------------------------------------------------


class TestConfigureLogging:
    def test_configures_without_error(self) -> None:
        configure_logging(level=logging.DEBUG, json_output=False)

    def test_json_output_mode(self) -> None:
        configure_logging(level=logging.INFO, json_output=True)

    def test_with_stdout_sink(self, capsys: pytest.CaptureFixture[str]) -> None:
        sink = StdoutSink()
        configure_logging(level=logging.INFO, json_output=True, sinks=[sink])
        log = get_logger("test.sink")
        log.info("hello from sink test")


# ---------------------------------------------------------------------------
# SanitizedLogger — backward compatibility
# ---------------------------------------------------------------------------


class TestSanitizedLogger:
    def setup_method(self) -> None:
        configure_logging(level=logging.DEBUG, json_output=False)

    def test_instantiates(self) -> None:
        log = SanitizedLogger("TestComponent")
        assert log is not None

    def test_all_methods_callable(self) -> None:
        log = SanitizedLogger("TestComponent")
        log.debug("debug msg")
        log.info("info msg")
        log.warning("warning msg")
        log.error("error msg")
        log.critical("critical msg")

    def test_sanitizes_data_on_info(self) -> None:
        received: list[dict[str, Any]] = []
        sink = CallbackSink(received.append)
        configure_logging(level=logging.DEBUG, json_output=False, sinks=[sink])

        log = SanitizedLogger("TestSanitized")
        log.info("login attempt", {"email": "alice@example.com", "password": "secret"})

        assert len(received) >= 1
        event = received[-1]
        assert event.get("password") == "[REDACTED]"
        assert event.get("email") == "[email]@example.com"

    def test_logs_without_data(self) -> None:
        log = SanitizedLogger("TestNoData")
        log.info("simple message")


# ---------------------------------------------------------------------------
# StdoutSink
# ---------------------------------------------------------------------------


class TestStdoutSink:
    def test_emit_writes_json_to_stdout(self, capsys: pytest.CaptureFixture[str]) -> None:
        sink = StdoutSink()
        sink.emit({"level": "info", "event": "hello"})
        captured = capsys.readouterr()
        parsed = json.loads(captured.out.strip())
        assert parsed["event"] == "hello"

    def test_flush_does_not_raise(self) -> None:
        StdoutSink().flush()

    def test_close_does_not_raise(self) -> None:
        StdoutSink().close()

    def test_satisfies_sink_protocol(self) -> None:
        assert isinstance(StdoutSink(), Sink)


# ---------------------------------------------------------------------------
# FileSink
# ---------------------------------------------------------------------------


class TestFileSink:
    def test_emit_writes_json_to_file(self) -> None:
        with tempfile.NamedTemporaryFile(suffix=".log", delete=False) as tmp:
            path = tmp.name

        try:
            sink = FileSink(path)
            sink.emit({"level": "info", "event": "file test"})
            sink.flush()
            sink.close()

            with open(path) as fh:
                content = fh.read().strip()
            assert "file test" in content
        finally:
            os.unlink(path)

    def test_rotation_parameters_accepted(self) -> None:
        with tempfile.NamedTemporaryFile(suffix=".log", delete=False) as tmp:
            path = tmp.name
        try:
            sink = FileSink(path, max_size_mb=10, backup_count=3)
            sink.close()
        finally:
            os.unlink(path)

    def test_satisfies_sink_protocol(self) -> None:
        with tempfile.NamedTemporaryFile(suffix=".log", delete=False) as tmp:
            path = tmp.name
        try:
            assert isinstance(FileSink(path), Sink)
        finally:
            os.unlink(path)


# ---------------------------------------------------------------------------
# SyslogSink
# ---------------------------------------------------------------------------


class TestSyslogSink:
    def test_emit_sends_udp_packet(self) -> None:
        mock_socket = MagicMock()
        with patch("penguintechinc_utils.sinks.socket.socket", return_value=mock_socket):
            sink = SyslogSink(host="127.0.0.1", port=514)
            sink.emit({"level": "info", "event": "syslog test"})

        mock_socket.sendto.assert_called_once()
        payload_bytes, addr = mock_socket.sendto.call_args[0]
        payload_str = payload_bytes.decode("utf-8")
        assert "syslog test" in payload_str
        assert addr == ("127.0.0.1", 514)

    def test_priority_encoding(self) -> None:
        mock_socket = MagicMock()
        with patch("penguintechinc_utils.sinks.socket.socket", return_value=mock_socket):
            # facility=1 (USER), severity debug=7 → priority = (1<<3)|7 = 15
            sink = SyslogSink(host="localhost", facility=1)
            sink.emit({"level": "debug", "event": "prio test"})

        payload_bytes = mock_socket.sendto.call_args[0][0]
        assert payload_bytes.startswith(b"<15>")

    def test_flush_and_close_do_not_raise(self) -> None:
        mock_socket = MagicMock()
        with patch("penguintechinc_utils.sinks.socket.socket", return_value=mock_socket):
            sink = SyslogSink(host="localhost")
            sink.flush()
            sink.close()
        mock_socket.close.assert_called_once()

    def test_satisfies_sink_protocol(self) -> None:
        mock_socket = MagicMock()
        with patch("penguintechinc_utils.sinks.socket.socket", return_value=mock_socket):
            assert isinstance(SyslogSink(host="localhost"), Sink)


# ---------------------------------------------------------------------------
# CallbackSink
# ---------------------------------------------------------------------------


class TestCallbackSink:
    def test_emit_invokes_callback(self) -> None:
        received: list[dict[str, Any]] = []
        sink = CallbackSink(received.append)
        event = {"level": "info", "event": "callback test"}
        sink.emit(event)
        assert received == [event]

    def test_callback_receives_copy_of_event(self) -> None:
        received: list[dict[str, Any]] = []
        sink = CallbackSink(received.append)
        original = {"level": "info", "event": "original"}
        sink.emit(original)
        # mutation of original should not affect received
        original["event"] = "mutated"
        assert received[0]["event"] == "original"

    def test_flush_and_close_do_not_raise(self) -> None:
        sink = CallbackSink(lambda e: None)
        sink.flush()
        sink.close()

    def test_satisfies_sink_protocol(self) -> None:
        assert isinstance(CallbackSink(lambda e: None), Sink)
