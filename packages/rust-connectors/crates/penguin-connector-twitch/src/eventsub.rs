//! Twitch EventSub webhook signature verification + challenge handling.
//!
//! Byte-identical algorithm to `core/svc_ingest/eventsub.py::verify_signature`
//! in the `waddles` repo: `sha256=` + hex HMAC-SHA256 of
//! `message_id + timestamp + body` under the EventSub secret, compared in
//! constant time. This module owns exactly the webhook verification and
//! challenge-echo steps (design spec §10.1/§10.2) — normalizing a
//! notification into a `PlatformEvent` is `core/svc_ingest`'s job, not this
//! crate's (see the crate root doc).

use std::collections::HashMap;
use std::sync::Mutex;
use std::time::{Duration, Instant};

use hmac::{Hmac, Mac};
use sha2::Sha256;
use subtle::ConstantTimeEq;
use time::format_description::well_known::Rfc3339;
use time::OffsetDateTime;

/// `Twitch-Eventsub-Message-Type` header name.
pub const HEADER_MESSAGE_TYPE: &str = "Twitch-Eventsub-Message-Type";
/// `Twitch-Eventsub-Message-Signature` header name.
pub const HEADER_SIGNATURE: &str = "Twitch-Eventsub-Message-Signature";
/// `Twitch-Eventsub-Message-Timestamp` header name.
pub const HEADER_TIMESTAMP: &str = "Twitch-Eventsub-Message-Timestamp";
/// `Twitch-Eventsub-Message-Id` header name.
pub const HEADER_MESSAGE_ID: &str = "Twitch-Eventsub-Message-Id";

/// The EventSub message type carrying the subscription-setup handshake.
pub const MESSAGE_TYPE_CHALLENGE: &str = "webhook_callback_verification";
/// The EventSub message type carrying a real event notification.
pub const MESSAGE_TYPE_NOTIFICATION: &str = "notification";
/// The EventSub message type Twitch sends when it revokes a subscription.
pub const MESSAGE_TYPE_REVOCATION: &str = "revocation";

/// `subscription.type` values this crate routes as [`WebhookOutcome::Notification`]
/// -- mirrors `core/svc_ingest/eventsub.py::DEFAULT_SUBSCRIPTION_TYPES` (the
/// `waddles` repo) byte-for-byte. A `notification` whose type is not in this
/// set is [`WebhookOutcome::Ignored`] rather than forwarded as though it
/// were a known event.
pub const KNOWN_EVENT_TYPES: [&str; 7] = [
    "channel.follow",
    "channel.subscribe",
    "channel.subscription.gift",
    "channel.cheer",
    "channel.raid",
    "stream.online",
    "stream.offline",
];

/// Replay-protection window (design spec §11.1 / §10.1): a signed message
/// whose `Twitch-Eventsub-Message-Timestamp` is more than this far from
/// "now", in either direction, is rejected as stale -- and
/// `Twitch-Eventsub-Message-Id` values are remembered for this same
/// duration to reject an exact resend. 600s (10 minutes) matches Twitch's
/// own documented timestamp tolerance; configurable via
/// [`ReplayGuard::with_window`].
pub const DEFAULT_REPLAY_WINDOW: Duration = Duration::from_secs(600);

type HmacSha256 = Hmac<Sha256>;

/// Verify a raw EventSub signature given its three signed pieces directly.
///
/// `signature_header` is the full `sha256=<hex>` header value. Returns
/// `false` (never panics) on any mismatch — an HMAC key of any length is
/// valid per RFC 2104, so key setup cannot fail in practice; the error path
/// is handled defensively rather than assumed away.
#[must_use]
pub fn verify_signature_parts(
    secret: &[u8],
    message_id: &str,
    timestamp: &str,
    body: &[u8],
    signature_header: &str,
) -> bool {
    let Ok(mut mac) = HmacSha256::new_from_slice(secret) else {
        return false;
    };
    mac.update(message_id.as_bytes());
    mac.update(timestamp.as_bytes());
    mac.update(body);
    let digest = mac.finalize().into_bytes();
    let expected = format!("sha256={}", hex::encode(digest));
    constant_time_str_eq(&expected, signature_header)
}

/// Verify an EventSub webhook request from its headers. Byte-identical
/// behaviour to `core/svc_ingest/eventsub.py::verify_signature`: any of the
/// three required headers missing or empty fails closed (`false`), never
/// panics.
#[must_use]
pub fn verify_signature(secret: &str, headers: &HashMap<String, String>, body: &[u8]) -> bool {
    let signature = headers.get(HEADER_SIGNATURE);
    let timestamp = headers.get(HEADER_TIMESTAMP);
    let message_id = headers.get(HEADER_MESSAGE_ID);
    let (Some(signature), Some(timestamp), Some(message_id)) = (signature, timestamp, message_id)
    else {
        return false;
    };
    if signature.is_empty() || timestamp.is_empty() || message_id.is_empty() {
        return false;
    }
    verify_signature_parts(secret.as_bytes(), message_id, timestamp, body, signature)
}

/// Constant-time comparison of two signature strings.
///
/// A length mismatch still performs a same-cost dummy comparison rather
/// than short-circuiting on `len()`, per the design spec's "a length
/// mismatch still performs the comparison" rule (§10.5).
fn constant_time_str_eq(expected: &str, actual: &str) -> bool {
    let expected_bytes = expected.as_bytes();
    let actual_bytes = actual.as_bytes();
    if expected_bytes.len() != actual_bytes.len() {
        let dummy = vec![0u8; expected_bytes.len()];
        let _ = dummy.ct_eq(&dummy);
        return false;
    }
    expected_bytes.ct_eq(actual_bytes).into()
}

/// Returns whether `timestamp` (an RFC 3339 string, e.g. Twitch's
/// `Twitch-Eventsub-Message-Timestamp` header) is within `window` of `now`,
/// in either direction. An unparseable timestamp fails closed (`false`) —
/// never panics.
fn timestamp_within_window(timestamp: &str, now: OffsetDateTime, window: Duration) -> bool {
    let Ok(parsed) = OffsetDateTime::parse(timestamp, &Rfc3339) else {
        return false;
    };
    let diff_secs = (now - parsed).whole_seconds().unsigned_abs();
    diff_secs <= window.as_secs()
}

/// Tracks recently-seen `Twitch-Eventsub-Message-Id` values to reject a
/// replayed webhook delivery (design spec §11.1) — a captured, validly
/// signed POST otherwise replays forever, since the HMAC alone has no
/// notion of "already processed."
///
/// Entries are remembered for `window` and opportunistically swept on
/// every check, so the set stays bounded without a background task. One
/// instance is meant to be constructed once and shared (behind a
/// reference) across every webhook delivery for a given secret/tenant —
/// a fresh guard per call defeats the point.
pub struct ReplayGuard {
    window: Duration,
    seen: Mutex<HashMap<String, Instant>>,
}

impl ReplayGuard {
    /// New guard using [`DEFAULT_REPLAY_WINDOW`] (600s, Twitch's own
    /// timestamp tolerance).
    #[must_use]
    pub fn new() -> Self {
        Self::with_window(DEFAULT_REPLAY_WINDOW)
    }

    /// New guard with a caller-supplied window — the "configurable" half
    /// of the finding, and the test hook for deterministic expiry.
    #[must_use]
    pub fn with_window(window: Duration) -> Self {
        Self {
            window,
            seen: Mutex::new(HashMap::new()),
        }
    }

    /// Returns `true` if `message_id` was already recorded within the
    /// window (a replay) — otherwise records it as seen and returns
    /// `false`.
    ///
    /// A poisoned lock (a prior panic while some other caller held it) is
    /// recovered from rather than propagated: degrading replay protection
    /// is preferable to panicking the whole webhook path over it.
    fn check_and_record(&self, message_id: &str, now: Instant) -> bool {
        let mut seen = self
            .seen
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner);
        seen.retain(|_, seen_at| now.saturating_duration_since(*seen_at) < self.window);
        if seen.contains_key(message_id) {
            return true;
        }
        seen.insert(message_id.to_string(), now);
        false
    }
}

impl Default for ReplayGuard {
    fn default() -> Self {
        Self::new()
    }
}

/// Extract the `challenge` string from a `webhook_callback_verification`
/// body. Returns `""` when absent, matching the Python handler's
/// `body_json.get("challenge", "")`.
#[must_use]
pub fn extract_challenge(body_json: &serde_json::Value) -> String {
    body_json
        .get("challenge")
        .and_then(serde_json::Value::as_str)
        .unwrap_or("")
        .to_string()
}

/// Outcome of routing one verified EventSub webhook POST.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum WebhookOutcome {
    /// Signature failed verification — respond 403, fan out nothing.
    InvalidSignature,
    /// Signature valid, but `Twitch-Eventsub-Message-Timestamp` is outside
    /// the replay window (design spec §11.1) — respond `403 replay_window`,
    /// fan out nothing.
    StaleTimestamp,
    /// Signature and timestamp valid, but this `Twitch-Eventsub-Message-Id`
    /// was already processed within the window (design spec §11.1) —
    /// respond `409 duplicate_message_id`, fan out nothing.
    DuplicateMessageId,
    /// Subscription-setup handshake — echo `challenge` back as `text/plain`, 200.
    Challenge(String),
    /// A real event notification, still opaque JSON — `core/svc_ingest`
    /// normalizes this into a `PlatformEvent` (out of scope here).
    Notification {
        /// The `subscription.type` value (e.g. `"channel.follow"`).
        event_type: String,
        /// The raw `event` object from the webhook body.
        event: serde_json::Value,
        /// The raw `subscription` object from the webhook body.
        subscription: serde_json::Value,
    },
    /// Twitch revoked a subscription — distinct from `Ignored` so a caller
    /// can log/alert on it; ack 200, fan out nothing.
    Revocation {
        /// The revoked `subscription.type` value, if present.
        subscription_type: Option<String>,
        /// The revocation `subscription.status` value, if present (e.g.
        /// `"authorization_revoked"`, `"user_removed"`).
        status: Option<String>,
    },
    /// A message type this crate does not route — ack 200, fan out nothing.
    Ignored,
}

/// Verify and route one EventSub webhook POST end to end, using the
/// current wall-clock time for the replay-freshness check.
///
/// Mirrors `TwitchEventSubHandler.handle_webhook`'s verify-then-route shape,
/// minus the fan-out call itself (out of scope for this crate — see the
/// crate root doc), plus the replay-protection checks the Python original
/// (deliberately, per its own docstring) left out of its MVP scope (design
/// spec §11.1).
#[must_use]
pub fn handle_webhook(
    secret: &str,
    headers: &HashMap<String, String>,
    body: &[u8],
    body_json: &serde_json::Value,
    replay_guard: &ReplayGuard,
) -> WebhookOutcome {
    handle_webhook_at(
        secret,
        headers,
        body,
        body_json,
        replay_guard,
        OffsetDateTime::now_utc(),
    )
}

/// [`handle_webhook`] with the "now" used for the replay-freshness check
/// injected explicitly, so tests can exercise stale/fresh boundaries
/// deterministically without sleeping real wall-clock time.
#[must_use]
pub fn handle_webhook_at(
    secret: &str,
    headers: &HashMap<String, String>,
    body: &[u8],
    body_json: &serde_json::Value,
    replay_guard: &ReplayGuard,
    now: OffsetDateTime,
) -> WebhookOutcome {
    if !verify_signature(secret, headers, body) {
        return WebhookOutcome::InvalidSignature;
    }
    let timestamp = headers.get(HEADER_TIMESTAMP).map_or("", String::as_str);
    if !timestamp_within_window(timestamp, now, replay_guard.window) {
        return WebhookOutcome::StaleTimestamp;
    }
    let message_id = headers.get(HEADER_MESSAGE_ID).map_or("", String::as_str);
    if replay_guard.check_and_record(message_id, Instant::now()) {
        return WebhookOutcome::DuplicateMessageId;
    }
    let message_type = headers.get(HEADER_MESSAGE_TYPE).map_or("", String::as_str);
    match message_type {
        MESSAGE_TYPE_CHALLENGE => WebhookOutcome::Challenge(extract_challenge(body_json)),
        MESSAGE_TYPE_NOTIFICATION => {
            let subscription = body_json
                .get("subscription")
                .cloned()
                .unwrap_or(serde_json::Value::Null);
            let event = body_json
                .get("event")
                .cloned()
                .unwrap_or(serde_json::Value::Null);
            let event_type = subscription
                .get("type")
                .and_then(serde_json::Value::as_str)
                .unwrap_or("")
                .to_string();
            if !KNOWN_EVENT_TYPES.contains(&event_type.as_str()) {
                return WebhookOutcome::Ignored;
            }
            WebhookOutcome::Notification {
                event_type,
                event,
                subscription,
            }
        }
        MESSAGE_TYPE_REVOCATION => {
            let subscription = body_json.get("subscription");
            WebhookOutcome::Revocation {
                subscription_type: subscription
                    .and_then(|s| s.get("type"))
                    .and_then(serde_json::Value::as_str)
                    .map(str::to_string),
                status: subscription
                    .and_then(|s| s.get("status"))
                    .and_then(serde_json::Value::as_str)
                    .map(str::to_string),
            }
        }
        _ => WebhookOutcome::Ignored,
    }
}

#[cfg(test)]
#[allow(clippy::unwrap_used, clippy::expect_used)]
mod tests {
    //! Ported verbatim from `core/svc_ingest/tests/test_eventsub.py::TestVerifySignature`
    //! (the `waddles` repo) — same secret literal, same message id/timestamp/body
    //! values, same four cases. Recorded acceptance-oracle behaviour, not
    //! synthetic invention.
    use super::*;

    const SECRET: &str = "s3cr3t-eventsub-secret";

    fn signed_headers(message_id: &str, timestamp: &str, body: &[u8]) -> HashMap<String, String> {
        let mut mac =
            HmacSha256::new_from_slice(SECRET.as_bytes()).expect("hmac accepts any key length");
        mac.update(message_id.as_bytes());
        mac.update(timestamp.as_bytes());
        mac.update(body);
        let signature = format!("sha256={}", hex::encode(mac.finalize().into_bytes()));
        HashMap::from([
            (HEADER_MESSAGE_ID.to_string(), message_id.to_string()),
            (HEADER_TIMESTAMP.to_string(), timestamp.to_string()),
            (HEADER_SIGNATURE.to_string(), signature),
        ])
    }

    #[test]
    fn valid_signature_passes() {
        let body = br#"{"a": 1}"#;
        let headers = signed_headers("m1", "t1", body);
        assert!(verify_signature(SECRET, &headers, body));
    }

    #[test]
    fn wrong_secret_fails() {
        let body = br#"{"a": 1}"#;
        let headers = signed_headers("m1", "t1", body);
        assert!(!verify_signature("wrong-secret", &headers, body));
    }

    #[test]
    fn tampered_body_fails() {
        let headers = signed_headers("m1", "t1", br#"{"a": 1}"#);
        assert!(!verify_signature(SECRET, &headers, br#"{"a": 2}"#));
    }

    #[test]
    fn missing_headers_fail_closed() {
        assert!(!verify_signature(SECRET, &HashMap::new(), b"{}"));
    }

    #[test]
    fn empty_header_values_fail_closed() {
        let headers = HashMap::from([
            (HEADER_MESSAGE_ID.to_string(), String::new()),
            (HEADER_TIMESTAMP.to_string(), "t1".to_string()),
            (HEADER_SIGNATURE.to_string(), "sha256=whatever".to_string()),
        ]);
        assert!(!verify_signature(SECRET, &headers, b"{}"));
    }

    #[test]
    fn different_length_signature_fails_without_panicking() {
        let mut headers = signed_headers("m1", "t1", b"{}");
        headers.insert(HEADER_SIGNATURE.to_string(), "sha256=short".to_string());
        assert!(!verify_signature(SECRET, &headers, b"{}"));
    }

    #[test]
    fn extract_challenge_present() {
        let body = serde_json::json!({"challenge": "abc123"});
        assert_eq!(extract_challenge(&body), "abc123");
    }

    #[test]
    fn extract_challenge_absent_defaults_empty() {
        let body = serde_json::json!({});
        assert_eq!(extract_challenge(&body), "");
    }

    /// A fixed, valid RFC 3339 timestamp used by every `handle_webhook_at`
    /// test below, paired with [`fixture_now`] so the replay-freshness
    /// check passes by construction unless a test deliberately shifts
    /// `now` to exercise the window boundary.
    const FIXTURE_TIMESTAMP: &str = "2020-01-01T00:00:00Z";

    fn fixture_now() -> OffsetDateTime {
        OffsetDateTime::parse(FIXTURE_TIMESTAMP, &Rfc3339).expect("fixture timestamp parses")
    }

    #[test]
    fn handle_webhook_invalid_signature() {
        let body = b"{}";
        let body_json = serde_json::json!({});
        let headers = HashMap::new();
        assert_eq!(
            handle_webhook_at(
                SECRET,
                &headers,
                body,
                &body_json,
                &ReplayGuard::new(),
                fixture_now()
            ),
            WebhookOutcome::InvalidSignature
        );
    }

    #[test]
    fn handle_webhook_challenge_flow() {
        let body_json = serde_json::json!({"challenge": "xyz"});
        let body = serde_json::to_vec(&body_json).expect("json body");
        let mut headers = signed_headers("m1", FIXTURE_TIMESTAMP, &body);
        headers.insert(
            HEADER_MESSAGE_TYPE.to_string(),
            MESSAGE_TYPE_CHALLENGE.to_string(),
        );
        assert_eq!(
            handle_webhook_at(
                SECRET,
                &headers,
                &body,
                &body_json,
                &ReplayGuard::new(),
                fixture_now()
            ),
            WebhookOutcome::Challenge("xyz".to_string())
        );
    }

    #[test]
    fn handle_webhook_notification_flow() {
        let body_json = serde_json::json!({
            "subscription": {"type": "channel.follow"},
            "event": {"broadcaster_user_id": "999"},
        });
        let body = serde_json::to_vec(&body_json).expect("json body");
        let mut headers = signed_headers("m1", FIXTURE_TIMESTAMP, &body);
        headers.insert(
            HEADER_MESSAGE_TYPE.to_string(),
            MESSAGE_TYPE_NOTIFICATION.to_string(),
        );
        let outcome = handle_webhook_at(
            SECRET,
            &headers,
            &body,
            &body_json,
            &ReplayGuard::new(),
            fixture_now(),
        );
        match outcome {
            WebhookOutcome::Notification { event_type, .. } => {
                assert_eq!(event_type, "channel.follow")
            }
            other => panic!("expected Notification, got {other:?}"),
        }
    }

    #[test]
    fn handle_webhook_unhandled_message_type_is_ignored() {
        let body_json = serde_json::json!({});
        let body = serde_json::to_vec(&body_json).expect("json body");
        let mut headers = signed_headers("m1", FIXTURE_TIMESTAMP, &body);
        headers.insert(
            HEADER_MESSAGE_TYPE.to_string(),
            "some_future_message_type".to_string(),
        );
        assert_eq!(
            handle_webhook_at(
                SECRET,
                &headers,
                &body,
                &body_json,
                &ReplayGuard::new(),
                fixture_now()
            ),
            WebhookOutcome::Ignored
        );
    }

    // --- finding 2: unknown `subscription.type` must not be forwarded ------

    #[test]
    fn handle_webhook_unknown_event_type_is_ignored_not_forwarded() {
        let body_json = serde_json::json!({
            "subscription": {"type": "channel.update"},
            "event": {"broadcaster_user_id": "999"},
        });
        let body = serde_json::to_vec(&body_json).expect("json body");
        let mut headers = signed_headers("m1", FIXTURE_TIMESTAMP, &body);
        headers.insert(
            HEADER_MESSAGE_TYPE.to_string(),
            MESSAGE_TYPE_NOTIFICATION.to_string(),
        );
        assert_eq!(
            handle_webhook_at(
                SECRET,
                &headers,
                &body,
                &body_json,
                &ReplayGuard::new(),
                fixture_now()
            ),
            WebhookOutcome::Ignored
        );
    }

    #[test]
    fn known_event_types_matches_python_default_subscription_types() {
        for known in [
            "channel.follow",
            "channel.subscribe",
            "channel.subscription.gift",
            "channel.cheer",
            "channel.raid",
            "stream.online",
            "stream.offline",
        ] {
            assert!(KNOWN_EVENT_TYPES.contains(&known), "missing {known}");
        }
        assert_eq!(KNOWN_EVENT_TYPES.len(), 7);
    }

    // --- finding 3: revocation is distinct from a generic `Ignored` --------

    #[test]
    fn handle_webhook_revocation_flow_is_distinct_from_ignored() {
        let body_json = serde_json::json!({
            "subscription": {"type": "channel.follow", "status": "authorization_revoked"},
        });
        let body = serde_json::to_vec(&body_json).expect("json body");
        let mut headers = signed_headers("m1", FIXTURE_TIMESTAMP, &body);
        headers.insert(
            HEADER_MESSAGE_TYPE.to_string(),
            MESSAGE_TYPE_REVOCATION.to_string(),
        );
        assert_eq!(
            handle_webhook_at(
                SECRET,
                &headers,
                &body,
                &body_json,
                &ReplayGuard::new(),
                fixture_now()
            ),
            WebhookOutcome::Revocation {
                subscription_type: Some("channel.follow".to_string()),
                status: Some("authorization_revoked".to_string()),
            }
        );
    }

    #[test]
    fn handle_webhook_revocation_missing_subscription_fields_are_none() {
        let body_json = serde_json::json!({});
        let body = serde_json::to_vec(&body_json).expect("json body");
        let mut headers = signed_headers("m1", FIXTURE_TIMESTAMP, &body);
        headers.insert(
            HEADER_MESSAGE_TYPE.to_string(),
            MESSAGE_TYPE_REVOCATION.to_string(),
        );
        assert_eq!(
            handle_webhook_at(
                SECRET,
                &headers,
                &body,
                &body_json,
                &ReplayGuard::new(),
                fixture_now()
            ),
            WebhookOutcome::Revocation {
                subscription_type: None,
                status: None,
            }
        );
    }

    // --- finding 1: replay protection (timestamp freshness + id dedup) -----

    #[test]
    fn timestamp_within_window_accepts_exact_match() {
        assert!(timestamp_within_window(
            FIXTURE_TIMESTAMP,
            fixture_now(),
            DEFAULT_REPLAY_WINDOW
        ));
    }

    #[test]
    fn timestamp_within_window_accepts_up_to_the_boundary() {
        let now = fixture_now() + time::Duration::seconds(600);
        assert!(timestamp_within_window(
            FIXTURE_TIMESTAMP,
            now,
            DEFAULT_REPLAY_WINDOW
        ));
    }

    #[test]
    fn timestamp_within_window_rejects_stale_past_the_boundary() {
        let now = fixture_now() + time::Duration::seconds(601);
        assert!(!timestamp_within_window(
            FIXTURE_TIMESTAMP,
            now,
            DEFAULT_REPLAY_WINDOW
        ));
    }

    #[test]
    fn timestamp_within_window_rejects_a_timestamp_too_far_in_the_future() {
        // Symmetric: "now" is far in the past relative to the (attacker
        // supplied) timestamp, not just the usual "timestamp is old" shape.
        let now = fixture_now() - time::Duration::seconds(601);
        assert!(!timestamp_within_window(
            FIXTURE_TIMESTAMP,
            now,
            DEFAULT_REPLAY_WINDOW
        ));
    }

    #[test]
    fn timestamp_within_window_fails_closed_on_malformed_timestamp() {
        assert!(!timestamp_within_window(
            "not-a-timestamp",
            fixture_now(),
            DEFAULT_REPLAY_WINDOW
        ));
        assert!(!timestamp_within_window(
            "",
            fixture_now(),
            DEFAULT_REPLAY_WINDOW
        ));
    }

    #[test]
    fn handle_webhook_stale_timestamp_is_rejected() {
        let body_json = serde_json::json!({"challenge": "xyz"});
        let body = serde_json::to_vec(&body_json).expect("json body");
        let mut headers = signed_headers("m1", FIXTURE_TIMESTAMP, &body);
        headers.insert(
            HEADER_MESSAGE_TYPE.to_string(),
            MESSAGE_TYPE_CHALLENGE.to_string(),
        );
        let too_late = fixture_now() + time::Duration::seconds(601);
        assert_eq!(
            handle_webhook_at(
                SECRET,
                &headers,
                &body,
                &body_json,
                &ReplayGuard::new(),
                too_late
            ),
            WebhookOutcome::StaleTimestamp
        );
    }

    #[test]
    fn replay_guard_allows_first_seen_message_id() {
        let guard = ReplayGuard::new();
        assert!(!guard.check_and_record("m1", Instant::now()));
    }

    #[test]
    fn replay_guard_rejects_duplicate_within_window() {
        let guard = ReplayGuard::new();
        let now = Instant::now();
        assert!(!guard.check_and_record("m1", now));
        assert!(guard.check_and_record("m1", now));
    }

    #[test]
    fn replay_guard_allows_reuse_after_window_expires() {
        let guard = ReplayGuard::with_window(Duration::from_millis(10));
        let seen_at = Instant::now();
        assert!(!guard.check_and_record("m1", seen_at));
        let after_expiry = seen_at + Duration::from_millis(20);
        assert!(!guard.check_and_record("m1", after_expiry));
    }

    #[test]
    fn handle_webhook_duplicate_message_id_is_rejected() {
        let body_json = serde_json::json!({"challenge": "xyz"});
        let body = serde_json::to_vec(&body_json).expect("json body");
        let mut headers = signed_headers("dup-id", FIXTURE_TIMESTAMP, &body);
        headers.insert(
            HEADER_MESSAGE_TYPE.to_string(),
            MESSAGE_TYPE_CHALLENGE.to_string(),
        );
        let guard = ReplayGuard::new();

        // First delivery: signature, timestamp and id all check out.
        assert_eq!(
            handle_webhook_at(SECRET, &headers, &body, &body_json, &guard, fixture_now()),
            WebhookOutcome::Challenge("xyz".to_string())
        );

        // Twitch (or an attacker replaying the captured POST) resends the
        // exact same signed request -- same id, same timestamp.
        assert_eq!(
            handle_webhook_at(SECRET, &headers, &body, &body_json, &guard, fixture_now()),
            WebhookOutcome::DuplicateMessageId
        );
    }
}
