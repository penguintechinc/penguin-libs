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

    /// An object exceeded the configured maximum size.
    #[error("object exceeds the configured limit of {limit} bytes")]
    TooLarge {
        /// Configured maximum, in bytes.
        limit: u64,
    },

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

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn display_messages_are_stable() {
        let cases = [
            (DalError::Config("x".into()), "DAL configuration error: x"),
            (DalError::Database("x".into()), "database error: x"),
            (DalError::Storage("x".into()), "storage error: x"),
            (DalError::Cache("x".into()), "cache error: x"),
            (DalError::Stream("x".into()), "stream error: x"),
            (DalError::NotFound("k".into()), "not found: k"),
            (
                DalError::Exhausted {
                    attempts: 3,
                    message: "m".into(),
                },
                "connection exhausted after 3 attempts: m",
            ),
            (
                DalError::Unsupported("u".into()),
                "unsupported DAL operation or backend: u",
            ),
            (
                DalError::TooLarge { limit: 7 },
                "object exceeds the configured limit of 7 bytes",
            ),
        ];
        for (err, want) in cases {
            assert_eq!(err.to_string(), want);
        }
    }
}
