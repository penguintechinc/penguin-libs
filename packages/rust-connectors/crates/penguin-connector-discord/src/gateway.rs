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
use tokio_tungstenite::tungstenite::protocol::CloseFrame;
use tokio_tungstenite::tungstenite::Message;
use tokio_tungstenite::{MaybeTlsStream, WebSocketStream};

use crate::error::DiscordError;

/// Dispatch — the gateway is telling us about an event (`t` names it).
pub const OP_DISPATCH: u8 = 0;
/// Heartbeat — sent by either side to keep the connection alive.
pub const OP_HEARTBEAT: u8 = 1;
/// Identify — the client's login, sent once right after `HELLO`.
pub const OP_IDENTIFY: u8 = 2;
/// Resume — reconnect to a prior session, replaying missed dispatches
/// instead of a fresh `IDENTIFY`. See [`build_resume`], [`resume`], and
/// [`GatewaySession::resume_handshake`].
pub const OP_RESUME: u8 = 6;
/// Reconnect — the gateway is asking the client to reconnect.
pub const OP_RECONNECT: u8 = 7;
/// Invalid Session — the client's session is no longer valid.
pub const OP_INVALID_SESSION: u8 = 9;
/// Hello — the gateway's first frame, carries `heartbeat_interval`.
pub const OP_HELLO: u8 = 10;
/// Heartbeat ACK — the gateway acknowledged our last heartbeat.
pub const OP_HEARTBEAT_ACK: u8 = 11;

/// How a Discord Gateway WebSocket close code should be handled, per
/// Discord's documented "Gateway Close Event Codes" table
/// (<https://discord.com/developers/docs/topics/opcodes-and-status-codes#gateway-close-event-codes>).
///
/// Collapsing every close to a single "connection ended" signal risks two
/// failure modes: reconnecting forever against a fatal close (e.g. a
/// revoked token, `4004`) causes a reconnect storm, and treating any close
/// as fully resumable when Discord says otherwise (`4007`/`4009`) causes a
/// `RESUME` attempt that will itself fail. This classification only labels
/// the close code; it is the caller's choice whether to actually attempt
/// [`resume`]/[`GatewaySession::resume_handshake`] on a `Resumable` close
/// or always fall back to a fresh `IDENTIFY`.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum CloseCodeClass {
    /// The session can be resumed with `RESUME` using the stored session
    /// id + last sequence number. Codes: `4000`-`4003`, `4005`, `4008`.
    Resumable,
    /// Reconnect is possible, but Discord has said the session itself
    /// cannot be resumed — a fresh `IDENTIFY` is required. Codes: `4007`
    /// (invalid seq), `4009` (session timed out), and any
    /// undocumented/standard WebSocket code (the safe default: attempting
    /// `RESUME` on a code Discord hasn't documented as resumable risks a
    /// second failed round trip before falling back to a fresh identify
    /// anyway).
    ReconnectFresh,
    /// Do not reconnect — the caller must stop retrying. Codes: `4004`
    /// (authentication failed), `4010` (invalid shard), `4011` (sharding
    /// required), `4012` (invalid API version), `4013` (invalid
    /// intent(s)), `4014` (disallowed intent(s)).
    Fatal,
}

impl CloseCodeClass {
    /// `true` for [`Self::Resumable`] and [`Self::ReconnectFresh`] —
    /// `false` only for [`Self::Fatal`], which must stop the caller's
    /// retry loop entirely.
    #[must_use]
    pub fn is_retryable(self) -> bool {
        !matches!(self, Self::Fatal)
    }
}

/// Classify a Discord Gateway WebSocket close code per Discord's
/// documented "Gateway Close Event Codes" table. Any code Discord hasn't
/// documented (including standard WebSocket codes like `1000`/`1001`)
/// classifies as [`CloseCodeClass::ReconnectFresh`], the safe default when
/// this crate has no specific resumability guidance for it.
#[must_use]
pub fn classify_close_code(code: u16) -> CloseCodeClass {
    match code {
        4004 | 4010 | 4011 | 4012 | 4013 | 4014 => CloseCodeClass::Fatal,
        4000..=4003 | 4005 | 4008 => CloseCodeClass::Resumable,
        _ => CloseCodeClass::ReconnectFresh,
    }
}

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

/// Build the `RESUME` payload sent once, immediately after `HELLO`, in
/// place of `IDENTIFY` when reconnecting with a still-valid session (never
/// logged — carries the bot token exactly like `IDENTIFY` does).
#[must_use]
pub fn build_resume(token: &str, session_id: &str, seq: Option<u64>) -> GatewayPayload {
    GatewayPayload {
        op: OP_RESUME,
        d: serde_json::json!({
            "token": token,
            "session_id": session_id,
            "seq": seq,
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
/// Returns `None` only when the message was authored by this bot's own
/// identity (`self_user_id`, by id — never by `author.bot`, so other bots'
/// messages still come through) or when `author`/`author.id`/`channel_id`
/// -- the fields this crate cannot function without (self-filtering and
/// reply routing) -- are missing/mistyped. `self_user_id: None` (before
/// `READY` has been seen) never filters, matching
/// `DiscordGatewayReceiver._is_self`'s own "unknown identity errs toward
/// NOT dropping" rule.
///
/// `author.username`/the message's own `id`/`content` are read leniently
/// (empty-string default, never a drop) to match
/// `discord_gateway.py::_build_raw_event`'s behavior, the Python
/// implementation this crate ports: py-cord's `discord.Message` object
/// always exposes `.content`/`.author.name`/`.id` as populated attributes
/// (defaulting internally, never raising) regardless of whether Discord's
/// raw payload happened to omit/null one of them for a given dispatch --
/// e.g. `content` legitimately arrives empty for messages sent in the
/// instant before Discord's per-connection Message Content Intent grant is
/// fully in effect. Silently discarding the *entire* message over a gap in
/// optional display/threading metadata was a regression introduced by this
/// port using `?` on every field indiscriminately: a real, non-self
/// `!ping` was dropped end to end (never reaching `svc-process`) whenever
/// any one of these three incidental fields didn't parse, even though
/// `author.id` and `channel_id` -- everything actually needed to identify
/// the sender and route a reply -- were present and correct.
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
    let author_username = author
        .get("username")
        .and_then(serde_json::Value::as_str)
        .unwrap_or_default()
        .to_string();
    let channel_id = d.get("channel_id")?.as_str()?.to_string();
    let message_id = d
        .get("id")
        .and_then(serde_json::Value::as_str)
        .unwrap_or_default()
        .to_string();
    let content = d
        .get("content")
        .and_then(serde_json::Value::as_str)
        .unwrap_or_default()
        .to_string();
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

/// A live session's `RESUME`-capable state — `READY`'s `session_id` and
/// `resume_gateway_url`, plus the last dispatch sequence number seen. See
/// [`GatewaySession::session_info`] (the getter callers persist for a
/// future reconnect) and [`resume`]/[`GatewaySession::resume_handshake`]
/// (the reconnect that consumes it).
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct GatewaySessionInfo {
    /// Discord's opaque session id from `READY`, sent back in `RESUME`.
    pub session_id: String,
    /// Last dispatch sequence number seen, sent back in `RESUME`.
    pub seq: Option<u64>,
    /// The per-session resume URL Discord's `READY` provides — `RESUME`
    /// must reconnect to this URL, not the original gateway URL.
    pub resume_gateway_url: String,
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
    /// Set from `READY`'s `session_id` on a fresh `IDENTIFY`, or carried
    /// straight through on a `RESUME` (the caller already knows it). `None`
    /// until either has happened.
    session_id: Option<String>,
    /// Set from `READY`'s `resume_gateway_url` on a fresh `IDENTIFY`, or
    /// carried straight through on a `RESUME` (it doesn't change across a
    /// successful resume). `None` until either has happened.
    resume_gateway_url: Option<String>,
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
            .field("session_id", &self.session_id)
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
        // Permanent DEBUG-level observability (critical-rules.md
        // Observability: log generously at DEBUG) -- the exact intents
        // value actually sent on the wire, read straight back out of the
        // payload we're about to serialize -- never the token.
        tracing::debug!(
            intents = identify
                .d
                .get("intents")
                .and_then(serde_json::Value::as_u64),
            heartbeat_interval_ms = heartbeat_interval.as_millis() as u64,
            "sending IDENTIFY"
        );
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
            session_id: None,
            resume_gateway_url: None,
        })
    }

    /// Read the expected `HELLO` frame and send `RESUME` (opcode 6) in
    /// response instead of a fresh `IDENTIFY` — reconnects to a prior
    /// session using `session`'s `session_id`/`seq`, exempt from Discord's
    /// `IDENTIFY` rate limit entirely. `ws` must already be connected to
    /// `session.resume_gateway_url` (see [`resume`], which does this for
    /// the real network case) and have completed the WebSocket upgrade.
    ///
    /// A successful resume does not raise `READY` again — Discord replays
    /// missed dispatches followed by a `RESUMED` dispatch instead — so
    /// `session_id`/`resume_gateway_url` are carried straight from `session`
    /// rather than re-parsed from a frame. If the session turns out not to
    /// be resumable after all, the gateway sends `INVALID_SESSION` (opcode
    /// 9) like any other dispatch frame, surfaced from
    /// [`GatewaySession::next_chat_message`] as
    /// [`DiscordError::SessionInvalidated`] exactly as it would be after a
    /// fresh `IDENTIFY`.
    pub async fn resume_handshake(
        mut ws: WebSocketStream<S>,
        token: &str,
        session: &GatewaySessionInfo,
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

        let resume = build_resume(token, &session.session_id, session.seq);
        // Permanent DEBUG-level observability (critical-rules.md
        // Observability: log generously at DEBUG) -- session id and
        // sequence sent on the wire, never the token.
        tracing::debug!(
            session_id = %session.session_id,
            seq = session.seq,
            heartbeat_interval_ms = heartbeat_interval.as_millis() as u64,
            "sending RESUME"
        );
        let resume_text =
            serde_json::to_string(&resume).map_err(|e| DiscordError::Decode(e.to_string()))?;
        ws.send(Message::text(resume_text))
            .await
            .map_err(|e| DiscordError::Transport(e.to_string()))?;

        Ok(Self {
            ws,
            heartbeat_interval,
            seq: session.seq,
            self_user_id: None,
            awaiting_ack: false,
            session_id: Some(session.session_id.clone()),
            resume_gateway_url: Some(session.resume_gateway_url.clone()),
        })
    }

    /// A snapshot of this session's `session_id`/`seq`/`resume_gateway_url`
    /// for a caller to persist and later hand back to [`resume`]/
    /// [`GatewaySession::resume_handshake`] — `None` until a `READY` (fresh
    /// `IDENTIFY`) or `resume_handshake` call has populated both the
    /// session id and resume URL.
    #[must_use]
    pub fn session_info(&self) -> Option<GatewaySessionInfo> {
        let session_id = self.session_id.clone()?;
        let resume_gateway_url = self.resume_gateway_url.clone()?;
        Some(GatewaySessionInfo {
            session_id,
            seq: self.seq,
            resume_gateway_url,
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
                // A close frame with no payload carries no code/reason to
                // classify (e.g. the peer never sent one) — preserve the
                // prior "clean end of stream" behavior rather than
                // fabricating a code.
                Message::Close(None) => return Ok(None),
                Message::Close(Some(frame)) => return Err(Self::close_frame_error(&frame)),
                _ => continue,
            };
            let payload = parse_payload(&text)?;
            if let Some(seq) = payload.s {
                self.seq = Some(seq);
            }
            // Permanent DEBUG-level observability -- every opcode/dispatch
            // received at the raw socket level, before any filtering, so
            // "did it arrive at all" vs. "was it dropped downstream" is
            // always distinguishable from the logs alone.
            tracing::debug!(
                op = payload.op,
                t = payload.t.as_deref(),
                seq = payload.s,
                "gateway frame received"
            );
            match payload.op {
                OP_HEARTBEAT => self.send_heartbeat().await?,
                OP_HEARTBEAT_ACK => self.awaiting_ack = false,
                OP_RECONNECT => return Err(DiscordError::ResumeRequested),
                OP_INVALID_SESSION => {
                    // Discord's own opcode-9 `d` payload: `true` permits an
                    // immediate `RESUME` attempt, `false` requires a fresh
                    // `IDENTIFY` -- never collapse this to a fixed value.
                    let resumable = payload.d.as_bool().unwrap_or(false);
                    tracing::warn!(resumable, "discord gateway sent INVALID_SESSION");
                    return Err(DiscordError::SessionInvalidated { resumable });
                }
                OP_DISPATCH => match payload.t.as_deref() {
                    Some("READY") => {
                        self.self_user_id = extract_ready_self_id(&payload.d);
                        self.session_id = payload
                            .d
                            .get("session_id")
                            .and_then(serde_json::Value::as_str)
                            .map(str::to_string);
                        self.resume_gateway_url = payload
                            .d
                            .get("resume_gateway_url")
                            .and_then(serde_json::Value::as_str)
                            .map(str::to_string);
                        let guilds = payload.d.get("guilds").and_then(|g| g.as_array());
                        let guild_count = guilds.map(Vec::len);
                        let unavailable_count = guilds.map(|a| {
                            a.iter()
                                .filter(|g| {
                                    g.get("unavailable").and_then(serde_json::Value::as_bool)
                                        == Some(true)
                                })
                                .count()
                        });
                        tracing::debug!(
                            self_user_id = self.self_user_id.as_deref(),
                            session_id = self.session_id.as_deref(),
                            guild_count,
                            unavailable_count,
                            guild_ids = ?guilds.map(|a| a.iter().filter_map(|g| g.get("id").and_then(serde_json::Value::as_str)).collect::<Vec<_>>()),
                            "READY received"
                        );
                    }
                    Some("RESUMED") => {
                        tracing::debug!(
                            session_id = self.session_id.as_deref(),
                            seq = self.seq,
                            "RESUMED received, session resumed successfully"
                        );
                    }
                    Some("GUILD_CREATE") => {
                        tracing::debug!(
                            guild_id = payload.d.get("id").and_then(serde_json::Value::as_str),
                            unavailable = payload
                                .d
                                .get("unavailable")
                                .and_then(serde_json::Value::as_bool),
                            "GUILD_CREATE received"
                        );
                    }
                    Some("MESSAGE_CREATE") => {
                        tracing::debug!(
                            guild_id = payload
                                .d
                                .get("guild_id")
                                .and_then(serde_json::Value::as_str),
                            channel_id = payload
                                .d
                                .get("channel_id")
                                .and_then(serde_json::Value::as_str),
                            author_id = payload
                                .d
                                .get("author")
                                .and_then(|a| a.get("id"))
                                .and_then(serde_json::Value::as_str),
                            self_user_id = self.self_user_id.as_deref(),
                            "MESSAGE_CREATE dispatch received (pre-filter)"
                        );
                        if let Some(chat) =
                            normalize_message_create(&payload.d, self.self_user_id.as_deref())
                        {
                            tracing::debug!(
                                author_id = %chat.author_id,
                                content_len = chat.content.len(),
                                "MESSAGE_CREATE normalize decision: pass"
                            );
                            return Ok(Some(chat));
                        }
                        // `normalize_message_create` only ever returns `None` for one of
                        // two reasons -- distinguish them here rather than leaving the
                        // drop unexplained (see that function's own doc comment for why
                        // every other field is read leniently and can never cause this).
                        let author_id = payload
                            .d
                            .get("author")
                            .and_then(|a| a.get("id"))
                            .and_then(serde_json::Value::as_str);
                        let reason = match (author_id, self.self_user_id.as_deref()) {
                            (Some(id), Some(self_id)) if id == self_id => "self-authored",
                            _ => "missing author/author.id/channel_id",
                        };
                        tracing::debug!(
                            author_id,
                            reason,
                            "MESSAGE_CREATE normalize decision: drop"
                        );
                    }
                    _ => {}
                },
                _ => {}
            }
        }
    }

    /// Turn a server-sent WebSocket close frame into a classified
    /// [`DiscordError::GatewayClosed`], logging at the severity the
    /// classification warrants. Fatal codes (bad token, invalid/disallowed
    /// intents, sharding misconfiguration) log at ERROR — the caller must
    /// stop retrying, so this is the last chance to surface the code
    /// somewhere actionable. Never logs the token; the close reason is
    /// server-supplied text, not caller-provided secrets.
    fn close_frame_error(frame: &CloseFrame) -> DiscordError {
        let code = u16::from(frame.code);
        let reason = frame.reason.to_string();
        let class = classify_close_code(code);
        match class {
            CloseCodeClass::Fatal => {
                tracing::error!(code, reason = %reason, ?class, "discord gateway closed fatally");
            }
            CloseCodeClass::Resumable | CloseCodeClass::ReconnectFresh => {
                tracing::warn!(code, reason = %reason, ?class, "discord gateway closed");
            }
        }
        DiscordError::GatewayClosed {
            code: Some(code),
            reason,
            class,
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

/// Discord's per-session resume URLs arrive bare (no `v`/`encoding` query
/// string) — appends the same `v=10&encoding=json` pair
/// [`DEFAULT_GATEWAY_URL`] hardcodes, unless the URL already carries a
/// query string (defensive: never double-append).
fn ensure_gateway_query_params(url: &str) -> String {
    if url.contains('?') {
        url.to_string()
    } else {
        format!("{}/?v=10&encoding=json", url.trim_end_matches('/'))
    }
}

/// Connect to `session.resume_gateway_url` over TLS and complete the
/// `HELLO`/`RESUME` handshake — reconnects a prior session (exempt from
/// Discord's `IDENTIFY` rate limit) instead of a fresh `IDENTIFY`.
pub async fn resume(
    cfg: &GatewayConfig,
    session: &GatewaySessionInfo,
) -> Result<GatewaySession<MaybeTlsStream<tokio::net::TcpStream>>, DiscordError> {
    let url = ensure_gateway_query_params(&session.resume_gateway_url);
    let (ws, _response) = tokio_tungstenite::connect_async(url.as_str())
        .await
        .map_err(|e| DiscordError::Transport(e.to_string()))?;
    GatewaySession::resume_handshake(ws, &cfg.token, session).await
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

    /// Resume a prior session (see [`GatewaySession::session_info`]) instead
    /// of a fresh `IDENTIFY`, returning a live [`GatewaySession`] to poll
    /// with [`GatewaySession::next_chat_message`]. Uses this receiver's
    /// configured bot token; `session` supplies the `session_id`/`seq`/
    /// `resume_gateway_url` to reconnect to.
    pub async fn resume(
        &self,
        session: &GatewaySessionInfo,
    ) -> Result<GatewaySession<MaybeTlsStream<tokio::net::TcpStream>>, DiscordError> {
        resume(&self.config, session).await
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
    fn normalize_message_create_missing_required_field_returns_none() {
        // `channel_id` is one of the two fields this crate cannot function
        // without (reply routing) -- still a hard drop.
        let mut d = message_create_fixture("42");
        d.as_object_mut().expect("object").remove("channel_id");
        assert_eq!(normalize_message_create(&d, None), None);
    }

    /// Regression: the live incident (a real, non-self `!ping` never
    /// reaching `svc-process`) was `normalize_message_create` treating
    /// `content` as hard-required via `?`, exactly like `author.id`/
    /// `channel_id` -- when Discord's payload for that specific dispatch
    /// didn't carry it as a parseable string, the *entire* message was
    /// silently dropped instead of forwarding with the metadata it did
    /// have (matching `discord_gateway.py::_build_raw_event`'s lenient
    /// behavior, see this function's own doc comment). A real human
    /// author (`!= self_user_id`) must never be dropped over a missing
    /// `content`/`username`/message `id` -- only self-authorship, or the
    /// absence of `author`/`author.id`/`channel_id`, may drop it.
    #[test]
    fn normalize_message_create_missing_content_still_forwards_non_self_message() {
        let mut d = message_create_fixture("328950127786065921");
        d.as_object_mut().expect("object").remove("content");
        let msg = normalize_message_create(&d, Some("587491432940699653"))
            .expect("a non-self message must forward even with no content");
        assert_eq!(msg.author_id, "328950127786065921");
        assert_eq!(msg.content, "");
    }

    #[test]
    fn normalize_message_create_null_content_still_forwards_non_self_message() {
        let mut d = message_create_fixture("328950127786065921");
        d["content"] = serde_json::Value::Null;
        let msg = normalize_message_create(&d, Some("587491432940699653"))
            .expect("a non-self message must forward even with null content");
        assert_eq!(msg.content, "");
    }

    #[test]
    fn normalize_message_create_missing_username_still_forwards_non_self_message() {
        let mut d = message_create_fixture("328950127786065921");
        d["author"]
            .as_object_mut()
            .expect("object")
            .remove("username");
        let msg = normalize_message_create(&d, Some("587491432940699653"))
            .expect("a non-self message must forward even with no username");
        assert_eq!(msg.author_username, "");
    }

    #[test]
    fn normalize_message_create_missing_message_id_still_forwards_non_self_message() {
        let mut d = message_create_fixture("328950127786065921");
        d.as_object_mut().expect("object").remove("id");
        let msg = normalize_message_create(&d, Some("587491432940699653"))
            .expect("a non-self message must forward even with no message id");
        assert_eq!(msg.message_id, "");
    }

    /// The bot's own message must still be filtered even though
    /// `content`/`username`/message `id` are now read leniently -- the
    /// self-filter runs on `author_id` before any of those fields are
    /// touched, so lenient-metadata parsing can never resurrect a
    /// self-authored message.
    #[test]
    fn normalize_message_create_self_authored_still_filtered_with_lenient_metadata() {
        let mut d = message_create_fixture("587491432940699653");
        d.as_object_mut().expect("object").remove("content");
        assert_eq!(
            normalize_message_create(&d, Some("587491432940699653")),
            None
        );
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
    async fn next_chat_message_invalid_session_false_is_not_resumable() {
        let (mut session, mut server_ws) = handshake_over_duplex(60_000).await;
        server_ws
            .send(Message::text(r#"{"op":9,"d":false}"#))
            .await
            .expect("send invalid session");
        let err = session
            .next_chat_message()
            .await
            .expect_err("invalid session opcode should error");
        assert!(matches!(
            err,
            DiscordError::SessionInvalidated { resumable: false }
        ));
    }

    #[tokio::test]
    async fn next_chat_message_invalid_session_true_is_resumable() {
        let (mut session, mut server_ws) = handshake_over_duplex(60_000).await;
        server_ws
            .send(Message::text(r#"{"op":9,"d":true}"#))
            .await
            .expect("send invalid session");
        let err = session
            .next_chat_message()
            .await
            .expect_err("invalid session opcode should error");
        assert!(matches!(
            err,
            DiscordError::SessionInvalidated { resumable: true }
        ));
    }

    #[tokio::test]
    async fn next_chat_message_invalid_session_missing_d_defaults_to_not_resumable() {
        // Malformed/unexpected payload shape -- err on the side of a fresh
        // IDENTIFY rather than assuming resumability that wasn't declared.
        let (mut session, mut server_ws) = handshake_over_duplex(60_000).await;
        server_ws
            .send(Message::text(r#"{"op":9,"d":null}"#))
            .await
            .expect("send invalid session");
        let err = session
            .next_chat_message()
            .await
            .expect_err("invalid session opcode should error");
        assert!(matches!(
            err,
            DiscordError::SessionInvalidated { resumable: false }
        ));
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

    /// Send a close frame carrying `code` and assert `next_chat_message`
    /// surfaces a [`DiscordError::GatewayClosed`] with the expected
    /// classification and code — shared by the close-code-class tests.
    async fn assert_close_code_classifies(code: u16, expected: CloseCodeClass) {
        let (mut session, mut server_ws) = handshake_over_duplex(60_000).await;
        server_ws
            .close(Some(CloseFrame {
                code: code.into(),
                reason: "test close".into(),
            }))
            .await
            .expect("send close frame");
        let err = session
            .next_chat_message()
            .await
            .expect_err("coded close should error");
        match err {
            DiscordError::GatewayClosed {
                code: got_code,
                class,
                ..
            } => {
                assert_eq!(got_code, Some(code));
                assert_eq!(class, expected);
                assert_eq!(class.is_retryable(), expected.is_retryable());
            }
            other => panic!("expected GatewayClosed, got {other:?}"),
        }
    }

    #[tokio::test]
    async fn close_code_4000_unknown_error_is_resumable() {
        assert_close_code_classifies(4000, CloseCodeClass::Resumable).await;
    }

    #[tokio::test]
    async fn close_code_4008_rate_limited_is_resumable() {
        assert_close_code_classifies(4008, CloseCodeClass::Resumable).await;
    }

    #[tokio::test]
    async fn close_code_4007_invalid_seq_is_reconnect_fresh() {
        assert_close_code_classifies(4007, CloseCodeClass::ReconnectFresh).await;
    }

    #[tokio::test]
    async fn close_code_4009_session_timed_out_is_reconnect_fresh() {
        assert_close_code_classifies(4009, CloseCodeClass::ReconnectFresh).await;
    }

    #[tokio::test]
    async fn close_code_4004_auth_failed_is_fatal() {
        assert_close_code_classifies(4004, CloseCodeClass::Fatal).await;
    }

    #[tokio::test]
    async fn close_code_4010_invalid_shard_is_fatal() {
        assert_close_code_classifies(4010, CloseCodeClass::Fatal).await;
    }

    #[tokio::test]
    async fn close_code_4011_sharding_required_is_fatal() {
        assert_close_code_classifies(4011, CloseCodeClass::Fatal).await;
    }

    #[tokio::test]
    async fn close_code_4013_invalid_intents_is_fatal() {
        assert_close_code_classifies(4013, CloseCodeClass::Fatal).await;
    }

    #[tokio::test]
    async fn close_code_4014_disallowed_intents_is_fatal() {
        assert_close_code_classifies(4014, CloseCodeClass::Fatal).await;
    }

    #[tokio::test]
    async fn close_code_undocumented_defaults_to_reconnect_fresh() {
        assert_close_code_classifies(1000, CloseCodeClass::ReconnectFresh).await;
    }

    #[test]
    fn classify_close_code_covers_every_documented_code() {
        let cases = [
            (4000, CloseCodeClass::Resumable),
            (4001, CloseCodeClass::Resumable),
            (4002, CloseCodeClass::Resumable),
            (4003, CloseCodeClass::Resumable),
            (4004, CloseCodeClass::Fatal),
            (4005, CloseCodeClass::Resumable),
            (4007, CloseCodeClass::ReconnectFresh),
            (4008, CloseCodeClass::Resumable),
            (4009, CloseCodeClass::ReconnectFresh),
            (4010, CloseCodeClass::Fatal),
            (4011, CloseCodeClass::Fatal),
            (4012, CloseCodeClass::Fatal),
            (4013, CloseCodeClass::Fatal),
            (4014, CloseCodeClass::Fatal),
        ];
        for (code, expected) in cases {
            assert_eq!(classify_close_code(code), expected, "code {code}");
        }
    }

    #[test]
    fn discord_error_gateway_closed_is_retryable_matches_class() {
        let resumable = DiscordError::GatewayClosed {
            code: Some(4000),
            reason: String::new(),
            class: CloseCodeClass::Resumable,
        };
        let reconnect_fresh = DiscordError::GatewayClosed {
            code: Some(4009),
            reason: String::new(),
            class: CloseCodeClass::ReconnectFresh,
        };
        let fatal = DiscordError::GatewayClosed {
            code: Some(4004),
            reason: String::new(),
            class: CloseCodeClass::Fatal,
        };
        assert!(resumable.is_retryable());
        assert!(reconnect_fresh.is_retryable());
        assert!(!fatal.is_retryable());
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

    // --- OP_RESUME ----------------------------------------------------

    fn resumable_session() -> GatewaySessionInfo {
        GatewaySessionInfo {
            session_id: "sess-abc".to_string(),
            seq: Some(7),
            resume_gateway_url: "wss://resume.example".to_string(),
        }
    }

    #[tokio::test]
    async fn ready_populates_session_info() {
        let (mut session, mut server_ws) = handshake_over_duplex(60_000).await;
        assert_eq!(session.session_info(), None);

        server_ws
            .send(Message::text(
                r#"{"op":0,"s":3,"t":"READY","d":{"user":{"id":"1000","username":"bot"},
                   "session_id":"sess-xyz","resume_gateway_url":"wss://resume.example"}}"#,
            ))
            .await
            .expect("send ready");
        server_ws
            .send(Message::text(
                r#"{"op":0,"s":4,"t":"MESSAGE_CREATE","d":{"id":"1","channel_id":"2",
                   "author":{"id":"3","username":"al","bot":false},"content":"hi"}}"#,
            ))
            .await
            .expect("send message_create");

        session
            .next_chat_message()
            .await
            .expect("should not error")
            .expect("message present");

        assert_eq!(
            session.session_info(),
            Some(GatewaySessionInfo {
                session_id: "sess-xyz".to_string(),
                seq: Some(4),
                resume_gateway_url: "wss://resume.example".to_string(),
            })
        );
    }

    /// Resume handshake over an in-memory duplex pipe: `HELLO` then a
    /// `RESUME` (not `IDENTIFY`) carrying the stored token/session
    /// id/seq, then a replayed dispatch followed by `RESUMED`.
    #[tokio::test]
    async fn resume_handshake_sends_resume_and_receives_resumed() {
        let (client_io, server_io) = tokio::io::duplex(16384);
        let mut server_ws =
            tokio_tungstenite::WebSocketStream::from_raw_socket(server_io, Role::Server, None)
                .await;
        let client_ws =
            tokio_tungstenite::WebSocketStream::from_raw_socket(client_io, Role::Client, None)
                .await;

        let send_hello = server_ws.send(Message::text(
            r#"{"op":10,"d":{"heartbeat_interval":60000}}"#,
        ));
        let session = resumable_session();
        let handshake = GatewaySession::resume_handshake(client_ws, "test-token", &session);
        let (send_result, handshake_result) = tokio::join!(send_hello, handshake);
        send_result.expect("send hello");
        let mut session_conn = handshake_result.expect("resume handshake");

        let resume_frame = server_ws
            .next()
            .await
            .expect("resume frame")
            .expect("ok frame");
        let resume =
            parse_payload(&resume_frame.into_text().expect("text frame")).expect("decode resume");
        assert_eq!(resume.op, OP_RESUME);
        assert_eq!(resume.d["token"], "test-token");
        assert_eq!(resume.d["session_id"], "sess-abc");
        assert_eq!(resume.d["seq"], 7);

        // A successful resume replays missed dispatches and then RESUMED --
        // session_id/resume_gateway_url were already known pre-handshake.
        assert_eq!(
            session_conn.session_info(),
            Some(GatewaySessionInfo {
                session_id: "sess-abc".to_string(),
                seq: Some(7),
                resume_gateway_url: "wss://resume.example".to_string(),
            })
        );

        server_ws
            .send(Message::text(
                r#"{"op":0,"s":8,"t":"MESSAGE_CREATE","d":{"id":"1","channel_id":"2",
                   "author":{"id":"3","username":"zed","bot":false},"content":"replayed"}}"#,
            ))
            .await
            .expect("send replayed message_create");
        server_ws
            .send(Message::text(r#"{"op":0,"s":9,"t":"RESUMED","d":{}}"#))
            .await
            .expect("send resumed");

        let msg = session_conn
            .next_chat_message()
            .await
            .expect("should not error")
            .expect("message present");
        assert_eq!(msg.author_username, "zed");
        // The sequence tracks forward past the replayed dispatch even
        // though RESUMED itself hasn't been consumed yet.
        assert_eq!(session_conn.session_info().unwrap().seq, Some(8));
    }

    #[tokio::test]
    async fn resume_rejects_an_invalid_gateway_url() {
        let cfg = GatewayConfig::new("test-token");
        let mut session = resumable_session();
        session.resume_gateway_url = "not a valid url".to_string();
        let err = resume(&cfg, &session)
            .await
            .expect_err("invalid URL should fail");
        assert!(matches!(err, DiscordError::Transport(_)));
    }

    #[tokio::test]
    async fn receiver_resume_wrapper_surfaces_the_same_resume_error() {
        let cfg = GatewayConfig::new("test-token");
        let receiver = DiscordGatewayReceiver::new(cfg);
        let mut session = resumable_session();
        session.resume_gateway_url = "not a valid url".to_string();
        let err = receiver
            .resume(&session)
            .await
            .expect_err("invalid URL should fail");
        assert!(matches!(err, DiscordError::Transport(_)));
    }

    #[test]
    fn ensure_gateway_query_params_appends_when_missing() {
        assert_eq!(
            ensure_gateway_query_params("wss://resume.example"),
            "wss://resume.example/?v=10&encoding=json"
        );
    }

    #[test]
    fn ensure_gateway_query_params_leaves_existing_query_alone() {
        assert_eq!(
            ensure_gateway_query_params("wss://resume.example/?v=10&encoding=json"),
            "wss://resume.example/?v=10&encoding=json"
        );
    }
}
