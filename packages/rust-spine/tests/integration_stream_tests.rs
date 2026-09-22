#![allow(clippy::unwrap_used, clippy::panic)]
//! Integration tests against the pinned Valkey container (spec Sec14.2).
//! Run via `make test-integration-spine`.

use penguin_spine::{
    Delivered, DlqError, DlqErrorKind, NoopMetrics, SpineClient, SpineConfig, Stage,
};
use redis::AsyncCommands;
use std::collections::HashSet;
use std::sync::Arc;

fn unique_stream(label: &str) -> String {
    format!(
        "waddles:t:acme:c:main:src:twitch:{label}-{}:events",
        uuid::Uuid::new_v4()
    )
}

async fn test_client() -> SpineClient {
    let cfg = SpineConfig::from_env()
        .expect("SpineConfig::from_env (run via make test-integration-spine)");
    SpineClient::connect(cfg, Arc::new(NoopMetrics))
        .await
        .expect("SpineClient::connect")
}

fn sample_envelope() -> penguin_spine::StageEnvelope {
    let json = serde_json::json!({
        "schema_version": 2,
        "tenant": "acme",
        "community": "main",
        "app_id": "waddles.bot.commands.default",
        "stage": "process",
        "event": {
            "platform": "twitch",
            "event_type": "chat.message",
            "actor": "some_user",
            "payload": {"text": "hello"},
            "occurred_at": "2026-09-14T12:00:00.000Z"
        },
        "ts": "2026-09-14T12:00:00.123Z",
        "target_app_id": null,
        "workstream_id": uuid::Uuid::new_v4().to_string(),
        "event_id": uuid::Uuid::new_v4().to_string(),
        "session_id": null,
        "trace": null,
        "binding": {
            "kid": "2026-09",
            "mac": "9f86d081884c7d659a2feaa0c55ad015a3bf4f1b2b0b822cd15d6c15b0f00a08"
        }
    });
    serde_json::from_value(json).unwrap()
}

async fn raw_admin_connection() -> redis::aio::MultiplexedConnection {
    let url = std::env::var("VALKEY_URL").unwrap();
    let username = std::env::var("VALKEY_USERNAME").unwrap();
    let password = std::env::var("VALKEY_PASSWORD").unwrap();
    let ca_file = std::env::var("VALKEY_CA_FILE").unwrap();
    let root_cert = std::fs::read(&ca_file).unwrap();
    let base: redis::ConnectionInfo =
        redis::IntoConnectionInfo::into_connection_info(url.as_str()).unwrap();
    let redis_settings = base
        .redis_settings()
        .clone()
        .set_username(&username)
        .set_password(&password);
    let info = base.set_redis_settings(redis_settings);
    let client = redis::Client::build_with_tls(
        info,
        redis::TlsCertificates {
            client_tls: None,
            root_cert: Some(root_cert),
        },
    )
    .unwrap();
    client.get_multiplexed_async_connection().await.unwrap()
}

async fn read_one_via_xreadgroup(
    stream: &str,
    app_id: &str,
    consumer: &str,
) -> (String, penguin_spine::StageEnvelope) {
    let mut conn = raw_admin_connection().await;
    let opts = redis::streams::StreamReadOptions::default()
        .group(app_id, consumer)
        .count(1);
    let reply: redis::streams::StreamReadReply =
        conn.xread_options(&[stream], &[">"], &opts).await.unwrap();
    let key = reply
        .keys
        .into_iter()
        .next()
        .expect("expected one stream key in the reply");
    let id_entry = key.ids.into_iter().next().expect("expected one entry");
    let env_field: String = redis::from_redis_value_ref(id_entry.map.get("env").unwrap()).unwrap();
    let env: penguin_spine::StageEnvelope = serde_json::from_str(&env_field).unwrap();
    (id_entry.id, env)
}

#[tokio::test]
async fn append_writes_and_returns_an_entry_id() {
    let client = test_client().await;
    let stream = unique_stream("append");
    let id = client.append(&stream, &sample_envelope()).await.unwrap();
    assert!(
        id.contains('-'),
        "a Valkey stream entry id looks like {{ms}}-{{seq}}, got {id:?}"
    );
}

#[tokio::test]
async fn ensure_group_creates_and_is_busygroup_tolerant() {
    let client = test_client().await;
    let stream = unique_stream("ensure-group");
    client.append(&stream, &sample_envelope()).await.unwrap();

    client
        .ensure_group(&stream, "waddles.bot.commands.default")
        .await
        .unwrap();
    // A second call against the same group must not error.
    client
        .ensure_group(&stream, "waddles.bot.commands.default")
        .await
        .unwrap();

    let mut conn = raw_admin_connection().await;
    let groups: redis::streams::StreamInfoGroupsReply = redis::cmd("XINFO")
        .arg("GROUPS")
        .arg(&stream)
        .query_async(&mut conn)
        .await
        .unwrap();
    assert!(
        groups
            .groups
            .iter()
            .any(|g| g.name == "waddles.bot.commands.default")
    );
}

#[tokio::test]
async fn destroy_group_removes_a_created_group() {
    let client = test_client().await;
    let stream = unique_stream("destroy-group");
    client.append(&stream, &sample_envelope()).await.unwrap();
    client
        .ensure_group(&stream, "waddles.bot.commands.default")
        .await
        .unwrap();

    client
        .destroy_group(&stream, "waddles.bot.commands.default")
        .await
        .unwrap();

    let mut conn = raw_admin_connection().await;
    let groups: redis::streams::StreamInfoGroupsReply = redis::cmd("XINFO")
        .arg("GROUPS")
        .arg(&stream)
        .query_async(&mut conn)
        .await
        .unwrap();
    assert!(
        !groups
            .groups
            .iter()
            .any(|g| g.name == "waddles.bot.commands.default"),
        "destroy_group must actually remove the consumer group"
    );
}

#[tokio::test]
async fn ack_removes_an_entry_from_the_pending_entries_list() {
    let client = test_client().await;
    let stream = unique_stream("ack");
    let app_id = "waddles.bot.commands.default";
    // Group must exist BEFORE the write: XGROUP CREATE ... $ starts the
    // group's cursor at "the last entry in the stream right now", so an
    // entry appended beforehand would be treated as already-seen and
    // never show up on a `>` read.
    client.ensure_group(&stream, app_id).await.unwrap();
    client.append(&stream, &sample_envelope()).await.unwrap();
    let (entry_id, env) = read_one_via_xreadgroup(&stream, app_id, "consumer-1").await;

    let d = Delivered {
        stream: stream.clone(),
        entry_id: entry_id.clone(),
        env,
        deliveries: 1,
    };
    client.ack(&d, app_id).await.unwrap();

    let stats = client.group_stats(&stream).await.unwrap();
    let group = stats.iter().find(|g| g.app_id == app_id).unwrap();
    assert_eq!(
        group.pending, 0,
        "acked entry must leave the group's PEL empty"
    );
}

#[tokio::test]
async fn claim_stale_recovers_an_unacked_entry_after_the_idle_window() {
    let client = test_client().await;
    let stream = unique_stream("claim-stale");
    let app_id = "waddles.bot.commands.default";
    // Group must exist BEFORE the write -- see the identical note in
    // ack_removes_an_entry_from_the_pending_entries_list.
    client.ensure_group(&stream, app_id).await.unwrap();
    client.append(&stream, &sample_envelope()).await.unwrap();
    // A first read leaves the entry pending (never acked, simulating a
    // consumer crash between read and ack).
    let _ = read_one_via_xreadgroup(&stream, app_id, "dead-consumer").await;

    // SPINE_CLAIM_IDLE_MS defaults to 30000; force it to 0 for this test
    // via a fresh client pointed at the same Valkey.
    let mut cfg = SpineConfig::from_env().unwrap();
    cfg.claim_idle_ms = 0;
    let claiming_client = SpineClient::connect(cfg, Arc::new(NoopMetrics))
        .await
        .unwrap();

    let claimed = claiming_client
        .claim_stale(&stream, app_id, Stage::Process)
        .await
        .unwrap();
    assert_eq!(claimed.len(), 1, "expected exactly one recovered entry");
    // Delivery count 2: the first XREADGROUP delivery, plus this
    // XAUTOCLAIM reclaim -- XAUTOCLAIM increments the delivery counter
    // the same way XCLAIM does, unless JUSTID is used (it isn't here).
    assert_eq!(claimed[0].deliveries, 2);

    claiming_client.ack(&claimed[0], app_id).await.unwrap();
    let stats = claiming_client.group_stats(&stream).await.unwrap();
    let group = stats.iter().find(|g| g.app_id == app_id).unwrap();
    assert_eq!(
        group.pending, 0,
        "PEL must be empty after the recovered entry is acked"
    );
}

#[tokio::test]
async fn fan_in_one_write_is_observed_by_every_group_exactly_once() {
    let client = test_client().await;
    let stream = unique_stream("fan-in");
    client.ensure_group(&stream, "app-a").await.unwrap();
    client.ensure_group(&stream, "app-b").await.unwrap();
    client.append(&stream, &sample_envelope()).await.unwrap();

    let (id_a, env_a) = read_one_via_xreadgroup(&stream, "app-a", "consumer-a").await;
    let (id_b, env_b) = read_one_via_xreadgroup(&stream, "app-b", "consumer-b").await;
    assert_eq!(
        id_a, id_b,
        "both groups must see the same entry id from one write"
    );

    client
        .ack(
            &Delivered {
                stream: stream.clone(),
                entry_id: id_a,
                env: env_a,
                deliveries: 1,
            },
            "app-a",
        )
        .await
        .unwrap();
    client
        .ack(
            &Delivered {
                stream: stream.clone(),
                entry_id: id_b,
                env: env_b,
                deliveries: 1,
            },
            "app-b",
        )
        .await
        .unwrap();

    let stats = client.group_stats(&stream).await.unwrap();
    assert!(
        stats.iter().all(|g| g.pending == 0),
        "both groups' PELs must be empty after acking"
    );
}

#[tokio::test]
async fn group_isolation_a_stuck_group_does_not_affect_a_healthy_group() {
    let client = test_client().await;
    let stream = unique_stream("group-isolation");
    client.ensure_group(&stream, "healthy-app").await.unwrap();
    client.ensure_group(&stream, "stuck-app").await.unwrap();
    client.append(&stream, &sample_envelope()).await.unwrap();

    // The "stuck" group reads but never acks.
    let _ = read_one_via_xreadgroup(&stream, "stuck-app", "stuck-consumer").await;

    // The healthy group reads and acks normally on the SAME stream.
    let (entry_id, env) = read_one_via_xreadgroup(&stream, "healthy-app", "healthy-consumer").await;
    client
        .ack(
            &Delivered {
                stream: stream.clone(),
                entry_id,
                env,
                deliveries: 1,
            },
            "healthy-app",
        )
        .await
        .unwrap();

    let stats = client.group_stats(&stream).await.unwrap();
    let healthy = stats.iter().find(|g| g.app_id == "healthy-app").unwrap();
    let stuck = stats.iter().find(|g| g.app_id == "stuck-app").unwrap();
    assert_eq!(healthy.pending, 0, "the healthy group's PEL must be empty");
    assert_eq!(
        stuck.pending, 1,
        "the stuck group's PEL must still hold its unacked entry"
    );
}

#[tokio::test]
async fn claim_concurrency_three_replicas_claim_disjoint_entries() {
    // A non-zero idle threshold is load-bearing for this test's own
    // premise: XAUTOCLAIM resets an entry's idle time to 0 the instant it
    // claims it, so with `claim_idle_ms = 0` a second, near-simultaneous
    // XAUTOCLAIM would see idle(0) >= min-idle-time(0) and legitimately
    // reclaim the very entry replica 1 just took -- that is correct
    // Valkey behavior, not a bug, but it defeats "each entry claimed by
    // exactly one replica" as a meaningful assertion. A small positive
    // threshold plus letting the reads age past it once, up front, is
    // what makes the three concurrent claims below mutually exclusive.
    let mut cfg = SpineConfig::from_env().unwrap();
    cfg.claim_idle_ms = 50;
    let stream = unique_stream("claim-concurrency");
    let app_id = "waddles.bot.commands.default";

    let writer = test_client().await;
    writer.ensure_group(&stream, app_id).await.unwrap();
    for _ in 0..9 {
        writer.append(&stream, &sample_envelope()).await.unwrap();
    }
    for _ in 0..9 {
        let _ = read_one_via_xreadgroup(&stream, app_id, "dead-consumer").await;
    }
    tokio::time::sleep(std::time::Duration::from_millis(80)).await;

    let c1 = SpineClient::connect(cfg.clone(), Arc::new(NoopMetrics))
        .await
        .unwrap();
    let c2 = SpineClient::connect(cfg.clone(), Arc::new(NoopMetrics))
        .await
        .unwrap();
    let c3 = SpineClient::connect(cfg, Arc::new(NoopMetrics))
        .await
        .unwrap();

    let (r1, r2, r3) = tokio::join!(
        c1.claim_stale(&stream, app_id, Stage::Process),
        c2.claim_stale(&stream, app_id, Stage::Process),
        c3.claim_stale(&stream, app_id, Stage::Process),
    );

    let mut all_ids: Vec<String> = Vec::new();
    for r in [r1, r2, r3] {
        for d in r.unwrap() {
            all_ids.push(d.entry_id);
        }
    }
    let unique: HashSet<&String> = all_ids.iter().collect();
    assert_eq!(
        unique.len(),
        all_ids.len(),
        "no entry may be claimed by more than one replica"
    );
    assert_eq!(
        all_ids.len(),
        9,
        "all nine pending entries must be claimed exactly once across all replicas"
    );
}

#[tokio::test]
async fn redelivery_cap_sends_the_entry_to_the_dlq_after_max_deliveries() {
    let mut cfg = SpineConfig::from_env().unwrap();
    cfg.claim_idle_ms = 0;
    cfg.max_deliveries = 3; // keep the test fast; the mechanism is identical at any cap
    let stream = unique_stream("redelivery-cap");
    let app_id = "waddles.bot.commands.default";

    let client = SpineClient::connect(cfg, Arc::new(NoopMetrics))
        .await
        .unwrap();
    client.ensure_group(&stream, app_id).await.unwrap();
    client.append(&stream, &sample_envelope()).await.unwrap();
    // First delivery: a normal read, never acked (simulating a crash).
    let _ = read_one_via_xreadgroup(&stream, app_id, "dead-consumer").await;

    // Second delivery: claim_stale reclaims it (delivery count now 2 < 3).
    let claimed = client
        .claim_stale(&stream, app_id, Stage::Process)
        .await
        .unwrap();
    assert_eq!(claimed.len(), 1);
    assert_eq!(claimed[0].deliveries, 2);
    // Left unacked again (simulating a second crash).

    // Third reclaim: delivery count reaches max_deliveries (3) -- the
    // client dead-letters it internally instead of returning it.
    let claimed_again = client
        .claim_stale(&stream, app_id, Stage::Process)
        .await
        .unwrap();
    assert!(
        claimed_again.is_empty(),
        "an entry at SPINE_MAX_DELIVERIES must not be returned for another attempt"
    );

    let stats = client.group_stats(&stream).await.unwrap();
    let group = stats.iter().find(|g| g.app_id == app_id).unwrap();
    assert_eq!(
        group.pending, 0,
        "the over-delivered entry must be XACKed once dead-lettered"
    );
}

#[tokio::test]
async fn stream_bounding_trims_within_the_approximate_maxlen() {
    let mut cfg = SpineConfig::from_env().unwrap();
    cfg.stream_maxlen = 20;
    let client = SpineClient::connect(cfg, Arc::new(NoopMetrics))
        .await
        .unwrap();
    let stream = unique_stream("maxlen");

    for _ in 0..70 {
        client.append(&stream, &sample_envelope()).await.unwrap();
    }

    let mut conn = raw_admin_connection().await;
    let len: u64 = redis::cmd("XLEN")
        .arg(&stream)
        .query_async(&mut conn)
        .await
        .unwrap();
    assert!(
        len < 70,
        "expected trimming to have occurred, stream length is {len}"
    );
    assert!(
        len <= 60,
        "MAXLEN ~ 20 should not leave the stream wildly over bound, got {len}"
    );
}

#[tokio::test]
async fn dlq_stays_within_the_configured_maxlen() {
    let mut cfg = SpineConfig::from_env().unwrap();
    cfg.dlq_maxlen = 5;
    let client = SpineClient::connect(cfg, Arc::new(NoopMetrics))
        .await
        .unwrap();
    let stream = unique_stream("dlq-cap");
    client.ensure_group(&stream, "app-dlq-cap").await.unwrap();

    for _ in 0..20 {
        client.append(&stream, &sample_envelope()).await.unwrap();
    }
    for _ in 0..20 {
        let (entry_id, env) = read_one_via_xreadgroup(&stream, "app-dlq-cap", "consumer-dlq").await;
        let d = Delivered {
            stream: stream.clone(),
            entry_id,
            env,
            deliveries: 1,
        };
        let err = DlqError {
            kind: DlqErrorKind::BundleError,
            code: "TEST_FORCED".to_string(),
            message: "forced for the dlq-capping test".to_string(),
            detail: None,
            artifact_digest: None,
            consumer_id: "test-consumer".to_string(),
        };
        client.dead_letter(&d, &err).await.unwrap();
    }

    let mut conn = raw_admin_connection().await;
    let len: u64 = redis::cmd("XLEN")
        .arg("waddles:dlq:process")
        .query_async(&mut conn)
        .await
        .unwrap();
    assert!(
        len < 20,
        "expected the DLQ to be trimmed toward its MAXLEN, got length {len}"
    );
}
