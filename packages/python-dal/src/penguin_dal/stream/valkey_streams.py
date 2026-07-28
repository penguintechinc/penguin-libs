"""Valkey Streams producer and consumer using valkey."""
from __future__ import annotations

import base64
import json
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
class ValkeyStreamConfig:
    """Valkey Streams client configuration."""

    host: str = "localhost"
    port: int = 6379
    db: int = 0
    password: str | None = None
    ssl: bool = False
    group_id: str = "penguin-dal"
    consumer_name: str = "consumer-1"
    block_ms: int = 1000
    batch_size: int = 100
    create_groups_if_missing: bool = True


class ValkeyStreamProducer:
    """Publishes to Valkey Streams via XADD."""

    def __init__(self, config: ValkeyStreamConfig) -> None:
        """Initialize Valkey Streams producer.

        Args:
            config: ValkeyStreamConfig instance.

        Raises:
            ImportError: If valkey is not installed.
        """
        try:
            import valkey
        except ImportError as e:
            raise ImportError(
                "valkey is required. Install with: pip install valkey>=0.1.0"
            ) from e

        self._config = config
        self._client = valkey.Valkey(
            host=config.host,
            port=config.port,
            db=config.db,
            password=config.password,
            ssl=config.ssl,
            decode_responses=False,
        )

    def publish(
        self,
        topic: str,
        message: bytes,
        key: bytes | None = None,
        headers: dict[str, str] | None = None,
    ) -> None:
        """Publish message to Valkey stream.

        Args:
            topic: Stream key name.
            message: Message bytes.
            key: Optional message key.
            headers: Optional dict of headers.
        """
        data = {
            "value": base64.b64encode(message).decode(),
        }

        if key:
            data["key"] = base64.b64encode(key).decode()
        else:
            data["key"] = ""

        if headers:
            data["headers_json"] = json.dumps(headers)
        else:
            data["headers_json"] = "{}"

        self._client.xadd(topic, data)

    def flush(self, timeout: float = 10.0) -> None:
        """Flush pending messages (no-op for Valkey).

        Args:
            timeout: Timeout in seconds (unused).
        """
        pass

    def close(self) -> None:
        """Close the Valkey connection."""
        self._client.close()


class ValkeyStreamConsumer:
    """Consumes from Valkey Streams via XREADGROUP."""

    def __init__(self, config: ValkeyStreamConfig) -> None:
        """Initialize Valkey Streams consumer.

        Args:
            config: ValkeyStreamConfig instance.

        Raises:
            ImportError: If valkey is not installed.
        """
        try:
            import valkey
        except ImportError as e:
            raise ImportError(
                "valkey is required. Install with: pip install valkey>=0.1.0"
            ) from e

        self._config = config
        self._client = valkey.Valkey(
            host=config.host,
            port=config.port,
            db=config.db,
            password=config.password,
            ssl=config.ssl,
            decode_responses=True,
        )
        self._topics: list[str] = []
        self._pending_ids: dict[str, list[str]] = {}

    def subscribe(self, topics: list[str]) -> None:
        """Subscribe to streams.

        Args:
            topics: List of stream key names.
        """
        self._topics = topics

        # Create consumer groups if they don't exist
        if self._config.create_groups_if_missing:
            for topic in topics:
                try:
                    self._client.xgroup_create(
                        topic, self._config.group_id, id="$", mkstream=True
                    )
                except Exception as e:
                    # Group might already exist
                    if "BUSYGROUP" not in str(e):
                        logger.warning(
                            f"Error creating consumer group for {topic}: {e}"
                        )

    def poll(self, timeout_ms: int = 1000) -> list[StreamMessage]:
        """Poll for messages from subscribed streams.

        Args:
            timeout_ms: Poll timeout in milliseconds.

        Returns:
            List of StreamMessage objects.
        """
        if not self._topics:
            return []

        messages = []

        # Build stream dict for XREADGROUP
        streams = {topic: ">" for topic in self._topics}

        try:
            results = self._client.xreadgroup(
                groupname=self._config.group_id,
                consumername=self._config.consumer_name,
                streams=streams,
                count=self._config.batch_size,
                block=timeout_ms,
            )

            if not results:
                return []

            for topic, entries in results:
                if topic not in self._pending_ids:
                    self._pending_ids[topic] = []

                for msg_id, data in entries:
                    # Store message ID for later commit
                    self._pending_ids[topic].append(msg_id)

                    # Decode message and key
                    value = base64.b64decode(data.get("value", ""))
                    key_b64 = data.get("key", "")
                    key = base64.b64decode(key_b64) if key_b64 else None

                    # Decode headers
                    headers_json = data.get("headers_json", "{}")
                    headers = json.loads(headers_json)

                    # Create timestamp from message ID (format: timestamp-sequence)
                    timestamp_str = msg_id.split("-")[0]
                    timestamp = datetime.fromtimestamp(
                        int(timestamp_str) / 1000.0, tz=timezone.utc
                    )

                    stream_msg = StreamMessage(
                        topic=topic,
                        partition=0,  # Valkey streams are single-partition per key
                        offset=msg_id,
                        key=key,
                        value=value,
                        headers=headers,
                        timestamp=timestamp,
                    )
                    messages.append(stream_msg)

        except Exception as e:
            logger.error(f"Error polling streams: {e}")
            raise RuntimeError(f"Failed to poll streams: {e}") from e

        return messages

    def commit(self) -> None:
        """Commit pending messages."""
        for topic, msg_ids in self._pending_ids.items():
            if msg_ids:
                try:
                    self._client.xack(topic, self._config.group_id, *msg_ids)
                except Exception as e:
                    logger.error(f"Error acknowledging messages for {topic}: {e}")

        # Clear pending IDs after commit
        self._pending_ids.clear()

    def close(self) -> None:
        """Close the Valkey connection."""
        self._client.close()
