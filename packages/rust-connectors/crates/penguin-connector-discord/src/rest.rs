//! Discord REST message sender: `POST /channels/{channel_id}/messages`.
//!
//! Ports `core/svc_action/bundles/discord_send_action.py::send_message`'s
//! (the `waddles` repo) status-code interpretation exactly: `429` is
//! retryable (caller owns the actual backoff — this crate never sleeps),
//! `401`/`403` is a non-retryable auth rejection, other `4xx` is
//! non-retryable, `5xx` is retryable. Does **not** apply the Python
//! bundle's SSRF guard (`waddle_transports.url_guard`) — that guard exists
//! because a *bundle* chooses the destination URL for its own egress; this
//! connector's channel/API-base configuration is operator-supplied
//! infrastructure, not bundle-controlled egress (design spec §10.6: "ingest's
//! own outbound connections are infrastructure, not bundle egress").

use crate::error::DiscordError;
use crate::gateway::DEFAULT_API_BASE;

/// Discord REST sender configuration.
#[derive(Debug, Clone)]
pub struct DiscordConfig {
    /// The bot token, sent as `Authorization: Bot <token>`. Never logged.
    pub bot_token: String,
    /// The Discord REST API base URL.
    pub api_base: String,
}

impl DiscordConfig {
    /// Build a config pointed at the real Discord API.
    #[must_use]
    pub fn new(bot_token: impl Into<String>) -> Self {
        Self {
            bot_token: bot_token.into(),
            api_base: DEFAULT_API_BASE.to_string(),
        }
    }
}

/// The outcome of a successful send.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct SendResult {
    /// The HTTP status Discord returned (always a `2xx` on this variant).
    pub http_status: u16,
    /// The created message's snowflake id, when Discord's response body
    /// parsed cleanly — best-effort, never fatal if absent.
    pub message_id: Option<String>,
}

/// Send one chat message to `channel_id`.
pub async fn send_message(
    client: &reqwest::Client,
    cfg: &DiscordConfig,
    channel_id: &str,
    text: &str,
) -> Result<SendResult, DiscordError> {
    if channel_id.is_empty() {
        return Err(DiscordError::Config("missing required channel_id".into()));
    }
    if text.is_empty() {
        return Err(DiscordError::Config("missing required text".into()));
    }

    let url = format!("{}/channels/{channel_id}/messages", cfg.api_base);
    let response = client
        .post(&url)
        .header("Authorization", format!("Bot {}", cfg.bot_token))
        .json(&serde_json::json!({"content": text}))
        .send()
        .await
        .map_err(|e| DiscordError::Http(e.to_string()))?;

    let status = response.status();
    if status.as_u16() == 429 {
        let retry_after = response
            .headers()
            .get("Retry-After")
            .and_then(|v| v.to_str().ok())
            .unwrap_or("1")
            .to_string();
        return Err(DiscordError::RateLimited {
            retry_after_seconds: retry_after,
        });
    }
    if status.as_u16() == 401 || status.as_u16() == 403 {
        return Err(DiscordError::AuthRejected(status.as_u16()));
    }
    if status.is_client_error() {
        let body = response.text().await.unwrap_or_default();
        return Err(DiscordError::ClientError {
            status: status.as_u16(),
            body: body.chars().take(200).collect(),
        });
    }
    if status.is_server_error() {
        return Err(DiscordError::ServerError(status.as_u16()));
    }

    let http_status = status.as_u16();
    let message_id = response
        .json::<serde_json::Value>()
        .await
        .ok()
        .and_then(|body| {
            body.get("id")
                .and_then(serde_json::Value::as_str)
                .map(str::to_string)
        });

    Ok(SendResult {
        http_status,
        message_id,
    })
}

/// Sender: a thin wrapper pairing a `reqwest::Client` with [`DiscordConfig`].
pub struct DiscordRestSender {
    client: reqwest::Client,
    config: DiscordConfig,
}

impl DiscordRestSender {
    /// Build a sender with a fresh `reqwest::Client` for the given config.
    #[must_use]
    pub fn new(config: DiscordConfig) -> Self {
        Self {
            client: reqwest::Client::new(),
            config,
        }
    }

    /// Send one chat message to `channel_id`.
    pub async fn send(&self, channel_id: &str, text: &str) -> Result<SendResult, DiscordError> {
        send_message(&self.client, &self.config, channel_id, text).await
    }
}

#[cfg(test)]
#[allow(clippy::unwrap_used, clippy::expect_used)]
mod tests {
    use super::*;
    use wiremock::matchers::{header, method, path};
    use wiremock::{Mock, MockServer, ResponseTemplate};

    fn cfg_for(server: &MockServer) -> DiscordConfig {
        DiscordConfig {
            bot_token: "tok".to_string(),
            api_base: server.uri(),
        }
    }

    #[tokio::test]
    async fn send_message_success_parses_id() {
        let server = MockServer::start().await;
        Mock::given(method("POST"))
            .and(path("/channels/6/messages"))
            .and(header("Authorization", "Bot tok"))
            .respond_with(ResponseTemplate::new(200).set_body_json(serde_json::json!({"id": "42"})))
            .mount(&server)
            .await;

        let client = reqwest::Client::new();
        let result = send_message(&client, &cfg_for(&server), "6", "hi")
            .await
            .expect("should succeed");
        assert_eq!(result.http_status, 200);
        assert_eq!(result.message_id, Some("42".to_string()));
    }

    #[tokio::test]
    async fn send_message_rate_limited_is_retryable() {
        let server = MockServer::start().await;
        Mock::given(method("POST"))
            .and(path("/channels/6/messages"))
            .respond_with(ResponseTemplate::new(429).insert_header("Retry-After", "3"))
            .mount(&server)
            .await;

        let client = reqwest::Client::new();
        let err = send_message(&client, &cfg_for(&server), "6", "hi")
            .await
            .expect_err("should fail");
        assert!(err.is_retryable());
        assert!(
            matches!(err, DiscordError::RateLimited { retry_after_seconds } if retry_after_seconds == "3")
        );
    }

    #[tokio::test]
    async fn send_message_auth_rejected_is_not_retryable() {
        let server = MockServer::start().await;
        Mock::given(method("POST"))
            .and(path("/channels/6/messages"))
            .respond_with(ResponseTemplate::new(401))
            .mount(&server)
            .await;

        let client = reqwest::Client::new();
        let err = send_message(&client, &cfg_for(&server), "6", "hi")
            .await
            .expect_err("should fail");
        assert!(!err.is_retryable());
        assert!(matches!(err, DiscordError::AuthRejected(401)));
    }

    #[tokio::test]
    async fn send_message_client_error_is_not_retryable() {
        let server = MockServer::start().await;
        Mock::given(method("POST"))
            .and(path("/channels/6/messages"))
            .respond_with(ResponseTemplate::new(400).set_body_string("bad request"))
            .mount(&server)
            .await;

        let client = reqwest::Client::new();
        let err = send_message(&client, &cfg_for(&server), "6", "hi")
            .await
            .expect_err("should fail");
        assert!(!err.is_retryable());
        assert!(matches!(err, DiscordError::ClientError { status: 400, .. }));
    }

    #[tokio::test]
    async fn send_message_server_error_is_retryable() {
        let server = MockServer::start().await;
        Mock::given(method("POST"))
            .and(path("/channels/6/messages"))
            .respond_with(ResponseTemplate::new(503))
            .mount(&server)
            .await;

        let client = reqwest::Client::new();
        let err = send_message(&client, &cfg_for(&server), "6", "hi")
            .await
            .expect_err("should fail");
        assert!(err.is_retryable());
        assert!(matches!(err, DiscordError::ServerError(503)));
    }

    #[tokio::test]
    async fn send_message_rejects_empty_channel_id() {
        let server = MockServer::start().await;
        let client = reqwest::Client::new();
        let err = send_message(&client, &cfg_for(&server), "", "hi")
            .await
            .expect_err("should fail");
        assert!(matches!(err, DiscordError::Config(_)));
    }

    #[tokio::test]
    async fn send_message_rejects_empty_text() {
        let server = MockServer::start().await;
        let client = reqwest::Client::new();
        let err = send_message(&client, &cfg_for(&server), "6", "")
            .await
            .expect_err("should fail");
        assert!(matches!(err, DiscordError::Config(_)));
    }

    #[tokio::test]
    async fn rest_sender_wrapper_delegates() {
        let server = MockServer::start().await;
        Mock::given(method("POST"))
            .and(path("/channels/6/messages"))
            .respond_with(ResponseTemplate::new(200).set_body_json(serde_json::json!({"id": "1"})))
            .mount(&server)
            .await;

        let sender = DiscordRestSender::new(cfg_for(&server));
        let result = sender.send("6", "hi").await.expect("should succeed");
        assert_eq!(result.message_id, Some("1".to_string()));
    }

    #[test]
    fn config_new_points_at_the_real_discord_api() {
        let cfg = DiscordConfig::new("tok");
        assert_eq!(cfg.bot_token, "tok");
        assert_eq!(cfg.api_base, crate::gateway::DEFAULT_API_BASE);
    }
}
