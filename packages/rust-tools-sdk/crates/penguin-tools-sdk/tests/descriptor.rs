//! Descriptor validation, canonical schema output, and failure bounding.
#![allow(clippy::unwrap_used, clippy::expect_used)]

use penguin_tools_sdk::{
    canonical_json, schema_json, DescriptorError, Effect, ToolDescriptor, ToolFailure,
    MAX_FAILURE_BYTES, MAX_PAYLOAD_BYTES,
};
use schemars::JsonSchema;

#[derive(JsonSchema)]
#[allow(dead_code)]
struct Sample {
    zeta: String,
    alpha: u32,
}

fn build(name: &str, version: &str, caps: &[&str]) -> Result<ToolDescriptor, DescriptorError> {
    ToolDescriptor::new(
        name,
        version,
        "A sample tool",
        "{}".to_string(),
        "{}".to_string(),
        Effect::Read,
        caps,
    )
}

#[test]
fn accepts_a_valid_descriptor() {
    let d = build(
        "echo.v2-test_1",
        "1.2.3",
        &["penguin:http", "waddle:reputation"],
    )
    .unwrap();
    assert_eq!(d.name, "echo.v2-test_1");
    assert_eq!(d.capabilities, vec!["penguin:http", "waddle:reputation"]);
    assert_eq!(d.effect, Effect::Read);
}

#[test]
fn accepts_connector_capability_ids() {
    assert!(build("send", "0.1.0", &["penguin:connector.twitch"]).is_ok());
}

#[test]
fn rejects_bad_names() {
    for bad in [
        "",
        "Echo",
        "1echo",
        "has space",
        "ünï",
        &"a".repeat(65),
        "a/b",
    ] {
        assert!(
            matches!(
                build(bad, "1.0.0", &[]),
                Err(DescriptorError::InvalidName(_))
            ),
            "name {bad:?} should be rejected"
        );
    }
}

#[test]
fn accepts_name_at_the_length_limit() {
    assert!(build(&"a".repeat(64), "1.0.0", &[]).is_ok());
}

#[test]
fn rejects_bad_versions() {
    for bad in [
        "", "1", "1.2", "1.2.3.4", "a.b.c", "1.2.x", "01.2.3", "v1.2.3",
    ] {
        assert!(
            matches!(
                build("echo", bad, &[]),
                Err(DescriptorError::InvalidVersion(_))
            ),
            "version {bad:?} should be rejected"
        );
    }
}

#[test]
fn rejects_non_namespaced_or_malformed_capabilities() {
    for bad in [
        "http",
        "penguin:",
        ":http",
        "Penguin:http",
        "penguin:ht tp",
        "a:b:c",
        "",
    ] {
        assert!(
            matches!(
                build("echo", "1.0.0", &[bad]),
                Err(DescriptorError::InvalidCapability(_))
            ),
            "capability {bad:?} should be rejected"
        );
    }
}

#[test]
fn rejects_duplicate_capabilities() {
    assert!(matches!(
        build("echo", "1.0.0", &["penguin:http", "penguin:http"]),
        Err(DescriptorError::DuplicateCapability(_))
    ));
}

#[test]
fn rejects_empty_or_oversized_description() {
    let empty = ToolDescriptor::new(
        "echo",
        "1.0.0",
        "",
        "{}".into(),
        "{}".into(),
        Effect::Read,
        &[],
    );
    assert!(matches!(empty, Err(DescriptorError::InvalidDescription)));
    let big = "x".repeat(1025);
    let oversized = ToolDescriptor::new(
        "echo",
        "1.0.0",
        &big,
        "{}".into(),
        "{}".into(),
        Effect::Read,
        &[],
    );
    assert!(matches!(
        oversized,
        Err(DescriptorError::InvalidDescription)
    ));
}

#[test]
fn rejects_schemas_that_are_not_json() {
    let r = ToolDescriptor::new(
        "echo",
        "1.0.0",
        "d",
        "not json".into(),
        "{}".into(),
        Effect::Read,
        &[],
    );
    assert!(matches!(r, Err(DescriptorError::InvalidSchema(_))));
    let r = ToolDescriptor::new(
        "echo",
        "1.0.0",
        "d",
        "{}".into(),
        "{".into(),
        Effect::Read,
        &[],
    );
    assert!(matches!(r, Err(DescriptorError::InvalidSchema(_))));
}

#[test]
fn schema_output_is_canonical_and_stable() {
    let a = schema_json::<Sample>().unwrap();
    let b = schema_json::<Sample>().unwrap();
    assert_eq!(a, b);
    let alpha = a.find("\"alpha\"").unwrap();
    let zeta = a.find("\"zeta\"").unwrap();
    assert!(alpha < zeta, "keys must be sorted: {a}");
    assert!(
        !a.contains(' ') && !a.contains('\n'),
        "no insignificant whitespace: {a}"
    );
}

#[test]
fn canonical_json_sorts_nested_keys() {
    let v: serde_json::Value =
        serde_json::from_str(r#"{"b":{"z":1,"a":[{"y":1,"x":2}]},"a":null}"#).unwrap();
    assert_eq!(
        canonical_json(&v),
        r#"{"a":null,"b":{"a":[{"x":2,"y":1}],"z":1}}"#
    );
}

#[test]
fn effect_serializes_lowercase() {
    assert_eq!(
        serde_json::to_string(&Effect::Destructive).unwrap(),
        "\"destructive\""
    );
    assert_eq!(Effect::Write.as_str(), "write");
}

#[test]
fn failure_is_bounded_on_a_char_boundary() {
    let long = "é".repeat(600);
    let f = ToolFailure::new(long);
    assert!(f.message().len() <= MAX_FAILURE_BYTES);
    assert!(f.message().is_char_boundary(f.message().len()));
    assert!(!f.message().is_empty());
}

#[test]
fn short_failure_is_unchanged() {
    assert_eq!(ToolFailure::new("nope").message(), "nope");
}

#[test]
fn payload_limit_is_one_mebibyte() {
    assert_eq!(MAX_PAYLOAD_BYTES, 1024 * 1024);
}
