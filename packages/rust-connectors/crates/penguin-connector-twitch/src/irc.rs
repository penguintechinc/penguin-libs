//! Twitch IRC chat transport: connect, register, receive `PRIVMSG` lines,
//! send one outbound message.
//!
//! Ports `libs/waddle_transports/waddle_transports/transports/irc.py`'s
//! `IrcTransport` (the `waddles` repo) wire protocol exactly: real
//! `PASS`/`NICK`/`USER`/`CAP REQ`/`JOIN`/`PRIVMSG`/`QUIT` lines over a
//! TCP+TLS socket, no third-party IRC library. The protocol layer
//! (`register`, `recv`, `parse_privmsg_line`, `sanitize_irc_component`) is
//! generic over any `AsyncRead + AsyncWrite` stream so it is fully testable
//! without a real socket (`tokio::io::duplex` in this crate's tests);
//! [`connect`] supplies the real TCP/TLS stream for production use.
//!
//! Per-network tag interpretation (Twitch's `user-id`/`badges`/`mod`
//! semantics) is deliberately **not** done here — this crate stays
//! Twitch-agnostic at the wire-protocol level, matching the Python
//! transport's own scope; a caller wanting Twitch-specific fields parses
//! [`ChatMessage::tags`] itself (see `receivers/twitch_irc.py`'s
//! `_parse_tags` for the reference behaviour to port at that layer).

use std::io;
use std::pin::Pin;
use std::sync::Arc;
use std::task::{Context, Poll};
use std::time::Duration;

use tokio::io::{
    AsyncBufRead, AsyncBufReadExt, AsyncRead, AsyncWrite, AsyncWriteExt, BufReader, ReadBuf,
    ReadHalf, WriteHalf,
};
use tokio::net::TcpStream;
use tokio_rustls::rustls::pki_types::ServerName;
use tokio_rustls::rustls::{ClientConfig, RootCertStore};
use tokio_rustls::TlsConnector;

use crate::error::TwitchError;

/// One IRC channel connection's configuration.
#[derive(Debug, Clone)]
pub struct IrcConfig {
    /// IRC server hostname (e.g. `irc.chat.twitch.tv`).
    pub host: String,
    /// IRC server port (Twitch: `6697` TLS, `6667` plaintext).
    pub port: u16,
    /// The bot's own nick, used for `NICK`/`USER` and self-message filtering
    /// by a caller layered on top of this crate.
    pub nick: String,
    /// OAuth/IRC password sent via `PASS`, if any.
    pub password: Option<String>,
    /// Channel to join, with or without a leading `#` (normalized on connect).
    pub channel: String,
    /// Whether to wrap the TCP socket in TLS. Twitch requires this on `6697`.
    pub use_tls: bool,
    /// IRCv3 `CAP REQ` capability strings requested at registration
    /// (e.g. `twitch.tv/tags`, `twitch.tv/commands`). Empty means no `CAP
    /// REQ` line is sent at all.
    pub cap_requests: Vec<String>,
    /// Deadline for connecting and completing registration.
    pub timeout: Duration,
}

impl IrcConfig {
    /// Build a config with Twitch's own defaults (port `6697`, TLS on, no
    /// capabilities requested, a 10s timeout) for the given host/nick/channel.
    #[must_use]
    pub fn new(
        host: impl Into<String>,
        nick: impl Into<String>,
        channel: impl Into<String>,
    ) -> Self {
        Self {
            host: host.into(),
            port: 6697,
            nick: nick.into(),
            password: None,
            channel: channel.into(),
            use_tls: true,
            cap_requests: Vec::new(),
            timeout: Duration::from_secs(10),
        }
    }
}

/// One normalized `PRIVMSG` line, the raw platform payload this crate's
/// receiver yields.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ChatMessage {
    /// The channel the message was sent to (e.g. `#somechannel`).
    pub channel: String,
    /// The sender's nick (the prefix before `!` in the IRC line).
    pub sender: String,
    /// The message text.
    pub text: String,
    /// The raw, unparsed IRCv3 `@tag1=val1;tag2=val2` segment, or `None`
    /// when the line carried no tags (capability not granted, or a
    /// non-Twitch server).
    pub tags: Option<String>,
}

/// Strip CR/LF and every other C0 control character (`\x00`-`\x1F`) before
/// an IRC wire write — an unsanitized message or channel name lets a
/// payload smuggle a second wire command (CRLF injection).
#[must_use]
pub fn sanitize_irc_component(value: &str) -> String {
    value
        .chars()
        .filter(|c| !matches!(*c, '\u{0}'..='\u{1f}'))
        .collect()
}

/// Parse one raw IRC line into a [`ChatMessage`] if — and only if — it is a
/// `PRIVMSG`. Any other line (`PING`, numeric replies, `JOIN` acks, …)
/// returns `None`; callers handle `PING`/`PONG` separately (see [`recv`]).
///
/// Format: `[@tags ]:nick!user@host PRIVMSG #channel :text`.
#[must_use]
pub fn parse_privmsg_line(line: &str) -> Option<ChatMessage> {
    let mut rest = line;
    let tags = if let Some(after_at) = rest.strip_prefix('@') {
        let (tag_part, remainder) = after_at.split_once(' ')?;
        rest = remainder;
        Some(tag_part.to_string())
    } else {
        None
    };

    let rest = rest.strip_prefix(':')?;
    let (prefix, remainder) = rest.split_once(' ')?;
    let remainder = remainder.strip_prefix("PRIVMSG ")?;
    let (channel, text) = remainder.split_once(" :")?;
    let sender = prefix.split('!').next().unwrap_or(prefix);

    Some(ChatMessage {
        channel: channel.to_string(),
        sender: sender.to_string(),
        text: text.to_string(),
        tags,
    })
}

async fn write_line<W: AsyncWrite + Unpin>(writer: &mut W, line: &str) -> Result<(), TwitchError> {
    writer
        .write_all(line.as_bytes())
        .await
        .map_err(|e| TwitchError::Connection(e.to_string()))?;
    writer
        .write_all(b"\r\n")
        .await
        .map_err(|e| TwitchError::Connection(e.to_string()))?;
    writer
        .flush()
        .await
        .map_err(|e| TwitchError::Connection(e.to_string()))
}

async fn wait_for_registration<R: AsyncBufRead + Unpin>(
    reader: &mut R,
    timeout: Duration,
) -> Result<(), TwitchError> {
    let read_loop = async {
        loop {
            let mut line = String::new();
            let n = reader
                .read_line(&mut line)
                .await
                .map_err(|e| TwitchError::Connection(e.to_string()))?;
            if n == 0 {
                return Err(TwitchError::ClosedBeforeRegistration);
            }
            let text = line.trim_end();
            if text.contains(" 001 ") {
                return Ok(());
            }
            if text.starts_with("ERROR") || text.contains(" 464 ") || text.contains(" 465 ") {
                return Err(TwitchError::RegistrationRejected(text.to_string()));
            }
        }
    };
    tokio::time::timeout(timeout, read_loop)
        .await
        .map_err(|_elapsed| TwitchError::RegistrationTimeout)?
}

/// One connected, registered, joined IRC session — generic over the
/// underlying stream so tests can drive it over an in-memory duplex pipe.
pub struct IrcConnection<S> {
    reader: BufReader<ReadHalf<S>>,
    writer: WriteHalf<S>,
    /// The joined channel name, normalized to always start with `#`.
    pub channel: String,
}

impl<S> std::fmt::Debug for IrcConnection<S> {
    /// Deliberately omits the reader/writer halves (no `Debug` bound on
    /// `S` required) — only the joined channel is useful in a test failure
    /// message or a log line.
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.debug_struct("IrcConnection")
            .field("channel", &self.channel)
            .finish_non_exhaustive()
    }
}

impl<S> IrcConnection<S>
where
    S: AsyncRead + AsyncWrite + Unpin,
{
    /// Register (`PASS`/`NICK`/`USER`/optional `CAP REQ`), wait for numeric
    /// `001`, then `JOIN` the configured channel — byte-identical sequence
    /// to `IrcTransport._connect_and_register`.
    pub async fn connect_and_register(mut stream: S, cfg: &IrcConfig) -> Result<Self, TwitchError> {
        if cfg.nick.is_empty() {
            return Err(TwitchError::Config(
                "irc config missing required 'nick'".into(),
            ));
        }
        if cfg.channel.is_empty() {
            return Err(TwitchError::Config(
                "irc config missing required 'channel'".into(),
            ));
        }

        if let Some(password) = &cfg.password {
            write_line(&mut stream, &format!("PASS {password}")).await?;
        }
        write_line(&mut stream, &format!("NICK {}", cfg.nick)).await?;
        write_line(&mut stream, &format!("USER {} 0 * :{}", cfg.nick, cfg.nick)).await?;
        if !cfg.cap_requests.is_empty() {
            write_line(
                &mut stream,
                &format!("CAP REQ :{}", cfg.cap_requests.join(" ")),
            )
            .await?;
        }

        let (read_half, mut write_half) = tokio::io::split(stream);
        let mut reader = BufReader::new(read_half);
        wait_for_registration(&mut reader, cfg.timeout).await?;

        let sanitized = sanitize_irc_component(&cfg.channel);
        let channel = if sanitized.starts_with('#') {
            sanitized
        } else {
            format!("#{sanitized}")
        };
        write_line(&mut write_half, &format!("JOIN {channel}")).await?;

        Ok(Self {
            reader,
            writer: write_half,
            channel,
        })
    }

    /// Read lines until the next `PRIVMSG` (yielded), the connection closes
    /// (`Ok(None)`), or an I/O error occurs. Transparently answers `PING`
    /// with `PONG` and ignores every other line, matching
    /// `IrcTransport.receive`'s loop exactly.
    pub async fn recv(&mut self) -> Result<Option<ChatMessage>, TwitchError> {
        loop {
            let mut line = String::new();
            let n = self
                .reader
                .read_line(&mut line)
                .await
                .map_err(|e| TwitchError::Connection(e.to_string()))?;
            if n == 0 {
                return Ok(None);
            }
            let text = line.trim_end();
            if let Some(rest) = text.strip_prefix("PING") {
                write_line(&mut self.writer, &format!("PONG{rest}")).await?;
                continue;
            }
            if let Some(msg) = parse_privmsg_line(text) {
                return Ok(Some(msg));
            }
        }
    }

    /// Send one `PRIVMSG` to the joined channel, then `QUIT` — Twitch chat
    /// sends are one-shot connections, matching `IrcTransport.send`'s own
    /// "connect, join, send, quit" contract (no persistent send socket is
    /// held between messages).
    pub async fn send_and_quit(&mut self, message: &str) -> Result<(), TwitchError> {
        let sanitized = sanitize_irc_component(message);
        if sanitized.is_empty() {
            return Err(TwitchError::Config(
                "irc target has no message to send (empty after sanitization)".into(),
            ));
        }
        write_line(
            &mut self.writer,
            &format!("PRIVMSG {} :{}", self.channel, sanitized),
        )
        .await?;
        write_line(&mut self.writer, "QUIT").await
    }
}

/// Either a plaintext or a TLS-wrapped TCP stream — the real network
/// transport [`connect`] hands to [`IrcConnection::connect_and_register`].
pub enum IrcStream {
    /// Plaintext TCP (Twitch's `6667`, or tests against a non-TLS server).
    Plain(TcpStream),
    /// TLS-wrapped TCP (Twitch's real `6697`).
    Tls(Box<tokio_rustls::client::TlsStream<TcpStream>>),
}

impl AsyncRead for IrcStream {
    fn poll_read(
        self: Pin<&mut Self>,
        cx: &mut Context<'_>,
        buf: &mut ReadBuf<'_>,
    ) -> Poll<io::Result<()>> {
        match self.get_mut() {
            IrcStream::Plain(s) => Pin::new(s).poll_read(cx, buf),
            IrcStream::Tls(s) => Pin::new(s.as_mut()).poll_read(cx, buf),
        }
    }
}

impl AsyncWrite for IrcStream {
    fn poll_write(
        self: Pin<&mut Self>,
        cx: &mut Context<'_>,
        buf: &[u8],
    ) -> Poll<io::Result<usize>> {
        match self.get_mut() {
            IrcStream::Plain(s) => Pin::new(s).poll_write(cx, buf),
            IrcStream::Tls(s) => Pin::new(s.as_mut()).poll_write(cx, buf),
        }
    }

    fn poll_flush(self: Pin<&mut Self>, cx: &mut Context<'_>) -> Poll<io::Result<()>> {
        match self.get_mut() {
            IrcStream::Plain(s) => Pin::new(s).poll_flush(cx),
            IrcStream::Tls(s) => Pin::new(s.as_mut()).poll_flush(cx),
        }
    }

    fn poll_shutdown(self: Pin<&mut Self>, cx: &mut Context<'_>) -> Poll<io::Result<()>> {
        match self.get_mut() {
            IrcStream::Plain(s) => Pin::new(s).poll_shutdown(cx),
            IrcStream::Tls(s) => Pin::new(s.as_mut()).poll_shutdown(cx),
        }
    }
}

fn build_tls_connector() -> TlsConnector {
    let mut root_store = RootCertStore::empty();
    root_store.extend(webpki_roots::TLS_SERVER_ROOTS.iter().cloned());
    let config = ClientConfig::builder()
        .with_root_certificates(root_store)
        .with_no_client_auth();
    TlsConnector::from(Arc::new(config))
}

/// Open a real TCP (optionally TLS-wrapped) connection to `cfg.host:cfg.port`
/// and register/join, returning a ready-to-use [`IrcConnection`].
pub async fn connect(cfg: &IrcConfig) -> Result<IrcConnection<IrcStream>, TwitchError> {
    if cfg.host.is_empty() {
        return Err(TwitchError::Config(
            "irc config missing required 'host'".into(),
        ));
    }
    let tcp = tokio::time::timeout(
        cfg.timeout,
        TcpStream::connect((cfg.host.as_str(), cfg.port)),
    )
    .await
    .map_err(|_elapsed| {
        TwitchError::Connection(format!("connect to {}:{} timed out", cfg.host, cfg.port))
    })?
    .map_err(|e| TwitchError::Connection(e.to_string()))?;

    let stream = if cfg.use_tls {
        let connector = build_tls_connector();
        let server_name = ServerName::try_from(cfg.host.clone()).map_err(|e| {
            TwitchError::Config(format!("invalid TLS server name '{}': {e}", cfg.host))
        })?;
        let tls_stream = connector
            .connect(server_name, tcp)
            .await
            .map_err(|e| TwitchError::Connection(e.to_string()))?;
        IrcStream::Tls(Box::new(tls_stream))
    } else {
        IrcStream::Plain(tcp)
    };

    IrcConnection::connect_and_register(stream, cfg).await
}

/// Send one outbound chat message: connect, register, `PRIVMSG`, `QUIT`,
/// close. Twitch chat sends never hold a persistent connection.
pub async fn send_message(cfg: &IrcConfig, message: &str) -> Result<(), TwitchError> {
    let mut connection = connect(cfg).await?;
    connection.send_and_quit(message).await
}

/// Receiver: one persistent IRC connection per channel, yielding raw
/// `PRIVMSG` payloads via [`IrcConnection::recv`].
pub struct TwitchIrcReceiver {
    config: IrcConfig,
}

impl TwitchIrcReceiver {
    /// Build a receiver for the given channel config. Does not connect yet.
    #[must_use]
    pub fn new(config: IrcConfig) -> Self {
        Self { config }
    }

    /// Connect and register, returning a live [`IrcConnection`] to poll with
    /// [`IrcConnection::recv`].
    pub async fn connect(&self) -> Result<IrcConnection<IrcStream>, TwitchError> {
        connect(&self.config).await
    }
}

/// Sender: opens a fresh IRC connection per outbound chat message, matching
/// Twitch chat's real semantics (no persistent send connection is held).
pub struct TwitchIrcSender {
    config: IrcConfig,
}

impl TwitchIrcSender {
    /// Build a sender for the given channel config.
    #[must_use]
    pub fn new(config: IrcConfig) -> Self {
        Self { config }
    }

    /// Send one chat message, ignoring `self.config.channel`'s case — the
    /// channel joined at registration is always the one `PRIVMSG` targets.
    pub async fn send(&self, message: &str) -> Result<(), TwitchError> {
        send_message(&self.config, message).await
    }
}

#[cfg(test)]
#[allow(clippy::unwrap_used, clippy::expect_used)]
mod tests {
    use super::*;
    use tokio::io::AsyncReadExt;

    #[test]
    fn sanitize_strips_control_chars_only() {
        assert_eq!(sanitize_irc_component("hello\r\nworld"), "helloworld");
        assert_eq!(
            sanitize_irc_component("no\tcontrol\x01here"),
            "nocontrolhere"
        );
        assert_eq!(sanitize_irc_component("unchanged"), "unchanged");
    }

    #[test]
    fn parse_privmsg_line_no_tags() {
        let line = ":ronni!ronni@ronni.tmi.twitch.tv PRIVMSG #dallas :Kappa Keepo Kappa";
        let msg = parse_privmsg_line(line).expect("should parse");
        assert_eq!(msg.channel, "#dallas");
        assert_eq!(msg.sender, "ronni");
        assert_eq!(msg.text, "Kappa Keepo Kappa");
        assert_eq!(msg.tags, None);
    }

    #[test]
    fn parse_privmsg_line_with_tags() {
        let line = "@badges=moderator/1,subscriber/12;display-name=Ronni;mod=1;room-id=1337;\
subscriber=1;user-id=1337 :ronni!ronni@ronni.tmi.twitch.tv PRIVMSG #dallas :Kappa";
        let msg = parse_privmsg_line(line).expect("should parse");
        assert_eq!(msg.channel, "#dallas");
        assert_eq!(msg.sender, "ronni");
        assert_eq!(msg.text, "Kappa");
        assert!(msg.tags.expect("tags present").contains("user-id=1337"));
    }

    #[test]
    fn parse_privmsg_line_text_containing_colon() {
        let line = ":a!a@a PRIVMSG #chan :hello :world";
        let msg = parse_privmsg_line(line).expect("should parse");
        assert_eq!(msg.text, "hello :world");
    }

    #[test]
    fn parse_privmsg_line_ignores_non_privmsg() {
        assert!(parse_privmsg_line(":tmi.twitch.tv 001 bot :Welcome").is_none());
        assert!(parse_privmsg_line("PING :tmi.twitch.tv").is_none());
        assert!(parse_privmsg_line("garbage").is_none());
    }

    // --- protocol-level tests over an in-memory duplex pipe -----------------
    // Fixtures below are modeled directly on Twitch's own documented IRC
    // wire format (synthetic — no live capture is available in this repo —
    // but shaped exactly like real Twitch IRC traffic: numeric 001 welcome,
    // PING/PONG keepalive, tagged PRIVMSG).

    async fn spawn_fake_server(
        mut server: tokio::io::DuplexStream,
        script: Vec<String>,
    ) -> tokio::task::JoinHandle<String> {
        tokio::spawn(async move {
            let mut received = String::new();
            let mut buf = [0u8; 4096];
            // Drain whatever the client already sent (PASS/NICK/USER/CAP),
            // then push the scripted server lines, then keep draining until
            // the client closes.
            let (mut read_half, mut write_half) = tokio::io::split(&mut server);
            for line in &script {
                write_half
                    .write_all(line.as_bytes())
                    .await
                    .expect("write script line");
            }
            loop {
                match read_half.read(&mut buf).await {
                    Ok(0) | Err(_) => break,
                    Ok(n) => received.push_str(&String::from_utf8_lossy(&buf[..n])),
                }
            }
            received
        })
    }

    #[tokio::test]
    async fn connect_and_register_then_recv_privmsg() {
        let (client, server) = tokio::io::duplex(8192);
        let script = vec![
            ":tmi.twitch.tv 001 bot :Welcome, GLHF!\r\n".to_string(),
            "PING :tmi.twitch.tv\r\n".to_string(),
            ":alice!alice@alice.tmi.twitch.tv PRIVMSG #dallas :hello there\r\n".to_string(),
        ];
        let server_task = spawn_fake_server(server, script).await;

        let cfg = IrcConfig::new("irc.chat.twitch.tv", "bot", "dallas");
        let mut conn = IrcConnection::connect_and_register(client, &cfg)
            .await
            .expect("registration should succeed");
        assert_eq!(conn.channel, "#dallas");

        let msg = conn
            .recv()
            .await
            .expect("recv should not error")
            .expect("message present");
        assert_eq!(msg.sender, "alice");
        assert_eq!(msg.text, "hello there");

        drop(conn);
        let received = server_task.await.expect("server task should not panic");
        assert!(received.contains("NICK bot"));
        assert!(received.contains("USER bot 0 * :bot"));
        assert!(received.contains("JOIN #dallas"));
        assert!(received.contains("PONG :tmi.twitch.tv"));
    }

    // The two tests below use a real TCP loopback rather than
    // `tokio::io::duplex`. Two things matter for a deterministic close:
    // (1) an in-memory duplex pipe's write/close ordering versus the
    // *other* end's cooperative-scheduling turn is an implementation
    // detail, where a real socket's kernel-buffered semantics (data then
    // FIN, strictly ordered) are not; (2) closing a TCP socket that still
    // has *unread inbound* bytes sitting in its receive buffer makes the
    // kernel send `RST` instead of a clean `FIN` — so the fake server
    // below always drains the client's `NICK`/`USER` bytes first.

    /// Reads from a `TcpStream` until a given needle has appeared, so a
    /// fake server test helper has no unread inbound data left when it
    /// later closes (see the tests' own comment above for why that
    /// matters). Bytes read *past* the needle in the same underlying
    /// `read()` call are retained for the next `until()` call rather than
    /// discarded — on a fast loopback connection a client's `NICK`/`USER`/
    /// `JOIN`/`PRIVMSG`/`QUIT` writes routinely all arrive coalesced in one
    /// read, so a stateless "read fresh each call" helper would silently
    /// drop everything past the first needle it finds.
    #[derive(Default)]
    struct ByteDrain {
        buf: Vec<u8>,
    }

    impl ByteDrain {
        async fn until(&mut self, socket: &mut TcpStream, needle: &[u8]) {
            loop {
                if let Some(pos) = self.buf.windows(needle.len()).position(|w| w == needle) {
                    self.buf.drain(..pos + needle.len());
                    return;
                }
                let mut chunk = [0u8; 256];
                let n = socket.read(&mut chunk).await.expect("read bytes");
                assert!(n > 0, "connection closed before seeing the expected bytes");
                self.buf.extend_from_slice(&chunk[..n]);
            }
        }
    }

    #[tokio::test]
    async fn recv_returns_none_on_clean_close() {
        let listener = tokio::net::TcpListener::bind("127.0.0.1:0")
            .await
            .expect("bind loopback");
        let addr = listener.local_addr().expect("local addr");
        let server_task = tokio::spawn(async move {
            let (mut socket, _peer) = listener.accept().await.expect("accept");
            let mut drain = ByteDrain::default();
            drain.until(&mut socket, b"USER").await;
            socket
                .write_all(b":tmi.twitch.tv 001 bot :Welcome\r\n")
                .await
                .expect("write registration line");
            // Registration succeeded, so `connect_and_register` also sends
            // `JOIN` — drain that too before closing, or the client's own
            // `JOIN` write races this socket's teardown (broken pipe).
            drain.until(&mut socket, b"JOIN").await;
            // `socket` drops here (clean FIN close) — no unread inbound
            // data remains, and the client is only reading from this point.
        });

        let stream = TcpStream::connect(addr).await.expect("connect loopback");
        let cfg = IrcConfig::new("irc.chat.twitch.tv", "bot", "dallas");
        let mut conn = IrcConnection::connect_and_register(stream, &cfg)
            .await
            .expect("registers");
        let result = conn
            .recv()
            .await
            .expect("recv should not error on clean close");
        assert!(result.is_none());
        server_task.await.expect("server task should not panic");
    }

    #[tokio::test]
    async fn registration_rejected_surfaces_error() {
        let (client, server) = tokio::io::duplex(8192);
        let script = vec![":tmi.twitch.tv 464 * :Login authentication failed\r\n".to_string()];
        let _server_task = spawn_fake_server(server, script).await;

        let cfg = IrcConfig::new("irc.chat.twitch.tv", "bot", "dallas");
        let err = IrcConnection::connect_and_register(client, &cfg)
            .await
            .expect_err("bad auth should reject");
        assert!(matches!(err, TwitchError::RegistrationRejected(_)));
        assert!(!err.is_retryable());
    }

    #[tokio::test]
    async fn registration_timeout_is_retryable() {
        let (client, _server) = tokio::io::duplex(8192);
        let mut cfg = IrcConfig::new("irc.chat.twitch.tv", "bot", "dallas");
        cfg.timeout = Duration::from_millis(50);
        let err = IrcConnection::connect_and_register(client, &cfg)
            .await
            .expect_err("no server response should time out");
        assert!(matches!(err, TwitchError::RegistrationTimeout));
        assert!(err.is_retryable());
    }

    #[tokio::test]
    async fn closed_before_registration_is_retryable() {
        let listener = tokio::net::TcpListener::bind("127.0.0.1:0")
            .await
            .expect("bind loopback");
        let addr = listener.local_addr().expect("local addr");
        let server_task = tokio::spawn(async move {
            let (mut socket, _peer) = listener.accept().await.expect("accept");
            ByteDrain::default().until(&mut socket, b"USER").await;
            // `socket` drops here without ever sending numeric 001 — but
            // only after draining, so this is a clean FIN, not an RST.
        });

        let stream = TcpStream::connect(addr).await.expect("connect loopback");
        let cfg = IrcConfig::new("irc.chat.twitch.tv", "bot", "dallas");
        let err = IrcConnection::connect_and_register(stream, &cfg)
            .await
            .expect_err("closed socket should fail registration");
        assert!(matches!(err, TwitchError::ClosedBeforeRegistration));
        assert!(err.is_retryable());
        server_task.await.expect("server task should not panic");
    }

    #[tokio::test]
    async fn send_and_quit_writes_privmsg_and_quit() {
        let (client, server) = tokio::io::duplex(8192);
        let script = vec![":tmi.twitch.tv 001 bot :Welcome\r\n".to_string()];
        let server_task = spawn_fake_server(server, script).await;

        let cfg = IrcConfig::new("irc.chat.twitch.tv", "bot", "dallas");
        let mut conn = IrcConnection::connect_and_register(client, &cfg)
            .await
            .expect("registers");
        conn.send_and_quit("gg\r\nwp")
            .await
            .expect("send should succeed");
        drop(conn);

        let received = server_task.await.expect("server task should not panic");
        assert!(received.contains("PRIVMSG #dallas :ggwp"));
        assert!(received.contains("QUIT"));
    }

    #[tokio::test]
    async fn send_and_quit_rejects_empty_message() {
        let (client, server) = tokio::io::duplex(8192);
        let script = vec![":tmi.twitch.tv 001 bot :Welcome\r\n".to_string()];
        let _server_task = spawn_fake_server(server, script).await;

        let cfg = IrcConfig::new("irc.chat.twitch.tv", "bot", "dallas");
        let mut conn = IrcConnection::connect_and_register(client, &cfg)
            .await
            .expect("registers");
        let err = conn
            .send_and_quit("\r\n")
            .await
            .expect_err("empty message should be rejected");
        assert!(matches!(err, TwitchError::Config(_)));
    }

    #[tokio::test]
    async fn missing_nick_is_a_config_error() {
        let (client, _server) = tokio::io::duplex(8192);
        let cfg = IrcConfig::new("irc.chat.twitch.tv", "", "dallas");
        let err = IrcConnection::connect_and_register(client, &cfg)
            .await
            .expect_err("empty nick should be rejected");
        assert!(matches!(err, TwitchError::Config(_)));
    }

    #[tokio::test]
    async fn connect_rejects_empty_host() {
        let cfg = IrcConfig::new("", "bot", "dallas");
        let err = connect(&cfg)
            .await
            .expect_err("empty host should be rejected");
        assert!(matches!(err, TwitchError::Config(_)));
    }

    #[tokio::test]
    async fn debug_impl_shows_channel() {
        let (client, server) = tokio::io::duplex(8192);
        let script = vec![":tmi.twitch.tv 001 bot :Welcome\r\n".to_string()];
        let _server_task = spawn_fake_server(server, script).await;
        let cfg = IrcConfig::new("irc.chat.twitch.tv", "bot", "dallas");
        let conn = IrcConnection::connect_and_register(client, &cfg)
            .await
            .expect("registers");
        let debug_str = format!("{conn:?}");
        assert!(debug_str.contains("#dallas"));
    }

    // --- real TCP loopback: exercises `connect()`, `IrcStream::Plain`'s
    // AsyncRead/AsyncWrite delegation, `send_message()`, and the
    // `TwitchIrcReceiver`/`TwitchIrcSender` wrappers end to end. TLS is off
    // (`use_tls = false`) since these tests target the plain-TCP code path;
    // the TLS handshake path itself is covered separately below.

    fn plain_tcp_config(addr: std::net::SocketAddr) -> IrcConfig {
        let mut cfg = IrcConfig::new("127.0.0.1", "bot", "dallas");
        cfg.port = addr.port();
        cfg.use_tls = false;
        cfg
    }

    #[tokio::test]
    async fn send_message_end_to_end_over_plain_tcp() {
        let listener = tokio::net::TcpListener::bind("127.0.0.1:0")
            .await
            .expect("bind loopback");
        let addr = listener.local_addr().expect("local addr");
        let server_task = tokio::spawn(async move {
            let (mut socket, _peer) = listener.accept().await.expect("accept");
            let mut drain = ByteDrain::default();
            drain.until(&mut socket, b"USER").await;
            socket
                .write_all(b":tmi.twitch.tv 001 bot :Welcome\r\n")
                .await
                .expect("write registration line");
            drain.until(&mut socket, b"JOIN").await;
            drain.until(&mut socket, b"QUIT").await;
        });

        let cfg = plain_tcp_config(addr);
        send_message(&cfg, "gg")
            .await
            .expect("send_message should succeed over plain TCP");
        server_task.await.expect("server task should not panic");
    }

    #[tokio::test]
    async fn receiver_and_sender_wrappers_work_over_plain_tcp() {
        let listener = tokio::net::TcpListener::bind("127.0.0.1:0")
            .await
            .expect("bind loopback");
        let addr = listener.local_addr().expect("local addr");
        let server_task = tokio::spawn(async move {
            let (mut socket, _peer) = listener.accept().await.expect("accept");
            let mut drain = ByteDrain::default();
            drain.until(&mut socket, b"USER").await;
            socket
                .write_all(b":tmi.twitch.tv 001 bot :Welcome\r\n")
                .await
                .expect("write registration line");
            drain.until(&mut socket, b"JOIN").await;
            socket
                .write_all(b":alice!alice@alice.tmi.twitch.tv PRIVMSG #dallas :hi\r\n")
                .await
                .expect("write privmsg");
        });

        let cfg = plain_tcp_config(addr);
        let receiver = TwitchIrcReceiver::new(cfg.clone());
        let mut conn = receiver
            .connect()
            .await
            .expect("receiver connect should succeed");
        let msg = conn
            .recv()
            .await
            .expect("recv should not error")
            .expect("message present");
        assert_eq!(msg.sender, "alice");
        server_task.await.expect("server task should not panic");

        let listener2 = tokio::net::TcpListener::bind("127.0.0.1:0")
            .await
            .expect("bind loopback");
        let addr2 = listener2.local_addr().expect("local addr");
        let server_task2 = tokio::spawn(async move {
            let (mut socket, _peer) = listener2.accept().await.expect("accept");
            let mut drain = ByteDrain::default();
            drain.until(&mut socket, b"USER").await;
            socket
                .write_all(b":tmi.twitch.tv 001 bot :Welcome\r\n")
                .await
                .expect("write registration line");
            drain.until(&mut socket, b"JOIN").await;
            drain.until(&mut socket, b"QUIT").await;
        });
        let cfg2 = plain_tcp_config(addr2);
        let sender = TwitchIrcSender::new(cfg2);
        sender
            .send("hello")
            .await
            .expect("sender send should succeed");
        server_task2.await.expect("server task should not panic");
    }

    #[tokio::test]
    async fn connect_tls_handshake_fails_against_a_plain_server() {
        // The fake server accepts and closes without ever speaking TLS —
        // exercises `build_tls_connector`, a valid `ServerName`, and the
        // handshake-failure error mapping without needing a real certificate.
        let listener = tokio::net::TcpListener::bind("127.0.0.1:0")
            .await
            .expect("bind loopback");
        let addr = listener.local_addr().expect("local addr");
        let server_task = tokio::spawn(async move {
            let (socket, _peer) = listener.accept().await.expect("accept");
            drop(socket);
        });

        let mut cfg = IrcConfig::new("127.0.0.1", "bot", "dallas");
        cfg.port = addr.port();
        cfg.use_tls = true;
        let err = connect(&cfg)
            .await
            .expect_err("non-TLS peer should fail the TLS handshake");
        assert!(matches!(err, TwitchError::Connection(_)));
        server_task.await.expect("server task should not panic");
    }
}
