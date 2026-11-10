//! `#[tool]` expansion: descriptor generation from real function signatures.
#![allow(clippy::unwrap_used, clippy::expect_used)]

use penguin_tools_sdk::{tool, Effect, ToolFailure};
use schemars::JsonSchema;
use serde::{Deserialize, Serialize};

#[derive(Deserialize, JsonSchema)]
struct EchoIn {
    text: String,
}

#[derive(Serialize, JsonSchema)]
struct EchoOut {
    text: String,
}

/// Echoes its input.
#[tool(
    name = "echo",
    version = "0.1.0",
    description = "Echoes the supplied text",
    effect = "read"
)]
fn echo(input: EchoIn) -> Result<EchoOut, ToolFailure> {
    Ok(EchoOut { text: input.text })
}

/// Sends a message.
#[tool(
    name = "post.message",
    version = "1.4.0",
    description = "Posts a chat message",
    effect = "write",
    capabilities = ["penguin:connector.twitch", "penguin:log"]
)]
pub(crate) fn post(input: EchoIn) -> Result<EchoOut, ToolFailure> {
    Ok(EchoOut { text: input.text })
}

#[test]
fn macro_keeps_the_function_callable() {
    let out = echo(EchoIn { text: "hi".into() }).unwrap();
    assert_eq!(out.text, "hi");
}

#[test]
fn generates_a_descriptor_from_attributes() {
    let d = echo_descriptor().unwrap();
    assert_eq!(d.name, "echo");
    assert_eq!(d.version, "0.1.0");
    assert_eq!(d.effect, Effect::Read);
    assert!(d.capabilities.is_empty());
}

#[test]
fn input_and_output_schemas_come_from_the_signature_types() {
    let d = echo_descriptor().unwrap();
    let input: serde_json::Value = serde_json::from_str(&d.input_schema).unwrap();
    let output: serde_json::Value = serde_json::from_str(&d.output_schema).unwrap();
    assert!(input["properties"]["text"].is_object(), "input: {input}");
    assert_eq!(input["required"][0], "text");
    assert!(output["properties"]["text"].is_object(), "output: {output}");
}

#[test]
fn capabilities_and_effect_are_carried_through() {
    let d = post_descriptor().unwrap();
    assert_eq!(d.name, "post.message");
    assert_eq!(d.effect, Effect::Write);
    assert_eq!(
        d.capabilities,
        vec!["penguin:connector.twitch", "penguin:log"]
    );
    assert_eq!(post(EchoIn { text: "x".into() }).unwrap().text, "x");
}

#[tool(
    name = "Bad Name",
    version = "0.1.0",
    description = "d",
    effect = "read"
)]
fn badly_named(input: EchoIn) -> Result<EchoOut, ToolFailure> {
    Ok(EchoOut { text: input.text })
}

#[tool(
    name = "bad.cap",
    version = "0.1.0",
    description = "d",
    effect = "read",
    capabilities = ["not-namespaced"]
)]
fn badly_granted(input: EchoIn) -> Result<EchoOut, ToolFailure> {
    Ok(EchoOut { text: input.text })
}

#[test]
fn invalid_name_is_rejected_when_the_descriptor_is_built() {
    use penguin_tools_sdk::DescriptorError;
    assert!(matches!(
        badly_named_descriptor(),
        Err(DescriptorError::InvalidName(_))
    ));
    let _ = badly_named(EchoIn {
        text: String::new(),
    });
}

#[test]
fn invalid_capability_is_rejected_when_the_descriptor_is_built() {
    use penguin_tools_sdk::DescriptorError;
    assert!(matches!(
        badly_granted_descriptor(),
        Err(DescriptorError::InvalidCapability(_))
    ));
    let _ = badly_granted(EchoIn {
        text: String::new(),
    });
}
