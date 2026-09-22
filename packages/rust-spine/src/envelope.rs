//! Byte-compatible port of `flask_core.stream_pipeline`'s `PlatformEvent`/
//! `StageEnvelope` dataclasses (spec Sec6.1). Strict deserialization only:
//! a missing/wrong-typed required field, an unknown top-level key, or a
//! structurally invalid value is an `EnvelopeError`, never coerced.

use serde::{Deserialize, Serialize};
use serde_json::Value;

/// Raised when a queue-crossing pipeline object is malformed on read.
/// Mirrors Python's `EnvelopeError(ValueError)` — refuses a bad shape
/// rather than coercing it.
#[derive(Debug, Clone, PartialEq, Eq, thiserror::Error)]
#[error("{0}")]
pub struct EnvelopeError(pub(crate) String);

fn env_err(msg: impl Into<String>) -> EnvelopeError {
    EnvelopeError(msg.into())
}

fn validate_rfc3339_millis_z(field: &str, s: &str) -> Result<(), EnvelopeError> {
    if s.is_empty() {
        return Err(env_err(format!(
            "{field:?} must be a non-empty string, got \"\""
        )));
    }
    if !s.ends_with('Z') {
        return Err(env_err(format!(
            "{field:?} must be RFC 3339 UTC with a 'Z' suffix, got {s:?}"
        )));
    }
    chrono::DateTime::parse_from_rfc3339(s)
        .map(|_| ())
        .map_err(|e| env_err(format!("{field:?} is not valid RFC 3339: {s:?} ({e})")))
}

/// Which connection produced a [`PlatformEvent`] — the bot account, app id,
/// or intake source name, plus the platform channel/guild/room it fired
/// in. Tenant/community stay outside the event; `source` answers "which of
/// possibly several connections to this platform" (spec Sec6.1.1).
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Source {
    /// The platform slug — mirrors the top-level `PlatformEvent::platform`.
    pub platform: String,
    /// The connection identity (bot login, app id, intake source name).
    /// Stable across restarts, never a secret.
    pub account_id: String,
    /// The platform's channel/guild/room id, or `None` for an
    /// account-level event with no channel.
    pub channel_id: Option<String>,
}

#[derive(Debug, Clone, Deserialize)]
#[serde(deny_unknown_fields)]
struct RawPlatformEvent {
    platform: String,
    event_type: String,
    actor: Option<String>,
    payload: serde_json::Map<String, Value>,
    occurred_at: String,
    source: Option<Source>,
}

/// A normalized inbound platform event: transport-neutral metadata
/// (`platform`, `event_type`, `actor`, `occurred_at`) plus a
/// platform-specific `payload` object and an optional `source` identifying
/// which connection produced it (spec Sec6.1.1).
#[derive(Debug, Clone, PartialEq, Serialize)]
pub struct PlatformEvent {
    /// Non-empty platform slug (`"twitch"`, `"discord"`, ...).
    pub platform: String,
    /// Non-empty, dotted lowercase event namespace (`"chat.message"`).
    pub event_type: String,
    /// The acting user, or `None` for a system/account-level event.
    pub actor: Option<String>,
    /// Platform-specific event data; may be empty, never a non-object.
    pub payload: serde_json::Map<String, Value>,
    /// RFC 3339 UTC timestamp, millisecond precision, `Z` suffix.
    pub occurred_at: String,
    /// Which connection produced this event, when known.
    pub source: Option<Source>,
}

impl TryFrom<RawPlatformEvent> for PlatformEvent {
    type Error = EnvelopeError;

    fn try_from(raw: RawPlatformEvent) -> Result<Self, EnvelopeError> {
        if raw.platform.is_empty() {
            return Err(env_err("'platform' must be a non-empty string, got \"\""));
        }
        if raw.event_type.is_empty() {
            return Err(env_err("'event_type' must be a non-empty string, got \"\""));
        }
        validate_rfc3339_millis_z("occurred_at", &raw.occurred_at)?;
        if let Some(source) = &raw.source
            && source.platform != raw.platform
        {
            return Err(env_err(format!(
                "'source.platform' ({:?}) must equal the top-level 'platform' ({:?})",
                source.platform, raw.platform
            )));
        }
        Ok(PlatformEvent {
            platform: raw.platform,
            event_type: raw.event_type,
            actor: raw.actor,
            payload: raw.payload,
            occurred_at: raw.occurred_at,
            source: raw.source,
        })
    }
}

impl<'de> Deserialize<'de> for PlatformEvent {
    fn deserialize<D>(deserializer: D) -> Result<Self, D::Error>
    where
        D: serde::Deserializer<'de>,
    {
        let raw = RawPlatformEvent::deserialize(deserializer)?;
        PlatformEvent::try_from(raw).map_err(serde::de::Error::custom)
    }
}

/// Reserved `PlatformEvent.payload` key a process-stage bundle sets to
/// request cross-app routing; the stage pops this key back out of the
/// payload before enqueuing, so it never reaches an action bundle or a
/// chat reply (spec Sec6.1.2, Sec5.9).
pub const PROCESS_TARGET_APP_ID_KEY: &str = "_target_app_id";

/// The only `StageEnvelope.schema_version` this crate accepts. No
/// dual-read (D3, D30): a `1` or absent value is the pre-D30 shape and is
/// rejected outright rather than interpreted (spec Sec6.1.2).
pub const ENVELOPE_SCHEMA_VERSION: u32 = 2;

const BUNDLE_STAGES: [&str; 3] = ["ingest", "process", "action"];

fn is_valid_app_id_segment(seg: &str) -> bool {
    let mut chars = seg.chars();
    let first_ok = matches!(chars.next(), Some(c) if c.is_ascii_lowercase() || c.is_ascii_digit());
    first_ok && chars.all(|c| c.is_ascii_lowercase() || c.is_ascii_digit() || c == '_' || c == '-')
}

/// Validates `^waddles\.[a-z0-9][a-z0-9_-]*\.[a-z0-9][a-z0-9_-]*\.[a-z0-9][a-z0-9_-]*$`
/// (spec Sec6.1.2) without pulling in a `regex` dependency for one pattern.
fn is_valid_app_id(s: &str) -> bool {
    let mut parts = s.split('.');
    if parts.next() != Some("waddles") {
        return false;
    }
    let rest: Vec<&str> = parts.collect();
    rest.len() == 3 && rest.iter().all(|seg| is_valid_app_id_segment(seg))
}

/// Validates a W3C `traceparent` (`00-<32 hex>-<16 hex>-<2 hex>`, spec Sec6.1.2).
fn is_valid_traceparent(s: &str) -> bool {
    let parts: Vec<&str> = s.split('-').collect();
    parts.len() == 4
        && parts[0] == "00"
        && parts[1].len() == 32
        && parts[1].chars().all(|c| c.is_ascii_hexdigit())
        && parts[2].len() == 16
        && parts[2].chars().all(|c| c.is_ascii_hexdigit())
        && parts[3].len() == 2
        && parts[3].chars().all(|c| c.is_ascii_hexdigit())
}

/// Extracts the 32-hex trace-id segment from a validated `traceparent`
/// (spec Sec5.11: `binding.mac`'s input is this segment, not the full
/// `traceparent` string). Returns `None` if `s` is not a valid traceparent.
pub fn trace_id_from_traceparent(s: &str) -> Option<&str> {
    if !is_valid_traceparent(s) {
        return None;
    }
    s.split('-').nth(1)
}

fn is_valid_uuid(s: &str) -> bool {
    uuid::Uuid::parse_str(s).is_ok()
}

/// `event_id` must be UUID **v4** specifically (spec Sec6.1.2, Sec5.11) --
/// stricter than `workstream_id`, which is any valid UUID minted by
/// hub-api.
fn is_valid_uuid_v4(s: &str) -> bool {
    uuid::Uuid::parse_str(s)
        .map(|u| u.get_version() == Some(uuid::Version::Random))
        .unwrap_or(false)
}

/// `binding.mac` is the lowercase-hex HMAC-SHA256 output (spec Sec5.11):
/// exactly 64 lowercase hex characters, never uppercase (a mixed-case
/// value is treated as malformed rather than case-normalized, since a
/// verifier that silently normalizes case could be tricked into comparing
/// two differently-cased representations of a byte-identical forgery).
fn is_lowercase_hex_64(s: &str) -> bool {
    s.len() == 64
        && s.chars()
            .all(|c| c.is_ascii_digit() || ('a'..='f').contains(&c))
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
struct RawTrace {
    traceparent: String,
    #[serde(default)]
    tracestate: Option<String>,
}

/// The W3C trace context carried on every envelope (spec Sec5.11,
/// Sec6.1.2) -- **supersedes the pre-D30 single-field `trace_context`**.
/// Absent means "no parent span"; when present, `traceparent` has already
/// passed the Sec6.1.2 shape check.
#[derive(Debug, Clone, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct Trace {
    /// The W3C `traceparent` string (`00-<32 hex>-<16 hex>-<2 hex>`).
    pub traceparent: String,
    /// The W3C `tracestate` string, or `None`.
    pub tracestate: Option<String>,
}

impl TryFrom<RawTrace> for Trace {
    type Error = EnvelopeError;

    fn try_from(raw: RawTrace) -> Result<Self, EnvelopeError> {
        if !is_valid_traceparent(&raw.traceparent) {
            return Err(env_err(format!(
                "'trace.traceparent' {:?} is not a valid W3C traceparent",
                raw.traceparent
            )));
        }
        Ok(Trace {
            traceparent: raw.traceparent,
            tracestate: raw.tracestate,
        })
    }
}

impl<'de> Deserialize<'de> for Trace {
    fn deserialize<D>(deserializer: D) -> Result<Self, D::Error>
    where
        D: serde::Deserializer<'de>,
    {
        let raw = RawTrace::deserialize(deserializer)?;
        Trace::try_from(raw).map_err(serde::de::Error::custom)
    }
}

#[derive(Debug, Clone, Deserialize)]
#[serde(deny_unknown_fields)]
struct RawBinding {
    kid: String,
    mac: String,
}

/// `{kid, mac}` -- `kid` names the active HMAC key version, `mac` is the
/// lowercase-hex `HMAC-SHA256` of spec Sec5.11's formula. Required on
/// every envelope; there is no unsigned shape (D30). Verified by every
/// stage on every read, before any other processing -- see the `binding`
/// module (Task 19) for `compute_binding_mac`/`verify_binding`.
#[derive(Debug, Clone, PartialEq, Serialize)]
pub struct Binding {
    /// Names the HMAC key version under which `mac` was computed.
    pub kid: String,
    /// Lowercase-hex HMAC-SHA256 output (64 hex chars, spec Sec5.11).
    pub mac: String,
}

impl TryFrom<RawBinding> for Binding {
    type Error = EnvelopeError;

    fn try_from(raw: RawBinding) -> Result<Self, EnvelopeError> {
        if raw.kid.is_empty() {
            return Err(env_err(
                "'binding.kid' must be a non-empty string, got \"\"",
            ));
        }
        if !is_lowercase_hex_64(&raw.mac) {
            return Err(env_err(format!(
                "'binding.mac' {:?} must be exactly 64 lowercase hex characters",
                raw.mac
            )));
        }
        Ok(Binding {
            kid: raw.kid,
            mac: raw.mac,
        })
    }
}

impl<'de> Deserialize<'de> for Binding {
    fn deserialize<D>(deserializer: D) -> Result<Self, D::Error>
    where
        D: serde::Deserializer<'de>,
    {
        let raw = RawBinding::deserialize(deserializer)?;
        Binding::try_from(raw).map_err(serde::de::Error::custom)
    }
}

#[derive(Debug, Clone, Deserialize)]
#[serde(deny_unknown_fields)]
struct RawStageEnvelope {
    schema_version: u32,
    tenant: String,
    community: Option<String>,
    app_id: String,
    stage: String,
    event: PlatformEvent,
    ts: String,
    #[serde(default)]
    target_app_id: Option<String>,
    workstream_id: String,
    event_id: String,
    #[serde(default)]
    session_id: Option<String>,
    #[serde(default)]
    trace: Option<Trace>,
    binding: Binding,
}

/// One pipeline queue message routed between stages. `event` (a
/// [`PlatformEvent`]) is the payload — never named `payload`, deliberately,
/// so a stage double-nesting a payload dict under a `payload` key is
/// structurally impossible (spec Sec6.1.2). `target_app_id` is the one
/// sanctioned cross-app routing escape hatch (spec Sec5.9); it changes
/// only the destination key's `app_id` segment.
///
/// `workstream_id`, `event_id`, `session_id`, `trace` and `binding` are
/// the D30 workstream-identity/trace/tenant-wall fields (spec Sec5.11):
/// minted once by svc-ingest from its own `intake_sources`/`workstreams`
/// cache, never from payload, and copied verbatim by every later stage --
/// a bundle's output is never read for them (spec Sec5.11 "Bundles cannot
/// move a workstream"). Field order matches the spec Sec6.1.2 JSON example
/// exactly, so golden-fixture round-trips (Task 8) are byte-identical.
#[derive(Debug, Clone, PartialEq, Serialize)]
pub struct StageEnvelope {
    /// Must equal [`ENVELOPE_SCHEMA_VERSION`] (`2`) -- no dual-read (D3, D30).
    pub schema_version: u32,
    /// Non-empty tenant slug; equals the `t:` segment of the key it came from.
    pub tenant: String,
    /// `None` iff the key's `c:` segment is the literal `_tenant`.
    pub community: Option<String>,
    /// Matches `^waddles\.[a-z0-9][a-z0-9_-]*\.[a-z0-9][a-z0-9_-]*\.[a-z0-9][a-z0-9_-]*$`.
    pub app_id: String,
    /// One of `"ingest"`, `"process"`, `"action"`.
    pub stage: String,
    /// The carried `PlatformEvent`.
    pub event: PlatformEvent,
    /// RFC 3339 UTC timestamp, millisecond precision, `Z` suffix.
    pub ts: String,
    /// The cross-app routing target, when a process bundle set one.
    pub target_app_id: Option<String>,
    /// UUID; minted by svc-ingest from `intake_sources`/`workstreams`
    /// (spec Sec5.11, Sec6.11), never from payload; copied verbatim by
    /// every later stage, never accepted from bundle output.
    pub workstream_id: String,
    /// UUID v4, minted once by svc-ingest per inbound event; distinct from
    /// the platform's own message id and the Valkey stream entry id.
    pub event_id: String,
    /// The platform connection/broadcast session, when the platform has
    /// one; absent otherwise (spec Sec5.11).
    pub session_id: Option<String>,
    /// W3C trace context for the entry's parent span, when present.
    /// Supersedes the pre-D30 `trace_context` field.
    pub trace: Option<Trace>,
    /// `{kid, mac}` -- the Sec5.11 tenant-binding MAC. Required.
    pub binding: Binding,
}

impl TryFrom<RawStageEnvelope> for StageEnvelope {
    type Error = EnvelopeError;

    fn try_from(raw: RawStageEnvelope) -> Result<Self, EnvelopeError> {
        if raw.schema_version != ENVELOPE_SCHEMA_VERSION {
            return Err(env_err(format!(
                "'schema_version' must equal {ENVELOPE_SCHEMA_VERSION}, got {} -- no dual-read of the pre-D30 shape",
                raw.schema_version
            )));
        }
        if raw.tenant.is_empty() {
            return Err(env_err("'tenant' must be a non-empty string, got \"\""));
        }
        if !BUNDLE_STAGES.contains(&raw.stage.as_str()) {
            return Err(env_err(format!(
                "'stage' {:?} is not one of {BUNDLE_STAGES:?}",
                raw.stage
            )));
        }
        if !is_valid_app_id(&raw.app_id) {
            return Err(env_err(format!(
                "'app_id' {:?} does not match the required waddles.<mod>.<feature>.<variant> shape",
                raw.app_id
            )));
        }
        validate_rfc3339_millis_z("ts", &raw.ts)?;
        if !is_valid_uuid(&raw.workstream_id) {
            return Err(env_err(format!(
                "'workstream_id' {:?} is not a valid UUID",
                raw.workstream_id
            )));
        }
        if !is_valid_uuid_v4(&raw.event_id) {
            return Err(env_err(format!(
                "'event_id' {:?} is not a valid UUID v4",
                raw.event_id
            )));
        }
        if let Some(session_id) = &raw.session_id
            && session_id.is_empty()
        {
            return Err(env_err(
                "'session_id' must be a non-empty string when present, got \"\"",
            ));
        }
        Ok(StageEnvelope {
            schema_version: raw.schema_version,
            tenant: raw.tenant,
            community: raw.community,
            app_id: raw.app_id,
            stage: raw.stage,
            event: raw.event,
            ts: raw.ts,
            target_app_id: raw.target_app_id,
            workstream_id: raw.workstream_id,
            event_id: raw.event_id,
            session_id: raw.session_id,
            trace: raw.trace,
            binding: raw.binding,
        })
    }
}

impl<'de> Deserialize<'de> for StageEnvelope {
    fn deserialize<D>(deserializer: D) -> Result<Self, D::Error>
    where
        D: serde::Deserializer<'de>,
    {
        let raw = RawStageEnvelope::deserialize(deserializer)?;
        StageEnvelope::try_from(raw).map_err(serde::de::Error::custom)
    }
}

impl From<serde_json::Error> for EnvelopeError {
    fn from(e: serde_json::Error) -> Self {
        env_err(e.to_string())
    }
}

#[cfg(test)]
mod tests {
    #![allow(clippy::unwrap_used)]
    use super::*;
    use serde_json::json;

    fn valid_event_json() -> Value {
        json!({
            "platform": "twitch",
            "event_type": "chat.message",
            "actor": "some_user",
            "payload": {"text": "!songrequest foo", "channel_id": "12345", "message_id": "abc"},
            "occurred_at": "2026-09-14T12:00:00.000Z",
            "source": {"platform": "twitch", "account_id": "bot-primary", "channel_id": "12345"}
        })
    }

    #[test]
    fn deserializes_a_fully_populated_valid_event() {
        let event: PlatformEvent = serde_json::from_value(valid_event_json()).unwrap();
        assert_eq!(event.platform, "twitch");
        assert_eq!(event.event_type, "chat.message");
        assert_eq!(event.actor.as_deref(), Some("some_user"));
        assert_eq!(event.payload.get("text").unwrap(), "!songrequest foo");
        assert_eq!(event.occurred_at, "2026-09-14T12:00:00.000Z");
        assert_eq!(event.source.as_ref().unwrap().account_id, "bot-primary");
    }

    #[test]
    fn actor_and_source_are_optional() {
        let mut v = valid_event_json();
        v.as_object_mut().unwrap().remove("source");
        v["actor"] = Value::Null;
        let event: PlatformEvent = serde_json::from_value(v).unwrap();
        assert_eq!(event.actor, None);
        assert_eq!(event.source, None);
    }

    #[test]
    fn empty_payload_object_is_valid() {
        let mut v = valid_event_json();
        v["payload"] = json!({});
        let event: PlatformEvent = serde_json::from_value(v).unwrap();
        assert!(event.payload.is_empty());
    }

    #[test]
    fn rejects_empty_platform() {
        let mut v = valid_event_json();
        v["platform"] = json!("");
        assert!(serde_json::from_value::<PlatformEvent>(v).is_err());
    }

    #[test]
    fn rejects_empty_event_type() {
        let mut v = valid_event_json();
        v["event_type"] = json!("");
        assert!(serde_json::from_value::<PlatformEvent>(v).is_err());
    }

    #[test]
    fn rejects_missing_required_field() {
        let mut v = valid_event_json();
        v.as_object_mut().unwrap().remove("occurred_at");
        assert!(serde_json::from_value::<PlatformEvent>(v).is_err());
    }

    #[test]
    fn rejects_unknown_top_level_key() {
        let mut v = valid_event_json();
        v["extra_field"] = json!("nope");
        assert!(serde_json::from_value::<PlatformEvent>(v).is_err());
    }

    #[test]
    fn rejects_non_object_payload() {
        let mut v = valid_event_json();
        v["payload"] = json!("not-an-object");
        assert!(serde_json::from_value::<PlatformEvent>(v).is_err());
    }

    #[test]
    fn rejects_wrong_typed_field() {
        let mut v = valid_event_json();
        v["platform"] = json!(12345);
        assert!(serde_json::from_value::<PlatformEvent>(v).is_err());
    }

    #[test]
    fn rejects_occurred_at_without_z_suffix() {
        let mut v = valid_event_json();
        v["occurred_at"] = json!("2026-09-14T12:00:00.000+00:00");
        assert!(serde_json::from_value::<PlatformEvent>(v).is_err());
    }

    #[test]
    fn rejects_malformed_occurred_at() {
        let mut v = valid_event_json();
        v["occurred_at"] = json!("not-a-timestamp");
        assert!(serde_json::from_value::<PlatformEvent>(v).is_err());
    }

    #[test]
    fn rejects_source_platform_mismatch() {
        let mut v = valid_event_json();
        v["source"]["platform"] = json!("discord");
        assert!(serde_json::from_value::<PlatformEvent>(v).is_err());
    }

    #[test]
    fn round_trips_through_serialize_and_deserialize() {
        let event: PlatformEvent = serde_json::from_value(valid_event_json()).unwrap();
        let out = serde_json::to_value(&event).unwrap();
        assert_eq!(out, valid_event_json());
    }

    fn valid_stage_envelope_json() -> Value {
        json!({
            "schema_version": 2,
            "tenant": "global",
            "community": null,
            "app_id": "waddles.bot.commands.default",
            "stage": "process",
            "event": valid_event_json(),
            "ts": "2026-09-14T12:00:00.123Z",
            "target_app_id": null,
            "workstream_id": "8f14e45f-ceea-467e-adde-3fb5c9752730",
            "event_id": "3fa85f64-5717-4562-b3fc-2c963f66afa6",
            "session_id": null,
            "trace": {
                "traceparent": "00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01",
                "tracestate": null
            },
            "binding": {
                "kid": "2026-09",
                "mac": "9f86d081884c7d659a2feaa0c55ad015a3bf4f1b2b0b822cd15d6c15b0f00a08"
            }
        })
    }

    #[test]
    fn deserializes_a_fully_populated_stage_envelope() {
        let env: StageEnvelope = serde_json::from_value(valid_stage_envelope_json()).unwrap();
        assert_eq!(env.schema_version, 2);
        assert_eq!(env.tenant, "global");
        assert_eq!(env.community, None);
        assert_eq!(env.app_id, "waddles.bot.commands.default");
        assert_eq!(env.stage, "process");
        assert_eq!(env.target_app_id, None);
        assert_eq!(env.workstream_id, "8f14e45f-ceea-467e-adde-3fb5c9752730");
        assert_eq!(env.event_id, "3fa85f64-5717-4562-b3fc-2c963f66afa6");
        assert_eq!(env.session_id, None);
        assert_eq!(
            env.trace.as_ref().map(|t| t.traceparent.as_str()),
            Some("00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01")
        );
        assert_eq!(env.binding.kid, "2026-09");
    }

    #[test]
    fn community_scoped_and_target_app_id_set() {
        let mut v = valid_stage_envelope_json();
        v["community"] = json!("main");
        v["target_app_id"] = json!("waddles.community.forums.default");
        let env: StageEnvelope = serde_json::from_value(v).unwrap();
        assert_eq!(env.community.as_deref(), Some("main"));
        assert_eq!(
            env.target_app_id.as_deref(),
            Some("waddles.community.forums.default")
        );
    }

    #[test]
    fn trace_absent_deserializes_to_none() {
        let mut v = valid_stage_envelope_json();
        v.as_object_mut().unwrap().remove("trace");
        let env: StageEnvelope = serde_json::from_value(v).unwrap();
        assert_eq!(env.trace, None);
    }

    #[test]
    fn session_id_present_round_trips() {
        let mut v = valid_stage_envelope_json();
        v["session_id"] = json!("gw-session-abc123");
        let env: StageEnvelope = serde_json::from_value(v).unwrap();
        assert_eq!(env.session_id.as_deref(), Some("gw-session-abc123"));
    }

    #[test]
    fn rejects_stage_outside_fixed_set() {
        let mut v = valid_stage_envelope_json();
        v["stage"] = json!("bogus");
        assert!(serde_json::from_value::<StageEnvelope>(v).is_err());
    }

    #[test]
    fn rejects_app_id_with_too_few_segments() {
        let mut v = valid_stage_envelope_json();
        v["app_id"] = json!("waddles.bot");
        assert!(serde_json::from_value::<StageEnvelope>(v).is_err());
    }

    #[test]
    fn rejects_app_id_without_waddles_prefix() {
        let mut v = valid_stage_envelope_json();
        v["app_id"] = json!("other.bot.commands.default");
        assert!(serde_json::from_value::<StageEnvelope>(v).is_err());
    }

    #[test]
    fn rejects_empty_tenant() {
        let mut v = valid_stage_envelope_json();
        v["tenant"] = json!("");
        assert!(serde_json::from_value::<StageEnvelope>(v).is_err());
    }

    #[test]
    fn rejects_missing_event_key_legacy_shape() {
        let mut v = valid_stage_envelope_json();
        v.as_object_mut().unwrap().remove("event");
        v["text"] = json!("legacy shape carried data at the top level");
        assert!(serde_json::from_value::<StageEnvelope>(v).is_err());
    }

    #[test]
    fn rejects_non_object_event() {
        let mut v = valid_stage_envelope_json();
        v["event"] = json!("not-an-object");
        assert!(serde_json::from_value::<StageEnvelope>(v).is_err());
    }

    #[test]
    fn rejects_malformed_traceparent() {
        let mut v = valid_stage_envelope_json();
        v["trace"] = json!({"traceparent": "not-a-traceparent", "tracestate": null});
        assert!(serde_json::from_value::<StageEnvelope>(v).is_err());
    }

    #[test]
    fn rejects_unknown_top_level_key_on_stage_envelope() {
        let mut v = valid_stage_envelope_json();
        v["extra"] = json!("nope");
        assert!(serde_json::from_value::<StageEnvelope>(v).is_err());
    }

    #[test]
    fn rejects_schema_version_1() {
        let mut v = valid_stage_envelope_json();
        v["schema_version"] = json!(1);
        let err = serde_json::from_value::<StageEnvelope>(v).unwrap_err();
        assert!(err.to_string().contains("schema_version"));
    }

    #[test]
    fn rejects_missing_schema_version() {
        let mut v = valid_stage_envelope_json();
        v.as_object_mut().unwrap().remove("schema_version");
        assert!(serde_json::from_value::<StageEnvelope>(v).is_err());
    }

    #[test]
    fn rejects_missing_workstream_id() {
        let mut v = valid_stage_envelope_json();
        v.as_object_mut().unwrap().remove("workstream_id");
        assert!(serde_json::from_value::<StageEnvelope>(v).is_err());
    }

    #[test]
    fn rejects_non_uuid_workstream_id() {
        let mut v = valid_stage_envelope_json();
        v["workstream_id"] = json!("not-a-uuid");
        assert!(serde_json::from_value::<StageEnvelope>(v).is_err());
    }

    #[test]
    fn rejects_missing_event_id() {
        let mut v = valid_stage_envelope_json();
        v.as_object_mut().unwrap().remove("event_id");
        assert!(serde_json::from_value::<StageEnvelope>(v).is_err());
    }

    #[test]
    fn rejects_event_id_that_is_not_uuid_v4() {
        let mut v = valid_stage_envelope_json();
        // A well-formed but v1 (time-based) UUID -- valid UUID, wrong version.
        v["event_id"] = json!("6ba7b810-9dad-11d1-80b4-00c04fd430c8");
        let err = serde_json::from_value::<StageEnvelope>(v).unwrap_err();
        assert!(err.to_string().contains("event_id"));
    }

    #[test]
    fn rejects_missing_binding() {
        let mut v = valid_stage_envelope_json();
        v.as_object_mut().unwrap().remove("binding");
        assert!(serde_json::from_value::<StageEnvelope>(v).is_err());
    }

    #[test]
    fn rejects_binding_mac_wrong_length() {
        let mut v = valid_stage_envelope_json();
        v["binding"]["mac"] = json!("deadbeef");
        assert!(serde_json::from_value::<StageEnvelope>(v).is_err());
    }

    #[test]
    fn rejects_binding_mac_with_uppercase_hex() {
        let mut v = valid_stage_envelope_json();
        v["binding"]["mac"] =
            json!("9F86D081884C7D659A2FEAA0C55AD015A3BF4F1B2B0B822CD15D6C15B0F00A0");
        assert!(serde_json::from_value::<StageEnvelope>(v).is_err());
    }

    #[test]
    fn rejects_empty_binding_kid() {
        let mut v = valid_stage_envelope_json();
        v["binding"]["kid"] = json!("");
        assert!(serde_json::from_value::<StageEnvelope>(v).is_err());
    }

    #[test]
    fn rejects_empty_session_id() {
        let mut v = valid_stage_envelope_json();
        v["session_id"] = json!("");
        assert!(serde_json::from_value::<StageEnvelope>(v).is_err());
    }

    #[test]
    fn trace_id_from_traceparent_extracts_the_32_hex_segment() {
        assert_eq!(
            trace_id_from_traceparent("00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01"),
            Some("4bf92f3577b34da6a3ce929d0e0e4736")
        );
        assert_eq!(trace_id_from_traceparent("not-a-traceparent"), None);
    }

    #[test]
    fn stage_envelope_round_trips_through_serialize_and_deserialize() {
        let env: StageEnvelope = serde_json::from_value(valid_stage_envelope_json()).unwrap();
        let out = serde_json::to_value(&env).unwrap();
        assert_eq!(out, valid_stage_envelope_json());
    }
}
