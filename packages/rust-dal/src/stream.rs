//! Event streaming producer and consumer abstractions matching `dal.StreamProducer` and `dal.StreamConsumer`.

use async_trait::async_trait;
use bytes::Bytes;

use crate::error::DalError;

/// Generic message envelope received from an event stream.
///
/// `Debug` is implemented manually and prints only the payload length, since payloads may
/// carry secrets or PII.
#[derive(Clone, PartialEq, Eq)]
pub struct StreamMessage {
    /// Stream topic or key name.
    pub topic: String,
    /// Backend message identifier (e.g. Valkey stream ID `1694700000000-0`).
    pub id: String,
    /// Message payload bytes.
    pub payload: Bytes,
}

impl std::fmt::Debug for StreamMessage {
    /// Formats the envelope without the payload bytes.
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.debug_struct("StreamMessage")
            .field("topic", &self.topic)
            .field("id", &self.id)
            .field("payload_len", &self.payload.len())
            .finish()
    }
}

/// Abstract stream producer for publishing messages onto event streams.
#[async_trait]
pub trait StreamProducer: Send + Sync {
    /// Publishes a payload onto `topic`, returning the unique message ID.
    async fn publish(&self, topic: &str, payload: Bytes) -> Result<String, DalError>;
}

/// Abstract stream consumer for consuming from event streams with consumer groups.
#[async_trait]
pub trait StreamConsumer: Send + Sync {
    /// Reads the next batch of messages for the configured topic and consumer group.
    async fn read_batch(&mut self, count: usize) -> Result<Vec<StreamMessage>, DalError>;

    /// Acknowledges successful processing of a message by ID.
    async fn ack(&mut self, message_id: &str) -> Result<(), DalError>;
}

#[cfg(test)]
mod tests {
    use super::*;

    struct Mem(Vec<StreamMessage>);

    #[async_trait]
    impl StreamProducer for Mem {
        async fn publish(&self, topic: &str, payload: Bytes) -> Result<String, DalError> {
            if topic.is_empty() {
                return Err(DalError::Stream("empty topic".into()));
            }
            Ok(format!("{topic}-{}", payload.len()))
        }
    }

    #[async_trait]
    impl StreamConsumer for Mem {
        async fn read_batch(&mut self, count: usize) -> Result<Vec<StreamMessage>, DalError> {
            let n = count.min(self.0.len());
            Ok(self.0.drain(..n).collect())
        }
        async fn ack(&mut self, message_id: &str) -> Result<(), DalError> {
            if message_id.is_empty() {
                return Err(DalError::NotFound("id".into()));
            }
            Ok(())
        }
    }

    fn msg(id: &str) -> StreamMessage {
        StreamMessage {
            topic: "t".into(),
            id: id.into(),
            payload: Bytes::from_static(b"s3cret"),
        }
    }

    #[test]
    fn debug_does_not_print_payload() {
        let shown = format!("{:?}", msg("1-0"));
        assert!(!shown.contains("s3cret"));
        assert!(shown.contains("payload_len: 6"));
    }

    #[tokio::test]
    async fn producer_and_consumer_contracts() {
        let mut m = Mem(vec![msg("1"), msg("2"), msg("3")]);
        assert_eq!(
            m.publish("a", Bytes::from_static(b"xy"))
                .await
                .ok()
                .as_deref(),
            Some("a-2")
        );
        assert!(m.publish("", Bytes::new()).await.is_err());
        let batch = m.read_batch(2).await.expect("batch");
        assert_eq!(batch.len(), 2);
        assert_eq!(batch[0], msg("1"));
        assert_eq!(m.read_batch(10).await.expect("rest").len(), 1);
        assert!(m.ack("1").await.is_ok());
        assert!(m.ack("").await.is_err());
    }
}
