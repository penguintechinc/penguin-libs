use serde::{Deserialize, Serialize};

const MAX_NAME_LEN: usize = 64;
const MAX_DESCRIPTION_BYTES: usize = 1024;

/// Side-effect class. Drives idempotency and approval policy in the host.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "lowercase")]
pub enum Effect {
    /// No observable side effects.
    Read,
    /// Mutates state; hosts require an idempotency key.
    Write,
    /// Irreversible mutation; hosts may require approval.
    Destructive,
}

impl Effect {
    /// The lowercase wire name, identical to the WIT enum case.
    pub fn as_str(self) -> &'static str {
        match self {
            Effect::Read => "read",
            Effect::Write => "write",
            Effect::Destructive => "destructive",
        }
    }
}

/// Why a [`ToolDescriptor`] was rejected.
#[derive(Debug, thiserror::Error, PartialEq, Eq)]
pub enum DescriptorError {
    /// Name does not match `[a-z][a-z0-9_.-]{0,63}`.
    #[error("invalid tool name {0:?}: must match [a-z][a-z0-9_.-]{{0,63}}")]
    InvalidName(String),
    /// Version is not a plain `major.minor.patch` triple.
    #[error("invalid tool version {0:?}: must be major.minor.patch")]
    InvalidVersion(String),
    /// Capability id is not a namespaced `ns:name`.
    #[error("invalid capability id {0:?}: must be a namespaced ns:name")]
    InvalidCapability(String),
    /// The same capability id was listed twice.
    #[error("duplicate capability id {0:?}")]
    DuplicateCapability(String),
    /// Description is empty or longer than 1024 bytes.
    #[error("description must be 1..=1024 bytes")]
    InvalidDescription,
    /// A schema string is not valid JSON.
    #[error("{0} schema is not valid JSON")]
    InvalidSchema(&'static str),
    /// Schema generation failed.
    #[error("schema serialization failed: {0}")]
    Serialization(String),
}

/// A tool's identity, contract, and requirements. Mirrors the WIT
/// `tool-descriptor` record and is a valid MCP tool definition source.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct ToolDescriptor {
    /// Unique within a module.
    pub name: String,
    /// Semver of the tool contract.
    pub version: String,
    /// Human-readable summary.
    pub description: String,
    /// JSON Schema 2020-12 for the arguments, canonical JSON.
    pub input_schema: String,
    /// JSON Schema 2020-12 for the result, canonical JSON.
    pub output_schema: String,
    /// Side-effect class.
    pub effect: Effect,
    /// Required capability ids, e.g. `penguin:http`.
    pub capabilities: Vec<String>,
}

impl ToolDescriptor {
    /// Validates every field and builds a descriptor.
    pub fn new(
        name: &str,
        version: &str,
        description: &str,
        input_schema: String,
        output_schema: String,
        effect: Effect,
        capabilities: &[&str],
    ) -> Result<Self, DescriptorError> {
        if !valid_name(name) {
            return Err(DescriptorError::InvalidName(name.to_string()));
        }
        if !valid_version(version) {
            return Err(DescriptorError::InvalidVersion(version.to_string()));
        }
        if description.is_empty() || description.len() > MAX_DESCRIPTION_BYTES {
            return Err(DescriptorError::InvalidDescription);
        }
        if serde_json::from_str::<serde_json::Value>(&input_schema).is_err() {
            return Err(DescriptorError::InvalidSchema("input"));
        }
        if serde_json::from_str::<serde_json::Value>(&output_schema).is_err() {
            return Err(DescriptorError::InvalidSchema("output"));
        }
        let mut seen: Vec<&str> = Vec::with_capacity(capabilities.len());
        for cap in capabilities {
            if !valid_capability(cap) {
                return Err(DescriptorError::InvalidCapability((*cap).to_string()));
            }
            if seen.contains(cap) {
                return Err(DescriptorError::DuplicateCapability((*cap).to_string()));
            }
            seen.push(cap);
        }
        Ok(Self {
            name: name.to_string(),
            version: version.to_string(),
            description: description.to_string(),
            input_schema,
            output_schema,
            effect,
            capabilities: capabilities.iter().map(|c| (*c).to_string()).collect(),
        })
    }
}

fn valid_name(name: &str) -> bool {
    let mut chars = name.chars();
    let Some(first) = chars.next() else {
        return false;
    };
    name.len() <= MAX_NAME_LEN
        && first.is_ascii_lowercase()
        && chars
            .all(|c| c.is_ascii_lowercase() || c.is_ascii_digit() || matches!(c, '_' | '.' | '-'))
}

fn valid_version(version: &str) -> bool {
    let parts: Vec<&str> = version.split('.').collect();
    parts.len() == 3
        && parts.iter().all(|p| {
            !p.is_empty()
                && p.chars().all(|c| c.is_ascii_digit())
                && (p.len() == 1 || !p.starts_with('0'))
        })
}

/// `ns:name`, one colon. `ns` is `[a-z][a-z0-9-]*`; `name` is `[a-z][a-z0-9._-]*`.
fn valid_capability(cap: &str) -> bool {
    let mut halves = cap.split(':');
    let (Some(ns), Some(name), None) = (halves.next(), halves.next(), halves.next()) else {
        return false;
    };
    segment_ok(ns, false) && segment_ok(name, true)
}

fn segment_ok(seg: &str, allow_dot_underscore: bool) -> bool {
    let mut chars = seg.chars();
    let Some(first) = chars.next() else {
        return false;
    };
    first.is_ascii_lowercase()
        && chars.all(|c| {
            c.is_ascii_lowercase()
                || c.is_ascii_digit()
                || c == '-'
                || (allow_dot_underscore && matches!(c, '.' | '_'))
        })
}
