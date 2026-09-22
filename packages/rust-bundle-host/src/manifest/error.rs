//! [`ManifestError`] and the stable `reason` codes every validation rule
//! reports (spec §6.4.4), matching
//! `waddlebot/libs/flask_core/flask_core/app_manifest.py`'s `REASON_*`
//! constants byte-for-byte where a rule number is shared, and extending
//! the same naming convention for the bundle.yaml-v2-only rules (V14-V31).

use std::fmt;

/// Every stable, machine-checkable rejection reason a manifest validation
/// rule can report. The `Display` impl is the exact `reason` string
/// callers and tests assert on — never the human `detail` text, which may
/// change without notice.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash)]
#[non_exhaustive]
pub enum Reason {
    /// V1: a required field is missing or an empty string.
    MissingField,
    /// V2: `version` is not valid SemVer 2.0.0.
    BadSemver,
    /// V3/V4: `app_id`/`feature` is not namespaced correctly.
    NotNamespaced,
    /// V5: `module` is not a member of `KNOWN_MODULES`.
    UnknownModule,
    /// V6: `app_id`'s feature prefix (or module segment) disagrees with
    /// the declared `feature`/`module`.
    FeaturePrefixMismatch,
    /// V7: `provider` is outside `{builtin, thirdparty}`.
    InvalidProvider,
    /// V8: a `stages`/`surfaces` key is outside the known surface set.
    UnknownSurface,
    /// V9: `execution_model` is outside `{native, thirdparty}`.
    InvalidExecutionModel,
    /// V10: a `platform_compatibility` version string is not valid SemVer.
    BadPlatformCompatSemver,
    /// V11: a `compatible_with`/`incompatible_with` entry is not a valid
    /// `app_id`.
    InvalidCompatAppId,
    /// V12: a `presentation` stage is missing `html_entrypoint`.
    PresentationMissingHtmlEntrypoint,
    /// V12: a `presentation` stage declares a script `entry`.
    PresentationHasScriptEntrypoint,
    /// V13: a script stage (`process`/`action`) declares `html_entrypoint`.
    ScriptStageHasHtmlEntrypoint,
    /// V14: `schema_version` is not exactly `2`.
    UnsupportedSchemaVersion,
    /// V15: `stages` declares an `ingest` key.
    IngestNotPluggable,
    /// V16: `stages` is empty.
    NoStagesDeclared,
    /// V17: `language` is outside the five allowed values, or `other` is
    /// used without `artifact: prebuilt`.
    UnsupportedLanguage,
    /// V18: `artifact: prebuilt` is used while `bundles.allow_prebuilt` is
    /// false.
    PrebuiltNotAllowed,
    /// V19: an `egress[].host` is not a lowercase FQDN or single-label
    /// wildcard.
    InvalidEgressHost,
    /// V20: an `egress[].methods` entry is outside the six allowed
    /// uppercase HTTP methods.
    InvalidEgressMethod,
    /// V21: an `egress[].host` matches the tenant-level denylist.
    EgressHostDenylisted,
    /// V22: `egress` is empty while the component imports
    /// `waddle:bundle/http`.
    HttpImportWithoutEgress,
    /// V23: a `data.tables` entry does not match the table-name pattern.
    InvalidDataTable,
    /// V23: a `data.tables` entry names a reserved Waddles identity table.
    ReservedDataTable,
    /// V24: a `limits.*` value is outside its allowed range.
    LimitOutOfRange,
    /// V25: the compiled component is missing a WIT export a declared
    /// script stage requires.
    WitExportMissing,
    /// V27: a `process` stage declares no `consumes` rules.
    ConsumesRequired,
    /// V28: an `action` stage declares `consumes`.
    ConsumesOnActionStage,
    /// V29: a `consumes[].platform` is not a known platform, a registered
    /// `custom:<name>`, or `*`.
    UnknownConsumesPlatform,
    /// V29: a `consumes[].event_types` entry is not a valid glob over the
    /// dotted `event_type` namespace.
    InvalidEventTypePattern,
    /// V29: a `consumes[].filters` key or value shape is not one of the
    /// documented filters.
    InvalidConsumesFilter,
    /// V30: a `consumes` rule uses `platform: "*"` or an `event_types`
    /// entry of `**` without `allow_wildcard_consumes`.
    WildcardConsumesNotAllowed,
    /// V30a: a `routes_to` entry is not a syntactically valid `app_id`, or
    /// names a wildcard.
    InvalidRoutesToTarget,
    /// V30a: a `routes_to` entry is syntactically valid but not present in
    /// the known app-id registry.
    UnknownRoutesToTarget,
    /// V31: the compiled component imports something outside the WIT
    /// world's import list plus the denying `wasi:sockets` stub set.
    ForbiddenHostImport,
}

impl Reason {
    /// The exact machine-checkable string this reason serializes to
    /// (spec §6.4.4's `reason` code column; `REASON_*` in
    /// `app_manifest.py` for the rules the two files share).
    pub fn as_str(self) -> &'static str {
        match self {
            Reason::MissingField => "missing_field",
            Reason::BadSemver => "bad_semver",
            Reason::NotNamespaced => "not_namespaced",
            Reason::UnknownModule => "unknown_module",
            Reason::FeaturePrefixMismatch => "feature_prefix_mismatch",
            Reason::InvalidProvider => "invalid_provider",
            Reason::UnknownSurface => "unknown_surface",
            Reason::InvalidExecutionModel => "invalid_execution_model",
            Reason::BadPlatformCompatSemver => "bad_platform_compat_semver",
            Reason::InvalidCompatAppId => "invalid_compat_app_id",
            Reason::PresentationMissingHtmlEntrypoint => "presentation_missing_html_entrypoint",
            Reason::PresentationHasScriptEntrypoint => "presentation_has_script_entrypoint",
            Reason::ScriptStageHasHtmlEntrypoint => "script_stage_has_html_entrypoint",
            Reason::UnsupportedSchemaVersion => "unsupported_schema_version",
            Reason::IngestNotPluggable => "ingest_not_pluggable",
            Reason::NoStagesDeclared => "no_stages_declared",
            Reason::UnsupportedLanguage => "unsupported_language",
            Reason::PrebuiltNotAllowed => "prebuilt_not_allowed",
            Reason::InvalidEgressHost => "invalid_egress_host",
            Reason::InvalidEgressMethod => "invalid_egress_method",
            Reason::EgressHostDenylisted => "egress_host_denylisted",
            Reason::HttpImportWithoutEgress => "http_import_without_egress",
            Reason::InvalidDataTable => "invalid_data_table",
            Reason::ReservedDataTable => "reserved_data_table",
            Reason::LimitOutOfRange => "limit_out_of_range",
            Reason::WitExportMissing => "wit_export_missing",
            Reason::ConsumesRequired => "consumes_required",
            Reason::ConsumesOnActionStage => "consumes_on_action_stage",
            Reason::UnknownConsumesPlatform => "unknown_consumes_platform",
            Reason::InvalidEventTypePattern => "invalid_event_type_pattern",
            Reason::InvalidConsumesFilter => "invalid_consumes_filter",
            Reason::WildcardConsumesNotAllowed => "wildcard_consumes_not_allowed",
            Reason::InvalidRoutesToTarget => "invalid_routes_to_target",
            Reason::UnknownRoutesToTarget => "unknown_routes_to_target",
            Reason::ForbiddenHostImport => "forbidden_host_import",
        }
    }
}

impl fmt::Display for Reason {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.write_str(self.as_str())
    }
}

/// Raised when a manifest fails validation. `reason` is the stable,
/// machine-checkable [`Reason`] (mirrors `app_manifest.py`'s
/// `ManifestError`); `detail` is a human-readable explanation that may
/// change without notice — tests must assert on `reason`, never on
/// `detail`.
#[derive(Debug, Clone, thiserror::Error, PartialEq, Eq)]
#[error("{reason}: {detail}")]
pub struct ManifestError {
    pub reason: Reason,
    pub detail: String,
}

impl ManifestError {
    /// Builds a [`ManifestError`] from a reason and a detail message.
    pub fn new(reason: Reason, detail: impl Into<String>) -> Self {
        Self {
            reason,
            detail: detail.into(),
        }
    }
}
