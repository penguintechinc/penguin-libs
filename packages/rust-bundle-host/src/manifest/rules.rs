//! `bundle.yaml` v2 validation: 31 numbered rules (spec §6.4.4), run in
//! order, first failure wins — matching
//! `waddlebot/libs/flask_core/flask_core/app_manifest.py::parse_manifest`'s
//! own "reject, in order" contract for the rules the two share (V1-V13),
//! extended with the bundle.yaml-v2-only rules (V14-V31; V26 is an
//! intentional gap in the spec's own numbering, so 31 rule *numbers*
//! (V1-V25, V27-V31, plus lettered V30a) implement exactly 31 checks).

use std::collections::HashSet;
use std::sync::LazyLock;

use regex::Regex;

use super::error::{ManifestError, Reason};
use super::schema::{Manifest, RawConsumeRule, RawManifest};

const SEGMENT_PATTERN: &str = "[a-z0-9][a-z0-9_-]*";

static APP_ID_RE: LazyLock<Regex> = LazyLock::new(|| {
    #[allow(clippy::unwrap_used)] // infallible: a literal regex built once at process startup.
    Regex::new(&format!(
        r"^waddles\.{SEGMENT_PATTERN}\.{SEGMENT_PATTERN}\.{SEGMENT_PATTERN}$"
    ))
    .unwrap()
});

static FEATURE_RE: LazyLock<Regex> = LazyLock::new(|| {
    #[allow(clippy::unwrap_used)] // infallible: a literal regex built once at process startup.
    Regex::new(&format!(r"^waddles\.{SEGMENT_PATTERN}\.{SEGMENT_PATTERN}$")).unwrap()
});

/// SemVer 2.0.0 core + optional pre-release/build metadata, ported
/// verbatim from `app_manifest.py::_SEMVER_RE`.
static SEMVER_RE: LazyLock<Regex> = LazyLock::new(|| {
    #[allow(clippy::unwrap_used)] // infallible: a literal regex built once at process startup.
    Regex::new(
        r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)(?:-(?:0|[1-9]\d*|\d*[a-zA-Z-][0-9a-zA-Z-]*)(?:\.(?:0|[1-9]\d*|\d*[a-zA-Z-][0-9a-zA-Z-]*))*)?(?:\+[0-9a-zA-Z-]+(?:\.[0-9a-zA-Z-]+)*)?$",
    )
    .unwrap()
});

static EVENT_TYPE_SEGMENT_RE: LazyLock<Regex> = LazyLock::new(|| {
    #[allow(clippy::unwrap_used)]
    Regex::new(r"^(\*\*|\*|[a-z][a-z0-9]*)$").unwrap()
});

static DATA_TABLE_RE: LazyLock<Regex> = LazyLock::new(|| {
    #[allow(clippy::unwrap_used)]
    Regex::new(r"^[a-z][a-z0-9_]{0,62}$").unwrap()
});

/// `KNOWN_MODULES` ported verbatim from `app_manifest.py:62-83`.
const KNOWN_MODULES: &[&str] = &[
    "socials",
    "customers",
    "community",
    "event",
    "marketing",
    "bot",
    "streaming",
    "social",
    "customer",
    "analytics",
    "video_proxy",
    "auth",
    "compliance",
    "integrations",
    "tenancy",
    "core",
];

/// `KNOWN_SURFACES` ported verbatim from `app_manifest.py:93` — V8 checks
/// against this four-value set (still including `ingest`); V15 is the
/// bundle.yaml-v2-only rule that additionally forbids `ingest` among it.
const KNOWN_SURFACES: &[&str] = &["ingest", "process", "action", "presentation"];

const KNOWN_PROVIDERS: &[&str] = &["builtin", "thirdparty"];
const KNOWN_EXECUTION_MODELS: &[&str] = &["native", "thirdparty"];
const KNOWN_LANGUAGES: &[&str] = &["python", "rust", "javascript", "typescript", "other"];
const KNOWN_ARTIFACTS: &[&str] = &["source", "prebuilt"];
const KNOWN_PLATFORMS: &[&str] = &["twitch", "discord", "slack", "youtube", "kick", "waddles"];
const ALLOWED_EGRESS_METHODS: &[&str] = &["GET", "HEAD", "POST", "PUT", "PATCH", "DELETE"];
const KNOWN_CONSUMES_FILTER_KEYS: &[&str] = &["command_prefix", "actor_roles"];
const RESERVED_DATA_TABLES: &[&str] = &[
    "users",
    "tenants",
    "communities",
    "app_catalog",
    "app_activations",
    "app_tenant_availability",
];

/// `limits.timeout_ms` bounds (spec §6.4.2: `EXECUTOR_MAX_CALL_TIMEOUT_MS`).
const TIMEOUT_MS_MIN: i64 = 50;
const TIMEOUT_MS_MAX: i64 = 10_000;
/// `limits.memory_mb` bounds (spec §6.4.2: `EXECUTOR_MAX_MEMORY_LIMIT_MB`).
const MEMORY_MB_MIN: i64 = 8;
const MEMORY_MB_MAX: i64 = 256;
/// `limits.egress_rps` bounds (spec §6.4.2: `EGRESS_RATE_LIMIT_RPS`
/// default ceiling; `ValidationContext::egress_rps_ceiling` overrides the
/// upper bound "unless the operator raised the ceiling").
const EGRESS_RPS_MIN: i64 = 1;
const EGRESS_RPS_DEFAULT_MAX: i64 = 10;

/// The `waddle:bundle/*` WIT world's import list (spec §6.5's `world
/// stage` import block) plus the interfaces the host implements purely to
/// *refuse* (spec assumption A19: denying `wasi:sockets` stubs so
/// toolchains that unconditionally link the full WASI P2 import set still
/// instantiate) and the two WASI interfaces a component may otherwise use
/// (assumption A15: `wasi:random`; a read-only `/scratch` preopen via
/// `wasi:filesystem`).
const ALLOWED_COMPONENT_IMPORTS: &[&str] = &[
    "waddle:bundle/context",
    "waddle:bundle/http",
    "waddle:bundle/kv",
    "waddle:bundle/db",
    "waddle:bundle/relay",
    "waddle:bundle/flags",
    "waddle:bundle/log",
    "waddle:bundle/clock",
    "wasi:random/random",
    "wasi:filesystem/types",
    "wasi:filesystem/preopens",
    "wasi:sockets/instance-network",
    "wasi:sockets/network",
    "wasi:sockets/ip-name-lookup",
    "wasi:sockets/tcp",
    "wasi:sockets/tcp-create-socket",
    "wasi:sockets/udp",
    "wasi:sockets/udp-create-socket",
];

/// External state the pure `bundle.yaml` validator has no way to know on
/// its own. Every field defaults to the most permissive value that skips
/// the corresponding artifact/registry-dependent rule rather than
/// spuriously failing it — a caller validating a manifest before any
/// compiled component or tenant config exists (e.g. an author's local
/// `bundle-compiler --check` dry run) gets V1-V24/V27-V30/V30a's
/// syntax-only half of V30a, and skips V21/V22/V25/V31 until it has real
/// data to check them against.
#[derive(Debug, Clone, Default)]
pub struct ValidationContext<'a> {
    /// Global `bundles.allow_prebuilt` setting (V18).
    pub allow_prebuilt: bool,
    /// Tenant-level egress host denylist: exact lowercase FQDNs or
    /// `*.`-prefixed wildcards (V21).
    pub egress_denylist: &'a [String],
    /// Tenant setting `allow_wildcard_consumes` (V30).
    pub allow_wildcard_consumes: bool,
    /// Platform names registered as `custom:<name>` for this tenant (V29).
    pub custom_platforms: &'a [String],
    /// `app_id`s registered in `app_catalog` for this tenant (V30a's
    /// existence half); `None` skips that half and checks only syntax.
    pub known_app_ids: Option<&'a HashSet<String>>,
    /// The compiled component's actual WIT export names (V25); `None`
    /// skips the artifact-level export check.
    pub component_exports: Option<&'a HashSet<String>>,
    /// The compiled component's actual WIT import names (V22, V31);
    /// `None` skips both artifact-level import checks.
    pub component_imports: Option<&'a HashSet<String>>,
    /// Operator-raised ceiling for `limits.egress_rps` (V24); `None` uses
    /// the spec default of `10`.
    pub egress_rps_ceiling: Option<i64>,
}

/// Validates a raw `bundle.yaml` v2 document and builds a [`Manifest`].
///
/// Rejects with a typed [`ManifestError`] on the first rule that fails,
/// checked in ascending rule-number order (V1..V31, V26 is an intentional
/// gap — see the module doc). `ctx` supplies the tenant/registry/
/// compiled-artifact state this crate cannot know on its own; see
/// [`ValidationContext`] for what each `None`/empty default skips.
pub fn validate(raw: &RawManifest, ctx: &ValidationContext<'_>) -> Result<Manifest, ManifestError> {
    // V1: every required field present and non-empty.
    let app_id = require_str(raw.app_id.as_deref(), "app_id")?;
    let name = require_str(raw.name.as_deref(), "name")?;
    let version = require_str(raw.version.as_deref(), "version")?;
    let feature = require_str(raw.feature.as_deref(), "feature")?;
    let module = require_str(raw.module.as_deref(), "module")?;
    let provider = require_str(raw.provider.as_deref(), "provider")?;
    let language = require_str(raw.language.as_deref(), "language")?;
    let artifact = require_str(raw.artifact.as_deref(), "artifact")?;

    // V2: version is valid SemVer 2.0.0.
    require_semver(version, "version")?;

    // V3: app_id matches the four-segment pattern.
    if !APP_ID_RE.is_match(app_id) {
        return Err(ManifestError::new(
            Reason::NotNamespaced,
            format!("app_id {app_id:?} must be namespaced 'waddles.<module>.<feature>.<app>'"),
        ));
    }

    // V4: feature matches the three-segment pattern.
    if !FEATURE_RE.is_match(feature) {
        return Err(ManifestError::new(
            Reason::NotNamespaced,
            format!("feature {feature:?} must be namespaced 'waddles.<module>.<feature>'"),
        ));
    }

    // V5: module is a known module.
    if !KNOWN_MODULES.contains(&module) {
        return Err(ManifestError::new(
            Reason::UnknownModule,
            format!("module {module:?} is not a known module"),
        ));
    }

    // V6: app_id's feature prefix equals feature, and module equals
    // feature's second segment.
    let app_id_feature_prefix = app_id
        .rsplit_once('.')
        .map(|(prefix, _)| prefix)
        .unwrap_or(app_id);
    if app_id_feature_prefix != feature {
        return Err(ManifestError::new(
            Reason::FeaturePrefixMismatch,
            format!(
                "app_id {app_id:?} implies feature {app_id_feature_prefix:?}, but manifest declares feature {feature:?}"
            ),
        ));
    }
    let feature_module_segment = feature.split('.').nth(1);
    if feature_module_segment != Some(module) {
        return Err(ManifestError::new(
            Reason::FeaturePrefixMismatch,
            format!("feature {feature:?} implies module {feature_module_segment:?}, but manifest declares module {module:?}"),
        ));
    }

    // V7: provider is a known provider.
    if !KNOWN_PROVIDERS.contains(&provider) {
        return Err(ManifestError::new(
            Reason::InvalidProvider,
            format!("provider {provider:?} is not one of {KNOWN_PROVIDERS:?}"),
        ));
    }

    // V8: every stages key is a known surface (python-parity set, still
    // including "ingest" -- V15 below is the v2-only rule that forbids it).
    for stage_name in raw.stages.keys() {
        if !KNOWN_SURFACES.contains(&stage_name.as_str()) {
            return Err(ManifestError::new(
                Reason::UnknownSurface,
                format!("stage {stage_name:?} is not one of {KNOWN_SURFACES:?}"),
            ));
        }
    }

    // V9: execution_model is a known execution model.
    let execution_model = raw.execution_model.as_deref().unwrap_or("native");
    if !KNOWN_EXECUTION_MODELS.contains(&execution_model) {
        return Err(ManifestError::new(
            Reason::InvalidExecutionModel,
            format!("execution_model {execution_model:?} is not one of {KNOWN_EXECUTION_MODELS:?}"),
        ));
    }

    // V10: platform_compatibility version strings are valid SemVer or null.
    if let Some(compat) = &raw.platform_compatibility {
        for (label, candidate) in [
            ("min_version", &compat.min_version),
            ("max_version", &compat.max_version),
        ] {
            if let Some(value) = candidate {
                if !SEMVER_RE.is_match(value) {
                    return Err(ManifestError::new(
                        Reason::BadPlatformCompatSemver,
                        format!(
                            "platform_compatibility.{label} {value:?} is not valid SemVer 2.0.0"
                        ),
                    ));
                }
            }
        }
    }

    // V11: every compatible_with/incompatible_with entry is a valid app_id.
    for other_app_id in raw
        .compatible_with
        .iter()
        .chain(raw.incompatible_with.iter())
    {
        if !APP_ID_RE.is_match(other_app_id) {
            return Err(ManifestError::new(
                Reason::InvalidCompatAppId,
                format!("compatible_with/incompatible_with entry {other_app_id:?} must be namespaced 'waddles.<module>.<feature>.<app>'"),
            ));
        }
    }

    // V12/V13: presentation vs. script stage entry-point shape.
    for (stage_name, stage) in &raw.stages {
        if stage_name == "presentation" {
            if stage.html_entrypoint.is_none() {
                return Err(ManifestError::new(
                    Reason::PresentationMissingHtmlEntrypoint,
                    "presentation stage requires html_entrypoint".to_string(),
                ));
            }
            if stage.entry.is_some() {
                return Err(ManifestError::new(
                    Reason::PresentationHasScriptEntrypoint,
                    "presentation stage must not declare a script entry".to_string(),
                ));
            }
        } else if stage.html_entrypoint.is_some() {
            return Err(ManifestError::new(
                Reason::ScriptStageHasHtmlEntrypoint,
                format!(
                    "stage {stage_name:?} is a script stage and must not declare html_entrypoint"
                ),
            ));
        }
    }

    // V14: schema_version is exactly 2.
    if raw.schema_version != Some(2) {
        return Err(ManifestError::new(
            Reason::UnsupportedSchemaVersion,
            format!("schema_version {:?} must be exactly 2", raw.schema_version),
        ));
    }

    // V15: stages contains no ingest key.
    if raw.stages.contains_key("ingest") {
        return Err(ManifestError::new(
            Reason::IngestNotPluggable,
            "stages must not declare an ingest key -- ingest is not pluggable in bundle.yaml v2"
                .to_string(),
        ));
    }

    // V16: stages is non-empty.
    if raw.stages.is_empty() {
        return Err(ManifestError::new(
            Reason::NoStagesDeclared,
            "stages must declare at least one entry".to_string(),
        ));
    }

    // V17: language is one of the five allowed values; "other" only with
    // artifact: prebuilt.
    if !KNOWN_LANGUAGES.contains(&language) {
        return Err(ManifestError::new(
            Reason::UnsupportedLanguage,
            format!("language {language:?} is not one of {KNOWN_LANGUAGES:?}"),
        ));
    }
    if language == "other" && artifact != "prebuilt" {
        return Err(ManifestError::new(
            Reason::UnsupportedLanguage,
            "language 'other' is only legal with artifact: prebuilt".to_string(),
        ));
    }

    // V18: artifact is source or prebuilt; prebuilt is refused when
    // bundles.allow_prebuilt is false.
    if !KNOWN_ARTIFACTS.contains(&artifact) {
        return Err(ManifestError::new(
            Reason::PrebuiltNotAllowed,
            format!("artifact {artifact:?} is not one of {KNOWN_ARTIFACTS:?}"),
        ));
    }
    if artifact == "prebuilt" && !ctx.allow_prebuilt {
        return Err(ManifestError::new(
            Reason::PrebuiltNotAllowed,
            "artifact: prebuilt is refused while bundles.allow_prebuilt is false".to_string(),
        ));
    }

    // V19/V20: egress host and method shape.
    for rule in &raw.egress {
        let host = require_str(rule.host.as_deref(), "egress[].host")?;
        if !is_valid_egress_host(host) {
            return Err(ManifestError::new(
                Reason::InvalidEgressHost,
                format!(
                    "egress host {host:?} must be a lowercase FQDN or a single-label '*.' wildcard"
                ),
            ));
        }
        if let Some(methods) = &rule.methods {
            for method in methods {
                if !ALLOWED_EGRESS_METHODS.contains(&method.as_str()) {
                    return Err(ManifestError::new(
                        Reason::InvalidEgressMethod,
                        format!(
                            "egress method {method:?} is not one of {ALLOWED_EGRESS_METHODS:?}"
                        ),
                    ));
                }
            }
        }
    }

    // V21: no egress host matches the tenant-level denylist.
    for rule in &raw.egress {
        if let Some(host) = &rule.host {
            if is_denylisted(host, ctx.egress_denylist) {
                return Err(ManifestError::new(
                    Reason::EgressHostDenylisted,
                    format!("egress host {host:?} matches the tenant egress denylist"),
                ));
            }
        }
    }

    // V22: egress is non-empty when the compiled component imports
    // waddle:bundle/http. Skipped until a compiled component exists.
    if let Some(imports) = ctx.component_imports {
        if imports.contains("waddle:bundle/http") && raw.egress.is_empty() {
            return Err(ManifestError::new(
                Reason::HttpImportWithoutEgress,
                "component imports waddle:bundle/http but declares no egress rules".to_string(),
            ));
        }
    }

    // V23: data.tables entries match the table-name pattern and are not
    // reserved Waddles identity tables.
    for table in &raw.data.tables {
        if !DATA_TABLE_RE.is_match(table) {
            return Err(ManifestError::new(
                Reason::InvalidDataTable,
                format!("data.tables entry {table:?} does not match ^[a-z][a-z0-9_]{{0,62}}$"),
            ));
        }
        if RESERVED_DATA_TABLES.contains(&table.as_str()) {
            return Err(ManifestError::new(
                Reason::ReservedDataTable,
                format!("data.tables entry {table:?} is a reserved Waddles identity table"),
            ));
        }
    }

    // V24: limits are within their allowed ranges.
    if raw.limits.timeout_ms < TIMEOUT_MS_MIN || raw.limits.timeout_ms > TIMEOUT_MS_MAX {
        return Err(ManifestError::new(
            Reason::LimitOutOfRange,
            format!(
                "limits.timeout_ms {} is outside [{TIMEOUT_MS_MIN}, {TIMEOUT_MS_MAX}]",
                raw.limits.timeout_ms
            ),
        ));
    }
    if raw.limits.memory_mb < MEMORY_MB_MIN || raw.limits.memory_mb > MEMORY_MB_MAX {
        return Err(ManifestError::new(
            Reason::LimitOutOfRange,
            format!(
                "limits.memory_mb {} is outside [{MEMORY_MB_MIN}, {MEMORY_MB_MAX}]",
                raw.limits.memory_mb
            ),
        ));
    }
    let egress_rps_max = ctx.egress_rps_ceiling.unwrap_or(EGRESS_RPS_DEFAULT_MAX);
    if raw.limits.egress_rps < EGRESS_RPS_MIN || raw.limits.egress_rps > egress_rps_max {
        return Err(ManifestError::new(
            Reason::LimitOutOfRange,
            format!(
                "limits.egress_rps {} is outside [{EGRESS_RPS_MIN}, {egress_rps_max}]",
                raw.limits.egress_rps
            ),
        ));
    }

    // V25: the compiled component's exports satisfy the WIT world for
    // every declared script stage. Skipped until a compiled component
    // exists.
    if let Some(exports) = ctx.component_exports {
        for stage_name in raw.stages.keys() {
            let required_export = match stage_name.as_str() {
                "process" => Some("transform"),
                "action" => Some("dispatch"),
                _ => None,
            };
            if let Some(export_name) = required_export {
                if !exports.contains(export_name) {
                    return Err(ManifestError::new(
                        Reason::WitExportMissing,
                        format!("stage {stage_name:?} requires WIT export {export_name:?}, which the component does not export"),
                    ));
                }
            }
        }
    }

    // V27: a process stage declares a non-empty consumes list.
    if let Some(process) = raw.stages.get("process") {
        if process.consumes.is_empty() {
            return Err(ManifestError::new(
                Reason::ConsumesRequired,
                "a process stage must declare at least one consumes rule".to_string(),
            ));
        }
    }

    // V28: an action stage declares no consumes.
    if let Some(action) = raw.stages.get("action") {
        if !action.consumes.is_empty() {
            return Err(ManifestError::new(
                Reason::ConsumesOnActionStage,
                "an action stage must not declare consumes".to_string(),
            ));
        }
    }

    // V29/V30: consumes rule shape, and the wildcard gate.
    for stage in raw.stages.values() {
        for rule in &stage.consumes {
            validate_consume_rule(rule, ctx)?;
        }
    }

    // V30a: routes_to entries are syntactically valid app_ids, and (when
    // a registry is supplied) present in it.
    for target in &raw.routes_to {
        if !APP_ID_RE.is_match(target) {
            return Err(ManifestError::new(
                Reason::InvalidRoutesToTarget,
                format!("routes_to entry {target:?} must be a namespaced 'waddles.<module>.<feature>.<app>' with no wildcard"),
            ));
        }
        if let Some(known) = ctx.known_app_ids {
            if !known.contains(target) {
                return Err(ManifestError::new(
                    Reason::UnknownRoutesToTarget,
                    format!("routes_to entry {target:?} is not a bundle present in app_catalog"),
                ));
            }
        }
    }

    // V31: the compiled component imports nothing outside the WIT world's
    // import list plus the denying wasi:sockets stub set. Skipped until a
    // compiled component exists.
    if let Some(imports) = ctx.component_imports {
        for import in imports {
            if !ALLOWED_COMPONENT_IMPORTS.contains(&import.as_str()) {
                return Err(ManifestError::new(
                    Reason::ForbiddenHostImport,
                    format!("component imports {import:?}, which is outside the waddle:bundle WIT world and the wasi:sockets denying stub set"),
                ));
            }
        }
    }

    let permissions = raw
        .requires_scopes
        .clone()
        .unwrap_or_else(|| raw.permissions.clone());

    Ok(Manifest {
        schema_version: raw.schema_version.unwrap_or(2),
        app_id: app_id.to_string(),
        name: name.to_string(),
        version: version.to_string(),
        feature: feature.to_string(),
        module: module.to_string(),
        provider: provider.to_string(),
        language: language.to_string(),
        artifact: artifact.to_string(),
        execution_model: execution_model.to_string(),
        is_default: raw.is_default,
        stages: raw.stages.keys().cloned().collect(),
        egress: raw
            .egress
            .iter()
            .map(|rule| {
                (
                    rule.host.clone().unwrap_or_default(),
                    rule.methods.clone().unwrap_or_else(|| {
                        ALLOWED_EGRESS_METHODS
                            .iter()
                            .map(|m| m.to_string())
                            .collect()
                    }),
                )
            })
            .collect(),
        data_tables: raw.data.tables.clone(),
        timeout_ms: raw.limits.timeout_ms,
        memory_mb: raw.limits.memory_mb,
        egress_rps: raw.limits.egress_rps,
        permissions,
        routes_to: raw.routes_to.clone(),
        compatible_with: raw.compatible_with.clone(),
        incompatible_with: raw.incompatible_with.clone(),
    })
}

fn require_str<'a>(value: Option<&'a str>, field: &str) -> Result<&'a str, ManifestError> {
    match value {
        Some(v) if !v.is_empty() => Ok(v),
        _ => Err(ManifestError::new(
            Reason::MissingField,
            format!("{field:?} must be a non-empty string"),
        )),
    }
}

fn require_semver(value: &str, field: &str) -> Result<(), ManifestError> {
    if SEMVER_RE.is_match(value) {
        Ok(())
    } else {
        Err(ManifestError::new(
            Reason::BadSemver,
            format!("{field} {value:?} is not valid SemVer 2.0.0"),
        ))
    }
}

fn is_valid_egress_host(host: &str) -> bool {
    if host.is_empty() || host == "*" {
        return false;
    }
    if host.to_ascii_lowercase() != host {
        return false;
    }
    if host.contains("://") || host.contains('/') || host.contains(':') || host.contains('@') {
        return false;
    }
    if host == "localhost" {
        return false;
    }
    if host.parse::<std::net::Ipv4Addr>().is_ok() || host.parse::<std::net::Ipv6Addr>().is_ok() {
        return false;
    }

    let fqdn = match host.strip_prefix("*.") {
        Some(suffix) if !suffix.contains('*') => suffix,
        Some(_) => return false, // more than one wildcard label
        None if !host.contains('*') => host,
        None => return false,
    };

    is_valid_fqdn(fqdn)
}

fn is_valid_fqdn(value: &str) -> bool {
    let labels: Vec<&str> = value.split('.').collect();
    labels.len() >= 2 && labels.iter().all(|label| is_valid_dns_label(label))
}

fn is_valid_dns_label(label: &str) -> bool {
    if label.is_empty() || label.len() > 63 {
        return false;
    }
    let bytes = label.as_bytes();
    let starts_ok = bytes[0].is_ascii_lowercase() || bytes[0].is_ascii_digit();
    let ends_ok = {
        let last = bytes[bytes.len() - 1];
        last.is_ascii_lowercase() || last.is_ascii_digit()
    };
    starts_ok
        && ends_ok
        && label
            .chars()
            .all(|c| c.is_ascii_lowercase() || c.is_ascii_digit() || c == '-')
}

fn is_denylisted(host: &str, denylist: &[String]) -> bool {
    denylist.iter().any(|entry| {
        if entry == host {
            return true;
        }
        if let Some(suffix) = entry.strip_prefix("*.") {
            return host == suffix || host.ends_with(&format!(".{suffix}"));
        }
        false
    })
}

fn validate_consume_rule(
    rule: &RawConsumeRule,
    ctx: &ValidationContext<'_>,
) -> Result<(), ManifestError> {
    let platform = require_str(rule.platform.as_deref(), "consumes[].platform")?;
    let platform_ok = platform == "*"
        || KNOWN_PLATFORMS.contains(&platform)
        || platform
            .strip_prefix("custom:")
            .is_some_and(|name| ctx.custom_platforms.iter().any(|p| p == name));
    if !platform_ok {
        return Err(ManifestError::new(
            Reason::UnknownConsumesPlatform,
            format!("consumes platform {platform:?} is not a known platform, a registered custom platform, or '*'"),
        ));
    }

    if rule.event_types.is_empty() {
        return Err(ManifestError::new(
            Reason::InvalidEventTypePattern,
            "consumes[].event_types must declare at least one glob pattern".to_string(),
        ));
    }
    let mut has_wildcard = platform == "*";
    for pattern in &rule.event_types {
        if pattern == "**" {
            has_wildcard = true;
        }
        let segments_ok = pattern
            .split('.')
            .all(|segment| EVENT_TYPE_SEGMENT_RE.is_match(segment));
        if !segments_ok {
            return Err(ManifestError::new(
                Reason::InvalidEventTypePattern,
                format!("consumes event_types entry {pattern:?} is not a valid glob over the dotted event_type namespace"),
            ));
        }
    }

    for (key, value) in &rule.filters {
        if !KNOWN_CONSUMES_FILTER_KEYS.contains(&key.as_str()) {
            return Err(ManifestError::new(
                Reason::InvalidConsumesFilter,
                format!(
                    "consumes filters key {key:?} is not one of {KNOWN_CONSUMES_FILTER_KEYS:?}"
                ),
            ));
        }
        let is_string_array = value
            .as_array()
            .is_some_and(|items| items.iter().all(|item| item.is_string()));
        if !is_string_array {
            return Err(ManifestError::new(
                Reason::InvalidConsumesFilter,
                format!("consumes filters.{key} must be a list of strings"),
            ));
        }
    }

    if has_wildcard && !ctx.allow_wildcard_consumes {
        return Err(ManifestError::new(
            Reason::WildcardConsumesNotAllowed,
            "a consumes rule uses platform: '*' or event_types: '**' but allow_wildcard_consumes is false".to_string(),
        ));
    }

    Ok(())
}

#[cfg(test)]
mod tests {
    #![allow(clippy::unwrap_used, clippy::expect_used)]

    use std::collections::HashMap;

    use super::*;
    use crate::manifest::schema::{RawDataSection, RawStage};

    fn base_manifest() -> RawManifest {
        let mut stages = HashMap::new();
        stages.insert(
            "process".to_string(),
            RawStage {
                entry: Some("bundles.x:transform".to_string()),
                consumes: vec![RawConsumeRule {
                    platform: Some("twitch".to_string()),
                    source_id: None,
                    event_types: vec!["chat.message".to_string()],
                    filters: HashMap::new(),
                }],
                ..Default::default()
            },
        );
        RawManifest {
            schema_version: Some(2),
            app_id: Some("waddles.socials.music.default".to_string()),
            name: Some("Music Station".to_string()),
            version: Some("3.0.0".to_string()),
            feature: Some("waddles.socials.music".to_string()),
            module: Some("socials".to_string()),
            provider: Some("builtin".to_string()),
            language: Some("python".to_string()),
            artifact: Some("source".to_string()),
            stages,
            ..Default::default()
        }
    }

    #[test]
    fn v6_second_condition_catches_a_module_that_does_not_match_features_second_segment() {
        let mut raw = base_manifest();
        // feature "waddles.socials.music" implies module "socials"; declare
        // a different, still-known module to isolate the second V6 check
        // from the first (app_id/feature prefix already agree).
        raw.module = Some("community".to_string());
        let err = validate(&raw, &ValidationContext::default()).expect_err("must fail V6");
        assert_eq!(err.reason, Reason::FeaturePrefixMismatch);
    }

    #[test]
    fn v24_catches_memory_mb_and_egress_rps_out_of_range_independently() {
        let mut raw = base_manifest();
        raw.limits.memory_mb = 1024;
        let err =
            validate(&raw, &ValidationContext::default()).expect_err("memory_mb out of range");
        assert_eq!(err.reason, Reason::LimitOutOfRange);

        let mut raw = base_manifest();
        raw.limits.egress_rps = 999;
        let err =
            validate(&raw, &ValidationContext::default()).expect_err("egress_rps out of range");
        assert_eq!(err.reason, Reason::LimitOutOfRange);

        // An operator-raised ceiling permits a higher egress_rps.
        let mut raw = base_manifest();
        raw.limits.egress_rps = 50;
        let ctx = ValidationContext {
            egress_rps_ceiling: Some(100),
            ..ValidationContext::default()
        };
        assert!(validate(&raw, &ctx).is_ok());
    }

    #[test]
    fn v25_passes_when_every_declared_export_is_present_including_a_non_script_stage() {
        let mut raw = base_manifest();
        raw.stages.insert(
            "action".to_string(),
            RawStage {
                entry: Some("bundles.x:send".to_string()),
                ..Default::default()
            },
        );
        raw.stages.insert(
            "presentation".to_string(),
            RawStage {
                html_entrypoint: Some("overlay.html".to_string()),
                ..Default::default()
            },
        );
        let exports: HashSet<String> =
            HashSet::from(["transform".to_string(), "dispatch".to_string()]);
        let ctx = ValidationContext {
            component_exports: Some(&exports),
            ..ValidationContext::default()
        };
        let manifest = validate(&raw, &ctx).expect("all required exports present");
        assert!(manifest.stages.contains(&"presentation".to_string()));
    }

    #[test]
    fn presentation_only_manifest_passes_without_a_script_entrypoint() {
        let mut raw = base_manifest();
        raw.stages = HashMap::new();
        raw.stages.insert(
            "presentation".to_string(),
            RawStage {
                html_entrypoint: Some("overlay.html".to_string()),
                ..Default::default()
            },
        );
        let manifest =
            validate(&raw, &ValidationContext::default()).expect("presentation-only is valid");
        assert_eq!(manifest.stages, vec!["presentation".to_string()]);
    }

    #[test]
    fn is_valid_egress_host_accepts_fqdn_and_single_wildcard() {
        assert!(is_valid_egress_host("api.example.com"));
        assert!(is_valid_egress_host("*.example.com"));
    }

    #[test]
    fn is_valid_egress_host_rejects_every_documented_shape() {
        assert!(!is_valid_egress_host(""));
        assert!(!is_valid_egress_host("*"));
        assert!(!is_valid_egress_host("API.EXAMPLE.COM"));
        assert!(!is_valid_egress_host("https://example.com"));
        assert!(!is_valid_egress_host("example.com/path"));
        assert!(!is_valid_egress_host("example.com:8080"));
        assert!(!is_valid_egress_host("user@example.com"));
        assert!(!is_valid_egress_host("localhost"));
        assert!(!is_valid_egress_host("127.0.0.1"));
        assert!(!is_valid_egress_host("::1"));
        assert!(!is_valid_egress_host("*.*.example.com"));
        assert!(!is_valid_egress_host("single-label"));
        assert!(!is_valid_egress_host(&format!("{}.com", "a".repeat(64))));
    }

    #[test]
    fn is_denylisted_matches_exact_and_wildcard_suffix_entries() {
        let exact = vec!["blocked.example.com".to_string()];
        assert!(is_denylisted("blocked.example.com", &exact));
        assert!(!is_denylisted("other.example.com", &exact));

        let wildcard = vec!["*.example.com".to_string()];
        assert!(is_denylisted("sub.example.com", &wildcard));
        assert!(is_denylisted("example.com", &wildcard));
        assert!(!is_denylisted("example.org", &wildcard));
    }

    #[test]
    fn require_str_rejects_missing_and_empty() {
        assert!(require_str(None, "field").is_err());
        assert!(require_str(Some(""), "field").is_err());
        assert_eq!(require_str(Some("value"), "field").unwrap(), "value");
    }

    #[test]
    fn require_semver_accepts_valid_and_rejects_invalid() {
        assert!(require_semver("1.2.3", "version").is_ok());
        assert!(require_semver("not-a-version", "version").is_err());
    }

    #[test]
    fn validate_consume_rule_allows_a_registered_custom_platform() {
        let rule = RawConsumeRule {
            platform: Some("custom:mycommunity".to_string()),
            source_id: None,
            event_types: vec!["chat.message".to_string()],
            filters: HashMap::new(),
        };
        let custom_platforms = vec!["mycommunity".to_string()];
        let ctx = ValidationContext {
            custom_platforms: &custom_platforms,
            ..ValidationContext::default()
        };
        assert!(validate_consume_rule(&rule, &ctx).is_ok());
    }

    #[test]
    fn validate_consume_rule_rejects_an_unregistered_custom_platform() {
        let rule = RawConsumeRule {
            platform: Some("custom:unregistered".to_string()),
            source_id: None,
            event_types: vec!["chat.message".to_string()],
            filters: HashMap::new(),
        };
        let err =
            validate_consume_rule(&rule, &ValidationContext::default()).expect_err("must fail");
        assert_eq!(err.reason, Reason::UnknownConsumesPlatform);
    }

    #[test]
    fn validate_consume_rule_allows_double_star_wildcard_when_permitted() {
        let rule = RawConsumeRule {
            platform: Some("twitch".to_string()),
            source_id: None,
            event_types: vec!["**".to_string()],
            filters: HashMap::new(),
        };
        let ctx = ValidationContext {
            allow_wildcard_consumes: true,
            ..ValidationContext::default()
        };
        assert!(validate_consume_rule(&rule, &ctx).is_ok());
    }

    #[test]
    fn validate_consume_rule_rejects_a_filter_value_that_is_not_a_string_array() {
        let mut filters = HashMap::new();
        filters.insert(
            "command_prefix".to_string(),
            serde_json::json!("not-an-array"),
        );
        let rule = RawConsumeRule {
            platform: Some("twitch".to_string()),
            source_id: None,
            event_types: vec!["chat.message".to_string()],
            filters,
        };
        let err =
            validate_consume_rule(&rule, &ValidationContext::default()).expect_err("must fail");
        assert_eq!(err.reason, Reason::InvalidConsumesFilter);
    }

    #[test]
    fn validate_consume_rule_rejects_an_empty_event_types_list() {
        let rule = RawConsumeRule {
            platform: Some("twitch".to_string()),
            source_id: None,
            event_types: vec![],
            filters: HashMap::new(),
        };
        let err =
            validate_consume_rule(&rule, &ValidationContext::default()).expect_err("must fail");
        assert_eq!(err.reason, Reason::InvalidEventTypePattern);
    }

    #[test]
    fn unused_data_section_default_has_no_tables() {
        assert_eq!(RawDataSection::default().tables.len(), 0);
    }
}
