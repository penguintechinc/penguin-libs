"""Tests for cloud log sinks (CloudWatch, GCP, Kafka) and configure_logging_from_env."""

import sys
from unittest.mock import MagicMock, patch

import pytest

from penguintechinc_utils.logging import configure_logging_from_env

# Import the module under test at module level so it is always loaded.
from penguintechinc_utils.sinks import CloudWatchSink, GCPCloudLoggingSink, KafkaSink


class TestCloudWatchSink:
    def test_import_error_without_boto3(self):
        """CloudWatchSink raises ImportError when boto3 not installed."""
        with patch.dict(sys.modules, {"boto3": None}):
            with pytest.raises(ImportError, match="boto3"):
                CloudWatchSink(log_group="g", log_stream="s")

    def test_cloudwatch_sink_buffers_events(self):
        """Events are buffered until batch_size is reached."""
        mock_boto3 = MagicMock()
        mock_client = MagicMock()
        mock_boto3.client.return_value = mock_client
        mock_client.put_log_events.return_value = {"nextSequenceToken": "tok1"}

        with patch.dict(sys.modules, {"boto3": mock_boto3}):
            sink = CloudWatchSink(log_group="mygroup", log_stream="mystream", batch_size=2)

        event1 = {"event": "msg1", "level": "info"}
        event2 = {"event": "msg2", "level": "info"}

        # First event — not flushed yet
        sink(None, "info", event1)
        mock_client.put_log_events.assert_not_called()

        # Second event — batch_size reached, flush triggered
        sink(None, "info", event2)
        mock_client.put_log_events.assert_called_once()

    def test_cloudwatch_sink_flush_empty_buffer(self):
        """Flush with empty buffer is a no-op."""
        mock_boto3 = MagicMock()
        mock_client = MagicMock()
        mock_boto3.client.return_value = mock_client

        with patch.dict(sys.modules, {"boto3": mock_boto3}):
            sink = CloudWatchSink(log_group="g", log_stream="s")

        sink.flush()  # Should not raise
        mock_client.put_log_events.assert_not_called()

    def test_cloudwatch_sink_sequence_token(self):
        """Sequence token is stored after PutLogEvents and used next time."""
        mock_boto3 = MagicMock()
        mock_client = MagicMock()
        mock_boto3.client.return_value = mock_client
        mock_client.put_log_events.return_value = {"nextSequenceToken": "token123"}

        with patch.dict(sys.modules, {"boto3": mock_boto3}):
            sink = CloudWatchSink(log_group="g", log_stream="s", batch_size=1)

        sink(None, "info", {"event": "first"})
        # After first flush, sequence token is stored
        assert sink._sequence_token == "token123"

    def test_cloudwatch_sink_returns_event_dict(self):
        """CloudWatchSink __call__ returns event_dict (structlog protocol)."""
        mock_boto3 = MagicMock()
        mock_boto3.client.return_value = MagicMock()

        with patch.dict(sys.modules, {"boto3": mock_boto3}):
            sink = CloudWatchSink(log_group="g", log_stream="s", batch_size=100)

        event = {"event": "test"}
        result = sink(None, "info", event)
        assert result is event


class TestGCPCloudLoggingSink:
    def test_import_error_without_gcp(self):
        """GCPCloudLoggingSink raises ImportError when google-cloud-logging not installed."""
        mock_modules = {
            "google": None,
            "google.cloud": None,
            "google.cloud.logging": None,
        }
        with patch.dict(sys.modules, mock_modules):
            with pytest.raises(ImportError, match="google-cloud-logging"):
                GCPCloudLoggingSink(project_id="proj", log_name="log")

    def test_gcp_sink_logs_event(self):
        """GCPCloudLoggingSink calls log_struct with event dict."""
        # The sink does: from google.cloud import logging as gcp_logging
        # then: client = gcp_logging.Client(project=project_id)
        # then: self._logger = client.logger(log_name)
        # So mock_gcp_logging_module.Client().logger() is self._logger.
        mock_gcp_logging_module = MagicMock()
        mock_logger_instance = MagicMock()
        mock_gcp_logging_module.Client.return_value.logger.return_value = mock_logger_instance

        mock_google_cloud = MagicMock()
        mock_google_cloud.logging = mock_gcp_logging_module

        mock_modules = {
            "google": MagicMock(),
            "google.cloud": mock_google_cloud,
            "google.cloud.logging": mock_gcp_logging_module,
        }
        with patch.dict(sys.modules, mock_modules):
            sink = GCPCloudLoggingSink(project_id="my-project", log_name="app-log")

        event = {"event": "user_login", "user_id": "abc"}
        sink(None, "info", event)
        mock_logger_instance.log_struct.assert_called_once_with(event, severity="INFO")

    def test_gcp_sink_returns_event_dict(self):
        """GCPCloudLoggingSink returns event_dict (structlog protocol)."""
        mock_gcp = MagicMock()
        mock_modules = {
            "google": MagicMock(),
            "google.cloud": MagicMock(),
            "google.cloud.logging": mock_gcp,
        }
        with patch.dict(sys.modules, mock_modules):
            sink = GCPCloudLoggingSink(project_id="proj", log_name="log")

        event = {"event": "test"}
        result = sink(None, "warning", event)
        assert result is event


class TestKafkaSink:
    def test_import_error_without_kafka(self):
        """KafkaSink raises ImportError when kafka-python not installed."""
        with patch.dict(sys.modules, {"kafka": None}):
            with pytest.raises(ImportError, match="kafka-python"):
                KafkaSink(bootstrap_servers="localhost:9092", topic="logs")

    def test_kafka_sink_sends_message(self):
        """KafkaSink sends event dict as JSON to configured topic."""
        mock_kafka = MagicMock()
        mock_producer = MagicMock()
        mock_kafka.KafkaProducer.return_value = mock_producer

        with patch.dict(sys.modules, {"kafka": mock_kafka}):
            sink = KafkaSink(bootstrap_servers="broker1:9092", topic="app-logs")

        event = {"event": "request", "path": "/api/v1/status"}
        sink(None, "info", event)
        mock_producer.send.assert_called_once_with("app-logs", value=event)

    def test_kafka_sink_flush(self):
        """KafkaSink.flush() calls producer.flush()."""
        mock_kafka = MagicMock()
        mock_producer = MagicMock()
        mock_kafka.KafkaProducer.return_value = mock_producer

        with patch.dict(sys.modules, {"kafka": mock_kafka}):
            sink = KafkaSink(bootstrap_servers="broker1:9092", topic="logs")

        sink.flush()
        mock_producer.flush.assert_called_once()

    def test_kafka_sink_multiple_brokers(self):
        """KafkaSink splits comma-separated bootstrap_servers."""
        mock_kafka = MagicMock()
        mock_producer = MagicMock()
        mock_kafka.KafkaProducer.return_value = mock_producer

        with patch.dict(sys.modules, {"kafka": mock_kafka}):
            KafkaSink(bootstrap_servers="broker1:9092,broker2:9092", topic="logs")

        call_kwargs = mock_kafka.KafkaProducer.call_args
        servers = call_kwargs[1]["bootstrap_servers"]
        assert "broker1:9092" in servers
        assert "broker2:9092" in servers

    def test_kafka_sink_returns_event_dict(self):
        """KafkaSink __call__ returns event_dict (structlog protocol)."""
        mock_kafka = MagicMock()
        mock_kafka.KafkaProducer.return_value = MagicMock()

        with patch.dict(sys.modules, {"kafka": mock_kafka}):
            sink = KafkaSink(bootstrap_servers="broker:9092", topic="logs")

        event = {"event": "test"}
        result = sink(None, "info", event)
        assert result is event


class TestConfigureLoggingFromEnv:
    def _clean_env(self, monkeypatch):
        """Remove all LOG_* env vars relevant to sinks."""
        for key in (
            "LOG_CLOUDWATCH_GROUP",
            "LOG_CLOUDWATCH_STREAM",
            "LOG_GCP_PROJECT",
            "LOG_GCP_LOG_NAME",
            "LOG_KAFKA_SERVERS",
            "LOG_KAFKA_TOPIC",
        ):
            monkeypatch.delenv(key, raising=False)

    def test_no_env_vars_returns_empty(self, monkeypatch):
        """No env vars set returns empty sink list."""
        self._clean_env(monkeypatch)
        sinks = configure_logging_from_env()
        assert sinks == []

    def test_cloudwatch_env_vars_creates_sink(self, monkeypatch):
        """LOG_CLOUDWATCH_GROUP + LOG_CLOUDWATCH_STREAM creates CloudWatchSink."""
        self._clean_env(monkeypatch)
        monkeypatch.setenv("LOG_CLOUDWATCH_GROUP", "my-group")
        monkeypatch.setenv("LOG_CLOUDWATCH_STREAM", "my-stream")

        mock_boto3 = MagicMock()
        mock_boto3.client.return_value = MagicMock()
        with patch.dict(sys.modules, {"boto3": mock_boto3}):
            sinks = configure_logging_from_env()

        assert len(sinks) == 1
        assert isinstance(sinks[0], CloudWatchSink)

    def test_gcp_env_vars_creates_sink(self, monkeypatch):
        """LOG_GCP_PROJECT + LOG_GCP_LOG_NAME creates GCPCloudLoggingSink."""
        self._clean_env(monkeypatch)
        monkeypatch.setenv("LOG_GCP_PROJECT", "my-project")
        monkeypatch.setenv("LOG_GCP_LOG_NAME", "app-log")

        mock_gcp = MagicMock()
        mock_modules = {
            "google": MagicMock(),
            "google.cloud": MagicMock(),
            "google.cloud.logging": mock_gcp,
        }
        with patch.dict(sys.modules, mock_modules):
            sinks = configure_logging_from_env()

        assert len(sinks) == 1
        assert isinstance(sinks[0], GCPCloudLoggingSink)

    def test_kafka_env_vars_creates_sink(self, monkeypatch):
        """LOG_KAFKA_SERVERS + LOG_KAFKA_TOPIC creates KafkaSink."""
        self._clean_env(monkeypatch)
        monkeypatch.setenv("LOG_KAFKA_SERVERS", "broker:9092")
        monkeypatch.setenv("LOG_KAFKA_TOPIC", "logs")

        mock_kafka = MagicMock()
        mock_kafka.KafkaProducer.return_value = MagicMock()
        with patch.dict(sys.modules, {"kafka": mock_kafka}):
            sinks = configure_logging_from_env()

        assert len(sinks) == 1
        assert isinstance(sinks[0], KafkaSink)

    def test_partial_env_vars_no_sink(self, monkeypatch):
        """Only one of the required pair set — no sink created."""
        self._clean_env(monkeypatch)
        monkeypatch.setenv("LOG_CLOUDWATCH_GROUP", "my-group")
        # LOG_CLOUDWATCH_STREAM not set

        sinks = configure_logging_from_env()
        assert sinks == []
