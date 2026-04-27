"""Kafka producer and consumer using confluent-kafka."""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class StreamMessage:
    """Represents a message from a stream."""

    topic: str
    partition: int
    offset: int
    key: bytes | None
    value: bytes
    headers: dict[str, str]
    timestamp: datetime


@dataclass(slots=True)
class KafkaConfig:
    """Kafka client configuration."""

    bootstrap_servers: list[str]
    group_id: str = "penguin-dal"
    auto_offset_reset: str = "earliest"
    enable_auto_commit: bool = False
    session_timeout_ms: int = 30000
    max_poll_records: int = 500
    security_protocol: str = "PLAINTEXT"
    sasl_mechanism: str | None = None
    sasl_username: str | None = None
    sasl_password: str | None = None
    ssl_ca_location: str | None = None


class KafkaProducer:
    """Synchronous Kafka producer using confluent-kafka."""

    def __init__(self, config: KafkaConfig) -> None:
        """Initialize Kafka producer.

        Args:
            config: KafkaConfig instance with bootstrap servers and auth settings.

        Raises:
            ImportError: If confluent-kafka is not installed.
        """
        try:
            from confluent_kafka import Producer
        except ImportError as e:
            raise ImportError(
                "confluent-kafka is required. Install with: pip install confluent-kafka>=2.3.0"
            ) from e

        self._config = config
        self._producer = None
        self._producer = Producer(self._build_config())

    def _build_config(self) -> dict[str, str]:
        """Build confluent-kafka producer configuration dict."""
        conf = {
            "bootstrap.servers": ",".join(self._config.bootstrap_servers),
        }

        if self._config.security_protocol != "PLAINTEXT":
            conf["security.protocol"] = self._config.security_protocol

        if self._config.sasl_mechanism:
            conf["sasl.mechanism"] = self._config.sasl_mechanism
            conf["sasl.username"] = self._config.sasl_username or ""
            conf["sasl.password"] = self._config.sasl_password or ""

        if self._config.ssl_ca_location:
            conf["ssl.ca.location"] = self._config.ssl_ca_location

        return conf

    def publish(
        self,
        topic: str,
        message: bytes,
        key: bytes | None = None,
        headers: dict[str, str] | None = None,
    ) -> None:
        """Publish message to Kafka topic.

        Args:
            topic: Topic name.
            message: Message bytes.
            key: Optional message key.
            headers: Optional dict of headers.

        Raises:
            RuntimeError: If publish fails.
        """
        if self._producer is None:
            raise RuntimeError("Producer not initialized")

        headers_list = None
        if headers:
            headers_list = [(k, v.encode()) for k, v in headers.items()]

        error = None

        def on_delivery(err, msg):
            nonlocal error
            if err:
                error = err

        self._producer.produce(
            topic=topic,
            value=message,
            key=key,
            headers=headers_list,
            on_delivery=on_delivery,
        )

        # Ensure message is sent before returning
        self._producer.flush(timeout=10.0)

        if error:
            raise RuntimeError(f"Failed to publish message to {topic}: {error}")

    def flush(self, timeout: float = 10.0) -> None:
        """Flush pending messages.

        Args:
            timeout: Timeout in seconds.
        """
        if self._producer is not None:
            self._producer.flush(timeout)

    def close(self) -> None:
        """Close the producer."""
        if self._producer is not None:
            self._producer.flush()
            self._producer = None


class KafkaConsumer:
    """Synchronous Kafka consumer using confluent-kafka."""

    def __init__(self, config: KafkaConfig) -> None:
        """Initialize Kafka consumer.

        Args:
            config: KafkaConfig instance with bootstrap servers and auth settings.

        Raises:
            ImportError: If confluent-kafka is not installed.
        """
        try:
            from confluent_kafka import Consumer
        except ImportError as e:
            raise ImportError(
                "confluent-kafka is required. Install with: pip install confluent-kafka>=2.3.0"
            ) from e

        self._config = config
        self._consumer = Consumer(self._build_config())

    def _build_config(self) -> dict[str, str]:
        """Build confluent-kafka consumer configuration dict."""
        conf = {
            "bootstrap.servers": ",".join(self._config.bootstrap_servers),
            "group.id": self._config.group_id,
            "auto.offset.reset": self._config.auto_offset_reset,
            "enable.auto.commit": str(self._config.enable_auto_commit).lower(),
            "session.timeout.ms": str(self._config.session_timeout_ms),
            "max.poll.records": str(self._config.max_poll_records),
        }

        if self._config.security_protocol != "PLAINTEXT":
            conf["security.protocol"] = self._config.security_protocol

        if self._config.sasl_mechanism:
            conf["sasl.mechanism"] = self._config.sasl_mechanism
            conf["sasl.username"] = self._config.sasl_username or ""
            conf["sasl.password"] = self._config.sasl_password or ""

        if self._config.ssl_ca_location:
            conf["ssl.ca.location"] = self._config.ssl_ca_location

        return conf

    def subscribe(self, topics: list[str]) -> None:
        """Subscribe to topics.

        Args:
            topics: List of topic names.
        """
        self._consumer.subscribe(topics)

    def poll(self, timeout_ms: int = 1000) -> list[StreamMessage]:
        """Poll for messages.

        Args:
            timeout_ms: Poll timeout in milliseconds.

        Returns:
            List of StreamMessage objects.
        """
        messages = []
        timeout_sec = timeout_ms / 1000.0
        max_attempts = (self._config.max_poll_records // 10) + 1

        for _ in range(max_attempts):
            msg = self._consumer.poll(timeout=timeout_sec)

            if msg is None:
                break

            # Check for errors (except ErrPartitionEOF)
            if msg.error():
                error_code = msg.error().code()
                # ErrPartitionEOF has code -191
                if error_code != -191:
                    raise RuntimeError(f"Consumer error: {msg.error()}")
                continue

            # Convert headers from list of tuples to dict
            headers_dict = {}
            if msg.headers():
                for key, value in msg.headers():
                    if isinstance(value, bytes):
                        headers_dict[key] = value.decode()
                    else:
                        headers_dict[key] = str(value)

            # Get timestamp
            ts_type, ts_millis = msg.timestamp()
            timestamp = datetime.fromtimestamp(ts_millis / 1000.0, tz=timezone.utc)

            stream_msg = StreamMessage(
                topic=msg.topic(),
                partition=msg.partition(),
                offset=msg.offset(),
                key=msg.key(),
                value=msg.value(),
                headers=headers_dict,
                timestamp=timestamp,
            )
            messages.append(stream_msg)

            if len(messages) >= self._config.max_poll_records:
                break

        return messages

    def commit(self) -> None:
        """Commit current offsets."""
        self._consumer.commit(asynchronous=False)

    def close(self) -> None:
        """Close the consumer."""
        if self._consumer is not None:
            self._consumer.close()
