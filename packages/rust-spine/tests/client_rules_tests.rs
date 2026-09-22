#![allow(clippy::unwrap_used, clippy::panic)]
//! The two Sec5.7 client connection-separation rules, plus grant
//! enforcement, tested against the pinned Valkey container. Run via
//! `make test-integration-spine`.

use penguin_spine::{Grant, GroupReader, NoopMetrics, Scope, SpineClient, SpineConfig, Stage};
use redis::AsyncCommands;
use std::sync::Arc;

fn sample_envelope() -> penguin_spine::StageEnvelope {
    let json = serde_json::json!({
        "schema_version": 2,
        "tenant": "acme", "community": "main", "app_id": "waddles.bot.commands.default",
        "stage": "process",
        "event": {"platform": "twitch", "event_type": "chat.message", "actor": "u",
                   "payload": {}, "occurred_at": "2026-09-14T12:00:00.000Z"},
        "ts": "2026-09-14T12:00:00.123Z", "target_app_id": null,
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

#[tokio::test]
async fn rule_1_construction_is_refused_when_block_ms_is_not_strictly_less_than_socket_timeout() {
    let mut cfg = SpineConfig::from_env().unwrap();
    cfg.drain_socket_timeout_s = 1;
    cfg.block_ms = 1_000; // 1000ms == 1s -- not strictly less

    let dlq = SpineClient::connect(SpineConfig::from_env().unwrap(), Arc::new(NoopMetrics))
        .await
        .unwrap();
    let result = GroupReader::connect(
        &cfg,
        vec![],
        "waddles.bot.commands.default".to_string(),
        Stage::Process,
        dlq,
        Arc::new(NoopMetrics),
    )
    .await;

    let err = result.expect_err("construction must be refused");
    let message = err.to_string();
    assert!(
        message.contains("SPINE_BLOCK_MS"),
        "error must name SPINE_BLOCK_MS: {message}"
    );
    assert!(
        message.contains('1'),
        "error must name the socket timeout value: {message}"
    );
}

#[tokio::test]
async fn rule_2_a_dedicated_reader_connection_survives_a_cancelled_block_and_a_same_client_admin_call()
 {
    let dlq_cfg = SpineConfig::from_env().unwrap();
    let dlq = SpineClient::connect(dlq_cfg.clone(), Arc::new(NoopMetrics))
        .await
        .unwrap();

    let scope = Scope::new("acme", Some("main".to_string()));
    let stream = scope.source_stream("twitch", &format!("client-rule2-{}", uuid::Uuid::new_v4()));
    let app_id = "waddles.bot.commands.default";
    dlq.ensure_group(&stream, app_id).await.unwrap();

    let grants = vec![Grant {
        stream: stream.clone(),
        platform: "twitch".to_string(),
        source_id: "client-rule2".to_string(),
    }];
    let mut reader_cfg = dlq_cfg.clone();
    reader_cfg.block_ms = 200; // short, so the cancellation below resolves quickly
    let mut reader = GroupReader::connect(
        &reader_cfg,
        grants,
        app_id.to_string(),
        Stage::Process,
        dlq.clone(),
        Arc::new(NoopMetrics),
    )
    .await
    .unwrap();

    // Nothing is on the stream yet, so this read blocks for up to
    // block_ms and is cancelled below before it resolves -- reproducing
    // the exact "cancel an in-flight blocking read" shape Sec5.7 rule 2
    // exists for. If the reader's connection were shared with
    // SpineClient's admin traffic, a subsequent admin call could race a
    // still-pending reply from this cancelled read.
    let _ = tokio::time::timeout(std::time::Duration::from_millis(50), reader.read()).await;

    // An admin-style call on the SEPARATE dlq/admin client, immediately
    // after. Bounded by a generous timeout so a violation of rule 2
    // (a hang) fails the assertion instead of wedging the test suite.
    // This is the actual rule-2 assertion: a cancelled blocking read on
    // the reader's dedicated connection must never stall unrelated admin
    // traffic on a different connection.
    let admin_result = tokio::time::timeout(
        std::time::Duration::from_secs(5),
        dlq.ensure_group(&stream, app_id),
    )
    .await;
    assert!(
        admin_result.is_ok(),
        "an admin call on a separate connection must not hang after a cancelled blocking read"
    );
    admin_result.unwrap().unwrap();

    // Cancelling the Rust future does not tell Valkey to abandon the
    // in-flight XREADGROUP: the command was already flushed, so the
    // server keeps that BLOCK window open on the reader's connection.
    // Give it time to expire naturally (reader_cfg.block_ms = 200) before
    // driving a fresh command through the same connection -- otherwise an
    // entry appended too soon would be delivered to the already-abandoned
    // command instead of the read below, discarded, and never observed by
    // either side. This sleep is what makes "the reader itself is still
    // usable afterward" a controlled check rather than a timing gamble.
    tokio::time::sleep(std::time::Duration::from_millis(300)).await;

    // The reader itself must still be usable afterward.
    dlq.append(&stream, &sample_envelope()).await.unwrap();
    let delivered = tokio::time::timeout(std::time::Duration::from_secs(2), reader.read())
        .await
        .expect("reader must still respond after the earlier cancelled read")
        .unwrap();
    assert_eq!(delivered.len(), 1);
}

#[tokio::test]
async fn grant_enforcement_refuses_a_stream_outside_the_grant_list_even_with_an_existing_group() {
    let cfg = SpineConfig::from_env().unwrap();
    let dlq = SpineClient::connect(cfg.clone(), Arc::new(NoopMetrics))
        .await
        .unwrap();

    let scope = Scope::new("acme", Some("main".to_string()));
    let granted_stream =
        scope.source_stream("discord", &format!("granted-{}", uuid::Uuid::new_v4()));
    let ungranted_stream =
        scope.source_stream("twitch", &format!("ungranted-{}", uuid::Uuid::new_v4()));
    let app_id = "waddles.bot.commands.default";

    // A group exists on the ungranted stream too -- proving the reader's
    // own grant list is the enforcement point, not group existence
    // (spec Sec5.2's negative test).
    dlq.ensure_group(&granted_stream, app_id).await.unwrap();
    dlq.ensure_group(&ungranted_stream, app_id).await.unwrap();

    let grants = vec![Grant {
        stream: granted_stream.clone(),
        platform: "discord".to_string(),
        source_id: "granted".to_string(),
    }];
    let reader = GroupReader::connect(
        &cfg,
        grants,
        app_id.to_string(),
        Stage::Process,
        dlq,
        Arc::new(NoopMetrics),
    )
    .await
    .unwrap();

    assert!(reader.ensure_granted(&granted_stream).is_ok());
    let err = reader
        .ensure_granted(&ungranted_stream)
        .expect_err("must refuse an ungranted stream");
    assert!(matches!(
        err,
        penguin_spine::SpineError::StreamNotGranted { .. }
    ));
}

#[tokio::test]
async fn envelope_invalid_entries_are_dead_lettered_and_excluded_from_read_results() {
    let cfg = SpineConfig::from_env().unwrap();
    let dlq = SpineClient::connect(cfg.clone(), Arc::new(NoopMetrics))
        .await
        .unwrap();

    let scope = Scope::new("acme", Some("main".to_string()));
    let stream = scope.source_stream(
        "twitch",
        &format!("envelope-invalid-{}", uuid::Uuid::new_v4()),
    );
    let app_id = "waddles.bot.commands.default";
    dlq.ensure_group(&stream, app_id).await.unwrap();

    // Write a malformed "env" field directly via a raw connection --
    // SpineClient::append always writes a valid envelope, so this
    // bypasses it deliberately to simulate real corruption in transit.
    let raw_url = std::env::var("VALKEY_URL").unwrap();
    let raw_username = std::env::var("VALKEY_USERNAME").unwrap();
    let raw_password = std::env::var("VALKEY_PASSWORD").unwrap();
    let raw_ca = std::env::var("VALKEY_CA_FILE").unwrap();
    let root_cert = std::fs::read(&raw_ca).unwrap();
    let base: redis::ConnectionInfo =
        redis::IntoConnectionInfo::into_connection_info(raw_url.as_str()).unwrap();
    let redis_settings = base
        .redis_settings()
        .clone()
        .set_username(&raw_username)
        .set_password(&raw_password);
    let info = base.set_redis_settings(redis_settings);
    let raw_client = redis::Client::build_with_tls(
        info,
        redis::TlsCertificates {
            client_tls: None,
            root_cert: Some(root_cert),
        },
    )
    .unwrap();
    let mut raw_conn = raw_client.get_multiplexed_async_connection().await.unwrap();
    let _id: Option<String> = raw_conn
        .xadd(&stream, "*", &[("env", "{not valid json")])
        .await
        .unwrap();

    let grants = vec![Grant {
        stream: stream.clone(),
        platform: "twitch".to_string(),
        source_id: "x".to_string(),
    }];
    let mut reader = GroupReader::connect(
        &cfg,
        grants,
        app_id.to_string(),
        Stage::Process,
        dlq,
        Arc::new(NoopMetrics),
    )
    .await
    .unwrap();

    let delivered = reader.read().await.unwrap();
    assert!(
        delivered.is_empty(),
        "a malformed entry must never be returned from read()"
    );

    let dlq_len: u64 = redis::cmd("XLEN")
        .arg("waddles:dlq:process")
        .query_async(&mut raw_conn)
        .await
        .unwrap();
    assert!(
        dlq_len >= 1,
        "the malformed entry must have reached the DLQ"
    );
}
