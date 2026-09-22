//! `bundle.yaml` v2 shape as deserialized off disk (spec §6.4). Every
//! field is optional/defaulted here even where the schema requires it —
//! [`crate::manifest::rules::validate`] is the single place that decides
//! what "required" and "in range" mean, so every rejection carries the
//! right [`super::error::Reason`] instead of a generic serde error.

use std::collections::HashMap;

use serde::Deserialize;

/// The default `limits.timeout_ms` (spec §6.4.2).
pub const DEFAULT_TIMEOUT_MS: i64 = 2000;
/// The default `limits.memory_mb` (spec §6.4.2).
pub const DEFAULT_MEMORY_MB: i64 = 64;
/// The default `limits.egress_rps` (spec §6.4.2).
pub const DEFAULT_EGRESS_RPS: i64 = 10;

/// Top-level `bundle.yaml` v2 document, exactly as YAML/JSON deserializes
/// it — no validation has happened yet.
#[derive(Debug, Clone, Default, Deserialize)]
#[serde(default)]
pub struct RawManifest {
    pub schema_version: Option<i64>,
    pub app_id: Option<String>,
    pub name: Option<String>,
    pub version: Option<String>,
    pub feature: Option<String>,
    pub module: Option<String>,
    pub provider: Option<String>,
    pub language: Option<String>,
    pub artifact: Option<String>,
    pub execution_model: Option<String>,
    pub is_default: bool,
    pub stages: HashMap<String, RawStage>,
    pub egress: Vec<RawEgressRule>,
    pub data: RawDataSection,
    pub limits: RawLimits,
    pub permissions: Vec<String>,
    /// `bundle.yaml`'s name for `permissions` (App Bundle SDK spec §3.3);
    /// accepted as an alias exactly like `app_manifest.py`'s
    /// `parse_manifest`.
    pub requires_scopes: Option<Vec<String>>,
    pub routes_to: Vec<String>,
    pub compatible_with: Vec<String>,
    pub incompatible_with: Vec<String>,
    pub platform_compatibility: Option<RawPlatformCompat>,
}

/// One `stages.<name>` entry. Script stages (`process`/`action`) use
/// `entry`/`consumes`/`produces`/`config`/`spec`; a `presentation` stage
/// uses `html_entrypoint`/`assets`/`browser_source_path` instead.
#[derive(Debug, Clone, Default, Deserialize)]
#[serde(default)]
pub struct RawStage {
    pub entry: Option<String>,
    pub consumes: Vec<RawConsumeRule>,
    pub produces: Vec<String>,
    pub spec: RawStageSpec,
    pub html_entrypoint: Option<String>,
    pub assets: Vec<String>,
    pub browser_source_path: Option<String>,
}

/// `stages.<s>.spec`.
#[derive(Debug, Clone, Default, Deserialize)]
#[serde(default)]
pub struct RawStageSpec {
    pub required_config: Vec<String>,
}

/// One entry of a `process` stage's `consumes` list (spec §6.4.3).
#[derive(Debug, Clone, Default, Deserialize)]
#[serde(default)]
pub struct RawConsumeRule {
    pub platform: Option<String>,
    pub source_id: Option<String>,
    pub event_types: Vec<String>,
    /// Deserialized as a generic map, not a fixed struct, so
    /// [`super::rules`] can flag an unrecognized key with
    /// `invalid_consumes_filter` (V29) instead of silently dropping it.
    pub filters: HashMap<String, serde_json::Value>,
}

/// One `egress[]` entry.
#[derive(Debug, Clone, Default, Deserialize)]
#[serde(default)]
pub struct RawEgressRule {
    pub host: Option<String>,
    pub methods: Option<Vec<String>>,
}

/// `data`.
#[derive(Debug, Clone, Default, Deserialize)]
#[serde(default)]
pub struct RawDataSection {
    pub tables: Vec<String>,
}

/// `limits`. Each field defaults to the spec §6.4.2 default when absent —
/// callers must not assume `0` means "unset".
#[derive(Debug, Clone, Deserialize)]
#[serde(default)]
pub struct RawLimits {
    pub timeout_ms: i64,
    pub memory_mb: i64,
    pub egress_rps: i64,
}

impl Default for RawLimits {
    fn default() -> Self {
        Self {
            timeout_ms: DEFAULT_TIMEOUT_MS,
            memory_mb: DEFAULT_MEMORY_MB,
            egress_rps: DEFAULT_EGRESS_RPS,
        }
    }
}

/// `platform_compatibility`.
#[derive(Debug, Clone, Default, Deserialize)]
#[serde(default)]
pub struct RawPlatformCompat {
    pub tested_with: String,
    pub min_version: Option<String>,
    pub max_version: Option<String>,
}

/// A validated, installable bundle descriptor. Built exclusively by
/// [`crate::manifest::rules::validate`] — constructing one directly
/// bypasses every semver/namespacing/module/feature-prefix/limit check, so
/// callers reading a manifest from disk, a marketplace payload, or a DB
/// row must always go through `validate` (mirrors
/// `app_manifest.py::AppManifest`'s own doc comment).
#[derive(Debug, Clone, PartialEq)]
pub struct Manifest {
    pub schema_version: i64,
    pub app_id: String,
    pub name: String,
    pub version: String,
    pub feature: String,
    pub module: String,
    pub provider: String,
    pub language: String,
    pub artifact: String,
    pub execution_model: String,
    pub is_default: bool,
    pub stages: Vec<String>,
    pub egress: Vec<(String, Vec<String>)>,
    pub data_tables: Vec<String>,
    pub timeout_ms: i64,
    pub memory_mb: i64,
    pub egress_rps: i64,
    pub permissions: Vec<String>,
    pub routes_to: Vec<String>,
    pub compatible_with: Vec<String>,
    pub incompatible_with: Vec<String>,
}
