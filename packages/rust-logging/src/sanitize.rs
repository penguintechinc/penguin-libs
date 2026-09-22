//! Sanitization, ported verbatim from the Python `penguin-utils`
//! `penguintechinc_utils.logging` module
//! (`packages/python-utils/src/penguintechinc_utils/logging.py`:
//! `SENSITIVE_KEYS`, `EMAIL_REGEX`, `sanitize_log_data`), per
//! `rules/critical-rules.md` Observability ("Sanitization applies at every
//! level ... secrets never reach any level, DEBUG included") and spec §4.9
//! ("Ports the `SENSITIVE_KEYS` sanitization contract ... verbatim").
//!
//! This is the single choke point every log line and OTel log record
//! passes through -- see [`crate::layer::SanitizingLayer`], which is the
//! only caller of [`sanitize_object`] in this crate.

use std::sync::LazyLock;

use regex::Regex;
use serde_json::{Map, Value};

/// Keys that must never be logged in the clear -- the exact set from the
/// Python implementation, matched case-insensitively by exact key or
/// substring (e.g. `user_password_hash` is redacted because it contains
/// `password`).
pub const SENSITIVE_KEYS: &[&str] = &[
    "password",
    "passwd",
    "secret",
    "token",
    "api_key",
    "apikey",
    "auth_token",
    "authtoken",
    "access_token",
    "refresh_token",
    "credential",
    "credentials",
    "mfa_code",
    "totp_code",
    "otp",
    "captcha_token",
    "session_id",
    "sessionid",
    "cookie",
    "authorization",
];

/// The literal redaction value used for sensitive keys, matching the Python
/// implementation's `"[REDACTED]"` exactly.
pub const REDACTED: &str = "[REDACTED]";

/// The literal value used when a string value looks email-shaped but splits
/// into anything other than exactly two `@`-delimited parts, matching the
/// Python implementation's `"[REDACTED_EMAIL]"` exactly.
pub const REDACTED_EMAIL: &str = "[REDACTED_EMAIL]";

/// Anchored at the start of the string (`^`), mirroring Python's
/// `re.Pattern.match`, which only requires the pattern to match starting at
/// position 0 -- not the whole string. `regex`'s `^` without the multi-line
/// flag is `\A`-equivalent, so this reproduces that semantics exactly.
///
/// Invariant: this pattern is a fixed string literal verified valid by this
/// module's own test suite (`email_regex_compiles`); a `LazyLock` panic here
/// would mean the crate itself is broken, not a runtime/input condition.
static EMAIL_REGEX: LazyLock<Regex> = LazyLock::new(|| {
    Regex::new(r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}")
        .expect("EMAIL_REGEX pattern is a fixed literal, valid by construction")
});

/// Returns `true` when `key_lower` (already lowercased by the caller) is or
/// contains one of [`SENSITIVE_KEYS`].
fn is_sensitive_key(key_lower: &str) -> bool {
    SENSITIVE_KEYS
        .iter()
        .any(|sensitive| key_lower == *sensitive || key_lower.contains(sensitive))
}

/// Sanitizes a single string value: email-shaped values are replaced with
/// `[email]@{domain}` (or `[REDACTED_EMAIL]` when the value contains more
/// than one `@`), everything else passes through unchanged. Verbatim port
/// of the Python `if "@" in value and EMAIL_REGEX.match(value)` branch,
/// including its `value.split("@")` behavior on multi-`@` strings.
fn sanitize_string(value: &str) -> Value {
    if value.contains('@') && EMAIL_REGEX.is_match(value) {
        let parts: Vec<&str> = value.split('@').collect();
        if parts.len() == 2 {
            Value::String(format!("[email]@{}", parts[1]))
        } else {
            Value::String(REDACTED_EMAIL.to_string())
        }
    } else {
        Value::String(value.to_string())
    }
}

/// Sanitizes a single JSON value, recursing into nested objects and into
/// object items of arrays (non-object array items pass through unchanged,
/// matching the Python implementation's list-comprehension behavior).
fn sanitize_value(value: &Value) -> Value {
    match value {
        Value::String(s) => sanitize_string(s),
        Value::Object(map) => Value::Object(sanitize_object(map)),
        Value::Array(items) => Value::Array(
            items
                .iter()
                .map(|item| match item {
                    Value::Object(map) => Value::Object(sanitize_object(map)),
                    other => other.clone(),
                })
                .collect(),
        ),
        other => other.clone(),
    }
}

/// Sanitizes a flat or nested JSON object for safe logging: keys matching
/// [`SENSITIVE_KEYS`] (exact or substring, case-insensitive) become
/// `"[REDACTED]"`; string values that look like emails are reduced to
/// `[email]@{domain}`; nested objects and arrays-of-objects recurse.
///
/// This is the Rust equivalent of the Python `sanitize_log_data`, operating
/// on a `serde_json::Map` (JSON object) instead of a `dict[str, Any]`. It is
/// pure and side-effect free, callable both from [`crate::layer`] on every
/// log event and directly by tests proving the redaction contract.
pub fn sanitize_object(data: &Map<String, Value>) -> Map<String, Value> {
    let mut sanitized = Map::with_capacity(data.len());
    for (key, value) in data {
        let key_lower = key.to_lowercase();
        if is_sensitive_key(&key_lower) {
            sanitized.insert(key.clone(), Value::String(REDACTED.to_string()));
        } else {
            sanitized.insert(key.clone(), sanitize_value(value));
        }
    }
    sanitized
}

#[cfg(test)]
mod tests {
    // `json!(...).as_object().unwrap()` on a literal we just wrote is
    // provably infallible; denying `unwrap_used` crate-wide is for
    // production code paths, not test fixtures built from object literals.
    #![allow(clippy::unwrap_used)]
    use super::*;
    use rstest::rstest;
    use serde_json::json;

    #[test]
    fn email_regex_compiles() {
        // Forces the LazyLock's initializer to run under test, proving the
        // "valid by construction" invariant documented on EMAIL_REGEX.
        assert!(EMAIL_REGEX.is_match("a@b.co"));
    }

    #[rstest]
    #[case("password", true)]
    #[case("PASSWORD", true)]
    #[case("passwd", true)]
    #[case("user_password_hash", true)] // substring match
    #[case("secret", true)]
    #[case("api_key", true)]
    #[case("apikey", true)]
    #[case("auth_token", true)]
    #[case("access_token", true)]
    #[case("refresh_token", true)]
    #[case("credential", true)]
    #[case("credentials", true)]
    #[case("mfa_code", true)]
    #[case("totp_code", true)]
    #[case("otp", true)]
    #[case("captcha_token", true)]
    #[case("session_id", true)]
    #[case("sessionid", true)]
    #[case("cookie", true)]
    #[case("authorization", true)]
    #[case("Authorization", true)]
    #[case("username", false)]
    #[case("message", false)]
    #[case("stage", false)]
    fn sensitive_key_detection(#[case] key: &str, #[case] expected: bool) {
        assert_eq!(is_sensitive_key(&key.to_lowercase()), expected);
    }

    #[test]
    fn sensitive_key_value_is_redacted_regardless_of_content() {
        let data = json!({"password": "hunter2"}).as_object().unwrap().clone();
        let sanitized = sanitize_object(&data);
        assert_eq!(sanitized["password"], json!(REDACTED));
    }

    #[rstest]
    #[case("token", "sk-abc123-super-secret")]
    #[case("api_key", "AKIA-real-key-value")]
    #[case("secret", "correct-horse-battery-staple")]
    #[case("credential", "swordfish")]
    #[case("mfa_code", "123456")]
    #[case("session_id", "sess-abcdef0123456789")]
    #[case("authorization", "Bearer eyJhbGciOi.secret.tok")]
    fn known_secret_values_never_survive_sanitization(
        #[case] key: &str,
        #[case] secret_value: &str,
    ) {
        let mut data = Map::new();
        data.insert(key.to_string(), Value::String(secret_value.to_string()));
        let sanitized = sanitize_object(&data);
        let rendered = serde_json::to_string(&sanitized).expect("map serializes");
        assert!(
            !rendered.contains(secret_value),
            "secret value {secret_value:?} leaked through sanitize_object for key {key:?}: {rendered}"
        );
        assert_eq!(sanitized[key], json!(REDACTED));
    }

    #[test]
    fn single_at_email_becomes_domain_only() {
        let mut data = Map::new();
        data.insert(
            "email".to_string(),
            Value::String("user@example.com".to_string()),
        );
        let sanitized = sanitize_object(&data);
        assert_eq!(sanitized["email"], json!("[email]@example.com"));
    }

    #[test]
    fn multi_at_value_becomes_redacted_email() {
        // Must still match EMAIL_REGEX from position 0 (matches on the
        // "user@example.com" prefix) while containing a second "@" later,
        // so `value.split("@")` yields more than two parts -- a value like
        // "a@b@example.com" never reaches the email branch at all, because
        // the domain char class excludes "@" and there is no valid
        // `\.[a-zA-Z]{2,}` before the second "@" to match against.
        let mut data = Map::new();
        data.insert(
            "note".to_string(),
            Value::String("user@example.com@evil".to_string()),
        );
        let sanitized = sanitize_object(&data);
        assert_eq!(sanitized["note"], json!(REDACTED_EMAIL));
    }

    #[test]
    fn non_email_string_passes_through_unchanged() {
        let mut data = Map::new();
        data.insert(
            "message".to_string(),
            Value::String("bundle loaded".to_string()),
        );
        let sanitized = sanitize_object(&data);
        assert_eq!(sanitized["message"], json!("bundle loaded"));
    }

    #[test]
    fn value_not_starting_with_email_is_left_alone() {
        // Python's re.match anchors at position 0; a value containing "@"
        // later in the string but not starting with an email-shaped prefix
        // must not be treated as an email.
        let mut data = Map::new();
        data.insert(
            "message".to_string(),
            Value::String("ping user@example.com please".to_string()),
        );
        let sanitized = sanitize_object(&data);
        assert_eq!(sanitized["message"], json!("ping user@example.com please"));
    }

    #[test]
    fn nested_object_recurses() {
        let data = json!({
            "user": {"name": "alice", "password": "hunter2"}
        })
        .as_object()
        .unwrap()
        .clone();
        let sanitized = sanitize_object(&data);
        let user = sanitized["user"]
            .as_object()
            .expect("nested object preserved");
        assert_eq!(user["name"], json!("alice"));
        assert_eq!(user["password"], json!(REDACTED));
    }

    #[test]
    fn list_of_objects_recurses_but_scalars_pass_through() {
        let data = json!({
            "items": [
                {"token": "abc123"},
                "plain-string",
                42,
            ]
        })
        .as_object()
        .unwrap()
        .clone();
        let sanitized = sanitize_object(&data);
        let items = sanitized["items"].as_array().expect("array preserved");
        assert_eq!(items[0]["token"], json!(REDACTED));
        assert_eq!(items[1], json!("plain-string"));
        assert_eq!(items[2], json!(42));
    }

    #[test]
    fn numbers_and_bools_pass_through_untouched() {
        let data = json!({"count": 3, "enabled": true, "ratio": 1.5})
            .as_object()
            .unwrap()
            .clone();
        let sanitized = sanitize_object(&data);
        assert_eq!(sanitized["count"], json!(3));
        assert_eq!(sanitized["enabled"], json!(true));
        assert_eq!(sanitized["ratio"], json!(1.5));
    }

    #[test]
    fn empty_object_sanitizes_to_empty_object() {
        let sanitized = sanitize_object(&Map::new());
        assert!(sanitized.is_empty());
    }
}
