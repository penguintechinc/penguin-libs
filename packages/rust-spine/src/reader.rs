//! The grant-scoped, dedicated-connection stream reader (spec Sec4.7,
//! Sec5.2, Sec5.7). Reads ONLY the streams in its grant list — a request
//! for any other stream fails with `SpineError::StreamNotGranted`, even
//! if a consumer group exists there (spec Sec5.2's negative test).

use std::sync::Arc;

use redis::AsyncCommands;
use redis::streams::StreamReadOptions;

use crate::client::{Delivered, Grant, SpineClient, build_redis_client};
use crate::config::{SpineConfig, validate_block_timeout};
use crate::envelope::StageEnvelope;
use crate::error::SpineError;
use crate::metrics::SpineMetrics;
use crate::scope::Stage;

/// A dedicated-connection, grant-scoped `XREADGROUP` reader (spec
/// Sec5.7). Never shares its connection with [`SpineClient`]'s admin
/// traffic — both connection-separation rules are enforced by
/// construction, not convention.
#[derive(Clone)]
pub struct GroupReader {
    conn: redis::aio::MultiplexedConnection,
    grants: Vec<Grant>,
    app_id: String,
    consumer_id: String,
    stage: Stage,
    dlq: SpineClient,
    metrics: Arc<dyn SpineMetrics>,
    read_count: usize,
    block_ms: u64,
}

/// Manual, redacted `Debug`: `dlq: SpineClient` holds a `SpineConfig`
/// whose own derive prints `valkey_password`, so this shows only
/// non-secret identity fields rather than deriving through it.
impl std::fmt::Debug for GroupReader {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.debug_struct("GroupReader")
            .field("app_id", &self.app_id)
            .field("stage", &self.stage)
            .field("grants", &self.grants.len())
            .finish_non_exhaustive()
    }
}

impl GroupReader {
    /// Opens this reader's own dedicated connection (spec Sec5.7 rule 1)
    /// and validates the block-timeout invariant before ever attempting
    /// that connection — construction is refused, naming both values,
    /// when `SPINE_BLOCK_MS` is not strictly less than the connection's
    /// own socket timeout (`DRAIN_SOCKET_TIMEOUT_S`). The signature
    /// differs from the spec's illustrative `new(grants, app_id,
    /// consumer_id) -> Self` sketch: `connect` is fallible because
    /// construction does real I/O, and `dlq`/`stage` exist so an
    /// unparseable entry (which can never become a `Delivered`) still
    /// reaches its own stage's DLQ.
    pub async fn connect(
        cfg: &SpineConfig,
        grants: Vec<Grant>,
        app_id: String,
        stage: Stage,
        dlq: SpineClient,
        metrics: Arc<dyn SpineMetrics>,
    ) -> Result<Self, SpineError> {
        validate_block_timeout("SPINE_BLOCK_MS", cfg.block_ms, cfg.drain_socket_timeout_s)?;

        let client = build_redis_client(cfg)?;

        // Sec5.7 rule 1: this connection's response timeout is the
        // dedicated blocking-read socket timeout, strictly greater than
        // SPINE_BLOCK_MS (validated above). Sec5.7 rule 2: this
        // connection is never shared with `dlq`'s admin traffic — it is
        // an entirely separate connection this GroupReader alone owns.
        let async_cfg = redis::AsyncConnectionConfig::new().set_response_timeout(Some(
            std::time::Duration::from_secs(cfg.drain_socket_timeout_s),
        ));
        let conn = client
            .get_multiplexed_async_connection_with_config(&async_cfg)
            .await?;

        Ok(GroupReader {
            conn,
            grants,
            app_id,
            consumer_id: cfg.consumer_id.clone(),
            stage,
            dlq,
            metrics,
            read_count: cfg.read_count.max(1) as usize,
            block_ms: cfg.block_ms,
        })
    }

    /// Reads up to `SPINE_READ_COUNT` entries from every granted stream,
    /// blocking up to `SPINE_BLOCK_MS` when nothing is available (spec
    /// Sec5.3). An entry whose `env` field fails strict deserialization
    /// is dead-lettered immediately (spec Sec5.5's `envelope_invalid`,
    /// the one DLQ reason that can never produce a `Delivered`) rather
    /// than included in the returned batch.
    pub async fn read(&mut self) -> Result<Vec<Delivered>, SpineError> {
        if self.grants.is_empty() {
            return Ok(Vec::new());
        }
        let streams: Vec<&str> = self.grants.iter().map(|g| g.stream.as_str()).collect();
        let ids: Vec<&str> = streams.iter().map(|_| ">").collect();

        let opts = StreamReadOptions::default()
            .group(&self.app_id, &self.consumer_id)
            .count(self.read_count)
            .block(self.block_ms as usize);

        let reply: Option<redis::streams::StreamReadReply> =
            self.conn.xread_options(&streams, &ids, &opts).await?;

        let mut delivered = Vec::new();
        let Some(reply) = reply else {
            return Ok(delivered);
        };
        for key in reply.keys {
            for entry in key.ids {
                let env_field: Option<String> = entry
                    .map
                    .get("env")
                    .and_then(|v| redis::from_redis_value_ref::<String>(v).ok());
                match env_field
                    .as_deref()
                    .and_then(|s| serde_json::from_str::<StageEnvelope>(s).ok())
                {
                    Some(env) => {
                        delivered.push(Delivered {
                            stream: key.key.clone(),
                            entry_id: entry.id,
                            env,
                            deliveries: 1,
                        });
                    }
                    None => {
                        self.dlq
                            .dead_letter_unparseable(
                                self.stage,
                                &key.key,
                                &self.app_id,
                                &entry.id,
                                1,
                                env_field.as_deref().unwrap_or(""),
                            )
                            .await?;
                        self.metrics
                            .consumer_skipped(&self.app_id, "envelope_invalid");
                    }
                }
            }
        }
        Ok(delivered)
    }

    /// Refuses a stream outside this reader's grant list (spec Sec5.2's
    /// negative test): the stage is the enforcement point, and a
    /// consumer group existing on a stream is not itself authority.
    pub fn ensure_granted(&self, stream: &str) -> Result<(), SpineError> {
        if self.grants.iter().any(|g| g.stream == stream) {
            Ok(())
        } else {
            Err(SpineError::StreamNotGranted {
                stream: stream.to_string(),
            })
        }
    }
}
