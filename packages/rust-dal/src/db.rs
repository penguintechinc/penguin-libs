//! Relational database connection pooling and configuration (PostgreSQL & SQLite via `sqlx`).
//!
//! Connections are built from typed `sqlx` option setters (never a hand-assembled DSN) and
//! PostgreSQL connections default to `verify-full` TLS.

use std::fmt;
use std::str::FromStr;
use std::time::Duration;

use figment::providers::Env;
use figment::Figment;
use serde::Deserialize;
use sqlx::postgres::{PgConnectOptions, PgPoolOptions, PgSslMode};
use sqlx::sqlite::{SqliteConnectOptions, SqlitePoolOptions};
use sqlx::{PgPool, SqlitePool};

use crate::error::DalError;

/// Supported database backends, selected via `DB_TYPE`.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Deserialize)]
#[serde(rename_all = "lowercase")]
pub enum DbType {
    /// PostgreSQL (production backend).
    Postgresql,
    /// SQLite (development and hermetic testing backend).
    Sqlite,
}

/// TLS policy for PostgreSQL connections, selected via `DB_SSLMODE`.
///
/// Defaults to [`DbSslMode::VerifyFull`]. `Disable` and `Prefer` are development-only and are
/// rejected unless `DB_ALLOW_INSECURE_SSL=true` is also set; `Require` and `VerifyCa` encrypt
/// but do not authenticate the server hostname and are accepted with a warning.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Default, Deserialize)]
#[serde(rename_all = "kebab-case")]
pub enum DbSslMode {
    /// No TLS (development only; needs explicit insecure opt-in).
    Disable,
    /// TLS if the server offers it, else plaintext (development only; needs opt-in).
    Prefer,
    /// TLS required, certificate not verified.
    Require,
    /// TLS required, certificate chain verified, hostname not checked.
    VerifyCa,
    /// TLS required, certificate chain and hostname verified (default).
    #[default]
    VerifyFull,
}

impl DbSslMode {
    /// Returns the libpq-style `sslmode` string (`verify-full`, ...).
    pub fn as_str(self) -> &'static str {
        match self {
            DbSslMode::Disable => "disable",
            DbSslMode::Prefer => "prefer",
            DbSslMode::Require => "require",
            DbSslMode::VerifyCa => "verify-ca",
            DbSslMode::VerifyFull => "verify-full",
        }
    }

    /// Maps to the `sqlx` PostgreSQL SSL mode.
    pub fn to_pg(self) -> PgSslMode {
        match self {
            DbSslMode::Disable => PgSslMode::Disable,
            DbSslMode::Prefer => PgSslMode::Prefer,
            DbSslMode::Require => PgSslMode::Require,
            DbSslMode::VerifyCa => PgSslMode::VerifyCa,
            DbSslMode::VerifyFull => PgSslMode::VerifyFull,
        }
    }

    /// True when the mode can fall back to plaintext (`Disable`, `Prefer`).
    pub fn is_insecure(self) -> bool {
        matches!(self, DbSslMode::Disable | DbSslMode::Prefer)
    }
}

/// Standard database connection settings read from `DB_*` environment variables.
///
/// `Debug` is implemented manually and redacts the password.
#[derive(Clone, Deserialize)]
pub struct DbConfig {
    /// Backend selector (`DB_TYPE` / `DB_DB_TYPE`).
    #[serde(rename = "type")]
    pub db_type: DbType,
    /// Database host (`DB_HOST`).
    #[serde(default = "default_host")]
    pub host: String,
    /// Database port (`DB_PORT`).
    #[serde(default = "default_port")]
    pub port: u16,
    /// Database name (`DB_NAME`).
    #[serde(default = "default_name")]
    pub name: String,
    /// Database user (`DB_USER`).
    #[serde(default = "default_user")]
    pub user: String,
    /// Database password (`DB_PASS`). Secret: never logged.
    #[serde(default)]
    pub pass: String,
    /// Maximum pool size (`DB_POOL_SIZE`).
    #[serde(default = "default_pool_size")]
    pub pool_size: u32,
    /// Startup connection retry attempts (`DB_MAX_RETRIES`).
    #[serde(default = "default_max_retries")]
    pub max_retries: u32,
    /// Base retry delay in seconds (`DB_RETRY_DELAY`).
    #[serde(default = "default_retry_delay")]
    pub retry_delay: u64,
    /// PostgreSQL TLS policy (`DB_SSLMODE`), default `verify-full`.
    #[serde(rename = "sslmode", alias = "ssl_mode", default)]
    pub ssl_mode: DbSslMode,
    /// Optional PEM root CA path used to verify the server (`DB_SSL_ROOT_CERT`).
    #[serde(default)]
    pub ssl_root_cert: Option<String>,
    /// Development-only opt-in permitting `disable`/`prefer` (`DB_ALLOW_INSECURE_SSL`).
    #[serde(default)]
    pub allow_insecure_ssl: bool,
}

impl fmt::Debug for DbConfig {
    /// Formats the config with the password redacted so it can never leak through logs.
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.debug_struct("DbConfig")
            .field("db_type", &self.db_type)
            .field("host", &self.host)
            .field("port", &self.port)
            .field("name", &self.name)
            .field("user", &self.user)
            .field("pass", &"[REDACTED]")
            .field("pool_size", &self.pool_size)
            .field("max_retries", &self.max_retries)
            .field("retry_delay", &self.retry_delay)
            .field("ssl_mode", &self.ssl_mode)
            .field("ssl_root_cert", &self.ssl_root_cert)
            .field("allow_insecure_ssl", &self.allow_insecure_ssl)
            .finish()
    }
}

fn default_host() -> String {
    "localhost".to_owned()
}
fn default_port() -> u16 {
    5432
}
fn default_name() -> String {
    "penguin".to_owned()
}
fn default_user() -> String {
    "penguin".to_owned()
}
fn default_pool_size() -> u32 {
    10
}
fn default_max_retries() -> u32 {
    5
}
fn default_retry_delay() -> u64 {
    2
}

/// Percent-encodes every byte of `input` outside the RFC 3986 unreserved set and `keep`.
fn percent_encode(input: &str, keep: &[u8]) -> String {
    let mut out = String::with_capacity(input.len());
    for &b in input.as_bytes() {
        if b.is_ascii_alphanumeric() || matches!(b, b'-' | b'.' | b'_' | b'~') || keep.contains(&b)
        {
            out.push(b as char);
        } else {
            out.push_str(&format!("%{b:02X}"));
        }
    }
    out
}

impl DbConfig {
    /// Loads configuration from `DB_*` prefixed environment variables via `figment`
    /// and validates the TLS policy.
    pub fn from_env() -> Result<Self, DalError> {
        Self::from_figment(Figment::new().merge(Env::prefixed("DB_")))
    }

    /// Extracts and validates a config from any figment source.
    pub(crate) fn from_figment(fig: Figment) -> Result<Self, DalError> {
        let cfg: Self = fig.extract().map_err(|e| DalError::Config(e.to_string()))?;
        cfg.validate()?;
        Ok(cfg)
    }

    /// Checks the TLS policy: plaintext-capable modes require the explicit dev opt-in.
    ///
    /// Emits a `tracing` warning whenever a non-`verify-full` PostgreSQL mode is in use.
    pub fn validate(&self) -> Result<(), DalError> {
        if self.db_type != DbType::Postgresql {
            return Ok(());
        }
        if self.ssl_mode.is_insecure() && !self.allow_insecure_ssl {
            return Err(DalError::Config(format!(
                "DB_SSLMODE={} permits plaintext connections; set DB_ALLOW_INSECURE_SSL=true                  (development only) or use verify-full",
                self.ssl_mode.as_str()
            )));
        }
        if self.ssl_mode != DbSslMode::VerifyFull {
            tracing::warn!(
                ssl_mode = self.ssl_mode.as_str(),
                "database TLS is weaker than verify-full; do not use outside development"
            );
        }
        Ok(())
    }

    /// Builds typed PostgreSQL connect options (no DSN string, so no injection via credentials).
    pub fn pg_connect_options(&self) -> Result<PgConnectOptions, DalError> {
        self.validate()?;
        let mut opts = PgConnectOptions::new()
            .host(&self.host)
            .port(self.port)
            .username(&self.user)
            .password(&self.pass)
            .database(&self.name)
            .ssl_mode(self.ssl_mode.to_pg());
        if let Some(ca) = &self.ssl_root_cert {
            opts = opts.ssl_root_cert(ca);
        }
        Ok(opts)
    }

    /// Builds typed SQLite connect options; `name` may be a path or a `sqlite:` URL.
    pub fn sqlite_connect_options(&self) -> Result<SqliteConnectOptions, DalError> {
        if self.name.starts_with("sqlite:") {
            SqliteConnectOptions::from_str(&self.name).map_err(|e| DalError::Config(e.to_string()))
        } else {
            Ok(SqliteConnectOptions::new()
                .filename(&self.name)
                .create_if_missing(true))
        }
    }

    /// Renders a connection URL with every component percent-encoded.
    ///
    /// The result contains the password in cleartext: never log it. Connections themselves use
    /// the typed `*_connect_options` builders instead.
    pub fn connection_url(&self) -> String {
        match self.db_type {
            DbType::Postgresql => {
                let host = if self.host.contains(':') {
                    format!("[{}]", self.host)
                } else {
                    percent_encode(&self.host, b"")
                };
                format!(
                    "postgres://{}:{}@{}:{}/{}?sslmode={}",
                    percent_encode(&self.user, b""),
                    percent_encode(&self.pass, b""),
                    host,
                    self.port,
                    percent_encode(&self.name, b""),
                    self.ssl_mode.as_str()
                )
            }
            DbType::Sqlite => {
                if self.name.starts_with("sqlite:") {
                    self.name.clone()
                } else {
                    format!("sqlite://{}?mode=rwc", percent_encode(&self.name, b"/:"))
                }
            }
        }
    }
}

/// Unified database pool enum wrapping either PostgreSQL or SQLite.
#[derive(Debug, Clone)]
pub enum DatabasePool {
    /// Active PostgreSQL pool.
    Postgres(PgPool),
    /// Active SQLite pool.
    Sqlite(SqlitePool),
}

impl DatabasePool {
    /// Pings the database connection to verify health and reachability.
    pub async fn ping(&self) -> Result<(), DalError> {
        match self {
            DatabasePool::Postgres(pool) => sqlx::query("SELECT 1")
                .execute(pool)
                .await
                .map(|_| ())
                .map_err(|e| DalError::Database(e.to_string())),
            DatabasePool::Sqlite(pool) => sqlx::query("SELECT 1")
                .execute(pool)
                .await
                .map(|_| ())
                .map_err(|e| DalError::Database(e.to_string())),
        }
    }
}

/// Connects a PostgreSQL pool with exponential backoff retry.
pub async fn connect_pg_pool(cfg: &DbConfig) -> Result<PgPool, DalError> {
    connect_pg_pool_with_timeout(cfg, Duration::from_secs(30)).await
}

/// Retrying PostgreSQL connect with an explicit per-attempt acquire timeout.
async fn connect_pg_pool_with_timeout(
    cfg: &DbConfig,
    acquire_timeout: Duration,
) -> Result<PgPool, DalError> {
    let opts = cfg.pg_connect_options()?;
    let mut delay = Duration::from_secs(cfg.retry_delay);
    let mut last_error = None;

    for attempt in 1..=cfg.max_retries {
        tracing::info!(
            attempt,
            max_retries = cfg.max_retries,
            "connecting to PostgreSQL"
        );
        match PgPoolOptions::new()
            .max_connections(cfg.pool_size)
            .acquire_timeout(acquire_timeout)
            .connect_with(opts.clone())
            .await
        {
            Ok(pool) => return Ok(pool),
            Err(e) => {
                tracing::warn!(attempt, error = %e, "database connection attempt failed");
                last_error = Some(e);
                if attempt < cfg.max_retries {
                    tokio::time::sleep(delay).await;
                    delay *= 2;
                }
            }
        }
    }

    Err(DalError::Exhausted {
        attempts: cfg.max_retries,
        message: last_error
            .map(|e| e.to_string())
            .unwrap_or_else(|| "unknown error".to_string()),
    })
}

/// Connects a SQLite pool.
pub async fn connect_sqlite_pool(cfg: &DbConfig) -> Result<SqlitePool, DalError> {
    let opts = cfg.sqlite_connect_options()?;
    SqlitePoolOptions::new()
        .max_connections(cfg.pool_size)
        .connect_with(opts)
        .await
        .map_err(|e| DalError::Database(e.to_string()))
}

/// Connects a [`DatabasePool`] based on the configured `db_type`.
pub async fn connect_pool(cfg: &DbConfig) -> Result<DatabasePool, DalError> {
    match cfg.db_type {
        DbType::Postgresql => connect_pg_pool(cfg).await.map(DatabasePool::Postgres),
        DbType::Sqlite => connect_sqlite_pool(cfg).await.map(DatabasePool::Sqlite),
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use figment::providers::Serialized;
    use serde_json::json;

    const NASTY: &str = "p@ss:w/o#r?d%41 &=";

    fn pg() -> DbConfig {
        DbConfig {
            db_type: DbType::Postgresql,
            host: "db.local".to_string(),
            port: 5432,
            name: "testdb".to_string(),
            user: "app".to_string(),
            pass: "secret".to_string(),
            pool_size: 5,
            max_retries: 3,
            retry_delay: 0,
            ssl_mode: DbSslMode::default(),
            ssl_root_cert: None,
            allow_insecure_ssl: false,
        }
    }

    fn sqlite(name: &str) -> DbConfig {
        DbConfig {
            db_type: DbType::Sqlite,
            name: name.to_string(),
            pool_size: 1,
            ..pg()
        }
    }

    fn from_json(v: serde_json::Value) -> Result<DbConfig, DalError> {
        DbConfig::from_figment(Figment::new().merge(Serialized::defaults(v)))
    }

    // regression: S-04 (Debug leaked the DB password)
    #[test]
    fn debug_redacts_password() {
        let mut cfg = pg();
        cfg.pass = "hunter2-very-secret".to_string();
        let shown = format!("{cfg:?}");
        assert!(!shown.contains("hunter2"), "{shown}");
        assert!(shown.contains("[REDACTED]"));
        assert!(shown.contains("db.local"));
    }

    // regression: S-05 (DSN built with format!, no encoding)
    #[test]
    fn url_percent_encodes_hostile_credentials() {
        let mut cfg = pg();
        cfg.pass = NASTY.to_string();
        cfg.user = "us@er:x".to_string();
        let url = cfg.connection_url();
        let rest = url.strip_prefix("postgres://").expect("scheme");
        let (userinfo, tail) = rest.rsplit_once('@').expect("one authority separator");
        assert_eq!(rest.matches('@').count(), 1, "{url}");
        assert_eq!(tail, "db.local:5432/testdb?sslmode=verify-full");
        let (u, p) = userinfo.split_once(':').expect("user:pass");
        assert_eq!(u, "us%40er%3Ax");
        assert!(
            p.chars()
                .all(|c| c.is_ascii_alphanumeric() || "-._~%".contains(c)),
            "{p}"
        );
        let opts = PgConnectOptions::from_str(&url).expect("parses");
        assert_eq!(opts.get_host(), "db.local");
        assert_eq!(opts.get_username(), "us@er:x");
        assert_eq!(format!("{:?}", opts.get_ssl_mode()), "VerifyFull");
    }

    #[test]
    fn typed_options_carry_fields_without_a_dsn() {
        let mut cfg = pg();
        cfg.host = "evil@host/x".to_string();
        cfg.pass = NASTY.to_string();
        let o = cfg.pg_connect_options().expect("options");
        assert_eq!(o.get_host(), "evil@host/x");
        assert_eq!(o.get_port(), 5432);
        assert_eq!(o.get_username(), "app");
        assert_eq!(o.get_database(), Some("testdb"));
    }

    #[test]
    fn url_ipv6_host_and_sqlite_forms() {
        let mut cfg = pg();
        cfg.host = "::1".to_string();
        assert!(cfg.connection_url().contains("@[::1]:5432/"));
        assert_eq!(
            sqlite("test.db").connection_url(),
            "sqlite://test.db?mode=rwc"
        );
        assert_eq!(
            sqlite("/tmp/a b?#.db").connection_url(),
            "sqlite:///tmp/a%20b%3F%23.db?mode=rwc"
        );
        assert_eq!(
            sqlite("sqlite::memory:").connection_url(),
            "sqlite::memory:"
        );
    }

    #[test]
    fn sqlite_options_variants() {
        let o = sqlite("x.db").sqlite_connect_options().expect("path");
        assert_eq!(o.get_filename().to_str(), Some("x.db"));
        assert!(sqlite("sqlite::memory:").sqlite_connect_options().is_ok());
        assert!(matches!(
            sqlite("sqlite://x?mode=bogus").sqlite_connect_options(),
            Err(DalError::Config(_))
        ));
    }

    // regression: TLS enforcement — default must be verify-full
    #[test]
    fn default_ssl_mode_is_verify_full() {
        assert_eq!(DbSslMode::default(), DbSslMode::VerifyFull);
        let cfg = from_json(json!({"type": "postgresql"})).expect("cfg");
        assert_eq!(cfg.ssl_mode, DbSslMode::VerifyFull);
        assert!(!cfg.allow_insecure_ssl);
        let o = cfg.pg_connect_options().expect("options");
        assert_eq!(format!("{:?}", o.get_ssl_mode()), "VerifyFull");
        assert!(cfg.connection_url().ends_with("sslmode=verify-full"));
    }

    #[test]
    fn insecure_modes_require_explicit_opt_in() {
        for m in ["disable", "prefer"] {
            let err = from_json(json!({"type": "postgresql", "sslmode": m})).expect_err("rejected");
            assert!(matches!(err, DalError::Config(ref s) if s.contains("DB_ALLOW_INSECURE_SSL")));
            let cfg =
                from_json(json!({"type": "postgresql", "sslmode": m, "allow_insecure_ssl": true}))
                    .expect("opt-in accepted");
            assert!(cfg.ssl_mode.is_insecure());
            let o = cfg.pg_connect_options().expect("options");
            assert_eq!(
                format!("{:?}", o.get_ssl_mode()),
                format!("{:?}", cfg.ssl_mode.to_pg())
            );
        }
        let mut c = pg();
        c.ssl_mode = DbSslMode::Disable;
        assert!(
            c.pg_connect_options().is_err(),
            "typed builder must also validate"
        );
    }

    #[test]
    fn ssl_modes_parse_and_map() {
        let all = [
            ("disable", PgSslMode::Disable),
            ("prefer", PgSslMode::Prefer),
            ("require", PgSslMode::Require),
            ("verify-ca", PgSslMode::VerifyCa),
            ("verify-full", PgSslMode::VerifyFull),
        ];
        for (s, want) in all {
            let cfg =
                from_json(json!({"type": "postgresql", "ssl_mode": s, "allow_insecure_ssl": true}))
                    .expect("parse");
            assert_eq!(cfg.ssl_mode.as_str(), s);
            assert_eq!(format!("{:?}", cfg.ssl_mode.to_pg()), format!("{want:?}"));
        }
        assert!(from_json(json!({"type": "postgresql", "sslmode": "bogus"})).is_err());
    }

    #[test]
    fn root_cert_is_applied_and_sqlite_skips_tls_validation() {
        let mut cfg = pg();
        cfg.ssl_root_cert = Some("/etc/ssl/ca.pem".to_string());
        assert!(cfg.pg_connect_options().is_ok());
        let mut s = sqlite("x.db");
        s.ssl_mode = DbSslMode::Disable;
        assert!(s.validate().is_ok());
        let mut v = pg();
        v.ssl_mode = DbSslMode::Require;
        assert!(v.validate().is_ok());
    }

    #[test]
    fn from_figment_defaults_and_errors() {
        let cfg = from_json(json!({"type": "sqlite"})).expect("defaults");
        assert_eq!(
            (cfg.host.as_str(), cfg.port, cfg.name.as_str()),
            ("localhost", 5432, "penguin")
        );
        assert_eq!(
            (
                cfg.user.as_str(),
                cfg.pool_size,
                cfg.max_retries,
                cfg.retry_delay
            ),
            ("penguin", 10, 5, 2)
        );
        assert!(matches!(from_json(json!({})), Err(DalError::Config(_))));
    }

    #[test]
    fn from_env_reads_db_prefix() {
        let _g = crate::ENV_LOCK.lock().unwrap_or_else(|p| p.into_inner());
        std::env::set_var("DB_TYPE", "sqlite");
        std::env::set_var("DB_NAME", "env.db");
        let cfg = DbConfig::from_env();
        std::env::remove_var("DB_TYPE");
        std::env::remove_var("DB_NAME");
        assert_eq!(cfg.expect("env").name, "env.db");
    }

    #[tokio::test]
    async fn sqlite_in_memory_connection_and_ping() {
        let cfg = sqlite(":memory:");
        let pool = connect_pool(&cfg).await.expect("connect sqlite memory");
        pool.ping().await.expect("ping sqlite memory");
        assert!(format!("{pool:?}").contains("Sqlite"));
    }

    #[tokio::test]
    async fn sqlite_file_pool_creates_database() {
        let dir = std::env::temp_dir().join(format!("penguin-dal-{}", std::process::id()));
        std::fs::create_dir_all(&dir).expect("mkdir");
        let path = dir.join("t.db");
        let pool = connect_sqlite_pool(&sqlite(path.to_str().expect("utf8")))
            .await
            .expect("pool");
        sqlx::query("SELECT 1").execute(&pool).await.expect("query");
        assert!(path.exists());
        drop(pool);
        let _ = std::fs::remove_dir_all(&dir);
    }

    #[tokio::test]
    async fn postgres_unreachable_exhausts_retries() {
        let port = {
            let l = std::net::TcpListener::bind("127.0.0.1:0").expect("bind");
            l.local_addr().expect("addr").port()
        };
        let mut cfg = pg();
        cfg.host = "127.0.0.1".to_string();
        cfg.port = port;
        cfg.max_retries = 2;
        cfg.ssl_mode = DbSslMode::Disable;
        cfg.allow_insecure_ssl = true;
        let err = connect_pg_pool_with_timeout(&cfg, Duration::from_millis(300))
            .await
            .expect_err("nothing listening");
        assert!(
            matches!(err, DalError::Exhausted { attempts: 2, .. }),
            "{err}"
        );
        assert!(!err.to_string().contains("secret"));
    }

    #[tokio::test]
    async fn postgres_zero_retries_reports_unknown() {
        let mut cfg = pg();
        cfg.max_retries = 0;
        let err = connect_pg_pool(&cfg).await.expect_err("no attempts");
        assert!(matches!(err, DalError::Exhausted { attempts: 0, .. }));
    }

    #[tokio::test]
    async fn postgres_rejects_insecure_config_before_connecting() {
        let mut cfg = pg();
        cfg.ssl_mode = DbSslMode::Prefer;
        assert!(matches!(
            connect_pg_pool(&cfg).await,
            Err(DalError::Config(_))
        ));
    }

    /// Needs a live PostgreSQL: set `DAL_TEST_PG_URL` (e.g. postgres://u:p@localhost/db?sslmode=disable).
    #[tokio::test]
    #[ignore = "requires a live PostgreSQL server (DAL_TEST_PG_URL)"]
    async fn postgres_live_connect_and_ping() {
        let url = std::env::var("DAL_TEST_PG_URL").expect("DAL_TEST_PG_URL");
        let pool = PgPoolOptions::new().connect(&url).await.expect("connect");
        DatabasePool::Postgres(pool).ping().await.expect("ping");
    }
}
