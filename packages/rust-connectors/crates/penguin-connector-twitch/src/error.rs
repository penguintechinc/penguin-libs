//! Error type for the Twitch connector (IRC transport + EventSub verification).
//!
//! Mirrors the retryable/non-retryable split `waddle_transports`
//! (`core/svc_ingest`'s Python predecessor) uses so a future caller in
//! `core/svc_ingest` can apply the same backoff-vs-give-up policy without
//! re-deriving it per error site.

/// Errors surfaced by IRC connect/register/send/receive and EventSub helpers.
#[derive(Debug, thiserror::Error)]
pub enum TwitchError {
    /// Missing or invalid configuration (empty host/nick/channel, etc.).
    #[error("twitch connector config error: {0}")]
    Config(String),

    /// Transport-level failure connecting or reading/writing the socket.
    /// Retryable — matches `RetryableTransportError` in the Python transport.
    #[error("twitch irc connection error: {0}")]
    Connection(String),

    /// The IRC server rejected registration (bad nick/password) or sent
    /// `ERROR`. Non-retryable — matches `NonRetryableTransportError`.
    #[error("twitch irc registration rejected: {0}")]
    RegistrationRejected(String),

    /// Registration did not complete (no numeric 001) before the deadline.
    /// Retryable.
    #[error("twitch irc registration timed out")]
    RegistrationTimeout,

    /// The connection closed before registration completed. Retryable.
    #[error("twitch irc connection closed before registration completed")]
    ClosedBeforeRegistration,
}

impl TwitchError {
    /// True when the caller should retry with backoff rather than give up.
    ///
    /// Mirrors the Python transport's `RetryableTransportError` vs
    /// `NonRetryableTransportError` split (`libs/waddle_transports/
    /// waddle_transports/transports/irc.py`): connection failures, closed
    /// sockets and timeouts are transient; a config error or an explicit
    /// registration rejection is not.
    #[must_use]
    pub fn is_retryable(&self) -> bool {
        matches!(
            self,
            TwitchError::Connection(_)
                | TwitchError::RegistrationTimeout
                | TwitchError::ClosedBeforeRegistration
        )
    }
}
