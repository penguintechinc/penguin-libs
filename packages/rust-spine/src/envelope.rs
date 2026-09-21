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
        return Err(env_err(format!("{field:?} must be a non-empty string, got \"\"")));
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
        if let Some(source) = &raw.source {
            if source.platform != raw.platform {
                return Err(env_err(format!(
                    "'source.platform' ({:?}) must equal the top-level 'platform' ({:?})",
                    source.platform, raw.platform
                )));
            }
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
}
