//! Error type for license/flag operations. Gating reads (`check_feature`,
//! `flag_enabled`) are infallible by design — errors surface only from
//! explicit calls like `validate()` and `keepalive()`.

/// Errors from license server / PostHog interactions.
#[derive(Debug, thiserror::Error)]
pub enum LicenseError {
    /// Invalid configuration (bad URL, missing product).
    #[error("license config error: {0}")]
    Config(String),

    /// Transport-level failure reaching the server.
    #[error("license transport error: {0}")]
    Transport(String),

    /// The server answered with a non-success status.
    #[error("license server returned status {0}")]
    Status(u16),

    /// The response body could not be decoded.
    #[error("license response decode error: {0}")]
    Decode(String),
}

impl From<reqwest::Error> for LicenseError {
    fn from(e: reqwest::Error) -> Self {
        LicenseError::Transport(e.to_string())
    }
}
