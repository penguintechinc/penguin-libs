//! Cache abstraction matching `dal.CacheStore`.

use async_trait::async_trait;
use bytes::Bytes;
use std::time::Duration;

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

#[cfg(test)]
mod tests {
    use super::*;
    use std::collections::HashMap;
    use tokio::sync::Mutex;

    #[derive(Default)]
    struct Mem(Mutex<HashMap<String, Bytes>>);

    #[async_trait]
    impl CacheStore for Mem {
        async fn get(&self, key: &str) -> Result<Option<Bytes>, DalError> {
            Ok(self.0.lock().await.get(key).cloned())
        }
        async fn set(
            &self,
            key: &str,
            value: Bytes,
            _ttl: Option<Duration>,
        ) -> Result<(), DalError> {
            self.0.lock().await.insert(key.to_owned(), value);
            Ok(())
        }
        async fn delete(&self, key: &str) -> Result<(), DalError> {
            self.0.lock().await.remove(key);
            Ok(())
        }
        async fn exists(&self, key: &str) -> Result<bool, DalError> {
            Ok(self.0.lock().await.contains_key(key))
        }
    }

    #[tokio::test]
    async fn cache_contract_roundtrip() {
        let c = Mem::default();
        assert_eq!(c.get("k").await.expect("get"), None);
        c.set("k", Bytes::from_static(b"v"), Some(Duration::from_secs(1)))
            .await
            .expect("set");
        assert!(c.exists("k").await.expect("exists"));
        assert_eq!(
            c.get("k").await.expect("get"),
            Some(Bytes::from_static(b"v"))
        );
        c.delete("k").await.expect("delete");
        assert!(!c.exists("k").await.expect("exists"));
    }
}
