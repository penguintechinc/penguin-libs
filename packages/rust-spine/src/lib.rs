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

// TODO(task-2): pub use scope::{parse_scope_from_key, Scope, Stage, TENANT_WIDE_SEGMENT};
// TODO(task-3): pub use envelope::{EnvelopeError, PlatformEvent, Source, StageEnvelope, PROCESS_TARGET_APP_ID_KEY};
// TODO(task-5): pub use dlq::{DlqError, DlqErrorDetail, DlqErrorKind, DlqRecord};
// TODO(task-5): pub use error::SpineError;
// TODO(task-6): pub use metrics::{NoopMetrics, SpineMetrics};
// TODO(task-9): pub use config::{ProbeClass, ProbeResult, SpineConfig};
// TODO(task-13): pub use client::{Delivered, Grant, GroupStats, SpineClient};
// TODO(task-17): pub use reader::GroupReader;
