"""
Tests for the KillKrill log aggregation sink.
"""

import json
import threading
import time
from typing import Any
from unittest.mock import MagicMock, patch

import httpx
import pytest

from penguintechinc_utils import KillKrillConfig, KillKrillSink
from penguintechinc_utils.sinks import Sink


# ---------------------------------------------------------------------------
# KillKrillConfig
# ---------------------------------------------------------------------------


class TestKillKrillConfig:
    def test_required_fields(self) -> None:
        cfg = KillKrillConfig(endpoint="https://logs.example.io", api_key="key-123")
        assert cfg.endpoint == "https://logs.example.io"
        assert cfg.api_key == "key-123"

    def test_default_values(self) -> None:
        cfg = KillKrillConfig(endpoint="https://logs.example.io", api_key="k")
        assert cfg.batch_size == 100
        assert cfg.flush_interval == 5.0
        assert cfg.use_grpc is False
        assert cfg.timeout == 10.0
        assert cfg.max_retries == 3

    def test_custom_values(self) -> None:
        cfg = KillKrillConfig(
            endpoint="https://logs.example.io",
            api_key="k",
            batch_size=50,
            flush_interval=2.0,
            timeout=5.0,
            max_retries=5,
        )
        assert cfg.batch_size == 50
        assert cfg.flush_interval == 2.0
        assert cfg.max_retries == 5

    def test_uses_slots(self) -> None:
        cfg = KillKrillConfig(endpoint="x", api_key="y")
        assert not hasattr(cfg, "__dict__")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_config(**overrides: Any) -> KillKrillConfig:
    defaults = {
        "endpoint": "https://logs.example.io",
        "api_key": "test-key",
        "batch_size": 10,
        "flush_interval": 60.0,  # long interval so tests control flush timing
        "max_retries": 3,
        "timeout": 5.0,
    }
    defaults.update(overrides)
    return KillKrillConfig(**defaults)


def _make_sink(config: KillKrillConfig, mock_client: MagicMock) -> KillKrillSink:
    """Return a KillKrillSink whose httpx.Client is replaced by mock_client."""
    with patch("penguintechinc_utils.killkrill.httpx.Client", return_value=mock_client):
        return KillKrillSink(config)


def _ok_response() -> MagicMock:
    resp = MagicMock(spec=httpx.Response)
    resp.raise_for_status = MagicMock()
    return resp


def _error_response() -> MagicMock:
    resp = MagicMock(spec=httpx.Response)
    resp.raise_for_status.side_effect = httpx.HTTPStatusError(
        "500", request=MagicMock(), response=MagicMock()
    )
    return resp


# ---------------------------------------------------------------------------
# KillKrillSink — basic behaviour
# ---------------------------------------------------------------------------


class TestKillKrillSinkEmitAndFlush:
    def test_satisfies_sink_protocol(self) -> None:
        mock_client = MagicMock()
        mock_client.post.return_value = _ok_response()
        sink = _make_sink(_make_config(), mock_client)
        try:
            assert isinstance(sink, Sink)
        finally:
            sink.close()

    def test_flush_posts_buffered_events(self) -> None:
        mock_client = MagicMock()
        mock_client.post.return_value = _ok_response()
        config = _make_config()
        sink = _make_sink(config, mock_client)

        try:
            sink.emit({"event": "alpha"})
            sink.emit({"event": "beta"})
            sink.flush()

            mock_client.post.assert_called_once()
            url, payload = _extract_post_call(mock_client)
            assert url == "https://logs.example.io/api/v1/events"
            assert any(e["event"] == "alpha" for e in payload)
            assert any(e["event"] == "beta" for e in payload)
        finally:
            sink.close()

    def test_flush_noop_when_buffer_empty(self) -> None:
        mock_client = MagicMock()
        config = _make_config()
        sink = _make_sink(config, mock_client)
        try:
            sink.flush()
            mock_client.post.assert_not_called()
        finally:
            sink.close()

    def test_eager_flush_when_batch_full(self) -> None:
        mock_client = MagicMock()
        mock_client.post.return_value = _ok_response()
        config = _make_config(batch_size=3)
        sink = _make_sink(config, mock_client)

        try:
            for i in range(3):
                sink.emit({"event": f"item-{i}"})
            # Batch was full — post should have been called automatically
            assert mock_client.post.call_count >= 1
        finally:
            sink.close()

    def test_close_flushes_remaining_events(self) -> None:
        mock_client = MagicMock()
        mock_client.post.return_value = _ok_response()
        config = _make_config()
        sink = _make_sink(config, mock_client)

        sink.emit({"event": "before-close"})
        sink.close()

        assert mock_client.post.call_count >= 1
        _, payload = _extract_post_call(mock_client)
        assert any(e["event"] == "before-close" for e in payload)

    def test_authorization_header(self) -> None:
        mock_client = MagicMock()
        mock_client.post.return_value = _ok_response()
        config = _make_config(api_key="my-secret-key")
        with patch("penguintechinc_utils.killkrill.httpx.Client") as MockClient:
            MockClient.return_value = mock_client
            KillKrillSink(config).close()
            _, kwargs = MockClient.call_args
            headers = kwargs.get("headers", {})
            assert headers.get("Authorization") == "Bearer my-secret-key"


# ---------------------------------------------------------------------------
# KillKrillSink — retry behaviour
# ---------------------------------------------------------------------------


class TestKillKrillSinkRetry:
    def test_retries_on_http_error(self) -> None:
        mock_client = MagicMock()
        # Fail twice, succeed on third attempt
        mock_client.post.side_effect = [
            httpx.NetworkError("timeout"),
            httpx.NetworkError("timeout"),
            _ok_response(),
        ]
        config = _make_config(max_retries=3)

        with patch("penguintechinc_utils.killkrill.time.sleep"):
            sink = _make_sink(config, mock_client)
            try:
                sink.emit({"event": "retry-test"})
                sink.flush()
            finally:
                sink.close()

        assert mock_client.post.call_count >= 3

    def test_drops_batch_after_max_retries(self) -> None:
        mock_client = MagicMock()
        mock_client.post.side_effect = httpx.NetworkError("always fails")
        config = _make_config(max_retries=2)

        with patch("penguintechinc_utils.killkrill.time.sleep"):
            sink = _make_sink(config, mock_client)
            try:
                sink.emit({"event": "will-be-dropped"})
                sink.flush()
            finally:
                sink.close()

        # Should have attempted exactly max_retries times
        assert mock_client.post.call_count == config.max_retries

    def test_backoff_increases_between_attempts(self) -> None:
        mock_client = MagicMock()
        mock_client.post.side_effect = [
            httpx.NetworkError("fail"),
            httpx.NetworkError("fail"),
            _ok_response(),
        ]
        config = _make_config(max_retries=3)
        sleep_calls: list[float] = []

        with patch("penguintechinc_utils.killkrill.time.sleep", side_effect=sleep_calls.append):
            sink = _make_sink(config, mock_client)
            try:
                sink.emit({"event": "backoff-test"})
                sink.flush()
            finally:
                sink.close()

        # Backoff should be increasing: 1s, 2s, …
        for i in range(1, len(sleep_calls)):
            assert sleep_calls[i] >= sleep_calls[i - 1]


# ---------------------------------------------------------------------------
# KillKrillSink — background flush thread
# ---------------------------------------------------------------------------


class TestKillKrillSinkBackgroundFlush:
    def test_background_thread_is_daemon(self) -> None:
        mock_client = MagicMock()
        mock_client.post.return_value = _ok_response()
        config = _make_config(flush_interval=0.05)
        sink = _make_sink(config, mock_client)
        try:
            assert sink._flush_thread.daemon is True
        finally:
            sink.close()

    def test_background_thread_flushes_automatically(self) -> None:
        mock_client = MagicMock()
        mock_client.post.return_value = _ok_response()
        config = _make_config(flush_interval=0.05)
        sink = _make_sink(config, mock_client)

        try:
            sink.emit({"event": "auto-flush"})
            # Wait long enough for at least one background flush
            time.sleep(0.2)
            assert mock_client.post.call_count >= 1
        finally:
            sink.close()

    def test_close_stops_background_thread(self) -> None:
        mock_client = MagicMock()
        mock_client.post.return_value = _ok_response()
        config = _make_config(flush_interval=60.0)
        sink = _make_sink(config, mock_client)

        thread = sink._flush_thread
        assert thread.is_alive()
        sink.close()
        thread.join(timeout=2.0)
        assert not thread.is_alive()


# ---------------------------------------------------------------------------
# Payload format
# ---------------------------------------------------------------------------


class TestKillKrillPayloadFormat:
    def test_payload_is_json_array(self) -> None:
        mock_client = MagicMock()
        mock_client.post.return_value = _ok_response()
        config = _make_config()
        sink = _make_sink(config, mock_client)

        try:
            sink.emit({"event": "json-check", "level": "info"})
            sink.flush()
        finally:
            sink.close()

        _, payload = _extract_post_call(mock_client)
        assert isinstance(payload, list)
        assert payload[0]["event"] == "json-check"

    def test_content_type_header(self) -> None:
        mock_client = MagicMock()
        mock_client.post.return_value = _ok_response()
        config = _make_config(api_key="k")

        with patch("penguintechinc_utils.killkrill.httpx.Client") as MockClient:
            MockClient.return_value = mock_client
            sink = KillKrillSink(config)
            sink.emit({"event": "ct-test"})
            sink.flush()
            sink.close()

            _, kwargs = MockClient.call_args
            assert kwargs["headers"]["Content-Type"] == "application/json"


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------


def _extract_post_call(mock_client: MagicMock) -> tuple[str, list[dict[str, Any]]]:
    """Return (url, decoded_payload_list) from the first post() call."""
    call = mock_client.post.call_args_list[0]
    url: str = call[0][0]
    content: bytes = call[1].get("content", b"[]")
    return url, json.loads(content)
