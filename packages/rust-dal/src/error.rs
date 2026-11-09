//! Error types for the PenguinTech Data Access Layer (DAL).

/// Errors raised across DAL operations (database, storage, cache, streams).
#[derive(Debug, thiserror::Error)]
pub enum DalError {
    /// Configuration loading or parsing failure.
    #[error("DAL configuration error: {0}")]
    Config(String),

    /// Relational database operation or connection failure.
    #[error("database error: {0}")]
    Database(String),

    /// Object storage operation failure.
    #[error("storage error: {0}")]
    Storage(String),

    /// Cache operation failure.
    #[error("cache error: {0}")]
    Cache(String),

    /// Streaming operation failure.
    #[error("stream error: {0}")]
    Stream(String),

    /// The requested entity or object was not found.
    #[error("not found: {0}")]
    NotFound(String),

    /// Retries were exhausted while establishing a connection.
    #[error("connection exhausted after {attempts} attempts: {message}")]
    Exhausted {
        /// Number of attempts executed.
        attempts: u32,
        /// Last underlying error message.
        message: String,
    },

    /// An unsupported backend or operation was requested.
    #[error("unsupported DAL operation or backend: {0}")]
    Unsupported(String),
}
