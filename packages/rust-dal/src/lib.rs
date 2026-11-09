//! PenguinTech Data Access Layer (DAL) for Rust — unified database pools,
//! S3/MinIO object storage, cache, and event streams.
//!
//! Replaces and consolidates disparate database pool and object storage
//! setups across services, providing 1:1 parity with the Go `go-dal` package.
//!
//! ## Modules
//!
//! - [`db`]: Resilient PostgreSQL / SQLite connection pooling with exponential
//!   backoff retry and `DB_*` environment variable configuration.
//! - [`storage`]: S3 and MinIO object storage abstraction honoring path-style
//!   addressing, endpoint overrides, and standard `S3_*` conventions.
//! - [`cache`]: Abstract key-value cache contract matching `dal.CacheStore`.
//! - [`stream`]: Abstract streaming producer and consumer contracts matching
//!   `dal.StreamProducer` / `dal.StreamConsumer`.

pub mod cache;
pub mod error;
pub mod stream;

#[cfg(feature = "sql")]
pub mod db;

#[cfg(feature = "storage")]
pub mod storage;

pub use cache::CacheStore;
pub use error::DalError;
pub use stream::{StreamConsumer, StreamMessage, StreamProducer};

#[cfg(feature = "sql")]
pub use db::{
    connect_pg_pool, connect_pool, connect_sqlite_pool, DatabasePool, DbConfig, DbSslMode, DbType,
};

#[cfg(feature = "storage")]
pub use storage::{build_s3_client, S3Config, S3StorageStore, StorageStore};

/// Serializes tests that mutate process environment variables.
#[cfg(test)]
pub(crate) static ENV_LOCK: std::sync::Mutex<()> = std::sync::Mutex::new(());
