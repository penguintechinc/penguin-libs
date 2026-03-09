"""Tests for penguin_aaa.audit.killkrill module."""

from __future__ import annotations

import logging
from unittest.mock import MagicMock, patch

import httpx
import pytest

from penguin_aaa.audit.killkrill import KillKrillConfig, KillKrillSink

# ---------------------------------------------------------------------------
# KillKrillConfig
# ---------------------------------------------------------------------------


class TestKillKrillConfig:
    def test_defaults(self) -> None:
        cfg = KillKrillConfig(endpoint="https://audit.example.io", api_key="key-1")
        assert cfg.endpoint == "https://audit.example.io"
        assert cfg.api_key == "key-1"
        assert cfg.batch_size == 100
        assert cfg.flush_interval == 5.0
        assert cfg.timeout == 10.0
        assert cfg.max_retries == 3

    def test_custom_values(self) -> None:
        cfg = KillKrillConfig(
            endpoint="https://x.io",
            api_key="k",
            batch_size=10,
            flush_interval=1.0,
            timeout=2.0,
            max_retries=0,
        )
        assert cfg.batch_size == 10
        assert cfg.flush_interval == 1.0
        assert cfg.timeout == 2.0
        assert cfg.max_retries == 0


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_sink(
    batch_size: int = 100,
    max_retries: int = 3,
    endpoint: str = "https://audit.example.io",
) -> KillKrillSink:
    """Create a sink with a very long flush_interval so the bg thread won't fire."""
    cfg = KillKrillConfig(
        endpoint=endpoint,
        api_key="test-key",
        batch_size=batch_size,
        flush_interval=999,
        timeout=5.0,
        max_retries=max_retries,
    )
    return KillKrillSink(cfg)


# ---------------------------------------------------------------------------
# KillKrillSink
# ---------------------------------------------------------------------------


class TestKillKrillSink:
    def test_emit_buffers_event(self) -> None:
        sink = _make_sink()
        try:
            sink.emit({"action": "login"})
            assert len(sink._buffer) == 1
            assert sink._buffer[0] == {"action": "login"}
        finally:
            sink._stopped.set()

    def test_emit_triggers_flush_at_batch_size(self) -> None:
        sink = _make_sink(batch_size=2)
        try:
            with patch.object(sink, "_flush_now") as mock_flush:
                sink.emit({"a": 1})
                mock_flush.assert_not_called()
                sink.emit({"a": 2})
                mock_flush.assert_called_once()
        finally:
            sink._stopped.set()

    def test_flush_calls_flush_now(self) -> None:
        sink = _make_sink()
        try:
            with patch.object(sink, "_flush_now") as mock_flush:
                sink.flush()
                mock_flush.assert_called_once()
        finally:
            sink._stopped.set()

    def test_close_stops_thread_and_flushes(self) -> None:
        sink = _make_sink()
        with patch.object(sink, "_flush_now") as mock_flush:
            sink.close()
            assert sink._stopped.is_set()
            assert not sink._thread.is_alive()
            mock_flush.assert_called_once()

    def test_flush_now_empty_buffer_noop(self) -> None:
        sink = _make_sink()
        try:
            # Should return without doing anything when buffer is empty.
            with patch("httpx.Client") as mock_client_cls:
                sink._flush_now()
                mock_client_cls.assert_not_called()
        finally:
            sink._stopped.set()

    @patch("penguin_aaa.audit.killkrill.time.sleep")
    @patch("httpx.Client")
    def test_flush_now_successful_post(
        self, mock_client_cls: MagicMock, _mock_sleep: MagicMock
    ) -> None:
        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock()
        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.post.return_value = mock_response
        mock_client_cls.return_value = mock_client

        sink = _make_sink()
        try:
            sink._buffer.append({"action": "test"})
            sink._flush_now()

            mock_client.post.assert_called_once()
            call_args = mock_client.post.call_args
            assert "/api/v1/events" in call_args[0][0] or "/api/v1/events" in str(
                call_args
            )
            assert len(sink._buffer) == 0
        finally:
            sink._stopped.set()

    @patch("penguin_aaa.audit.killkrill.time.sleep")
    @patch("httpx.Client")
    def test_flush_now_retries_on_failure(
        self, mock_client_cls: MagicMock, mock_sleep: MagicMock
    ) -> None:
        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        # Fail twice, then succeed on third attempt.
        mock_response_ok = MagicMock()
        mock_response_ok.raise_for_status = MagicMock()
        mock_client.post.side_effect = [
            httpx.HTTPStatusError("500", request=MagicMock(), response=MagicMock()),
            httpx.HTTPStatusError("500", request=MagicMock(), response=MagicMock()),
            mock_response_ok,
        ]
        mock_client_cls.return_value = mock_client

        sink = _make_sink(max_retries=3)
        try:
            sink._buffer.append({"action": "retry-test"})
            sink._flush_now()

            assert mock_client.post.call_count == 3
            assert mock_sleep.call_count == 2
            # backoff: 2^0=1, 2^1=2
            mock_sleep.assert_any_call(1)
            mock_sleep.assert_any_call(2)
        finally:
            sink._stopped.set()

    @patch("penguin_aaa.audit.killkrill.time.sleep")
    @patch("httpx.Client")
    def test_flush_now_logs_error_after_all_retries(
        self,
        mock_client_cls: MagicMock,
        mock_sleep: MagicMock,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.post.side_effect = RuntimeError("connection refused")
        mock_client_cls.return_value = mock_client

        sink = _make_sink(max_retries=2)
        try:
            sink._buffer.extend([{"a": 1}, {"a": 2}])
            with caplog.at_level(logging.ERROR, logger="penguin_aaa.audit.killkrill"):
                sink._flush_now()

            # 1 initial + 2 retries = 3 attempts
            assert mock_client.post.call_count == 3
            assert "failed after 3 attempts" in caplog.text
            assert "2 events dropped" in caplog.text
        finally:
            sink._stopped.set()

    @patch("penguin_aaa.audit.killkrill.time.sleep")
    @patch("httpx.Client")
    def test_flush_now_no_retries_when_max_retries_zero(
        self,
        mock_client_cls: MagicMock,
        mock_sleep: MagicMock,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.post.side_effect = RuntimeError("fail")
        mock_client_cls.return_value = mock_client

        sink = _make_sink(max_retries=0)
        try:
            sink._buffer.append({"x": 1})
            with caplog.at_level(logging.ERROR, logger="penguin_aaa.audit.killkrill"):
                sink._flush_now()

            assert mock_client.post.call_count == 1
            mock_sleep.assert_not_called()
            assert "failed after 1 attempts" in caplog.text
        finally:
            sink._stopped.set()

    def test_endpoint_trailing_slash_stripped(self) -> None:
        sink = _make_sink(endpoint="https://audit.example.io/")
        try:
            with patch("httpx.Client") as mock_client_cls:
                mock_client = MagicMock()
                mock_client.__enter__ = MagicMock(return_value=mock_client)
                mock_client.__exit__ = MagicMock(return_value=False)
                mock_response = MagicMock()
                mock_response.raise_for_status = MagicMock()
                mock_client.post.return_value = mock_response
                mock_client_cls.return_value = mock_client

                sink._buffer.append({"e": 1})
                sink._flush_now()

                url_arg = mock_client.post.call_args[0][0]
                assert url_arg == "https://audit.example.io/api/v1/events"
        finally:
            sink._stopped.set()
