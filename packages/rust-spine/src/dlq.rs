//! The dead-letter record shape (spec Sec6.3) and the caller-supplied
//! classification `SpineClient::dead_letter` (Task 16) accepts.

use crate::envelope::Trace;
use serde::{Deserialize, Serialize};

/// The DLQ record's `error.kind` classification (spec Sec6.3) — exactly
/// ten values, each also the `reason` label on `waddles_spine_dlq_total`.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum DlqErrorKind {
    /// Strict envelope deserialization failed.
    EnvelopeInvalid,
    /// The WASM component trapped (panic, unreachable, guest OOM).
    BundleTrap,
    /// The component returned a terminal (non-retryable) error.
    BundleError,
    /// The per-call epoch deadline fired.
    CallTimeout,
    /// The instance exceeded its memory cap.
    MemoryLimit,
    /// A capability check refused the call.
    HostCallDenied,
    /// `deliveries` reached `SPINE_MAX_DELIVERIES`.
    MaxDeliveries,
    /// The Sec5.11 hop verification failed: `binding.mac` mismatch,
    /// envelope tenant/community disagreeing with the stream key, a
    /// grant/approval scoped to a different tenant or community, or a
    /// bundle output that tried to set an identity field (D30). **Never
    /// retried** — see [`DlqErrorKind::never_retry`].
    TenantBoundary,
    /// The bundle is disabled after three sandbox trips.
    BundleDisabled,
    /// The executor was unavailable past its ready-timeout.
    ExecutorUnavailable,
}

impl DlqErrorKind {
    /// The exact snake_case wire string (matches the spec's `error.kind`
    /// values and the `reason` label on `waddles_spine_dlq_total`).
    pub fn as_str(&self) -> &'static str {
        match self {
            DlqErrorKind::EnvelopeInvalid => "envelope_invalid",
            DlqErrorKind::BundleTrap => "bundle_trap",
            DlqErrorKind::BundleError => "bundle_error",
            DlqErrorKind::CallTimeout => "call_timeout",
            DlqErrorKind::MemoryLimit => "memory_limit",
            DlqErrorKind::HostCallDenied => "host_call_denied",
            DlqErrorKind::MaxDeliveries => "max_deliveries",
            DlqErrorKind::TenantBoundary => "tenant_boundary",
            DlqErrorKind::BundleDisabled => "bundle_disabled",
            DlqErrorKind::ExecutorUnavailable => "executor_unavailable",
        }
    }

    /// True when an entry classified this way must never be attempted
    /// again after being DLQ'd — currently only `tenant_boundary` (spec
    /// Sec5.11, D30): a forged, replayed or cross-tenant envelope is not
    /// made valid by retrying it. Every other kind is retried up to
    /// `SPINE_MAX_DELIVERIES` by the stage's normal redelivery path.
    pub fn never_retry(&self) -> bool {
        matches!(self, DlqErrorKind::TenantBoundary)
    }
}

/// The nested `error` object inside a [`DlqRecord`] (spec Sec6.3).
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct DlqErrorDetail {
    /// The classification (spec Sec6.3's ten values).
    pub kind: DlqErrorKind,
    /// A short machine-readable code (e.g. `"EXECUTOR_DEADLINE"`).
    pub code: String,
    /// A human-readable failure message.
    pub message: String,
    /// Optional extra detail; `None` when there is nothing more to say.
    pub detail: Option<String>,
}

/// One JSON object written to `waddles:dlq:{stage}` per failed entry
/// (spec Sec6.3), carried under the single field `rec`. Field order
/// matches the spec's JSON example exactly, for byte-identical
/// golden-fixture round-trips (Task 8).
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct DlqRecord {
    /// Always `1` for this spec revision.
    pub schema_version: u32,
    /// The stage that wrote this record (`"process"`/`"action"`).
    pub stage: String,
    /// The Valkey key of the stream the entry came from.
    pub key: String,
    /// The stream entry id the record came from — the stable
    /// de-duplication key, also handed to a bundle as `message-id`.
    pub entry_id: String,
    /// The consumer group that was processing the entry (`XREADGROUP`'s
    /// group argument) — not necessarily the same as `app_id` below: they
    /// coincide for a per-bundle action stream but not for a shared
    /// ingest-source stream, where the group is shared across bundles.
    pub group: String,
    /// The tenant slug, sourced from the key, never the payload.
    pub tenant: String,
    /// The community slug, or `None` for a tenant-wide activation.
    pub community: Option<String>,
    /// The bundle's `app_id`.
    pub app_id: String,
    /// Copied from the envelope (spec Sec5.11, D30); present whenever the
    /// envelope parsed far enough to carry one — including a
    /// `tenant_boundary` rejection, which is exactly the record an
    /// operator needs to trace a boundary violation back to its source.
    /// `None` only for `envelope_invalid`, where no envelope exists yet.
    pub workstream_id: Option<String>,
    /// `None` when the failure happened before a bundle was selected
    /// (e.g. `envelope_invalid`).
    pub artifact_digest: Option<String>,
    /// The pod identity that was processing the entry.
    pub consumer_id: String,
    /// The delivery count at the time of failure.
    pub deliveries: u64,
    /// RFC 3339 UTC timestamp, millisecond precision, `Z` suffix.
    pub failed_at: String,
    /// The classified failure.
    pub error: DlqErrorDetail,
    /// W3C trace context, when the originating envelope carried one.
    /// Supersedes the pre-D30 single-field `trace_context`.
    pub trace: Option<Trace>,
    /// The original envelope JSON, verbatim, as a string — so a malformed
    /// envelope is still replayable/inspectable even though it failed to
    /// parse.
    pub raw: String,
}

/// What a caller hands [`crate::SpineClient::dead_letter`] (Task 16) to
/// classify why an entry failed. `consumer_id` travels here rather than on
/// [`crate::Delivered`] because only the stage runner constructing this
/// value (not the entry itself) knows its own `SPINE_CONSUMER_ID`.
#[derive(Debug, Clone)]
pub struct DlqError {
    /// The classification.
    pub kind: DlqErrorKind,
    /// A short machine-readable code.
    pub code: String,
    /// A human-readable failure message.
    pub message: String,
    /// Optional extra detail.
    pub detail: Option<String>,
    /// The bundle's verified artifact digest, when one was selected.
    pub artifact_digest: Option<String>,
    /// The pod identity handling the entry.
    pub consumer_id: String,
}

#[cfg(test)]
mod tests {
    #![allow(clippy::unwrap_used)]
    use super::*;
    use serde_json::json;

    fn valid_record_json() -> serde_json::Value {
        json!({
            "schema_version": 1,
            "stage": "process",
            "key": "waddles:t:global:c:_tenant:src:twitch:tw-channelA:events",
            "entry_id": "1757851200000-0",
            "group": "waddles.bot.commands.default",
            "tenant": "global",
            "community": null,
            "app_id": "waddles.bot.commands.default",
            "workstream_id": "8f14e45f-ceea-467e-adde-3fb5c9752730",
            "artifact_digest": "sha256:9f86d081884c7d659a2feaa0c55ad015a3bf4f1b2b0b822cd15d6c15b0f00a08",
            "consumer_id": "svc-process-7d9c4f",
            "deliveries": 5,
            "failed_at": "2026-09-14T12:00:01.500Z",
            "error": {
                "kind": "call_timeout",
                "code": "EXECUTOR_DEADLINE",
                "message": "bundle call exceeded 2000 ms",
                "detail": null
            },
            "trace": {
                "traceparent": "00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01",
                "tracestate": null
            },
            "raw": "{\"tenant\":\"global\",\"community\":null}"
        })
    }

    #[test]
    fn deserializes_the_spec_example_record() {
        let rec: DlqRecord = serde_json::from_value(valid_record_json()).unwrap();
        assert_eq!(rec.schema_version, 1);
        assert_eq!(rec.error.kind, DlqErrorKind::CallTimeout);
        assert_eq!(rec.error.code, "EXECUTOR_DEADLINE");
        assert_eq!(
            rec.workstream_id.as_deref(),
            Some("8f14e45f-ceea-467e-adde-3fb5c9752730")
        );
        assert_eq!(
            rec.trace.as_ref().map(|t| t.traceparent.as_str()),
            Some("00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01")
        );
    }

    #[test]
    fn record_round_trips_through_serialize_and_deserialize() {
        let rec: DlqRecord = serde_json::from_value(valid_record_json()).unwrap();
        let out = serde_json::to_value(&rec).unwrap();
        assert_eq!(out, valid_record_json());
    }

    #[test]
    fn workstream_id_absent_is_valid_for_envelope_invalid() {
        let mut v = valid_record_json();
        v["workstream_id"] = json!(null);
        v["error"]["kind"] = json!("envelope_invalid");
        v["error"]["code"] = json!("MALFORMED_ENVELOPE");
        v["artifact_digest"] = json!(null);
        let rec: DlqRecord = serde_json::from_value(v).unwrap();
        assert_eq!(rec.workstream_id, None);
    }

    #[test]
    fn every_error_kind_has_the_exact_spec_wire_string() {
        let expected = [
            (DlqErrorKind::EnvelopeInvalid, "envelope_invalid"),
            (DlqErrorKind::BundleTrap, "bundle_trap"),
            (DlqErrorKind::BundleError, "bundle_error"),
            (DlqErrorKind::CallTimeout, "call_timeout"),
            (DlqErrorKind::MemoryLimit, "memory_limit"),
            (DlqErrorKind::HostCallDenied, "host_call_denied"),
            (DlqErrorKind::MaxDeliveries, "max_deliveries"),
            (DlqErrorKind::TenantBoundary, "tenant_boundary"),
            (DlqErrorKind::BundleDisabled, "bundle_disabled"),
            (DlqErrorKind::ExecutorUnavailable, "executor_unavailable"),
        ];
        assert_eq!(
            expected.len(),
            10,
            "spec Sec6.3 enumerates exactly ten error.kind values (D30 adds tenant_boundary)"
        );
        for (kind, expected_str) in expected {
            assert_eq!(kind.as_str(), expected_str);
            let round_tripped: DlqErrorKind = serde_json::from_value(json!(expected_str)).unwrap();
            assert_eq!(round_tripped, kind);
        }
    }

    #[test]
    fn only_tenant_boundary_is_never_retried() {
        let all = [
            DlqErrorKind::EnvelopeInvalid,
            DlqErrorKind::BundleTrap,
            DlqErrorKind::BundleError,
            DlqErrorKind::CallTimeout,
            DlqErrorKind::MemoryLimit,
            DlqErrorKind::HostCallDenied,
            DlqErrorKind::MaxDeliveries,
            DlqErrorKind::TenantBoundary,
            DlqErrorKind::BundleDisabled,
            DlqErrorKind::ExecutorUnavailable,
        ];
        let never_retry: Vec<DlqErrorKind> = all
            .iter()
            .copied()
            .filter(DlqErrorKind::never_retry)
            .collect();
        assert_eq!(never_retry, vec![DlqErrorKind::TenantBoundary]);
    }

    #[test]
    fn rejects_unknown_error_kind() {
        let mut v = valid_record_json();
        v["error"]["kind"] = json!("not_a_real_kind");
        assert!(serde_json::from_value::<DlqRecord>(v).is_err());
    }

    #[test]
    fn rejects_unknown_top_level_key() {
        let mut v = valid_record_json();
        v["extra"] = json!("nope");
        assert!(serde_json::from_value::<DlqRecord>(v).is_err());
    }
}
