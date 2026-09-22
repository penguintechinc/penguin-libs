//! Error type for the Discord connector (Gateway client + REST sender).

/// Errors surfaced by the Gateway client and the REST message sender.
#[derive(Debug, thiserror::Error)]
pub enum DiscordError {
    /// Missing or invalid configuration (empty token, channel id, or text).
    #[error("discord connector config error: {0}")]
    Config(String),

    /// Transport-level failure reading/writing the gateway websocket.
    /// Retryable.
    #[error("discord gateway transport error: {0}")]
    Transport(String),

    /// The gateway connection closed before the `HELLO`/`IDENTIFY`
    /// handshake completed. Retryable.
    #[error("discord gateway closed during handshake")]
    ClosedDuringHandshake,

    /// The gateway sent something other than `HELLO` (opcode 10) as its
    /// first frame. Non-retryable — a protocol-level surprise.
    #[error("discord gateway sent unexpected opcode {0} during handshake")]
    UnexpectedOpcode(u8),

    /// A gateway frame could not be decoded as the expected JSON envelope.
    #[error("discord gateway payload decode error: {0}")]
    Decode(String),

    /// The gateway asked for `RECONNECT` or declared the session invalid
    /// (`INVALID_SESSION`) — the caller must reconnect. Retryable.
    #[error("discord gateway session invalidated, reconnect required")]
    SessionInvalidated,

    /// The REST send request itself failed at the transport layer.
    /// Retryable.
    #[error("discord REST request failed: {0}")]
    Http(String),

    /// `429 Too Many Requests`. Retryable — the caller owns the actual
    /// backoff, this crate never sleeps internally.
    #[error("discord REST rate limited, retry after {retry_after_seconds}s")]
    RateLimited {
        /// The `Retry-After` header value, verbatim (seconds, as a string).
        retry_after_seconds: String,
    },

    /// `401`/`403` — bad or revoked bot token. Non-retryable.
    #[error("discord REST rejected auth: HTTP {0}")]
    AuthRejected(u16),

    /// Any other `4xx`. Non-retryable.
    #[error("discord REST client error: HTTP {status} {body}")]
    ClientError {
        /// The HTTP status code.
        status: u16,
        /// The response body, truncated to 200 characters.
        body: String,
    },

    /// `5xx`. Retryable.
    #[error("discord REST server error: HTTP {0}")]
    ServerError(u16),
}

impl DiscordError {
    /// True when the caller should retry with backoff rather than give up.
    #[must_use]
    pub fn is_retryable(&self) -> bool {
        matches!(
            self,
            DiscordError::Transport(_)
                | DiscordError::ClosedDuringHandshake
                | DiscordError::SessionInvalidated
                | DiscordError::Http(_)
                | DiscordError::RateLimited { .. }
                | DiscordError::ServerError(_)
        )
    }
}
