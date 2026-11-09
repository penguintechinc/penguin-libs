//! Event streaming producer and consumer abstractions matching `dal.StreamProducer` and `dal.StreamConsumer`.

use async_trait::async_trait;
use bytes::Bytes;

use crate::error::DalError;

/// Generic message envelope received from an event stream.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct StreamMessage {
    /// Stream topic or key name.
    pub topic: String,
    /// Backend message identifier (e.g. Valkey stream ID `1694700000000-0`).
    pub id: String,
    /// Message payload bytes.
    pub payload: Bytes,
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
