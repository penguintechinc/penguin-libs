//! Cache abstraction matching `dal.CacheStore`.

use std::time::Duration;
use async_trait::async_trait;
use bytes::Bytes;

use crate::error::DalError;

/// Abstract key-value cache contract (Redis, Valkey, in-memory).
#[async_trait]
pub trait CacheStore: Send + Sync {
    /// Retrieves a cached value by key, returning `None` if key does not exist.
    async fn get(&self, key: &str) -> Result<Option<Bytes>, DalError>;

    /// Stores a cached value by key with optional TTL.
    async fn set(&self, key: &str, value: Bytes, ttl: Option<Duration>) -> Result<(), DalError>;

    /// Deletes a key from the cache.
    async fn delete(&self, key: &str) -> Result<(), DalError>;

    /// Checks if a key exists in the cache.
    async fn exists(&self, key: &str) -> Result<bool, DalError>;
}
