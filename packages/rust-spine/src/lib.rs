//! `penguin-spine` — the Waddles data-plane spine over Valkey Streams.
//!
//! One stream per ingest source (`{scope}:src:{platform}:{source_id}:events`)
//! and one action stream per app bundle (`{scope}:app:{app_id}:action`),
//! read through per-bundle consumer groups with `XREADGROUP`/`XACK`/
//! `XAUTOCLAIM`, and a dead-letter stream per stage (`waddles:dlq:{stage}`).
//! Envelope JSON is byte-compatible with `flask_core.stream_pipeline`'s
//! `PlatformEvent`/`StageEnvelope` dataclasses (Python source of truth,
//! `libs/flask_core/flask_core/stream_pipeline.py` in the `waddlebot` repo).
//!
//! Two client rules are enforced by construction, not by convention (spec
//! §5.7): a blocking `XREADGROUP ... BLOCK` read always runs on its own
//! dedicated connection with its own response timeout, strictly longer than
//! the configured block duration; and that dedicated connection is never
//! shared with administrative traffic (`XADD`/`XACK`/`XAUTOCLAIM`/`XGROUP`/
//! `XINFO`), which lives on [`SpineClient`]'s own `MultiplexedConnection`.
//!
//! This crate emits no logs/metrics of its own destination — it calls back
//! into a caller-supplied [`SpineMetrics`] implementation, since no Rust
//! penguin-logging crate exists yet (`backend-rust.md`, known gap).

mod client;
mod config;
mod dlq;
mod envelope;
mod error;
mod metrics;
mod reader;
mod scope;

pub use client::{Delivered, Grant, GroupStats, SpineClient};
pub use config::{
    ProbeClass, ProbeResult, SpineConfig, classify_connect_error, probe_valkey,
    validate_block_timeout,
};
pub use dlq::{DlqError, DlqErrorDetail, DlqErrorKind, DlqRecord};
pub use envelope::{
    Binding, ENVELOPE_SCHEMA_VERSION, EnvelopeError, PROCESS_TARGET_APP_ID_KEY, PlatformEvent,
    Source, StageEnvelope, Trace, trace_id_from_traceparent,
};
pub use error::SpineError;
pub use metrics::{NoopMetrics, SpineMetrics};
pub use reader::GroupReader;
pub use scope::{Scope, Stage, TENANT_WIDE_SEGMENT, parse_scope_from_key};
