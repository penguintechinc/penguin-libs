//! The crate-wide error type. Every fallible `penguin-spine` function
//! returns `Result<_, SpineError>`.

use crate::envelope::EnvelopeError;

/// Every fallible operation this crate exposes returns this error. Wraps
/// the two external failure sources (`redis`, `serde_json`) plus the
/// spine-specific conditions the spec calls out by name.
#[derive(Debug, thiserror::Error)]
pub enum SpineError {
    /// A Valkey command failed, or a connection could not be established.
    #[error("valkey command failed: {0}")]
    Redis(#[from] redis::RedisError),
    /// A stream entry's envelope JSON failed strict deserialization.
    #[error("envelope error: {0}")]
    Envelope(#[from] EnvelopeError),
    /// A [`crate::GroupReader`] was asked to read a stream outside its
    /// grant list (spec Sec5.2 — the stage is the enforcement point).
    #[error("stream {stream:?} is not in this reader's grant list")]
    StreamNotGranted {
        /// The ungranted stream that was requested.
        stream: String,
    },
    /// A blocking-read timeout was not strictly less than its owning
    /// connection's socket timeout (spec Sec5.7 rule 1) — construction is
    /// refused rather than allowed to race silently in production.
    #[error(
        "blocking timeout {block_name} = {block_ms}ms must be strictly less than \
         the connection's socket timeout (DRAIN_SOCKET_TIMEOUT_S = {socket_timeout_s}s)"
    )]
    BlockTimeoutInvalid {
        /// Which config value failed the check.
        block_name: &'static str,
        /// The offending value, in milliseconds.
        block_ms: u64,
        /// The connection's configured socket timeout, in seconds.
        socket_timeout_s: u64,
    },
    /// JSON encode/decode failure outside envelope parsing (DLQ records,
    /// the ACL matrix).
    #[error("json error: {0}")]
    Json(#[from] serde_json::Error),
    /// A configuration or environment-loading error.
    #[error("spine config error: {0}")]
    Config(String),
}

#[cfg(test)]
mod tests {
    #![allow(clippy::unwrap_used)]
    use super::*;

    #[test]
    fn stream_not_granted_message_names_the_stream() {
        let err = SpineError::StreamNotGranted {
            stream: "waddles:t:acme:c:main:src:discord:dg-x:events".to_string(),
        };
        assert!(
            err.to_string()
                .contains("waddles:t:acme:c:main:src:discord:dg-x:events")
        );
    }

    #[test]
    fn block_timeout_invalid_message_names_both_values() {
        let err = SpineError::BlockTimeoutInvalid {
            block_name: "SPINE_BLOCK_MS",
            block_ms: 70_000,
            socket_timeout_s: 65,
        };
        let msg = err.to_string();
        assert!(msg.contains("SPINE_BLOCK_MS"));
        assert!(msg.contains("70000"));
        assert!(msg.contains("65"));
    }

    #[test]
    fn envelope_error_converts_via_from() {
        let env_err = crate::EnvelopeError::from(
            serde_json::from_str::<crate::PlatformEvent>("{}").unwrap_err(),
        );
        let spine_err: SpineError = env_err.into();
        assert!(matches!(spine_err, SpineError::Envelope(_)));
    }
}
