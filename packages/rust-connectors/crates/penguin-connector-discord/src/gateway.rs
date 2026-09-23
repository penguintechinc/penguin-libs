//! Discord Gateway v10 client: `HELLO`/`IDENTIFY`/heartbeat handshake,
//! `MESSAGE_CREATE` dispatch parsing.
//!
//! `receivers/discord_gateway.py` (the `waddles` repo) delegates the real
//! wire protocol entirely to py-cord, so there is no repo source to port
//! here — this module implements Discord's own public Gateway v10 protocol
//! directly (opcode table, `HELLO`/`IDENTIFY`/heartbeat sequence,
//! `MESSAGE_CREATE` dispatch shape are all part of Discord's published API,
//! not repo-internal behaviour). The fixtures in this module's tests are
//! therefore **synthetic**, shaped exactly like Discord's documented
//! payloads rather than captured from any repo source.
//!
//! Generic over the underlying `WebSocketStream<S>` so the handshake and
//! dispatch-parsing logic are fully testable without a real TLS/TCP
//! connection to `gateway.discord.gg` (see this module's tests, which run
//! the real WS handshake over an in-memory duplex pipe).

use std::time::Duration;

use futures_util::{SinkExt, StreamExt};
use serde::{Deserialize, Serialize};
use tokio::io::{AsyncRead, AsyncWrite};
use tokio_tungstenite::tungstenite::Message;
use tokio_tungstenite::{MaybeTlsStream, WebSocketStream};

use crate::error::DiscordError;

/// Dispatch — the gateway is telling us about an event (`t` names it).
pub const OP_DISPATCH: u8 = 0;
/// Heartbeat — sent by either side to keep the connection alive.
pub const OP_HEARTBEAT: u8 = 1;
/// Identify — the client's login, sent once right after `HELLO`.
pub const OP_IDENTIFY: u8 = 2;
/// Resume — reconnect to a prior session (not implemented by this crate yet).
pub const OP_RESUME: u8 = 6;
/// Reconnect — the gateway is asking the client to reconnect.
pub const OP_RECONNECT: u8 = 7;
/// Invalid Session — the client's session is no longer valid.
pub const OP_INVALID_SESSION: u8 = 9;
/// Hello — the gateway's first frame, carries `heartbeat_interval`.
pub const OP_HELLO: u8 = 10;
/// Heartbeat ACK — the gateway acknowledged our last heartbeat.
pub const OP_HEARTBEAT_ACK: u8 = 11;

/// Default Discord gateway URL (API v10, JSON encoding).
pub const DEFAULT_GATEWAY_URL: &str = "wss://gateway.discord.gg/?v=10&encoding=json";

/// Default Discord REST API base (v10).
pub const DEFAULT_API_BASE: &str = "https://discord.com/api/v10";

/// The `{op, d, s, t}` envelope every gateway frame uses.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct GatewayPayload {
    /// The opcode (see the `OP_*` constants).
    pub op: u8,
    /// The opcode-specific data.
    #[serde(default)]
    pub d: serde_json::Value,
    /// The sequence number, present only on `Dispatch` frames.
    #[serde(default)]
    pub s: Option<u64>,
    /// The event name, present only on `Dispatch` frames.
    #[serde(default)]
    pub t: Option<String>,
}

/// Parse one raw gateway text frame into a [`GatewayPayload`].
pub fn parse_payload(raw: &str) -> Result<GatewayPayload, DiscordError> {
    serde_json::from_str(raw).map_err(|e| DiscordError::Decode(e.to_string()))
}

/// Build the `IDENTIFY` payload sent once, immediately after `HELLO`.
#[must_use]
pub fn build_identify(token: &str, intents: u64) -> GatewayPayload {
    GatewayPayload {
        op: OP_IDENTIFY,
        d: serde_json::json!({
            "token": token,
            "intents": intents,
            "properties": {
                "os": "linux",
                "browser": "penguin-connector-discord",
                "device": "penguin-connector-discord",
            },
        }),
        s: None,
        t: None,
    }
}

/// Build a `HEARTBEAT` payload carrying the last-seen sequence number
/// (`null` before any `Dispatch` frame has arrived).
#[must_use]
pub fn build_heartbeat(seq: Option<u64>) -> GatewayPayload {
    GatewayPayload {
        op: OP_HEARTBEAT,
        d: seq.map_or(serde_json::Value::Null, serde_json::Value::from),
        s: None,
        t: None,
    }
}

/// Extract `heartbeat_interval` (milliseconds) from a `HELLO` payload's `d`.
pub fn parse_hello(payload: &GatewayPayload) -> Result<Duration, DiscordError> {
    let millis = payload
        .d
        .get("heartbeat_interval")
        .and_then(serde_json::Value::as_u64)
        .ok_or_else(|| DiscordError::Decode("HELLO payload missing heartbeat_interval".into()))?;
    Ok(Duration::from_millis(millis))
}

/// Extract the connecting bot's own user id from a `READY` dispatch's `d`.
#[must_use]
pub fn extract_ready_self_id(d: &serde_json::Value) -> Option<String> {
    d.get("user")?.get("id")?.as_str().map(str::to_string)
}

/// One normalized inbound chat message, the raw platform payload this
/// crate's receiver yields.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ChatMessage {
    /// The guild (server) id, `None` for a DM.
    pub guild_id: Option<String>,
    /// The channel id the message was posted to.
    pub channel_id: String,
    /// The message's own snowflake id.
    pub message_id: String,
    /// The author's user id.
    pub author_id: String,
    /// The author's username.
    pub author_username: String,
    /// The message text.
    pub content: String,
}

/// Normalize a `MESSAGE_CREATE` dispatch's `d` into a [`ChatMessage`].
///
/// Returns `None` when the message was authored by this bot's own identity
/// (`self_user_id`, by id — never by `author.bot`, so other bots' messages
/// still come through) or when a required field is missing/mistyped.
/// `self_user_id: None` (before `READY` has been seen) never filters,
/// matching `DiscordGatewayReceiver._is_self`'s own "unknown identity errs
/// toward NOT dropping" rule.
#[must_use]
pub fn normalize_message_create(
    d: &serde_json::Value,
    self_user_id: Option<&str>,
) -> Option<ChatMessage> {
    let author = d.get("author")?;
    let author_id = author.get("id")?.as_str()?.to_string();
    if let Some(self_id) = self_user_id {
        if author_id == self_id {
            return None;
        }
    }
    let author_username = author.get("username")?.as_str()?.to_string();
    let channel_id = d.get("channel_id")?.as_str()?.to_string();
    let message_id = d.get("id")?.as_str()?.to_string();
    let content = d.get("content")?.as_str()?.to_string();
    let guild_id = d
        .get("guild_id")
        .and_then(serde_json::Value::as_str)
        .map(str::to_string);

    Some(ChatMessage {
        guild_id,
        channel_id,
        message_id,
        author_id,
        author_username,
        content,
    })
}

/// Gateway connection configuration.
#[derive(Debug, Clone)]
pub struct GatewayConfig {
    /// The bot token, sent in `IDENTIFY`. Never logged.
    pub token: String,
    /// The gateway URL to connect to.
    pub gateway_url: String,
    /// The Gateway Intents bitfield (`message_content` + `guilds` at
    /// minimum, to match `DiscordGatewayReceiver`'s own intents).
    pub intents: u64,
}

impl GatewayConfig {
    /// Build a config with the default gateway URL and the intents
    /// `DiscordGatewayReceiver._build_bot` requests: `GUILDS` (1 << 0) +
    /// `GUILD_MESSAGES` (1 << 9) + `MESSAGE_CONTENT` (1 << 15).
    #[must_use]
    pub fn new(token: impl Into<String>) -> Self {
        const GUILDS: u64 = 1 << 0;
        const GUILD_MESSAGES: u64 = 1 << 9;
        const MESSAGE_CONTENT: u64 = 1 << 15;
        Self {
            token: token.into(),
            gateway_url: DEFAULT_GATEWAY_URL.to_string(),
            intents: GUILDS | GUILD_MESSAGES | MESSAGE_CONTENT,
        }
    }
}

/// One connected, identified Gateway session — generic over the underlying
/// stream so tests can drive it over an in-memory duplex pipe.
pub struct GatewaySession<S> {
    ws: WebSocketStream<S>,
    heartbeat_interval: Duration,
    seq: Option<u64>,
    self_user_id: Option<String>,
    /// `true` from the moment a heartbeat is sent until its `HEARTBEAT_ACK`
    /// (opcode 11) is observed. If still `true` when the *next* heartbeat
    /// comes due, the connection is zombied (no RST/FIN, just silence) and
    /// [`GatewaySession::next_chat_message`] errors out to force a
    /// reconnect rather than heartbeating forever.
    awaiting_ack: bool,
}

impl<S> std::fmt::Debug for GatewaySession<S> {
    /// Deliberately omits the underlying websocket stream (no `Debug`
    /// bound on `S` required) — the negotiated state is what's useful in a
    /// test failure message or a log line.
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.debug_struct("GatewaySession")
            .field("heartbeat_interval", &self.heartbeat_interval)
            .field("seq", &self.seq)
            .field("self_user_id", &self.self_user_id)
            .field("awaiting_ack", &self.awaiting_ack)
            .finish_non_exhaustive()
    }
}

impl<S> GatewaySession<S>
where
    S: AsyncRead + AsyncWrite + Unpin,
{
    /// Read the expected `HELLO` frame and send `IDENTIFY` in response.
    /// `ws` must already have completed the WebSocket upgrade handshake.
    pub async fn handshake(
        mut ws: WebSocketStream<S>,
        cfg: &GatewayConfig,
    ) -> Result<Self, DiscordError> {
        let frame = ws
            .next()
            .await
            .ok_or(DiscordError::ClosedDuringHandshake)?
            .map_err(|e| DiscordError::Transport(e.to_string()))?;
        let text = match frame {
            Message::Text(text) => text.to_string(),
            _ => return Err(DiscordError::UnexpectedOpcode(u8::MAX)),
        };
        let hello = parse_payload(&text)?;
        if hello.op != OP_HELLO {
            return Err(DiscordError::UnexpectedOpcode(hello.op));
        }
        let heartbeat_interval = parse_hello(&hello)?;

        let identify = build_identify(&cfg.token, cfg.intents);
        let identify_text =
            serde_json::to_string(&identify).map_err(|e| DiscordError::Decode(e.to_string()))?;
        ws.send(Message::text(identify_text))
            .await
            .map_err(|e| DiscordError::Transport(e.to_string()))?;

        Ok(Self {
            ws,
            heartbeat_interval,
            seq: None,
            self_user_id: None,
            awaiting_ack: false,
        })
    }

    /// Read gateway frames until the next `MESSAGE_CREATE` (yielded), the
    /// connection closes (`Ok(None)`), or a fatal protocol error occurs.
    /// Transparently answers server-requested heartbeats and sends its own
    /// on the negotiated interval; tracks `READY`'s self user id for the
    /// self-message filter.
    pub async fn next_chat_message(&mut self) -> Result<Option<ChatMessage>, DiscordError> {
        loop {
            let next = tokio::time::timeout(self.heartbeat_interval, self.ws.next()).await;
            let frame = match next {
                Ok(Some(Ok(frame))) => frame,
                Ok(Some(Err(e))) => return Err(DiscordError::Transport(e.to_string())),
                Ok(None) => return Ok(None),
                Err(_elapsed) => {
                    // The interval elapsed with no ack for the heartbeat we
                    // already sent — a zombied connection would otherwise
                    // heartbeat forever without ever reconnecting (no
                    // RST/FIN arrives to surface as a transport error).
                    if self.awaiting_ack {
                        return Err(DiscordError::HeartbeatAckTimeout);
                    }
                    self.send_heartbeat().await?;
                    continue;
                }
            };

            let text = match frame {
                Message::Text(text) => text.to_string(),
                Message::Close(_) => return Ok(None),
                _ => continue,
            };
            let payload = parse_payload(&text)?;
            if let Some(seq) = payload.s {
                self.seq = Some(seq);
            }
            match payload.op {
                OP_HEARTBEAT => self.send_heartbeat().await?,
                OP_HEARTBEAT_ACK => self.awaiting_ack = false,
                OP_RECONNECT => return Err(DiscordError::ResumeRequested),
                OP_INVALID_SESSION => return Err(DiscordError::SessionInvalidated),
                OP_DISPATCH => match payload.t.as_deref() {
                    Some("READY") => self.self_user_id = extract_ready_self_id(&payload.d),
                    Some("MESSAGE_CREATE") => {
                        if let Some(chat) =
                            normalize_message_create(&payload.d, self.self_user_id.as_deref())
                        {
                            return Ok(Some(chat));
                        }
                    }
                    _ => {}
                },
                _ => {}
            }
        }
    }

    /// Send a `HEARTBEAT` frame and mark this session as awaiting its ack —
    /// [`GatewaySession::next_chat_message`] forces a reconnect if the ack
    /// never arrives before the next heartbeat comes due.
    async fn send_heartbeat(&mut self) -> Result<(), DiscordError> {
        let heartbeat = build_heartbeat(self.seq);
        let text =
            serde_json::to_string(&heartbeat).map_err(|e| DiscordError::Decode(e.to_string()))?;
        self.ws
            .send(Message::text(text))
            .await
            .map_err(|e| DiscordError::Transport(e.to_string()))?;
        self.awaiting_ack = true;
        Ok(())
    }
}

/// Connect to the real Discord gateway over TLS and complete the
/// `HELLO`/`IDENTIFY` handshake.
pub async fn connect(
    cfg: &GatewayConfig,
) -> Result<GatewaySession<MaybeTlsStream<tokio::net::TcpStream>>, DiscordError> {
    let (ws, _response) = tokio_tungstenite::connect_async(cfg.gateway_url.as_str())
        .await
        .map_err(|e| DiscordError::Transport(e.to_string()))?;
    GatewaySession::handshake(ws, cfg).await
}

/// Receiver: one persistent Gateway connection, yielding raw
/// `MESSAGE_CREATE` payloads via [`GatewaySession::next_chat_message`].
pub struct DiscordGatewayReceiver {
    config: GatewayConfig,
}

impl DiscordGatewayReceiver {
    /// Build a receiver for the given bot config. Does not connect yet.
    #[must_use]
    pub fn new(config: GatewayConfig) -> Self {
        Self { config }
    }

    /// Connect and identify, returning a live [`GatewaySession`] to poll
    /// with [`GatewaySession::next_chat_message`].
    pub async fn connect(
        &self,
    ) -> Result<GatewaySession<MaybeTlsStream<tokio::net::TcpStream>>, DiscordError> {
        connect(&self.config).await
    }
}

#[cfg(test)]
#[allow(clippy::unwrap_used, clippy::expect_used)]
mod tests {
    use super::*;
    use tokio_tungstenite::tungstenite::protocol::Role;

    #[test]
    fn parse_payload_decodes_envelope() {
        let payload =
            parse_payload(r#"{"op":10,"d":{"heartbeat_interval":41250},"s":null,"t":null}"#)
                .expect("should decode");
        assert_eq!(payload.op, OP_HELLO);
        assert_eq!(payload.s, None);
    }

    #[test]
    fn parse_payload_rejects_garbage() {
        assert!(parse_payload("not json").is_err());
    }

    #[test]
    fn parse_hello_extracts_interval() {
        let payload =
            parse_payload(r#"{"op":10,"d":{"heartbeat_interval":45000}}"#).expect("decode");
        assert_eq!(
            parse_hello(&payload).expect("interval present"),
            Duration::from_millis(45000)
        );
    }

    #[test]
    fn parse_hello_missing_interval_errors() {
        let payload = parse_payload(r#"{"op":10,"d":{}}"#).expect("decode");
        assert!(parse_hello(&payload).is_err());
    }

    #[test]
    fn build_identify_shape() {
        let payload = build_identify("tok", 33280);
        assert_eq!(payload.op, OP_IDENTIFY);
        assert_eq!(payload.d["token"], "tok");
        assert_eq!(payload.d["intents"], 33280);
    }

    #[test]
    fn build_heartbeat_carries_sequence() {
        assert_eq!(build_heartbeat(Some(7)).d, serde_json::json!(7));
        assert_eq!(build_heartbeat(None).d, serde_json::Value::Null);
    }

    #[test]
    fn extract_ready_self_id_present() {
        let d = serde_json::json!({"user": {"id": "42", "username": "bot"}});
        assert_eq!(extract_ready_self_id(&d), Some("42".to_string()));
    }

    #[test]
    fn extract_ready_self_id_missing() {
        assert_eq!(extract_ready_self_id(&serde_json::json!({})), None);
    }

    fn message_create_fixture(author_id: &str) -> serde_json::Value {
        serde_json::json!({
            "id": "999",
            "channel_id": "111",
            "guild_id": "222",
            "author": {"id": author_id, "username": "alice", "bot": false},
            "content": "hello world",
        })
    }

    #[test]
    fn normalize_message_create_full_shape() {
        let d = message_create_fixture("555");
        let msg = normalize_message_create(&d, Some("999999")).expect("should normalize");
        assert_eq!(msg.channel_id, "111");
        assert_eq!(msg.guild_id, Some("222".to_string()));
        assert_eq!(msg.author_id, "555");
        assert_eq!(msg.author_username, "alice");
        assert_eq!(msg.content, "hello world");
    }

    #[test]
    fn normalize_message_create_filters_self_by_id() {
        let d = message_create_fixture("42");
        assert_eq!(normalize_message_create(&d, Some("42")), None);
    }

    #[test]
    fn normalize_message_create_never_filters_other_bots() {
        let mut d = message_create_fixture("77");
        d["author"]["bot"] = serde_json::json!(true);
        assert!(normalize_message_create(&d, Some("42")).is_some());
    }

    #[test]
    fn normalize_message_create_no_self_id_never_filters() {
        let d = message_create_fixture("42");
        assert!(normalize_message_create(&d, None).is_some());
    }

    #[test]
    fn normalize_message_create_missing_field_returns_none() {
        let mut d = message_create_fixture("42");
        d.as_object_mut().expect("object").remove("content");
        assert_eq!(normalize_message_create(&d, None), None);
    }

    #[test]
    fn normalize_message_create_dm_has_no_guild_id() {
        let mut d = message_create_fixture("42");
        d.as_object_mut().expect("object").remove("guild_id");
        let msg = normalize_message_create(&d, None).expect("should normalize");
        assert_eq!(msg.guild_id, None);
    }

    // --- handshake + dispatch loop over an in-memory duplex pipe -----------
    // Fixtures are synthetic, modeled on Discord's own published Gateway v10
    // payload shapes (see module doc) — no live capture exists in this repo.

    #[tokio::test]
    async fn handshake_and_receive_message_create() {
        let (client_io, server_io) = tokio::io::duplex(16384);

        let server_task = tokio::spawn(async move {
            let mut server_ws =
                tokio_tungstenite::WebSocketStream::from_raw_socket(server_io, Role::Server, None)
                    .await;
            server_ws
                .send(Message::text(
                    r#"{"op":10,"d":{"heartbeat_interval":60000}}"#,
                ))
                .await
                .expect("send hello");

            let identify_frame = server_ws
                .next()
                .await
                .expect("identify frame")
                .expect("ok frame");
            let identify_text = identify_frame.into_text().expect("text frame");
            let identify = parse_payload(&identify_text).expect("decode identify");
            assert_eq!(identify.op, OP_IDENTIFY);
            assert_eq!(identify.d["token"], "test-token");

            server_ws
                .send(Message::text(
                    r#"{"op":0,"s":1,"t":"READY","d":{"user":{"id":"1000","username":"bot"}}}"#,
                ))
                .await
                .expect("send ready");
            server_ws
                .send(Message::text(
                    r#"{"op":0,"s":2,"t":"MESSAGE_CREATE","d":{"id":"5","channel_id":"6",
                       "author":{"id":"7","username":"carol","bot":false},"content":"hi"}}"#,
                ))
                .await
                .expect("send message_create");
        });

        let client_ws =
            tokio_tungstenite::WebSocketStream::from_raw_socket(client_io, Role::Client, None)
                .await;
        let cfg = GatewayConfig::new("test-token");
        let mut session = GatewaySession::handshake(client_ws, &cfg)
            .await
            .expect("gateway handshake");

        let msg = session
            .next_chat_message()
            .await
            .expect("should not error")
            .expect("message present");
        assert_eq!(msg.channel_id, "6");
        assert_eq!(msg.author_username, "carol");
        assert_eq!(msg.content, "hi");

        server_task.await.expect("server task should not panic");
    }

    #[tokio::test]
    async fn handshake_rejects_non_hello_first_frame() {
        let (client_io, server_io) = tokio::io::duplex(16384);
        let server_task = tokio::spawn(async move {
            let mut server_ws =
                tokio_tungstenite::WebSocketStream::from_raw_socket(server_io, Role::Server, None)
                    .await;
            server_ws
                .send(Message::text(r#"{"op":11,"d":null}"#))
                .await
                .expect("send ack");
        });

        let client_ws =
            tokio_tungstenite::WebSocketStream::from_raw_socket(client_io, Role::Client, None)
                .await;
        let cfg = GatewayConfig::new("test-token");
        let err = GatewaySession::handshake(client_ws, &cfg)
            .await
            .expect_err("should reject");
        assert!(matches!(
            err,
            DiscordError::UnexpectedOpcode(OP_HEARTBEAT_ACK)
        ));
        server_task.await.expect("server task should not panic");
    }

    /// Handshake once against a scripted fake server, returning the ready
    /// `GatewaySession` plus the server-side handle for the test to keep
    /// driving. Shared by the `next_chat_message` branch tests below.
    async fn handshake_over_duplex(
        heartbeat_interval_ms: u64,
    ) -> (
        GatewaySession<tokio::io::DuplexStream>,
        tokio_tungstenite::WebSocketStream<tokio::io::DuplexStream>,
    ) {
        let (client_io, server_io) = tokio::io::duplex(16384);
        let mut server_ws =
            tokio_tungstenite::WebSocketStream::from_raw_socket(server_io, Role::Server, None)
                .await;
        let client_ws =
            tokio_tungstenite::WebSocketStream::from_raw_socket(client_io, Role::Client, None)
                .await;

        let hello = format!(r#"{{"op":10,"d":{{"heartbeat_interval":{heartbeat_interval_ms}}}}}"#);
        let send_hello = server_ws.send(Message::text(hello));
        let cfg = GatewayConfig::new("test-token");
        let handshake = GatewaySession::handshake(client_ws, &cfg);
        let (send_result, handshake_result) = tokio::join!(send_hello, handshake);
        send_result.expect("send hello");
        let session = handshake_result.expect("gateway handshake");

        let identify_frame = server_ws
            .next()
            .await
            .expect("identify frame")
            .expect("ok frame");
        let identify =
            parse_payload(&identify_frame.into_text().expect("text frame")).expect("decode");
        assert_eq!(identify.op, OP_IDENTIFY);

        (session, server_ws)
    }

    #[tokio::test]
    async fn debug_impl_shows_negotiated_state() {
        let (session, _server_ws) = handshake_over_duplex(60_000).await;
        let debug_str = format!("{session:?}");
        assert!(debug_str.contains("heartbeat_interval"));
    }

    #[tokio::test]
    async fn next_chat_message_answers_server_requested_heartbeat() {
        let (mut session, mut server_ws) = handshake_over_duplex(60_000).await;

        server_ws
            .send(Message::text(r#"{"op":1,"d":null}"#))
            .await
            .expect("send heartbeat request");

        let recv_task = tokio::spawn(async move { session.next_chat_message().await });
        let heartbeat_frame = server_ws
            .next()
            .await
            .expect("heartbeat frame")
            .expect("ok frame");
        let heartbeat =
            parse_payload(&heartbeat_frame.into_text().expect("text frame")).expect("decode");
        assert_eq!(heartbeat.op, OP_HEARTBEAT);

        server_ws
            .send(Message::text(
                r#"{"op":0,"s":1,"t":"MESSAGE_CREATE","d":{"id":"1","channel_id":"2",
                   "author":{"id":"3","username":"bob","bot":false},"content":"hey"}}"#,
            ))
            .await
            .expect("send message_create");
        let msg = recv_task
            .await
            .expect("task should not panic")
            .expect("should not error")
            .expect("message present");
        assert_eq!(msg.author_username, "bob");
    }

    #[tokio::test]
    async fn next_chat_message_sends_heartbeat_on_interval_timeout() {
        let (mut session, mut server_ws) = handshake_over_duplex(20).await;

        let recv_task = tokio::spawn(async move { session.next_chat_message().await });
        // No frame is sent for longer than the 20ms heartbeat interval, so
        // the client must send its own heartbeat unprompted.
        let heartbeat_frame = server_ws
            .next()
            .await
            .expect("heartbeat frame")
            .expect("ok frame");
        let heartbeat =
            parse_payload(&heartbeat_frame.into_text().expect("text frame")).expect("decode");
        assert_eq!(heartbeat.op, OP_HEARTBEAT);

        server_ws
            .send(Message::text(
                r#"{"op":0,"s":1,"t":"MESSAGE_CREATE","d":{"id":"1","channel_id":"2",
                   "author":{"id":"3","username":"dee","bot":false},"content":"hey"}}"#,
            ))
            .await
            .expect("send message_create");
        let msg = recv_task
            .await
            .expect("task should not panic")
            .expect("should not error")
            .expect("message present");
        assert_eq!(msg.author_username, "dee");
    }

    #[tokio::test]
    async fn next_chat_message_reconnects_when_heartbeat_ack_missing() {
        let (mut session, mut server_ws) = handshake_over_duplex(30).await;

        let recv_task = tokio::spawn(async move { session.next_chat_message().await });

        // First heartbeat, sent because the interval elapsed with no frames
        // from the server at all -- exactly the "zombied, no RST/FIN"
        // shape this fix targets.
        let first_heartbeat = server_ws
            .next()
            .await
            .expect("heartbeat frame")
            .expect("ok frame");
        let heartbeat =
            parse_payload(&first_heartbeat.into_text().expect("text frame")).expect("decode");
        assert_eq!(heartbeat.op, OP_HEARTBEAT);

        // Never ack it. The next heartbeat interval elapses with the prior
        // heartbeat still unacked, so the session must error out to force
        // a reconnect rather than heartbeat forever.
        let err = recv_task
            .await
            .expect("task should not panic")
            .expect_err("missing ack should force a reconnect");
        assert!(matches!(err, DiscordError::HeartbeatAckTimeout));
    }

    #[tokio::test]
    async fn next_chat_message_survives_when_heartbeat_ack_arrives_in_time() {
        let (mut session, mut server_ws) = handshake_over_duplex(30).await;

        let recv_task = tokio::spawn(async move { session.next_chat_message().await });

        let first_heartbeat = server_ws
            .next()
            .await
            .expect("heartbeat frame")
            .expect("ok frame");
        let heartbeat =
            parse_payload(&first_heartbeat.into_text().expect("text frame")).expect("decode");
        assert_eq!(heartbeat.op, OP_HEARTBEAT);

        // Ack it before the next heartbeat interval elapses, then deliver a
        // message -- the session must NOT treat this as a zombied
        // connection.
        server_ws
            .send(Message::text(r#"{"op":11,"d":null}"#))
            .await
            .expect("send ack");
        server_ws
            .send(Message::text(
                r#"{"op":0,"s":1,"t":"MESSAGE_CREATE","d":{"id":"1","channel_id":"2",
                   "author":{"id":"3","username":"eve","bot":false},"content":"hey"}}"#,
            ))
            .await
            .expect("send message_create");

        let msg = recv_task
            .await
            .expect("task should not panic")
            .expect("should not error")
            .expect("message present");
        assert_eq!(msg.author_username, "eve");
    }

    #[tokio::test]
    async fn next_chat_message_reconnect_opcode_is_resumable() {
        let (mut session, mut server_ws) = handshake_over_duplex(60_000).await;
        server_ws
            .send(Message::text(r#"{"op":7,"d":null}"#))
            .await
            .expect("send reconnect");
        let err = session
            .next_chat_message()
            .await
            .expect_err("reconnect opcode should error");
        assert!(matches!(err, DiscordError::ResumeRequested));
    }

    #[tokio::test]
    async fn next_chat_message_invalid_session_opcode_is_not_resumable() {
        let (mut session, mut server_ws) = handshake_over_duplex(60_000).await;
        server_ws
            .send(Message::text(r#"{"op":9,"d":false}"#))
            .await
            .expect("send invalid session");
        let err = session
            .next_chat_message()
            .await
            .expect_err("invalid session opcode should error");
        assert!(matches!(err, DiscordError::SessionInvalidated));
    }

    #[tokio::test]
    async fn next_chat_message_returns_none_on_close_frame() {
        let (mut session, mut server_ws) = handshake_over_duplex(60_000).await;
        server_ws.close(None).await.expect("send close frame");
        let result = session
            .next_chat_message()
            .await
            .expect("close should not error");
        assert!(result.is_none());
    }

    #[tokio::test]
    async fn next_chat_message_errors_on_abrupt_peer_drop() {
        // Dropping the peer without a WS close handshake is a *protocol*
        // error (`Connection reset without closing handshake`), not a clean
        // end of stream — tungstenite surfaces it as `Err`, exercising this
        // crate's `Ok(Some(Err(e))) => Err(Transport(..))` branch.
        let (mut session, server_ws) = handshake_over_duplex(60_000).await;
        drop(server_ws);
        let err = session
            .next_chat_message()
            .await
            .expect_err("abrupt close should error");
        assert!(matches!(err, DiscordError::Transport(_)));
    }

    #[tokio::test]
    async fn connect_rejects_an_invalid_gateway_url() {
        // No real network needed: an invalid URI fails request construction
        // before `connect_async` ever opens a socket.
        let mut cfg = GatewayConfig::new("test-token");
        cfg.gateway_url = "not a valid url".to_string();
        let err = connect(&cfg).await.expect_err("invalid URL should fail");
        assert!(matches!(err, DiscordError::Transport(_)));
    }

    #[tokio::test]
    async fn receiver_wrapper_surfaces_the_same_connect_error() {
        let mut cfg = GatewayConfig::new("test-token");
        cfg.gateway_url = "not a valid url".to_string();
        let receiver = DiscordGatewayReceiver::new(cfg);
        let err = receiver
            .connect()
            .await
            .expect_err("invalid URL should fail");
        assert!(matches!(err, DiscordError::Transport(_)));
    }
}
