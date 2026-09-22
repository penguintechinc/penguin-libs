//! Golden manifest fixtures: every valid fixture under
//! `tests/fixtures/manifests/valid/` must pass [`penguin_bundle_host::manifest::validate`],
//! and every invalid fixture under `.../invalid/` must fail with the exact
//! [`Reason`] its filename names — one fixture per rule number (spec
//! §6.4.4), with a rule that reports more than one reason getting one
//! fixture per reason.
#![allow(clippy::unwrap_used, clippy::expect_used, clippy::panic)]

use std::collections::HashSet;
use std::fs;
use std::path::Path;

use penguin_bundle_host::manifest::{schema::RawManifest, validate, Reason, ValidationContext};

const VALID_DIR: &str = "tests/fixtures/manifests/valid";
const INVALID_DIR: &str = "tests/fixtures/manifests/invalid";

fn read_fixture(dir: &str, name: &str) -> RawManifest {
    let path = Path::new(dir).join(name);
    let source = fs::read_to_string(&path).unwrap_or_else(|err| panic!("read {path:?}: {err}"));
    serde_yaml_ng::from_str(&source).unwrap_or_else(|err| panic!("parse {path:?}: {err}"))
}

#[test]
fn valid_basic_manifest_passes_every_rule() {
    let raw = read_fixture(VALID_DIR, "basic.yaml");
    let ctx = ValidationContext::default();
    let manifest = validate(&raw, &ctx).expect("golden valid manifest must pass all 31 rules");
    assert_eq!(manifest.app_id, "waddles.socials.music.default");
    assert_eq!(manifest.schema_version, 2);
    assert!(manifest.stages.contains(&"process".to_string()));
    assert!(manifest.stages.contains(&"action".to_string()));
}

/// Every invalid fixture, its expected [`Reason`], and the
/// [`ValidationContext`] it needs to reach the rule under test (most rules
/// need only the manifest-only default; a few depend on tenant/registry/
/// compiled-artifact state this crate cannot infer on its own).
fn invalid_cases() -> Vec<(&'static str, Reason, ValidationContext<'static>)> {
    let mut cases = vec![
        (
            "v01_missing_field.yaml",
            Reason::MissingField,
            ValidationContext::default(),
        ),
        (
            "v02_bad_semver.yaml",
            Reason::BadSemver,
            ValidationContext::default(),
        ),
        (
            "v03_app_id_not_namespaced.yaml",
            Reason::NotNamespaced,
            ValidationContext::default(),
        ),
        (
            "v04_feature_not_namespaced.yaml",
            Reason::NotNamespaced,
            ValidationContext::default(),
        ),
        (
            "v05_unknown_module.yaml",
            Reason::UnknownModule,
            ValidationContext::default(),
        ),
        (
            "v06_feature_prefix_mismatch.yaml",
            Reason::FeaturePrefixMismatch,
            ValidationContext::default(),
        ),
        (
            "v07_invalid_provider.yaml",
            Reason::InvalidProvider,
            ValidationContext::default(),
        ),
        (
            "v08_unknown_surface.yaml",
            Reason::UnknownSurface,
            ValidationContext::default(),
        ),
        (
            "v09_invalid_execution_model.yaml",
            Reason::InvalidExecutionModel,
            ValidationContext::default(),
        ),
        (
            "v10_bad_platform_compat_semver.yaml",
            Reason::BadPlatformCompatSemver,
            ValidationContext::default(),
        ),
        (
            "v11_invalid_compat_app_id.yaml",
            Reason::InvalidCompatAppId,
            ValidationContext::default(),
        ),
        (
            "v12_presentation_missing_html_entrypoint.yaml",
            Reason::PresentationMissingHtmlEntrypoint,
            ValidationContext::default(),
        ),
        (
            "v12_presentation_has_script_entrypoint.yaml",
            Reason::PresentationHasScriptEntrypoint,
            ValidationContext::default(),
        ),
        (
            "v13_script_stage_has_html_entrypoint.yaml",
            Reason::ScriptStageHasHtmlEntrypoint,
            ValidationContext::default(),
        ),
        (
            "v14_unsupported_schema_version.yaml",
            Reason::UnsupportedSchemaVersion,
            ValidationContext::default(),
        ),
        (
            "v15_ingest_not_pluggable.yaml",
            Reason::IngestNotPluggable,
            ValidationContext::default(),
        ),
        (
            "v16_no_stages_declared.yaml",
            Reason::NoStagesDeclared,
            ValidationContext::default(),
        ),
        (
            "v17_unsupported_language.yaml",
            Reason::UnsupportedLanguage,
            ValidationContext::default(),
        ),
        // V18: allow_prebuilt defaults to false, so the default context
        // already exercises the rejection path.
        (
            "v18_prebuilt_not_allowed.yaml",
            Reason::PrebuiltNotAllowed,
            ValidationContext::default(),
        ),
        (
            "v19_invalid_egress_host.yaml",
            Reason::InvalidEgressHost,
            ValidationContext::default(),
        ),
        (
            "v20_invalid_egress_method.yaml",
            Reason::InvalidEgressMethod,
            ValidationContext::default(),
        ),
        (
            "v23_invalid_data_table.yaml",
            Reason::InvalidDataTable,
            ValidationContext::default(),
        ),
        (
            "v23_reserved_data_table.yaml",
            Reason::ReservedDataTable,
            ValidationContext::default(),
        ),
        (
            "v24_limit_out_of_range.yaml",
            Reason::LimitOutOfRange,
            ValidationContext::default(),
        ),
        (
            "v27_consumes_required.yaml",
            Reason::ConsumesRequired,
            ValidationContext::default(),
        ),
        (
            "v28_consumes_on_action_stage.yaml",
            Reason::ConsumesOnActionStage,
            ValidationContext::default(),
        ),
        (
            "v29_unknown_consumes_platform.yaml",
            Reason::UnknownConsumesPlatform,
            ValidationContext::default(),
        ),
        (
            "v29_invalid_event_type_pattern.yaml",
            Reason::InvalidEventTypePattern,
            ValidationContext::default(),
        ),
        (
            "v29_invalid_consumes_filter.yaml",
            Reason::InvalidConsumesFilter,
            ValidationContext::default(),
        ),
        (
            "v30_wildcard_consumes_not_allowed.yaml",
            Reason::WildcardConsumesNotAllowed,
            ValidationContext::default(),
        ),
        (
            "v30a_invalid_routes_to_target.yaml",
            Reason::InvalidRoutesToTarget,
            ValidationContext::default(),
        ),
    ];

    // V21 needs the tenant egress denylist supplied.
    let denylist: &'static [String] = Box::leak(Box::new(vec!["blocked.example.com".to_string()]));
    cases.push((
        "v21_egress_host_denylisted.yaml",
        Reason::EgressHostDenylisted,
        ValidationContext {
            egress_denylist: denylist,
            ..ValidationContext::default()
        },
    ));

    // V22 needs a compiled component that imports waddle:bundle/http.
    let http_import: &'static HashSet<String> =
        Box::leak(Box::new(HashSet::from(["waddle:bundle/http".to_string()])));
    cases.push((
        "v22_http_import_without_egress.yaml",
        Reason::HttpImportWithoutEgress,
        ValidationContext {
            component_imports: Some(http_import),
            ..ValidationContext::default()
        },
    ));

    // V25 needs a compiled component missing the required exports.
    let no_exports: &'static HashSet<String> = Box::leak(Box::new(HashSet::new()));
    cases.push((
        "v25_wit_export_missing.yaml",
        Reason::WitExportMissing,
        ValidationContext {
            component_exports: Some(no_exports),
            ..ValidationContext::default()
        },
    ));

    // V30a's "unknown" half needs a known-app-id registry that does not
    // contain the target.
    let empty_registry: &'static HashSet<String> = Box::leak(Box::new(HashSet::new()));
    cases.push((
        "v30a_unknown_routes_to_target.yaml",
        Reason::UnknownRoutesToTarget,
        ValidationContext {
            known_app_ids: Some(empty_registry),
            ..ValidationContext::default()
        },
    ));

    // V31 needs a compiled component importing something outside the WIT
    // world's allowlist.
    let forbidden_import: &'static HashSet<String> = Box::leak(Box::new(HashSet::from([
        "waddle:bundle/http".to_string(),
        "wasi:clocks/wall-clock".to_string(),
    ])));
    cases.push((
        "v31_forbidden_host_import.yaml",
        Reason::ForbiddenHostImport,
        ValidationContext {
            component_imports: Some(forbidden_import),
            ..ValidationContext::default()
        },
    ));

    cases
}

#[test]
fn every_invalid_fixture_fails_with_its_named_reason() {
    let cases = invalid_cases();
    // 36 fixture cases cover the 31 numbered rules (V1-V25, V27-V31, plus
    // lettered V30a): four rule numbers (V12, V23, V29, V30a) report more
    // than one reason and get one fixture per reason, so 36 cases exercise
    // 35 distinct Reason variants. Zero fixtures examined would be a
    // silent pass, not a real gate (critical-rules.md Verification
    // Integrity) -- assert the exact count this test suite covers.
    assert_eq!(
        cases.len(),
        36,
        "expected exactly 36 invalid-fixture cases across the 31 numbered rules"
    );

    let mut examined = 0usize;
    for (filename, expected_reason, ctx) in &cases {
        let raw = read_fixture(INVALID_DIR, filename);
        let err = validate(&raw, ctx).expect_err(&format!(
            "fixture {filename} was expected to fail validation but passed"
        ));
        assert_eq!(
            err.reason, *expected_reason,
            "fixture {filename} failed with reason {:?}, expected {:?} (detail: {})",
            err.reason, expected_reason, err.detail
        );
        examined += 1;
    }

    assert_eq!(
        examined, 36,
        "must have examined all 36 invalid fixture cases"
    );
}

#[test]
fn invalid_fixture_directory_has_no_untested_files() {
    let mut on_disk: Vec<String> = fs::read_dir(INVALID_DIR)
        .expect("read invalid fixtures dir")
        .map(|entry| {
            entry
                .expect("dir entry")
                .file_name()
                .to_string_lossy()
                .into_owned()
        })
        .collect();
    on_disk.sort();

    let mut tested: Vec<String> = invalid_cases()
        .into_iter()
        .map(|(name, _, _)| name.to_string())
        .collect();
    tested.sort();

    assert_eq!(
        on_disk, tested,
        "every fixture on disk must have exactly one test case, and vice versa"
    );
}
