//! Golden-shape and round-trip tests for the host-API wire frame codec
//! (spec §6.6). Every JSON shape asserted here is copied from the spec's
//! own worked examples so a shape drift is caught here, not in an
//! integration test against a real stage/executor pair.
#![allow(clippy::unwrap_used, clippy::expect_used, clippy::panic)]

use std::io::Cursor;

use penguin_bundle_host::wire::{
    read_frame, write_frame, CapabilityKind, CorrelationTable, ErrorBody, ErrorCode, ExportKind,
    Frame, HelloBody, HelloLimits, HelloOkBody, HostCallBody, HostResultBody, HostResultError,
    IdAllocator, InvokeBody, LoadBody, LoadLimits, LoadedBody, Message, SandboxInfo, ShutdownBody,
    TraceContext, UnloadBody, UnloadedBody,
};

fn hello_frame() -> Frame {
    Frame::new(
        1,
        Message::Hello(HelloBody {
            protocol_version: 1,
            executor_version: "0.1.0".to_string(),
            wasmtime_version: "48.0.2".to_string(),
            wasmtime_abi: "component-model-async".to_string(),
            collector: "drc".to_string(),
            sandbox: SandboxInfo {
                runtime: "gvisor".to_string(),
                verified: true,
            },
        }),
    )
}

#[test]
fn hello_frame_matches_expected_json_shape() {
    let frame = hello_frame();
    let value: serde_json::Value = serde_json::to_value(&frame).expect("serialize");

    assert_eq!(value["v"], 1);
    assert_eq!(value["id"], 1);
    assert_eq!(value["kind"], "hello");
    assert_eq!(value["protocol_version"], 1);
    assert_eq!(value["collector"], "drc");
    assert_eq!(value["sandbox"]["runtime"], "gvisor");
    assert_eq!(value["sandbox"]["verified"], true);

    let round_tripped: Frame = serde_json::from_value(value).expect("deserialize");
    assert_eq!(round_tripped, frame);
}

#[test]
fn hello_ok_frame_matches_expected_json_shape() {
    let frame = Frame::new(
        1,
        Message::HelloOk(HelloOkBody {
            stage: "svc_process".to_string(),
            protocol_version: 1,
            limits: HelloLimits {
                call_timeout_ms: 2000,
                memory_mb: 64,
                max_concurrent_calls: 32,
            },
        }),
    );
    let value = serde_json::to_value(&frame).expect("serialize");
    assert_eq!(value["kind"], "hello-ok");
    assert_eq!(value["limits"]["call_timeout_ms"], 2000);

    let round_tripped: Frame = serde_json::from_value(value).expect("deserialize");
    assert_eq!(round_tripped, frame);
}

#[test]
fn load_and_loaded_frames_round_trip() {
    let load = Frame::new(
        7,
        Message::Load(LoadBody {
            app_id: "waddles.socials.music.default".to_string(),
            version: "3.0.0".to_string(),
            digest: format!("sha256:{}", "a".repeat(64)),
            component_key: "bundles/waddles.socials.music.default/3.0.0/deadbeef.wasm".to_string(),
            sidecar_key: "bundles/waddles.socials.music.default/3.0.0/deadbeef.json".to_string(),
            capabilities: vec![
                CapabilityKind::Http,
                CapabilityKind::Kv,
                CapabilityKind::Context,
            ],
            limits: LoadLimits {
                timeout_ms: 2000,
                memory_mb: 64,
            },
        }),
    );
    let value = serde_json::to_value(&load).expect("serialize");
    assert_eq!(value["kind"], "load");
    assert_eq!(value["capabilities"][0], "http");
    let round_tripped: Frame = serde_json::from_value(value).expect("deserialize");
    assert_eq!(round_tripped, load);

    let loaded = Frame::new(
        7,
        Message::Loaded(LoadedBody {
            app_id: "waddles.socials.music.default".to_string(),
            digest: format!("sha256:{}", "a".repeat(64)),
            precompile_ms: 42,
            exports: vec!["transform".to_string()],
        }),
    );
    assert_eq!(
        loaded.id, load.id,
        "loaded reuses the load frame's correlation id"
    );
    let round_tripped: Frame =
        serde_json::from_value(serde_json::to_value(&loaded).expect("serialize"))
            .expect("deserialize");
    assert_eq!(round_tripped, loaded);
}

#[test]
fn unload_and_unloaded_frames_round_trip() {
    let unload = Frame::new(
        9,
        Message::Unload(UnloadBody {
            app_id: "waddles.socials.music.default".to_string(),
            digest: format!("sha256:{}", "b".repeat(64)),
        }),
    );
    let unloaded = Frame::new(
        9,
        Message::Unloaded(UnloadedBody {
            app_id: "waddles.socials.music.default".to_string(),
            digest: format!("sha256:{}", "b".repeat(64)),
        }),
    );
    for frame in [&unload, &unloaded] {
        let round_tripped: Frame =
            serde_json::from_value(serde_json::to_value(frame).expect("serialize"))
                .expect("deserialize");
        assert_eq!(&round_tripped, frame);
    }
}

#[test]
fn invoke_frame_carries_optional_trace_context() {
    let with_trace = Frame::new(
        3,
        Message::Invoke(InvokeBody {
            app_id: "waddles.socials.music.default".to_string(),
            digest: format!("sha256:{}", "c".repeat(64)),
            export: ExportKind::Transform,
            payload: serde_json::json!({"platform": "twitch"}),
            deadline_ms: 2000,
            trace: Some(TraceContext {
                traceparent: "00-trace-01-01".to_string(),
                tracestate: None,
            }),
        }),
    );
    let value = serde_json::to_value(&with_trace).expect("serialize");
    assert_eq!(value["kind"], "invoke");
    assert_eq!(value["export"], "transform");
    assert!(value.get("trace").is_some());
    let round_tripped: Frame = serde_json::from_value(value).expect("deserialize");
    assert_eq!(round_tripped, with_trace);

    let without_trace = Frame::new(
        4,
        Message::Invoke(InvokeBody {
            app_id: "waddles.socials.music.default".to_string(),
            digest: format!("sha256:{}", "c".repeat(64)),
            export: ExportKind::Dispatch,
            payload: serde_json::Value::Null,
            deadline_ms: 2000,
            trace: None,
        }),
    );
    let value = serde_json::to_value(&without_trace).expect("serialize");
    assert!(
        value.get("trace").is_none(),
        "absent trace must not serialize a null field"
    );
    let round_tripped: Frame = serde_json::from_value(value).expect("deserialize");
    assert_eq!(round_tripped, without_trace);
}

#[test]
fn host_call_and_host_result_frames_round_trip_both_outcomes() {
    let host_call = Frame::new(
        11,
        Message::HostCall(HostCallBody {
            app_id: "waddles.socials.music.default".to_string(),
            capability: CapabilityKind::Db,
            op: "execute".to_string(),
            args: serde_json::json!({"statement": "select 1"}),
            call_id: 3,
        }),
    );
    let round_tripped: Frame =
        serde_json::from_value(serde_json::to_value(&host_call).expect("serialize"))
            .expect("deserialize");
    assert_eq!(round_tripped, host_call);

    let ok_result = Frame::new(
        11,
        Message::HostResult(HostResultBody {
            result: Some(serde_json::json!({"rows": []})),
            error: None,
        }),
    );
    let value = serde_json::to_value(&ok_result).expect("serialize");
    assert!(value.get("error").is_none());
    let round_tripped: Frame = serde_json::from_value(value).expect("deserialize");
    assert_eq!(round_tripped, ok_result);

    let err_result = Frame::new(
        12,
        Message::HostResult(HostResultBody {
            result: None,
            error: Some(HostResultError {
                code: "denied".to_string(),
                message: "no such table".to_string(),
            }),
        }),
    );
    let value = serde_json::to_value(&err_result).expect("serialize");
    assert!(value.get("result").is_none());
    let round_tripped: Frame = serde_json::from_value(value).expect("deserialize");
    assert_eq!(round_tripped, err_result);
}

#[test]
fn error_frame_uses_stable_screaming_snake_case_codes() {
    let frame = Frame::new(
        5,
        Message::Error(ErrorBody {
            code: ErrorCode::UnsandboxedExecutor,
            message: "executor reported runc but stage requires gvisor".to_string(),
            detail: None,
        }),
    );
    let value = serde_json::to_value(&frame).expect("serialize");
    assert_eq!(value["code"], "UNSANDBOXED_EXECUTOR");
    let round_tripped: Frame = serde_json::from_value(value).expect("deserialize");
    assert_eq!(round_tripped, frame);
}

#[test]
fn ping_pong_and_shutdown_frames_have_no_extra_fields_where_unit() {
    let ping = Frame::new(6, Message::Ping);
    let value = serde_json::to_value(&ping).expect("serialize");
    assert_eq!(value, serde_json::json!({"v": 1, "id": 6, "kind": "ping"}));

    let pong = Frame::new(6, Message::Pong);
    let value = serde_json::to_value(&pong).expect("serialize");
    assert_eq!(value, serde_json::json!({"v": 1, "id": 6, "kind": "pong"}));

    let shutdown = Frame::new(8, Message::Shutdown(ShutdownBody { grace_ms: 5000 }));
    let round_tripped: Frame =
        serde_json::from_value(serde_json::to_value(&shutdown).expect("serialize"))
            .expect("deserialize");
    assert_eq!(round_tripped, shutdown);
}

#[tokio::test]
async fn write_frame_then_read_frame_round_trips_over_a_duplex_stream() {
    let frame = hello_frame();
    let mut buf: Vec<u8> = Vec::new();
    write_frame(&mut buf, &frame).await.expect("write");

    // First 4 bytes are the big-endian length prefix (spec §6.6).
    let declared_len = u32::from_be_bytes(buf[0..4].try_into().expect("4 bytes"));
    assert_eq!(declared_len as usize, buf.len() - 4);

    let mut cursor = Cursor::new(buf);
    let decoded = read_frame(&mut cursor).await.expect("read");
    assert_eq!(decoded, frame);
}

#[tokio::test]
async fn read_frame_rejects_a_length_over_max_frame_bytes() {
    use penguin_bundle_host::wire::{FrameError, MAX_FRAME_BYTES};

    let mut buf = Vec::new();
    buf.extend_from_slice(&(MAX_FRAME_BYTES + 1).to_be_bytes());
    let mut cursor = Cursor::new(buf);

    let err = read_frame(&mut cursor)
        .await
        .expect_err("must reject oversized length");
    match err {
        FrameError::TooLarge { len } => assert_eq!(len, MAX_FRAME_BYTES + 1),
        other => panic!("expected TooLarge, got {other:?}"),
    }
}

#[tokio::test]
async fn read_frame_reports_malformed_json_without_panicking() {
    let payload = b"not json";
    let mut buf = Vec::new();
    buf.extend_from_slice(&(payload.len() as u32).to_be_bytes());
    buf.extend_from_slice(payload);
    let mut cursor = Cursor::new(buf);

    let err = read_frame(&mut cursor)
        .await
        .expect_err("must reject malformed JSON");
    assert!(matches!(
        err,
        penguin_bundle_host::wire::FrameError::Malformed(_)
    ));
}

#[tokio::test]
async fn write_frame_rejects_a_payload_over_max_frame_bytes() {
    use penguin_bundle_host::wire::{FrameError, MAX_FRAME_BYTES};

    // A payload string alone, well past MAX_FRAME_BYTES once JSON-encoded.
    let oversized = Frame::new(
        1,
        Message::Invoke(InvokeBody {
            app_id: "waddles.socials.music.default".to_string(),
            digest: format!("sha256:{}", "a".repeat(64)),
            export: ExportKind::Transform,
            payload: serde_json::Value::String("x".repeat(MAX_FRAME_BYTES as usize + 1024)),
            deadline_ms: 2000,
            trace: None,
        }),
    );
    let mut buf: Vec<u8> = Vec::new();
    let err = write_frame(&mut buf, &oversized)
        .await
        .expect_err("must reject oversized payload");
    assert!(matches!(err, FrameError::TooLarge { .. }));
    assert!(
        buf.is_empty(),
        "nothing should be written once the size check fails"
    );
}

#[test]
fn capability_from_str_maps_every_known_name_and_rejects_unknown() {
    use penguin_bundle_host::wire::message::capability_from_str;

    assert_eq!(capability_from_str("http"), Some(CapabilityKind::Http));
    assert_eq!(capability_from_str("kv"), Some(CapabilityKind::Kv));
    assert_eq!(capability_from_str("db"), Some(CapabilityKind::Db));
    assert_eq!(capability_from_str("relay"), Some(CapabilityKind::Relay));
    assert_eq!(capability_from_str("flags"), Some(CapabilityKind::Flags));
    assert_eq!(capability_from_str("log"), Some(CapabilityKind::Log));
    assert_eq!(capability_from_str("clock"), Some(CapabilityKind::Clock));
    assert_eq!(
        capability_from_str("context"),
        Some(CapabilityKind::Context)
    );
    assert_eq!(capability_from_str("bogus"), None);
}

#[test]
fn id_allocator_is_monotonically_increasing_and_never_zero() {
    let allocator = IdAllocator::new();
    let first = allocator.next_id();
    let second = allocator.next_id();
    assert_ne!(first, 0);
    assert!(second > first);
}

#[tokio::test]
async fn correlation_table_delivers_the_reply_to_the_registered_id() {
    let table = CorrelationTable::new();
    let rx = table.register(42).expect("register");
    assert_eq!(table.pending_count(), 1);

    let reply = Frame::new(42, Message::Pong);
    table.complete(reply.clone()).expect("complete");
    assert_eq!(table.pending_count(), 0);

    let received = rx.await.expect("receiver not dropped");
    assert_eq!(received, reply);
}

#[test]
fn correlation_table_rejects_double_registration_and_unknown_completion() {
    let table = CorrelationTable::new();
    let _rx = table.register(1).expect("first register succeeds");
    let err = table.register(1).expect_err("second register must fail");
    assert_eq!(
        err,
        penguin_bundle_host::wire::CorrelationError::AlreadyRegistered(1)
    );

    let err = table
        .complete(Frame::new(999, Message::Pong))
        .expect_err("completing an unregistered id must fail");
    assert_eq!(
        err,
        penguin_bundle_host::wire::CorrelationError::Unknown(999)
    );
}

#[test]
fn correlation_table_cancel_is_idempotent() {
    let table = CorrelationTable::new();
    let _rx = table.register(5).expect("register");
    table.cancel(5);
    table.cancel(5); // idempotent, must not panic
    assert_eq!(table.pending_count(), 0);
}
