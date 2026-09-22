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

use hmac::{Hmac, Mac};
use sha2::Sha256;
use subtle::ConstantTimeEq;

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
    /// A message type this crate does not route — ack 200, fan out nothing.
    Ignored,
}

/// Verify and route one EventSub webhook POST end to end.
///
/// Mirrors `TwitchEventSubHandler.handle_webhook`'s verify-then-route shape,
/// minus the fan-out call itself (out of scope for this crate — see the
/// crate root doc).
#[must_use]
pub fn handle_webhook(
    secret: &str,
    headers: &HashMap<String, String>,
    body: &[u8],
    body_json: &serde_json::Value,
) -> WebhookOutcome {
    if !verify_signature(secret, headers, body) {
        return WebhookOutcome::InvalidSignature;
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
            WebhookOutcome::Notification {
                event_type,
                event,
                subscription,
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

    #[test]
    fn handle_webhook_invalid_signature() {
        let body = b"{}";
        let body_json = serde_json::json!({});
        let headers = HashMap::new();
        assert_eq!(
            handle_webhook(SECRET, &headers, body, &body_json),
            WebhookOutcome::InvalidSignature
        );
    }

    #[test]
    fn handle_webhook_challenge_flow() {
        let body_json = serde_json::json!({"challenge": "xyz"});
        let body = serde_json::to_vec(&body_json).expect("json body");
        let mut headers = signed_headers("m1", "t1", &body);
        headers.insert(
            HEADER_MESSAGE_TYPE.to_string(),
            MESSAGE_TYPE_CHALLENGE.to_string(),
        );
        assert_eq!(
            handle_webhook(SECRET, &headers, &body, &body_json),
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
        let mut headers = signed_headers("m1", "t1", &body);
        headers.insert(
            HEADER_MESSAGE_TYPE.to_string(),
            MESSAGE_TYPE_NOTIFICATION.to_string(),
        );
        let outcome = handle_webhook(SECRET, &headers, &body, &body_json);
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
        let mut headers = signed_headers("m1", "t1", &body);
        headers.insert(HEADER_MESSAGE_TYPE.to_string(), "revocation".to_string());
        assert_eq!(
            handle_webhook(SECRET, &headers, &body, &body_json),
            WebhookOutcome::Ignored
        );
    }
}
