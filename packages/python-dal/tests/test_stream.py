"""Tests for streaming backends."""
from __future__ import annotations

import base64
import json
import sys
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

# Mock the external streaming libraries before importing stream modules
sys.modules["confluent_kafka"] = MagicMock()
sys.modules["valkey"] = MagicMock()

from penguin_dal.stream.kafka import KafkaConfig, KafkaConsumer, KafkaProducer
from penguin_dal.stream.redis_streams import (
    RedisStreamConfig,
    RedisStreamConsumer,
    RedisStreamProducer,
)
from penguin_dal.stream.valkey_streams import (
    ValkeyStreamConfig,
    ValkeyStreamConsumer,
    ValkeyStreamProducer,
)


class TestKafkaProducer:
    """Tests for KafkaProducer."""

    def test_init_success(self):
        """Test successful producer initialization."""
        mock_producer_instance = MagicMock()
        sys.modules["confluent_kafka"].Producer = MagicMock(return_value=mock_producer_instance)
        config = KafkaConfig(bootstrap_servers=["localhost:9092"])
        producer = KafkaProducer(config)
        assert producer._config == config

    def test_publish_basic(self):
        """Test publishing a basic message."""
        mock_producer = MagicMock()
        sys.modules["confluent_kafka"].Producer = MagicMock(return_value=mock_producer)
        config = KafkaConfig(bootstrap_servers=["localhost:9092"])
        producer = KafkaProducer(config)

        producer.publish(b"test_topic", b"test_message")

        mock_producer.produce.assert_called_once()
        call_kwargs = mock_producer.produce.call_args[1]
        assert call_kwargs["topic"] == b"test_topic"
        assert call_kwargs["value"] == b"test_message"

    def test_publish_with_key(self):
        """Test publishing message with key."""
        mock_producer = MagicMock()
        sys.modules["confluent_kafka"].Producer = MagicMock(return_value=mock_producer)
        config = KafkaConfig(bootstrap_servers=["localhost:9092"])
        producer = KafkaProducer(config)

        producer.publish(b"test_topic", b"test_message", key=b"test_key")

        call_kwargs = mock_producer.produce.call_args[1]
        assert call_kwargs["key"] == b"test_key"

    def test_publish_with_headers(self):
        """Test publishing message with headers."""
        mock_producer = MagicMock()
        sys.modules["confluent_kafka"].Producer = MagicMock(return_value=mock_producer)
        config = KafkaConfig(bootstrap_servers=["localhost:9092"])
        producer = KafkaProducer(config)

        headers = {"header1": "value1", "header2": "value2"}
        producer.publish(b"test_topic", b"test_message", headers=headers)

        call_kwargs = mock_producer.produce.call_args[1]
        header_list = call_kwargs["headers"]
        assert ("header1", b"value1") in header_list
        assert ("header2", b"value2") in header_list

    def test_publish_error(self):
        """Test publish raises on error."""
        mock_producer = MagicMock()

        def side_effect(topic, value, key=None, headers=None, on_delivery=None):
            on_delivery(Exception("Delivery failed"), None)

        mock_producer.produce.side_effect = side_effect
        mock_producer.flush.return_value = None

        sys.modules["confluent_kafka"].Producer = MagicMock(return_value=mock_producer)
        config = KafkaConfig(bootstrap_servers=["localhost:9092"])
        producer = KafkaProducer(config)

        with pytest.raises(RuntimeError, match="Failed to publish"):
            producer.publish(b"test_topic", b"test_message")

    def test_flush(self):
        """Test flush operation."""
        mock_producer = MagicMock()
        sys.modules["confluent_kafka"].Producer = MagicMock(return_value=mock_producer)
        config = KafkaConfig(bootstrap_servers=["localhost:9092"])
        producer = KafkaProducer(config)

        producer.flush(timeout=5.0)
        mock_producer.flush.assert_called_with(5.0)

    def test_close(self):
        """Test close operation."""
        mock_producer = MagicMock()
        sys.modules["confluent_kafka"].Producer = MagicMock(return_value=mock_producer)
        config = KafkaConfig(bootstrap_servers=["localhost:9092"])
        producer = KafkaProducer(config)

        producer.close()
        mock_producer.flush.assert_called_once()
        assert producer._producer is None


class TestKafkaConsumer:
    """Tests for KafkaConsumer."""

    def test_init_success(self):
        """Test successful consumer initialization."""
        mock_consumer_instance = MagicMock()
        sys.modules["confluent_kafka"].Consumer = MagicMock(return_value=mock_consumer_instance)
        config = KafkaConfig(bootstrap_servers=["localhost:9092"])
        consumer = KafkaConsumer(config)
        assert consumer._config == config

    def test_subscribe(self):
        """Test topic subscription."""
        mock_consumer = MagicMock()
        sys.modules["confluent_kafka"].Consumer = MagicMock(return_value=mock_consumer)
        config = KafkaConfig(bootstrap_servers=["localhost:9092"])
        consumer = KafkaConsumer(config)

        consumer.subscribe(["topic1", "topic2"])
        mock_consumer.subscribe.assert_called_once_with(["topic1", "topic2"])

    def test_poll_no_messages(self):
        """Test poll returns empty list when no messages."""
        mock_consumer = MagicMock()
        mock_consumer.poll.return_value = None
        sys.modules["confluent_kafka"].Consumer = MagicMock(return_value=mock_consumer)
        config = KafkaConfig(bootstrap_servers=["localhost:9092"])
        consumer = KafkaConsumer(config)

        messages = consumer.poll(timeout_ms=100)
        assert messages == []

    def test_poll_single_message(self):
        """Test poll returns StreamMessage correctly."""
        mock_consumer = MagicMock()
        mock_msg = MagicMock()
        mock_msg.topic.return_value = "test_topic"
        mock_msg.partition.return_value = 0
        mock_msg.offset.return_value = 123
        mock_msg.key.return_value = b"test_key"
        mock_msg.value.return_value = b"test_value"
        mock_msg.headers.return_value = [("header1", b"value1")]
        mock_msg.timestamp.return_value = (0, 1000000)  # type, millis
        mock_msg.error.return_value = None

        mock_consumer.poll.side_effect = [mock_msg, None]

        sys.modules["confluent_kafka"].Consumer = MagicMock(return_value=mock_consumer)
        config = KafkaConfig(bootstrap_servers=["localhost:9092"])
        consumer = KafkaConsumer(config)

        messages = consumer.poll(timeout_ms=100)
        assert len(messages) == 1
        assert messages[0].topic == "test_topic"
        assert messages[0].partition == 0
        assert messages[0].offset == 123
        assert messages[0].key == b"test_key"
        assert messages[0].value == b"test_value"
        assert messages[0].headers == {"header1": "value1"}

    def test_poll_error_partition_eof(self):
        """Test poll skips ErrPartitionEOF."""
        mock_consumer = MagicMock()
        mock_msg_error = MagicMock()
        mock_error_obj = MagicMock()
        mock_error_obj.code.return_value = -191  # ErrPartitionEOF
        mock_msg_error.error.return_value = mock_error_obj

        mock_msg_valid = MagicMock()
        mock_msg_valid.topic.return_value = "test_topic"
        mock_msg_valid.partition.return_value = 0
        mock_msg_valid.offset.return_value = 123
        mock_msg_valid.key.return_value = None
        mock_msg_valid.value.return_value = b"test_value"
        mock_msg_valid.headers.return_value = []
        mock_msg_valid.timestamp.return_value = (0, 1000000)
        mock_msg_valid.error.return_value = None

        mock_consumer.poll.side_effect = [mock_msg_error, mock_msg_valid, None]

        sys.modules["confluent_kafka"].Consumer = MagicMock(return_value=mock_consumer)
        config = KafkaConfig(bootstrap_servers=["localhost:9092"])
        consumer = KafkaConsumer(config)

        messages = consumer.poll(timeout_ms=100)
        assert len(messages) == 1

    def test_poll_error_other(self):
        """Test poll raises on non-EOF error."""
        mock_consumer = MagicMock()
        mock_msg = MagicMock()
        mock_error_obj = MagicMock()
        mock_error_obj.code.return_value = -1  # Some other error
        mock_msg.error.return_value = mock_error_obj

        mock_consumer.poll.return_value = mock_msg

        sys.modules["confluent_kafka"].Consumer = MagicMock(return_value=mock_consumer)
        config = KafkaConfig(bootstrap_servers=["localhost:9092"])
        consumer = KafkaConsumer(config)

        with pytest.raises(RuntimeError, match="Consumer error"):
            consumer.poll(timeout_ms=100)

    def test_commit(self):
        """Test commit operation."""
        mock_consumer = MagicMock()
        sys.modules["confluent_kafka"].Consumer = MagicMock(return_value=mock_consumer)
        config = KafkaConfig(bootstrap_servers=["localhost:9092"])
        consumer = KafkaConsumer(config)

        consumer.commit()
        mock_consumer.commit.assert_called_once_with(asynchronous=False)

    def test_close(self):
        """Test close operation."""
        mock_consumer = MagicMock()
        sys.modules["confluent_kafka"].Consumer = MagicMock(return_value=mock_consumer)
        config = KafkaConfig(bootstrap_servers=["localhost:9092"])
        consumer = KafkaConsumer(config)

        consumer.close()
        mock_consumer.close.assert_called_once()


class TestRedisStreamProducer:
    """Tests for RedisStreamProducer."""

    def test_init_success(self):
        """Test successful producer initialization."""
        with patch("redis.Redis"):
            config = RedisStreamConfig()
            producer = RedisStreamProducer(config)
            assert producer._config == config

    def test_publish_basic(self):
        """Test publishing message to Redis stream."""
        mock_redis = MagicMock()
        with patch("redis.Redis", return_value=mock_redis):
            config = RedisStreamConfig()
            producer = RedisStreamProducer(config)

            producer.publish("test_stream", b"test_message")

            call_args = mock_redis.xadd.call_args
            assert call_args[0][0] == "test_stream"
            data = call_args[0][1]
            assert base64.b64decode(data["value"]) == b"test_message"
            assert data["key"] == ""

    def test_publish_with_key(self):
        """Test publishing message with key."""
        mock_redis = MagicMock()
        with patch("redis.Redis", return_value=mock_redis):
            config = RedisStreamConfig()
            producer = RedisStreamProducer(config)

            producer.publish("test_stream", b"test_message", key=b"test_key")

            call_args = mock_redis.xadd.call_args
            data = call_args[0][1]
            assert base64.b64decode(data["key"]) == b"test_key"

    def test_publish_with_headers(self):
        """Test publishing message with headers."""
        mock_redis = MagicMock()
        with patch("redis.Redis", return_value=mock_redis):
            config = RedisStreamConfig()
            producer = RedisStreamProducer(config)

            headers = {"h1": "v1", "h2": "v2"}
            producer.publish("test_stream", b"test_message", headers=headers)

            call_args = mock_redis.xadd.call_args
            data = call_args[0][1]
            assert json.loads(data["headers_json"]) == headers

    def test_flush(self):
        """Test flush is no-op."""
        mock_redis = MagicMock()
        with patch("redis.Redis", return_value=mock_redis):
            config = RedisStreamConfig()
            producer = RedisStreamProducer(config)

            producer.flush(timeout=5.0)
            # flush should not call anything on client

    def test_close(self):
        """Test close operation."""
        mock_redis = MagicMock()
        with patch("redis.Redis", return_value=mock_redis):
            config = RedisStreamConfig()
            producer = RedisStreamProducer(config)
            producer.close()
            mock_redis.close.assert_called_once()


class TestRedisStreamConsumer:
    """Tests for RedisStreamConsumer."""

    def test_init_success(self):
        """Test successful consumer initialization."""
        with patch("redis.Redis"):
            config = RedisStreamConfig()
            consumer = RedisStreamConsumer(config)
            assert consumer._config == config

    def test_subscribe_creates_groups(self):
        """Test subscribe creates consumer groups."""
        mock_redis = MagicMock()
        with patch("redis.Redis", return_value=mock_redis):
            config = RedisStreamConfig(create_groups_if_missing=True)
            consumer = RedisStreamConsumer(config)

            consumer.subscribe(["stream1", "stream2"])

            assert mock_redis.xgroup_create.call_count == 2

    def test_subscribe_skips_existing_groups(self):
        """Test subscribe skips existing groups."""
        mock_redis = MagicMock()
        mock_redis.xgroup_create.side_effect = Exception(
            "BUSYGROUP Consumer Group name already exists"
        )

        with patch("redis.Redis", return_value=mock_redis):
            config = RedisStreamConfig(create_groups_if_missing=True)
            consumer = RedisStreamConsumer(config)

            # Should not raise
            consumer.subscribe(["stream1"])

    def test_poll_no_messages(self):
        """Test poll returns empty list when no messages."""
        mock_redis = MagicMock()
        mock_redis.xreadgroup.return_value = None

        with patch("redis.Redis", return_value=mock_redis):
            config = RedisStreamConfig()
            consumer = RedisStreamConsumer(config)
            consumer.subscribe(["test_stream"])

            messages = consumer.poll(timeout_ms=100)
            assert messages == []

    def test_poll_single_message(self):
        """Test poll recovers message correctly."""
        mock_redis = MagicMock()
        msg_data = {
            "value": base64.b64encode(b"test_value").decode(),
            "key": base64.b64encode(b"test_key").decode(),
            "headers_json": json.dumps({"h1": "v1"}),
        }
        mock_redis.xreadgroup.return_value = [("test_stream", [("1000-0", msg_data)])]

        with patch("redis.Redis", return_value=mock_redis):
            config = RedisStreamConfig()
            consumer = RedisStreamConsumer(config)
            consumer.subscribe(["test_stream"])

            messages = consumer.poll(timeout_ms=100)
            assert len(messages) == 1
            assert messages[0].topic == "test_stream"
            assert messages[0].partition == 0
            assert messages[0].value == b"test_value"
            assert messages[0].key == b"test_key"
            assert messages[0].headers == {"h1": "v1"}

    def test_commit_acks_messages(self):
        """Test commit acknowledges pending messages."""
        mock_redis = MagicMock()
        msg_data = {
            "value": base64.b64encode(b"test").decode(),
            "key": "",
            "headers_json": "{}",
        }
        mock_redis.xreadgroup.return_value = [("test_stream", [("1000-0", msg_data)])]

        with patch("redis.Redis", return_value=mock_redis):
            config = RedisStreamConfig()
            consumer = RedisStreamConsumer(config)
            consumer.subscribe(["test_stream"])

            consumer.poll(timeout_ms=100)
            consumer.commit()

            mock_redis.xack.assert_called_once()
            call_args = mock_redis.xack.call_args
            assert call_args[0][0] == "test_stream"
            assert call_args[0][1] == "penguin-dal"
            assert "1000-0" in call_args[0]

    def test_close(self):
        """Test close operation."""
        mock_redis = MagicMock()
        with patch("redis.Redis", return_value=mock_redis):
            config = RedisStreamConfig()
            consumer = RedisStreamConsumer(config)
            consumer.close()
            mock_redis.close.assert_called_once()


class TestValkeyStreamProducer:
    """Tests for ValkeyStreamProducer."""

    def test_init_success(self):
        """Test successful producer initialization."""
        mock_valkey_instance = MagicMock()
        sys.modules["valkey"].Valkey = MagicMock(return_value=mock_valkey_instance)
        config = ValkeyStreamConfig()
        producer = ValkeyStreamProducer(config)
        assert producer._config == config

    def test_publish_basic(self):
        """Test publishing message to Valkey stream."""
        mock_valkey = MagicMock()
        sys.modules["valkey"].Valkey = MagicMock(return_value=mock_valkey)
        config = ValkeyStreamConfig()
        producer = ValkeyStreamProducer(config)

        producer.publish("test_stream", b"test_message")

        call_args = mock_valkey.xadd.call_args
        assert call_args[0][0] == "test_stream"
        data = call_args[0][1]
        assert base64.b64decode(data["value"]) == b"test_message"

    def test_publish_with_key(self):
        """Test publishing message with key."""
        mock_valkey = MagicMock()
        sys.modules["valkey"].Valkey = MagicMock(return_value=mock_valkey)
        config = ValkeyStreamConfig()
        producer = ValkeyStreamProducer(config)

        producer.publish("test_stream", b"test_message", key=b"test_key")

        call_args = mock_valkey.xadd.call_args
        data = call_args[0][1]
        assert base64.b64decode(data["key"]) == b"test_key"

    def test_close(self):
        """Test close operation."""
        mock_valkey = MagicMock()
        sys.modules["valkey"].Valkey = MagicMock(return_value=mock_valkey)
        config = ValkeyStreamConfig()
        producer = ValkeyStreamProducer(config)
        producer.close()
        mock_valkey.close.assert_called_once()


class TestValkeyStreamConsumer:
    """Tests for ValkeyStreamConsumer."""

    def test_init_success(self):
        """Test successful consumer initialization."""
        mock_valkey_instance = MagicMock()
        sys.modules["valkey"].Valkey = MagicMock(return_value=mock_valkey_instance)
        config = ValkeyStreamConfig()
        consumer = ValkeyStreamConsumer(config)
        assert consumer._config == config

    def test_subscribe_creates_groups(self):
        """Test subscribe creates consumer groups."""
        mock_valkey = MagicMock()
        sys.modules["valkey"].Valkey = MagicMock(return_value=mock_valkey)
        config = ValkeyStreamConfig(create_groups_if_missing=True)
        consumer = ValkeyStreamConsumer(config)

        consumer.subscribe(["stream1"])

        mock_valkey.xgroup_create.assert_called_once()

    def test_poll_message_recovery(self):
        """Test poll recovers message correctly from Valkey."""
        mock_valkey = MagicMock()
        msg_data = {
            "value": base64.b64encode(b"test_value").decode(),
            "key": base64.b64encode(b"test_key").decode(),
            "headers_json": json.dumps({"h1": "v1"}),
        }
        mock_valkey.xreadgroup.return_value = [("test_stream", [("1000-0", msg_data)])]

        sys.modules["valkey"].Valkey = MagicMock(return_value=mock_valkey)
        config = ValkeyStreamConfig()
        consumer = ValkeyStreamConsumer(config)
        consumer.subscribe(["test_stream"])

        messages = consumer.poll(timeout_ms=100)
        assert len(messages) == 1
        assert messages[0].value == b"test_value"
        assert messages[0].key == b"test_key"

    def test_close(self):
        """Test close operation."""
        mock_valkey = MagicMock()
        sys.modules["valkey"].Valkey = MagicMock(return_value=mock_valkey)
        config = ValkeyStreamConfig()
        consumer = ValkeyStreamConsumer(config)
        consumer.close()
        mock_valkey.close.assert_called_once()


class TestRoundTrip:
    """Round-trip tests for message encoding/decoding."""

    def test_redis_roundtrip(self):
        """Test Redis producer/consumer round-trip."""
        mock_redis = MagicMock()

        # Producer publishes
        sys.modules["redis"].Redis = MagicMock(return_value=mock_redis)
        producer = RedisStreamProducer(RedisStreamConfig())
        producer.publish("stream", b"hello", key=b"key123", headers={"x": "y"})

        # Capture what was sent
        xadd_call = mock_redis.xadd.call_args
        sent_data = xadd_call[0][1]

        # Consumer reads same data
        mock_redis.xreadgroup.return_value = [("stream", [("1000-0", sent_data)])]

        consumer = RedisStreamConsumer(RedisStreamConfig())
        consumer.subscribe(["stream"])
        messages = consumer.poll()

        assert len(messages) == 1
        assert messages[0].value == b"hello"
        assert messages[0].key == b"key123"
        assert messages[0].headers == {"x": "y"}

    def test_valkey_roundtrip(self):
        """Test Valkey producer/consumer round-trip."""
        mock_valkey = MagicMock()

        # Producer publishes
        sys.modules["valkey"].Valkey = MagicMock(return_value=mock_valkey)
        producer = ValkeyStreamProducer(ValkeyStreamConfig())
        producer.publish("stream", b"world", key=b"k456")

        # Capture what was sent
        xadd_call = mock_valkey.xadd.call_args
        sent_data = xadd_call[0][1]

        # Consumer reads same data
        mock_valkey.xreadgroup.return_value = [("stream", [("2000-0", sent_data)])]

        consumer = ValkeyStreamConsumer(ValkeyStreamConfig())
        consumer.subscribe(["stream"])
        messages = consumer.poll()

        assert len(messages) == 1
        assert messages[0].value == b"world"
        assert messages[0].key == b"k456"
