# penguin-dal

PenguinTech Data Access Layer (DAL) for Rust — unified database pools (PostgreSQL/SQLite via `sqlx`), S3/MinIO object storage, cache, and streaming contracts.

Direct Rust replacement for [`go-dal`](../go-dal) and [`python-dal`](../python-dal).

## Features

- `sql` (default): Resilient PostgreSQL and SQLite connection pool factory with exponential backoff and `DB_*` environment parsing.
- `storage` (default): S3 and MinIO object storage client with path-style addressing and `S3_*` environment parsing.

## Usage

```rust
use penguin_dal::{DbConfig, DbType, connect_pool};

#[tokio::main]
async fn main() -> Result<(), Box<dyn std::error::Error>> {
    let cfg = DbConfig::from_env()?;
    let pool = connect_pool(&cfg).await?;
    pool.ping().await?;
    Ok(())
}
```
