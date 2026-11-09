//! Relational database connection pooling and configuration (PostgreSQL & SQLite via `sqlx`).

use std::time::Duration;

use figment::Figment;
use figment::providers::Env;
use serde::Deserialize;
use sqlx::postgres::PgPoolOptions;
use sqlx::sqlite::SqlitePoolOptions;
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

/// Standard database connection settings read from `DB_*` environment variables.
#[derive(Debug, Clone, Deserialize)]
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
    /// Database password (`DB_PASS`).
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

impl DbConfig {
    /// Loads configuration from `DB_*` prefixed environment variables via `figment`.
    pub fn from_env() -> Result<Self, DalError> {
        Figment::new()
            .merge(Env::prefixed("DB_"))
            .extract()
            .map_err(|e| DalError::Config(e.to_string()))
    }

    /// Renders the database connection string for this backend.
    pub fn connection_url(&self) -> String {
        match self.db_type {
            DbType::Postgresql => format!(
                "postgres://{}:{}@{}:{}/{}",
                self.user, self.pass, self.host, self.port, self.name
            ),
            DbType::Sqlite => {
                if self.name.starts_with("sqlite:") {
                    self.name.clone()
                } else {
                    format!("sqlite://{}?mode=rwc", self.name)
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
    let url = cfg.connection_url();
    let mut delay = Duration::from_secs(cfg.retry_delay);
    let mut last_error = None;

    for attempt in 1..=cfg.max_retries {
        tracing::info!(attempt, max_retries = cfg.max_retries, "connecting to PostgreSQL");
        match PgPoolOptions::new()
            .max_connections(cfg.pool_size)
            .connect(&url)
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
    let url = cfg.connection_url();
    SqlitePoolOptions::new()
        .max_connections(cfg.pool_size)
        .connect(&url)
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

    #[test]
    fn renders_postgres_and_sqlite_urls() {
        let pg_cfg = DbConfig {
            db_type: DbType::Postgresql,
            host: "db.local".to_string(),
            port: 5432,
            name: "testdb".to_string(),
            user: "app".to_string(),
            pass: "secret".to_string(),
            pool_size: 5,
            max_retries: 3,
            retry_delay: 1,
        };
        assert_eq!(
            pg_cfg.connection_url(),
            "postgres://app:secret@db.local:5432/testdb"
        );

        let sqlite_cfg = DbConfig {
            db_type: DbType::Sqlite,
            name: "test.db".to_string(),
            ..pg_cfg
        };
        assert_eq!(sqlite_cfg.connection_url(), "sqlite://test.db?mode=rwc");
    }

    #[tokio::test]
    async fn sqlite_in_memory_connection_and_ping() {
        let cfg = DbConfig {
            db_type: DbType::Sqlite,
            host: "".to_string(),
            port: 0,
            name: ":memory:".to_string(),
            user: "".to_string(),
            pass: "".to_string(),
            pool_size: 1,
            max_retries: 1,
            retry_delay: 0,
        };

        let pool = connect_pool(&cfg).await.expect("connect sqlite memory");
        pool.ping().await.expect("ping sqlite memory");
    }
}
