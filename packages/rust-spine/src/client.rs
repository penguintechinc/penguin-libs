//! The Valkey Streams admin/write client (spec Sec4.7): `XADD`, group
//! lifecycle, `XACK`, `XAUTOCLAIM`, the DLQ, and `XINFO GROUPS`.
//! Non-blocking traffic only — a blocking `XREADGROUP` read never runs
//! through this type (spec Sec5.7 rule 2); see [`crate::GroupReader`].

use std::sync::Arc;

use redis::AsyncCommands;
use redis::streams::StreamMaxlen;

use crate::config::{ProbeClass, SpineConfig, ensure_crypto_provider_installed, probe_valkey};
use crate::dlq::{DlqError, DlqErrorDetail, DlqErrorKind, DlqRecord};
use crate::envelope::StageEnvelope;
use crate::error::SpineError;
use crate::metrics::SpineMetrics;
use crate::scope::{Stage, dlq_key, parse_scope_from_key};

/// One stream a bundle is permitted to read, resolved by hub-api from its
/// `consumes` request (spec Sec5.2).
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Grant {
    /// The granted stream key.
    pub stream: String,
    /// The platform the stream belongs to.
    pub platform: String,
    /// The ingest source id the stream belongs to.
    pub source_id: String,
}

/// One entry successfully read and deserialized from a granted stream.
#[derive(Debug, Clone)]
pub struct Delivered {
    /// The stream the entry was read from.
    pub stream: String,
    /// The Valkey stream entry id.
    pub entry_id: String,
    /// The deserialized envelope.
    pub env: StageEnvelope,
    /// The delivery count at read time (`1` for a first delivery).
    pub deliveries: u64,
    /// The consumer group this entry was actually delivered under
    /// (`XREADGROUP`/`XAUTOCLAIM`'s group argument — [`crate::GroupReader::read`]
    /// and [`SpineClient::claim_stale`] are the only producers of a
    /// `Delivered`, and both set this to the group they read with). May
    /// differ from `env.app_id`: that field is per-message routing
    /// metadata describing which bundle the envelope is destined for,
    /// while this is the group that owns the entry's pending-entries-list
    /// slot. They coincide for svc_action's per-bundle action streams but
    /// not for svc_process's shared ingest-source streams — this struct
    /// carries both so [`SpineClient::dead_letter`] can `XACK` under the
    /// right one instead of guessing from `env.app_id`.
    pub group: String,
}

/// Per-group stats from `XINFO GROUPS` (spec Sec5.6).
#[derive(Debug, Clone)]
pub struct GroupStats {
    /// The consumer group name (equals the bundle's `app_id`).
    pub app_id: String,
    /// The stream the group belongs to.
    pub stream: String,
    /// Undelivered entries for the group, when the server reports one.
    pub lag: Option<u64>,
    /// The group's pending-entries-list size — the stuck-bundle signal.
    pub pending: u64,
}

/// Recovers `(platform, source_id)` from a source-stream key
/// (`...:src:{platform}:{source_id}:events`) for metric labeling. Returns
/// `None` for a key with no `:src:` segment (e.g. an action or DLQ key) —
/// callers skip the metric rather than mislabeling it.
fn parse_platform_and_source_id(stream: &str) -> Option<(String, String)> {
    let idx = stream.find(":src:")?;
    let rest = &stream[idx + ":src:".len()..];
    let mut parts = rest.split(':');
    let platform = parts.next()?.to_string();
    let source_id = parts.next()?.to_string();
    Some((platform, source_id))
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

/// Builds a `redis::Client` for `cfg`'s transport, installing the
/// process-level rustls `CryptoProvider` first when TLS is enabled. Shared
/// by [`SpineClient::connect`] and `GroupReader::connect`, neither of
/// which may assume the other has already run.
pub(crate) fn build_redis_client(cfg: &SpineConfig) -> Result<redis::Client, SpineError> {
    let info = build_connection_info(cfg)?;
    if cfg.security_transport_tls {
        ensure_crypto_provider_installed();
        let root_cert = std::fs::read(&cfg.valkey_ca_file).ok();
        let client = redis::Client::build_with_tls(
            info,
            redis::TlsCertificates {
                client_tls: None,
                root_cert,
            },
        )?;
        Ok(client)
    } else {
        Ok(redis::Client::open(info)?)
    }
}

/// The spine's admin/write client. Backed by one
/// `redis::aio::MultiplexedConnection`, which already serves concurrent
/// callers safely over a single socket — no separate pool crate needed
/// (`deadpool-redis`'s `Manager` cannot honor a custom `VALKEY_CA_FILE`,
/// `redis::Client::build_with_tls` can). `Clone` is cheap: a
/// `MultiplexedConnection` clone plus an `Arc` clone.
#[derive(Clone)]
pub struct SpineClient {
    conn: redis::aio::MultiplexedConnection,
    cfg: SpineConfig,
    metrics: Arc<dyn SpineMetrics>,
}

/// Manual, redacted `Debug`: `SpineConfig`'s own derive prints
/// `valkey_password`, so a naive `#[derive(Debug)]` here would let a
/// stray `{:?}` log a credential. Only the (non-secret) endpoint URL is
/// shown.
impl std::fmt::Debug for SpineClient {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.debug_struct("SpineClient")
            .field("valkey_url", &self.cfg.valkey_url)
            .finish_non_exhaustive()
    }
}

impl SpineClient {
    /// Runs the Sec12.6 startup probe, then connects to Valkey per `cfg`
    /// (TLS/auth per Sec11.6.1). Refuses to return a client for a
    /// dependency that never became reachable.
    pub async fn connect(
        cfg: SpineConfig,
        metrics: Arc<dyn SpineMetrics>,
    ) -> Result<Self, SpineError> {
        cfg.validate()?;

        let probe = probe_valkey(
            &cfg,
            std::time::Duration::from_millis(5_000),
            3,
            std::time::Duration::from_secs(1),
        )
        .await;
        metrics.insecure_transport("valkey", "tls", !cfg.security_transport_tls);
        metrics.insecure_transport("valkey", "auth", !cfg.security_transport_auth);
        if probe.class != ProbeClass::Ok {
            return Err(SpineError::Config(format!(
                "valkey startup probe failed ({}): {}",
                probe.class.as_str(),
                probe.message
            )));
        }

        let client = build_redis_client(&cfg)?;
        let async_cfg = redis::AsyncConnectionConfig::new().set_response_timeout(Some(
            std::time::Duration::from_secs(cfg.drain_socket_timeout_s),
        ));
        let conn = client
            .get_multiplexed_async_connection_with_config(&async_cfg)
            .await?;

        Ok(SpineClient { conn, cfg, metrics })
    }

    /// Writes one envelope to `stream` with approximate `MAXLEN` trimming
    /// (spec Sec5.1): `XADD {stream} MAXLEN ~ {maxlen} * env {json}`.
    pub async fn append(&self, stream: &str, env: &StageEnvelope) -> Result<String, SpineError> {
        let json = serde_json::to_string(env)?;
        let mut conn = self.conn.clone();
        let maxlen = StreamMaxlen::Approx(self.cfg.stream_maxlen as usize);
        let id: Option<String> = conn
            .xadd_maxlen(stream, maxlen, "*", &[("env", json.as_str())])
            .await?;
        let id = id.ok_or_else(|| {
            SpineError::Config(format!("XADD to {stream:?} returned no entry id"))
        })?;

        // MAXLEN ~ is approximate and XADD's reply carries no trim count;
        // a stream sitting at-or-above its approximate cap right after a
        // write is the cheap, honest proxy for "trimming is happening
        // here" (spec Sec5.1's own test only asserts trimming happened at
        // all, never an exact count).
        let len: usize = conn.xlen(stream).await.unwrap_or(0);
        if len as u64 >= self.cfg.stream_maxlen {
            self.metrics.stream_trimmed(stream);
        }

        if let Some((platform, source_id)) = parse_platform_and_source_id(stream) {
            self.metrics.stream_event_written(&platform, &source_id);
        }

        Ok(id)
    }

    /// Creates the consumer group `app_id` on `stream` starting from `$`
    /// (new entries only), `MKSTREAM`, `BUSYGROUP`-tolerant (spec Sec5.2)
    /// — idempotent, safe to call on every distribution refresh so a
    /// group lost to a Valkey restore self-heals without operator action.
    pub async fn ensure_group(&self, stream: &str, app_id: &str) -> Result<(), SpineError> {
        let mut conn = self.conn.clone();
        let result: redis::RedisResult<()> = conn.xgroup_create_mkstream(stream, app_id, "$").await;
        match result {
            Ok(()) => Ok(()),
            Err(e) if e.code() == Some("BUSYGROUP") => Ok(()),
            Err(e) => Err(e.into()),
        }
    }

    /// Destroys the consumer group `app_id` on `stream` (`XGROUP
    /// DESTROY`), at deactivation or grant revocation (spec Sec5.2).
    pub async fn destroy_group(&self, stream: &str, app_id: &str) -> Result<(), SpineError> {
        let mut conn = self.conn.clone();
        let _removed: bool = conn.xgroup_destroy(stream, app_id).await?;
        Ok(())
    }

    /// Acknowledges one delivered entry (`XACK`), removing it from the
    /// group's pending-entries list (spec Sec5.3).
    pub async fn ack(&self, d: &Delivered, app_id: &str) -> Result<(), SpineError> {
        let mut conn = self.conn.clone();
        let _count: usize = conn.xack(&d.stream, app_id, &[d.entry_id.as_str()]).await?;
        Ok(())
    }

    /// Dead-letters one previously-delivered entry (spec Sec5.5/Sec6.3):
    /// `XADD waddles:dlq:{stage} MAXLEN ~ {dlq_maxlen} * rec {json}`, then
    /// `XACK`s the source entry so it stops being redelivered. The DLQ
    /// stage segment comes from `d.env.stage` (already validated to
    /// `process`/`action`), never from a caller-chosen `Stage`. The `XACK`
    /// (and the record's `group` field) use `d.group` — the consumer
    /// group [`crate::GroupReader::read`]/`claim_stale` actually delivered
    /// this entry under — never `d.env.app_id`: those coincide for
    /// svc_action's per-bundle action streams but not svc_process's
    /// shared ingest-source streams, where acking under `env.app_id`
    /// would target a group that never read the entry and leave it stuck
    /// in the real group's PEL forever.
    pub async fn dead_letter(&self, d: &Delivered, err: &DlqError) -> Result<(), SpineError> {
        let stage = Stage::parse(&d.env.stage)?;
        let raw = serde_json::to_string(&d.env)?;
        let record = DlqRecord {
            schema_version: 1,
            stage: stage.as_str().to_string(),
            key: d.stream.clone(),
            entry_id: d.entry_id.clone(),
            group: d.group.clone(),
            tenant: d.env.tenant.clone(),
            community: d.env.community.clone(),
            app_id: d.env.app_id.clone(),
            workstream_id: Some(d.env.workstream_id.clone()),
            artifact_digest: err.artifact_digest.clone(),
            consumer_id: err.consumer_id.clone(),
            deliveries: d.deliveries,
            failed_at: chrono::Utc::now().to_rfc3339_opts(chrono::SecondsFormat::Millis, true),
            error: DlqErrorDetail {
                kind: err.kind,
                code: err.code.clone(),
                message: err.message.clone(),
                detail: err.detail.clone(),
            },
            trace: d.env.trace.clone(),
            raw,
        };
        self.dead_letter_raw(stage, &record, &d.stream, &d.group, &d.entry_id)
            .await
    }

    /// Shared by `dead_letter` and (via `pub(crate)` — see
    /// `GroupReader::read`) the one DLQ path that never has a `Delivered`
    /// to hand to the public `dead_letter` method.
    pub(crate) async fn dead_letter_raw(
        &self,
        stage: Stage,
        record: &DlqRecord,
        source_stream: &str,
        group: &str,
        entry_id: &str,
    ) -> Result<(), SpineError> {
        let key = dlq_key(stage);
        let json = serde_json::to_string(record)?;
        let mut conn = self.conn.clone();
        let maxlen = StreamMaxlen::Approx(self.cfg.dlq_maxlen as usize);
        let _id: Option<String> = conn
            .xadd_maxlen(&key, maxlen, "*", &[("rec", json.as_str())])
            .await?;
        let _acked: usize = conn.xack(source_stream, group, &[entry_id]).await?;
        self.metrics
            .dlq_written(stage.as_str(), record.error.kind.as_str());
        Ok(())
    }

    /// `pub(crate)`: [`crate::GroupReader::read`] calls this directly for
    /// an entry whose `env` field fails to parse — the one DLQ reason
    /// that, by construction, can never produce a `Delivered` (spec
    /// Sec5.5).
    pub(crate) async fn dead_letter_unparseable(
        &self,
        stage: Stage,
        stream: &str,
        app_id: &str,
        entry_id: &str,
        deliveries: u64,
        raw_field: &str,
    ) -> Result<(), SpineError> {
        let (tenant, community) =
            parse_scope_from_key(stream).unwrap_or_else(|| ("unknown".to_string(), None));
        let record = DlqRecord {
            schema_version: 1,
            stage: stage.as_str().to_string(),
            key: stream.to_string(),
            entry_id: entry_id.to_string(),
            group: app_id.to_string(),
            tenant,
            community,
            app_id: app_id.to_string(),
            workstream_id: None,
            artifact_digest: None,
            consumer_id: self.cfg.consumer_id.clone(),
            deliveries,
            failed_at: chrono::Utc::now().to_rfc3339_opts(chrono::SecondsFormat::Millis, true),
            error: DlqErrorDetail {
                kind: DlqErrorKind::EnvelopeInvalid,
                code: "ENVELOPE_INVALID".to_string(),
                message: "strict deserialization failed".to_string(),
                detail: None,
            },
            trace: None,
            raw: raw_field.to_string(),
        };
        self.dead_letter_raw(stage, &record, stream, app_id, entry_id)
            .await
    }

    /// Reclaims entries idle longer than `SPINE_CLAIM_IDLE_MS` on
    /// `stream`'s `app_id` group (`XAUTOCLAIM`, spec Sec5.4). An entry
    /// whose delivery count has already reached `SPINE_MAX_DELIVERIES` is
    /// dead-lettered and `XACK`ed here rather than returned for another
    /// attempt; an entry whose `env` field fails to parse is also
    /// dead-lettered here, recovering tenant/community from the stream
    /// key itself rather than trusting an unparsed payload (spec
    /// Sec5.5/Sec3.3/Sec11.8).
    pub async fn claim_stale(
        &self,
        stream: &str,
        app_id: &str,
        stage: Stage,
    ) -> Result<Vec<Delivered>, SpineError> {
        let mut conn = self.conn.clone();
        let count = self.cfg.read_count.max(1) as usize;
        let opts = redis::streams::StreamAutoClaimOptions::default().count(count);
        let reply: redis::streams::StreamAutoClaimReply = conn
            .xautoclaim_options(
                stream,
                app_id,
                &self.cfg.consumer_id,
                self.cfg.claim_idle_ms as usize,
                "0-0",
                opts,
            )
            .await?;

        if reply.claimed.is_empty() {
            return Ok(Vec::new());
        }

        // redis 1.7.0's `StreamAutoClaimReply` parser always leaves
        // `StreamId::delivered_count` as `None` for XAUTOCLAIM's "full"
        // response shape (its `FromRedisValue` impl hard-codes it) --
        // XPENDING's extended form is the only reliable source for a
        // claimed entry's true delivery count, so fetch it in a
        // follow-up call bounded to the ids we just claimed.
        let first_id = reply.claimed[0].id.clone();
        let last_id = reply.claimed[reply.claimed.len() - 1].id.clone();
        let pending: redis::streams::StreamPendingCountReply = conn
            .xpending_count(stream, app_id, first_id, last_id, 10_000usize)
            .await?;
        let delivery_counts: std::collections::HashMap<String, u64> = pending
            .ids
            .into_iter()
            .map(|p| (p.id, p.times_delivered as u64))
            .collect();

        let mut delivered = Vec::new();
        for entry in reply.claimed {
            let deliveries = delivery_counts.get(&entry.id).copied().unwrap_or(1);
            let env_field: Option<String> = entry
                .map
                .get("env")
                .and_then(|v| redis::from_redis_value_ref::<String>(v).ok());
            let parsed: Option<StageEnvelope> = env_field
                .as_deref()
                .and_then(|s| serde_json::from_str(s).ok());

            match parsed {
                Some(env) if deliveries < self.cfg.max_deliveries as u64 => {
                    self.metrics.stream_claimed(app_id);
                    delivered.push(Delivered {
                        stream: stream.to_string(),
                        entry_id: entry.id,
                        env,
                        deliveries,
                        group: app_id.to_string(),
                    });
                }
                Some(env) => {
                    let err = DlqError {
                        kind: DlqErrorKind::MaxDeliveries,
                        code: "MAX_DELIVERIES".to_string(),
                        message: format!(
                            "delivery count {deliveries} reached SPINE_MAX_DELIVERIES"
                        ),
                        detail: None,
                        artifact_digest: None,
                        consumer_id: self.cfg.consumer_id.clone(),
                    };
                    let d = Delivered {
                        stream: stream.to_string(),
                        entry_id: entry.id,
                        env,
                        deliveries,
                        group: app_id.to_string(),
                    };
                    self.dead_letter(&d, &err).await?;
                }
                None => {
                    self.dead_letter_unparseable(
                        stage,
                        stream,
                        app_id,
                        &entry.id,
                        deliveries,
                        env_field.as_deref().unwrap_or(""),
                    )
                    .await?;
                }
            }
        }
        Ok(delivered)
    }

    /// Per-group stats from `XINFO GROUPS` (spec Sec5.6), also recorded
    /// via [`crate::SpineMetrics`].
    pub async fn group_stats(&self, stream: &str) -> Result<Vec<GroupStats>, SpineError> {
        let mut conn = self.conn.clone();
        let reply: redis::streams::StreamInfoGroupsReply = conn.xinfo_groups(stream).await?;
        let mut out = Vec::new();
        for g in reply.groups {
            let lag = g.lag.map(|l| l as u64);
            let pending = g.pending as u64;
            self.metrics.group_lag(&g.name, stream, lag);
            self.metrics.group_pending(&g.name, stream, pending);
            out.push(GroupStats {
                app_id: g.name,
                stream: stream.to_string(),
                lag,
                pending,
            });
        }
        Ok(out)
    }
}
