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

    /// The gateway sent `RECONNECT` (opcode 7) — Discord is asking for a
    /// fresh connection but the *session* is still resumable (a real
    /// `RESUME` using the stored session id + last sequence number would
    /// avoid re-`IDENTIFY`ing). Retryable.
    ///
    /// TODO: this crate does not yet capture the `session_id` from `READY`
    /// or implement `OP_RESUME`, so today's caller can only reconnect via
    /// a fresh handshake — same recovery as [`Self::SessionInvalidated`],
    /// just distinguished here so a future resume implementation (and any
    /// jittered reconnect backoff, which belongs in the caller's reconnect
    /// loop — this crate has none) has a signal to key off of.
    #[error("discord gateway asked for reconnect (resumable)")]
    ResumeRequested,

    /// The gateway declared the session invalid (`INVALID_SESSION`,
    /// opcode 9) — no resume is possible, the caller must reconnect and
    /// re-`IDENTIFY` from scratch. Retryable.
    #[error("discord gateway session invalidated, reconnect required")]
    SessionInvalidated,

    /// No `HEARTBEAT_ACK` (opcode 11) arrived for the previous heartbeat
    /// before the next one came due — a zombied connection (no RST/FIN)
    /// that would otherwise heartbeat forever without ever reconnecting.
    /// The caller must drop this session and reconnect. Retryable.
    #[error("discord gateway heartbeat not acked before next heartbeat due")]
    HeartbeatAckTimeout,

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
                | DiscordError::ResumeRequested
                | DiscordError::SessionInvalidated
                | DiscordError::HeartbeatAckTimeout
                | DiscordError::Http(_)
                | DiscordError::RateLimited { .. }
                | DiscordError::ServerError(_)
        )
    }
}

#[cfg(test)]
mod tests {
    use super::DiscordError;

    #[test]
    fn resume_requested_and_session_invalidated_are_retryable() {
        assert!(DiscordError::ResumeRequested.is_retryable());
        assert!(DiscordError::SessionInvalidated.is_retryable());
    }

    #[test]
    fn heartbeat_ack_timeout_is_retryable() {
        assert!(DiscordError::HeartbeatAckTimeout.is_retryable());
    }
}
