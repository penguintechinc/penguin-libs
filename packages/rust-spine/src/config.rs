//! Environment-driven spine configuration: Valkey connection details, the
//! transport-security opt-out (spec Sec11.6.4/D20), and every `SPINE_*`
//! tuning knob (spec Sec12.7).

use std::path::PathBuf;

use crate::error::SpineError;

fn lookup_string(lookup: &impl Fn(&str) -> Option<String>, name: &str) -> Option<String> {
    lookup(name)
}

fn lookup_u64(
    lookup: &impl Fn(&str) -> Option<String>,
    name: &str,
    default: u64,
) -> Result<u64, SpineError> {
    match lookup(name) {
        None => Ok(default),
        Some(v) => v
            .parse::<u64>()
            .map_err(|e| SpineError::Config(format!("{name}={v:?} is not a valid u64: {e}"))),
    }
}

fn lookup_i64(
    lookup: &impl Fn(&str) -> Option<String>,
    name: &str,
    default: i64,
) -> Result<i64, SpineError> {
    match lookup(name) {
        None => Ok(default),
        Some(v) => v
            .parse::<i64>()
            .map_err(|e| SpineError::Config(format!("{name}={v:?} is not a valid i64: {e}"))),
    }
}

fn lookup_bool(
    lookup: &impl Fn(&str) -> Option<String>,
    name: &str,
    default: bool,
) -> Result<bool, SpineError> {
    match lookup(name) {
        None => Ok(default),
        Some(v) => match v.to_ascii_lowercase().as_str() {
            "true" | "1" | "yes" | "on" => Ok(true),
            "false" | "0" | "no" | "off" => Ok(false),
            other => Err(SpineError::Config(format!(
                "{name}={other:?} is not a valid boolean"
            ))),
        },
    }
}

fn read_secret_from_lookup(
    lookup: &impl Fn(&str) -> Option<String>,
    env_name: &str,
    file_env_name: &str,
) -> Result<Option<String>, SpineError> {
    if let Some(v) = lookup(env_name) {
        return Ok(Some(v));
    }
    if let Some(path) = lookup(file_env_name) {
        let contents = std::fs::read_to_string(&path).map_err(|e| {
            SpineError::Config(format!("failed to read {file_env_name} ({path}): {e}"))
        })?;
        return Ok(Some(contents.trim_end().to_string()));
    }
    Ok(None)
}

fn default_consumer_id(lookup: &impl Fn(&str) -> Option<String>) -> String {
    // Spec Sec5.2: "the pod name, else {hostname}-{uuid-v4}". Kubernetes
    // sets HOSTNAME to the pod name by default, so a present HOSTNAME IS
    // the pod name; a missing one (non-k8s dev environment) falls back to
    // a UUID alone rather than pulling in a `hostname`-resolution crate
    // just to satisfy a rare fallback path.
    match lookup("HOSTNAME") {
        Some(h) if !h.is_empty() => h,
        _ => format!("unknown-{}", uuid::Uuid::new_v4()),
    }
}

/// Validates that a blocking-read timeout is strictly less than its
/// connection's socket timeout (spec Sec5.7 rule 1) — construction that
/// violates this must be refused, naming both values, rather than racing
/// silently in production.
pub fn validate_block_timeout(
    name: &'static str,
    block_ms: u64,
    socket_timeout_s: u64,
) -> Result<(), SpineError> {
    let socket_timeout_ms = socket_timeout_s.saturating_mul(1000);
    if block_ms >= socket_timeout_ms {
        return Err(SpineError::BlockTimeoutInvalid {
            block_name: name,
            block_ms,
            socket_timeout_s,
        });
    }
    Ok(())
}

/// Environment-driven spine configuration (spec Sec12.7). Construct via
/// [`SpineConfig::from_env`] at startup.
///
/// `Debug` is hand-written, not derived: `valkey_password` is a credential
/// and must never appear verbatim in a `{:?}` log line (critical-rules.md
/// Token & Secret Hygiene). Every other field has been audited and holds no
/// secret value -- `valkey_username` is a non-secret identifier,
/// `valkey_ca_file` is a filesystem path (not a key/cert value), and
/// `valkey_url` never carries embedded credentials in this crate's usage
/// (auth is always via the separate username/password fields, matching
/// `SpineClient`'s existing manual `Debug` impl printing `valkey_url`
/// unredacted).
#[derive(Clone)]
pub struct SpineConfig {
    /// `VALKEY_URL`, falling back to `REDIS_URL` for compatibility. Required.
    pub valkey_url: String,
    /// `VALKEY_USERNAME`.
    pub valkey_username: Option<String>,
    /// `VALKEY_PASSWORD` or `VALKEY_PASSWORD_FILE` (file wins only when the
    /// plain var is unset; env value never logged).
    pub valkey_password: Option<String>,
    /// `VALKEY_CA_FILE`, default `/etc/waddles/ca/valkey-ca.crt`.
    pub valkey_ca_file: PathBuf,
    /// `SECURITY_TRANSPORT_TLS`, default `true`.
    pub security_transport_tls: bool,
    /// `SECURITY_TRANSPORT_AUTH`, default `true`.
    pub security_transport_auth: bool,
    /// `SPINE_CONSUMER_ID`, default the pod name else `unknown-{uuid-v4}`.
    pub consumer_id: String,
    /// `SPINE_STREAM_MAXLEN`, default `100000`.
    pub stream_maxlen: u64,
    /// `SPINE_READ_COUNT`, default `64`.
    pub read_count: i64,
    /// `SPINE_BLOCK_MS`, default `1000`.
    pub block_ms: u64,
    /// `SPINE_CLAIM_IDLE_MS`, default `30000`.
    pub claim_idle_ms: u64,
    /// `SPINE_CLAIM_INTERVAL_MS`, default `15000`.
    pub claim_interval_ms: u64,
    /// `SPINE_STATS_INTERVAL_MS`, default `10000`.
    pub stats_interval_ms: u64,
    /// `SPINE_PEL_ALERT`, default `5000`.
    pub pel_alert: u64,
    /// `SPINE_DLQ_MAXLEN`, default `10000`.
    pub dlq_maxlen: u64,
    /// `SPINE_MAX_DELIVERIES`, default `5`.
    pub max_deliveries: u32,
    /// `DRAIN_SOCKET_TIMEOUT_S`, default `65` (spec Sec5.7).
    pub drain_socket_timeout_s: u64,
    /// `RELAY_BLOCK_TIMEOUT_S`, default `30` (spec Sec5.7/Sec5.8).
    pub relay_block_timeout_s: u64,
}

impl std::fmt::Debug for SpineConfig {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.debug_struct("SpineConfig")
            .field("valkey_url", &self.valkey_url)
            .field("valkey_username", &self.valkey_username)
            .field(
                "valkey_password",
                &self.valkey_password.as_ref().map(|_| "<redacted>"),
            )
            .field("valkey_ca_file", &self.valkey_ca_file)
            .field("security_transport_tls", &self.security_transport_tls)
            .field("security_transport_auth", &self.security_transport_auth)
            .field("consumer_id", &self.consumer_id)
            .field("stream_maxlen", &self.stream_maxlen)
            .field("read_count", &self.read_count)
            .field("block_ms", &self.block_ms)
            .field("claim_idle_ms", &self.claim_idle_ms)
            .field("claim_interval_ms", &self.claim_interval_ms)
            .field("stats_interval_ms", &self.stats_interval_ms)
            .field("pel_alert", &self.pel_alert)
            .field("dlq_maxlen", &self.dlq_maxlen)
            .field("max_deliveries", &self.max_deliveries)
            .field("drain_socket_timeout_s", &self.drain_socket_timeout_s)
            .field("relay_block_timeout_s", &self.relay_block_timeout_s)
            .finish()
    }
}

impl SpineConfig {
    /// Loads configuration from the real process environment.
    pub fn from_env() -> Result<Self, SpineError> {
        Self::from_lookup(&|name| std::env::var(name).ok())
    }

    fn from_lookup(lookup: &impl Fn(&str) -> Option<String>) -> Result<Self, SpineError> {
        let valkey_url = lookup_string(lookup, "VALKEY_URL")
            .or_else(|| lookup_string(lookup, "REDIS_URL"))
            .ok_or_else(|| SpineError::Config("VALKEY_URL (or REDIS_URL) is required".into()))?;
        let valkey_username = lookup_string(lookup, "VALKEY_USERNAME");
        let valkey_password =
            read_secret_from_lookup(lookup, "VALKEY_PASSWORD", "VALKEY_PASSWORD_FILE")?;
        let valkey_ca_file = PathBuf::from(
            lookup_string(lookup, "VALKEY_CA_FILE")
                .unwrap_or_else(|| "/etc/waddles/ca/valkey-ca.crt".to_string()),
        );
        let security_transport_tls = lookup_bool(lookup, "SECURITY_TRANSPORT_TLS", true)?;
        let security_transport_auth = lookup_bool(lookup, "SECURITY_TRANSPORT_AUTH", true)?;
        let consumer_id = lookup_string(lookup, "SPINE_CONSUMER_ID")
            .unwrap_or_else(|| default_consumer_id(lookup));
        let stream_maxlen = lookup_u64(lookup, "SPINE_STREAM_MAXLEN", 100_000)?;
        let read_count = lookup_i64(lookup, "SPINE_READ_COUNT", 64)?;
        let block_ms = lookup_u64(lookup, "SPINE_BLOCK_MS", 1_000)?;
        let claim_idle_ms = lookup_u64(lookup, "SPINE_CLAIM_IDLE_MS", 30_000)?;
        let claim_interval_ms = lookup_u64(lookup, "SPINE_CLAIM_INTERVAL_MS", 15_000)?;
        let stats_interval_ms = lookup_u64(lookup, "SPINE_STATS_INTERVAL_MS", 10_000)?;
        let pel_alert = lookup_u64(lookup, "SPINE_PEL_ALERT", 5_000)?;
        let dlq_maxlen = lookup_u64(lookup, "SPINE_DLQ_MAXLEN", 10_000)?;
        let max_deliveries = lookup_u64(lookup, "SPINE_MAX_DELIVERIES", 5)? as u32;
        let drain_socket_timeout_s = lookup_u64(lookup, "DRAIN_SOCKET_TIMEOUT_S", 65)?;
        let relay_block_timeout_s = lookup_u64(lookup, "RELAY_BLOCK_TIMEOUT_S", 30)?;

        let cfg = SpineConfig {
            valkey_url,
            valkey_username,
            valkey_password,
            valkey_ca_file,
            security_transport_tls,
            security_transport_auth,
            consumer_id,
            stream_maxlen,
            read_count,
            block_ms,
            claim_idle_ms,
            claim_interval_ms,
            stats_interval_ms,
            pel_alert,
            dlq_maxlen,
            max_deliveries,
            drain_socket_timeout_s,
            relay_block_timeout_s,
        };
        cfg.validate()?;
        Ok(cfg)
    }

    /// Re-runs every startup refusal check (spec Sec11.6.1, Sec5.7 rule 1).
    /// Called automatically by [`SpineConfig::from_env`]; exposed so a
    /// caller building a `SpineConfig` by hand (tests, `--dev`) still gets
    /// the same guarantees.
    pub fn validate(&self) -> Result<(), SpineError> {
        if self.security_transport_tls
            && !(self.valkey_url.starts_with("rediss://")
                || self.valkey_url.starts_with("valkeys://"))
        {
            return Err(SpineError::Config(format!(
                "security.transport.tls is enabled but VALKEY_URL {:?} is not rediss://; \
                 refusing to start with a plaintext transport",
                self.valkey_url
            )));
        }
        if self.security_transport_auth
            && self.valkey_username.is_none()
            && self.valkey_password.is_none()
        {
            return Err(SpineError::Config(
                "security.transport.auth is enabled but neither VALKEY_USERNAME nor \
                 VALKEY_PASSWORD/_FILE is set"
                    .to_string(),
            ));
        }
        validate_block_timeout("SPINE_BLOCK_MS", self.block_ms, self.drain_socket_timeout_s)?;
        validate_block_timeout(
            "RELAY_BLOCK_TIMEOUT_S",
            self.relay_block_timeout_s.saturating_mul(1000),
            self.drain_socket_timeout_s,
        )?;
        Ok(())
    }
}

/// One classified startup connectivity probe result (spec Sec12.6) —
/// never a bare "connection failed".
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum ProbeClass {
    /// The hostname did not resolve.
    Dns,
    /// Resolved, but the connection was refused, timed out, or was blocked.
    Tcp,
    /// Connected, but the handshake or certificate verification failed.
    Tls,
    /// TLS succeeded, credentials were rejected.
    Auth,
    /// Reachable and authenticated.
    Ok,
}

impl ProbeClass {
    /// The lowercase wire form used in `waddles_dependency_check_total{class}`.
    pub fn as_str(&self) -> &'static str {
        match self {
            ProbeClass::Dns => "dns",
            ProbeClass::Tcp => "tcp",
            ProbeClass::Tls => "tls",
            ProbeClass::Auth => "auth",
            ProbeClass::Ok => "ok",
        }
    }
}

/// The outcome of one startup connectivity probe against one dependency
/// (spec Sec12.6), always classified — never a bare failure.
#[derive(Debug, Clone)]
pub struct ProbeResult {
    /// The dependency name (`"valkey"`, `"postgres"`, ...).
    pub dependency: String,
    /// The classification.
    pub class: ProbeClass,
    /// A human-readable message naming the endpoint and what went wrong.
    pub message: String,
}

/// Classifies a `redis::RedisError` observed while connecting or
/// authenticating into a Sec12.6 probe class. See this task's "known
/// limitation" note for the TLS-vs-TCP heuristic (the `redis` crate has no
/// dedicated TLS error kind, so this searches the error's `Display` text
/// for TLS/certificate-shaped substrings — a best-effort heuristic, not a
/// structural guarantee).
pub fn classify_connect_error(err: &redis::RedisError) -> ProbeClass {
    if err.kind() == redis::ErrorKind::AuthenticationFailed {
        return ProbeClass::Auth;
    }
    if err.is_io_error() {
        let text = err.to_string().to_ascii_lowercase();
        let tls_markers = [
            "certificate",
            "tls",
            "handshake",
            "unknownissuer",
            "invalid peer certificate",
        ];
        if tls_markers.iter().any(|m| text.contains(m)) {
            return ProbeClass::Tls;
        }
        return ProbeClass::Tcp;
    }
    ProbeClass::Tcp
}

fn build_connection_info(cfg: &SpineConfig) -> Result<redis::ConnectionInfo, SpineError> {
    let base: redis::ConnectionInfo =
        redis::IntoConnectionInfo::into_connection_info(cfg.valkey_url.as_str()).map_err(|e| {
            SpineError::Config(format!("invalid VALKEY_URL {:?}: {e}", cfg.valkey_url))
        })?;
    let mut redis_settings = base.redis_settings().clone();
    if let Some(username) = &cfg.valkey_username {
        redis_settings = redis_settings.set_username(username);
    }
    if let Some(password) = &cfg.valkey_password {
        redis_settings = redis_settings.set_password(password);
    }
    Ok(base.set_redis_settings(redis_settings))
}

fn host_port_from_url(url: &str) -> Result<(String, u16), SpineError> {
    let info: redis::ConnectionInfo = redis::IntoConnectionInfo::into_connection_info(url)
        .map_err(|e| SpineError::Config(format!("invalid VALKEY_URL {url:?}: {e}")))?;
    match info.addr() {
        redis::ConnectionAddr::Tcp(host, port) => Ok((host.clone(), *port)),
        redis::ConnectionAddr::TcpTls { host, port, .. } => Ok((host.clone(), *port)),
        redis::ConnectionAddr::Unix(_) => Err(SpineError::Config(
            "VALKEY_URL must be a TCP address, not a unix socket".to_string(),
        )),
        // `ConnectionAddr` is `#[non_exhaustive]` upstream; any future
        // variant is refused the same way a unix socket is, rather than
        // silently misparsed as a host:port pair.
        _ => Err(SpineError::Config(
            "VALKEY_URL resolved to an unsupported connection address type".to_string(),
        )),
    }
}

/// Resolves `host:port` via DNS only (spec Sec12.6's first probe layer).
async fn resolve_host(host: &str, port: u16) -> Result<(), String> {
    tokio::net::lookup_host((host, port))
        .await
        .map(|_| ())
        .map_err(|e| e.to_string())
}

static CRYPTO_PROVIDER_INIT: std::sync::Once = std::sync::Once::new();

/// Installs the process-level rustls `CryptoProvider` (the `ring` backend)
/// exactly once. `redis`'s `tls-rustls` feature enables `dep:rustls` but
/// requests no provider itself, so the first TLS handshake anywhere in the
/// process panics without this -- see the `rustls` dependency comment in
/// `Cargo.toml`. Safe to call from every TLS-capable entry point
/// (`probe_valkey`, `SpineClient::connect`, `GroupReader::connect`):
/// `Once` makes repeat calls a no-op, and a losing race against another
/// caller installing the same provider is not an error either.
pub(crate) fn ensure_crypto_provider_installed() {
    CRYPTO_PROVIDER_INIT.call_once(|| {
        let _ = rustls::crypto::ring::default_provider().install_default();
    });
}

async fn single_valkey_probe_attempt(host: &str, port: u16, cfg: &SpineConfig) -> ProbeResult {
    if cfg.security_transport_tls {
        ensure_crypto_provider_installed();
    }
    let dependency = "valkey".to_string();
    if let Err(e) = resolve_host(host, port).await {
        return ProbeResult {
            dependency,
            class: ProbeClass::Dns,
            message: format!("valkey: DNS resolution failed for {host:?}: {e}"),
        };
    }

    let info = match build_connection_info(cfg) {
        Ok(i) => i,
        Err(e) => {
            return ProbeResult {
                dependency,
                class: ProbeClass::Dns,
                message: e.to_string(),
            };
        }
    };

    let client_result = if cfg.security_transport_tls {
        let root_cert = std::fs::read(&cfg.valkey_ca_file).ok();
        redis::Client::build_with_tls(
            info,
            redis::TlsCertificates {
                client_tls: None,
                root_cert,
            },
        )
    } else {
        redis::Client::open(info)
    };

    let client = match client_result {
        Ok(c) => c,
        Err(e) => {
            return ProbeResult {
                dependency,
                class: classify_connect_error(&e),
                message: format!("valkey: failed to build client: {e}"),
            };
        }
    };

    let async_cfg = redis::AsyncConnectionConfig::new().set_response_timeout(Some(
        std::time::Duration::from_secs(cfg.drain_socket_timeout_s),
    ));

    let mut conn = match client
        .get_multiplexed_async_connection_with_config(&async_cfg)
        .await
    {
        Ok(c) => c,
        Err(e) => {
            return ProbeResult {
                dependency,
                class: classify_connect_error(&e),
                message: format!("valkey: connect failed: {e}"),
            };
        }
    };

    match redis::cmd("PING").query_async::<String>(&mut conn).await {
        Ok(_) => ProbeResult {
            dependency,
            class: ProbeClass::Ok,
            message: "ok".to_string(),
        },
        Err(e) => ProbeResult {
            dependency,
            class: classify_connect_error(&e),
            message: format!("valkey: PING failed: {e}"),
        },
    }
}

/// Probes Valkey connectivity per spec Sec12.6: DNS resolution, then a
/// connect + `AUTH` + `PING`, classified and retried up to `attempts`
/// times at `retry_interval` apart, each attempt bounded by `timeout`.
/// Never a silent retry loop — every attempt's classified result is meant
/// to be logged by the caller (this crate only classifies; logging is the
/// caller's job, see [`crate::SpineMetrics`]).
pub async fn probe_valkey(
    cfg: &SpineConfig,
    timeout: std::time::Duration,
    attempts: u32,
    retry_interval: std::time::Duration,
) -> ProbeResult {
    let dependency = "valkey".to_string();
    let (host, port) = match host_port_from_url(&cfg.valkey_url) {
        Ok(hp) => hp,
        Err(e) => {
            return ProbeResult {
                dependency,
                class: ProbeClass::Dns,
                message: e.to_string(),
            };
        }
    };

    let mut last = ProbeResult {
        dependency: dependency.clone(),
        class: ProbeClass::Tcp,
        message: "probe never ran".to_string(),
    };

    for attempt in 0..attempts.max(1) {
        if attempt > 0 {
            tokio::time::sleep(retry_interval).await;
        }
        last = match tokio::time::timeout(timeout, single_valkey_probe_attempt(&host, port, cfg))
            .await
        {
            Ok(result) => result,
            Err(_) => ProbeResult {
                dependency: dependency.clone(),
                class: ProbeClass::Tcp,
                message: format!(
                    "valkey: TCP connect to {host}:{port} timed out after {}s",
                    timeout.as_secs()
                ),
            },
        };
        if last.class == ProbeClass::Ok {
            break;
        }
    }
    last
}

#[cfg(test)]
mod tests {
    #![allow(clippy::unwrap_used)]
    use super::*;
    use std::collections::HashMap;

    fn lookup_from<'a>(map: &'a HashMap<&'a str, &'a str>) -> impl Fn(&str) -> Option<String> + 'a {
        move |name| map.get(name).map(|v| v.to_string())
    }

    fn base_env() -> HashMap<&'static str, &'static str> {
        let mut m = HashMap::new();
        m.insert(
            "VALKEY_URL",
            "rediss://valkey.waddles.svc.cluster.local:6379",
        );
        m.insert("VALKEY_USERNAME", "svc-process");
        m.insert("VALKEY_PASSWORD", "test-password");
        m
    }

    #[test]
    fn from_lookup_succeeds_with_required_vars_and_secure_defaults() {
        let env = base_env();
        let cfg = SpineConfig::from_lookup(&lookup_from(&env)).unwrap();
        assert_eq!(
            cfg.valkey_url,
            "rediss://valkey.waddles.svc.cluster.local:6379"
        );
        assert!(cfg.security_transport_tls);
        assert!(cfg.security_transport_auth);
        assert_eq!(cfg.stream_maxlen, 100_000);
        assert_eq!(cfg.block_ms, 1_000);
        assert_eq!(cfg.drain_socket_timeout_s, 65);
    }

    #[test]
    fn falls_back_to_redis_url_when_valkey_url_unset() {
        let mut env = base_env();
        env.remove("VALKEY_URL");
        env.insert("REDIS_URL", "rediss://legacy.example:6379");
        let cfg = SpineConfig::from_lookup(&lookup_from(&env)).unwrap();
        assert_eq!(cfg.valkey_url, "rediss://legacy.example:6379");
    }

    #[test]
    fn missing_valkey_url_is_an_error() {
        let env: HashMap<&str, &str> = HashMap::new();
        assert!(SpineConfig::from_lookup(&lookup_from(&env)).is_err());
    }

    #[test]
    fn tls_required_refuses_plaintext_url() {
        let mut env = base_env();
        env.insert(
            "VALKEY_URL",
            "redis://valkey.waddles.svc.cluster.local:6379",
        );
        assert!(SpineConfig::from_lookup(&lookup_from(&env)).is_err());
    }

    #[test]
    fn tls_opt_out_allows_plaintext_url() {
        let mut env = base_env();
        env.insert(
            "VALKEY_URL",
            "redis://valkey.waddles.svc.cluster.local:6379",
        );
        env.insert("SECURITY_TRANSPORT_TLS", "false");
        let cfg = SpineConfig::from_lookup(&lookup_from(&env)).unwrap();
        assert!(!cfg.security_transport_tls);
    }

    #[test]
    fn auth_required_refuses_missing_credentials() {
        let mut env = base_env();
        env.remove("VALKEY_USERNAME");
        env.remove("VALKEY_PASSWORD");
        assert!(SpineConfig::from_lookup(&lookup_from(&env)).is_err());
    }

    #[test]
    fn auth_opt_out_allows_missing_credentials() {
        let mut env = base_env();
        env.remove("VALKEY_USERNAME");
        env.remove("VALKEY_PASSWORD");
        env.insert("SECURITY_TRANSPORT_AUTH", "false");
        let cfg = SpineConfig::from_lookup(&lookup_from(&env)).unwrap();
        assert!(!cfg.security_transport_auth);
    }

    #[test]
    fn password_file_is_read_and_trimmed() {
        let dir = std::env::temp_dir().join(format!("spine-test-{}", uuid::Uuid::new_v4()));
        std::fs::create_dir_all(&dir).unwrap();
        let path = dir.join("password");
        std::fs::write(&path, "from-file-password\n").unwrap();

        let mut env = base_env();
        env.remove("VALKEY_PASSWORD");
        let path_str = path.to_string_lossy().to_string();
        env.insert("VALKEY_PASSWORD_FILE", Box::leak(path_str.into_boxed_str()));
        let cfg = SpineConfig::from_lookup(&lookup_from(&env)).unwrap();
        assert_eq!(cfg.valkey_password.as_deref(), Some("from-file-password"));

        std::fs::remove_dir_all(&dir).unwrap();
    }

    #[test]
    fn validate_block_timeout_rejects_block_ms_not_strictly_less() {
        assert!(validate_block_timeout("SPINE_BLOCK_MS", 65_000, 65).is_err());
        assert!(validate_block_timeout("SPINE_BLOCK_MS", 70_000, 65).is_err());
    }

    #[test]
    fn validate_block_timeout_accepts_strictly_less_values() {
        assert!(validate_block_timeout("SPINE_BLOCK_MS", 1_000, 65).is_ok());
        assert!(validate_block_timeout("RELAY_BLOCK_TIMEOUT_S", 30_000, 65).is_ok());
    }

    #[test]
    fn from_lookup_rejects_default_relay_timeout_against_a_too_small_socket_timeout() {
        let mut env = base_env();
        env.insert("DRAIN_SOCKET_TIMEOUT_S", "25"); // < RELAY_BLOCK_TIMEOUT_S default (30s)
        assert!(SpineConfig::from_lookup(&lookup_from(&env)).is_err());
    }

    #[test]
    fn default_consumer_id_uses_hostname_when_present() {
        let mut env = base_env();
        env.insert("HOSTNAME", "svc-process-7d9c4f");
        let cfg = SpineConfig::from_lookup(&lookup_from(&env)).unwrap();
        assert_eq!(cfg.consumer_id, "svc-process-7d9c4f");
    }

    #[test]
    fn default_consumer_id_falls_back_to_a_uuid_when_hostname_absent() {
        let env = base_env();
        let cfg = SpineConfig::from_lookup(&lookup_from(&env)).unwrap();
        assert!(cfg.consumer_id.starts_with("unknown-"));
    }

    /// Regression: `SpineConfig` used to `#[derive(Debug)]`, which prints
    /// `valkey_password` verbatim -- a credential leak into any `{:?}` log
    /// line. This must fail against the derive and pass only once the
    /// hand-written `Debug` impl redacts the password (critical-rules.md
    /// Token & Secret Hygiene: never print/log a full token value).
    #[test]
    fn debug_output_never_contains_the_raw_password() {
        let mut env = base_env();
        env.insert("VALKEY_PASSWORD", "sup3r-secret-do-not-leak-9f8e7d");
        let cfg = SpineConfig::from_lookup(&lookup_from(&env)).unwrap();
        let debug_output = format!("{cfg:?}");
        assert!(
            !debug_output.contains("sup3r-secret-do-not-leak-9f8e7d"),
            "Debug output leaked the raw password: {debug_output}"
        );
    }

    fn synthetic_io_error(message: &str) -> redis::RedisError {
        redis::RedisError::from(std::io::Error::other(message.to_string()))
    }

    #[test]
    fn classify_connect_error_maps_authentication_failed_to_auth() {
        let err = redis::RedisError::from((
            redis::ErrorKind::AuthenticationFailed,
            "authentication rejected",
        ));
        assert_eq!(classify_connect_error(&err), ProbeClass::Auth);
    }

    #[test]
    fn classify_connect_error_maps_plain_io_error_to_tcp() {
        let err = synthetic_io_error("connection refused (os error 111)");
        assert_eq!(classify_connect_error(&err), ProbeClass::Tcp);
    }

    #[test]
    fn classify_connect_error_maps_tls_shaped_io_error_to_tls() {
        let err = synthetic_io_error("invalid peer certificate: UnknownIssuer");
        assert_eq!(classify_connect_error(&err), ProbeClass::Tls);
    }

    #[tokio::test]
    async fn resolve_host_fails_for_the_reserved_invalid_tld() {
        // `.invalid` is IANA-reserved to never resolve (RFC 2606) -- a
        // deterministic DNS failure with no external service dependency.
        let result = resolve_host("this-host-does-not-exist.invalid", 6379).await;
        assert!(result.is_err());
    }

    #[tokio::test]
    async fn probe_valkey_classifies_dns_failure() {
        let mut env = base_env();
        env.insert(
            "VALKEY_URL",
            "rediss://this-host-does-not-exist.invalid:6379",
        );
        let cfg = SpineConfig::from_lookup(&lookup_from(&env)).unwrap();
        let result = probe_valkey(
            &cfg,
            std::time::Duration::from_millis(500),
            1,
            std::time::Duration::from_millis(10),
        )
        .await;
        assert_eq!(result.class, ProbeClass::Dns);
        assert!(result.message.contains("this-host-does-not-exist.invalid"));
    }

    #[tokio::test]
    async fn probe_valkey_classifies_connection_refused_as_tcp() {
        // Port 1 on loopback is a reserved low port nothing listens on in
        // a test container; the connection attempt fails immediately with
        // "connection refused" rather than timing out.
        let mut env = base_env();
        env.insert("VALKEY_URL", "rediss://127.0.0.1:1");
        let cfg = SpineConfig::from_lookup(&lookup_from(&env)).unwrap();
        let result = probe_valkey(
            &cfg,
            std::time::Duration::from_millis(500),
            1,
            std::time::Duration::from_millis(10),
        )
        .await;
        assert_eq!(result.class, ProbeClass::Tcp);
    }
}
