//! Coverage for the two thin surfaces around the 31-rule validator: every
//! [`Reason`]'s stable string ([`penguin_bundle_host::manifest::error`]) and
//! the [`parse_yaml`] convenience function that parses-then-validates in
//! one call ([`penguin_bundle_host::manifest`]).
#![allow(clippy::unwrap_used, clippy::expect_used, clippy::panic)]

use penguin_bundle_host::manifest::{parse_yaml, ParseError, Reason, ValidationContext};

/// Every [`Reason`] variant paired with the exact machine-checkable string
/// it must serialize to (spec §6.4.4's `reason` column / `app_manifest.py`'s
/// `REASON_*` constants). A variant added to the enum without an entry here
/// is a bug this test is designed to catch.
fn all_reasons_with_expected_strings() -> Vec<(Reason, &'static str)> {
    vec![
        (Reason::MissingField, "missing_field"),
        (Reason::BadSemver, "bad_semver"),
        (Reason::NotNamespaced, "not_namespaced"),
        (Reason::UnknownModule, "unknown_module"),
        (Reason::FeaturePrefixMismatch, "feature_prefix_mismatch"),
        (Reason::InvalidProvider, "invalid_provider"),
        (Reason::UnknownSurface, "unknown_surface"),
        (Reason::InvalidExecutionModel, "invalid_execution_model"),
        (
            Reason::BadPlatformCompatSemver,
            "bad_platform_compat_semver",
        ),
        (Reason::InvalidCompatAppId, "invalid_compat_app_id"),
        (
            Reason::PresentationMissingHtmlEntrypoint,
            "presentation_missing_html_entrypoint",
        ),
        (
            Reason::PresentationHasScriptEntrypoint,
            "presentation_has_script_entrypoint",
        ),
        (
            Reason::ScriptStageHasHtmlEntrypoint,
            "script_stage_has_html_entrypoint",
        ),
        (
            Reason::UnsupportedSchemaVersion,
            "unsupported_schema_version",
        ),
        (Reason::IngestNotPluggable, "ingest_not_pluggable"),
        (Reason::NoStagesDeclared, "no_stages_declared"),
        (Reason::UnsupportedLanguage, "unsupported_language"),
        (Reason::PrebuiltNotAllowed, "prebuilt_not_allowed"),
        (Reason::InvalidEgressHost, "invalid_egress_host"),
        (Reason::InvalidEgressMethod, "invalid_egress_method"),
        (Reason::EgressHostDenylisted, "egress_host_denylisted"),
        (
            Reason::HttpImportWithoutEgress,
            "http_import_without_egress",
        ),
        (Reason::InvalidDataTable, "invalid_data_table"),
        (Reason::ReservedDataTable, "reserved_data_table"),
        (Reason::LimitOutOfRange, "limit_out_of_range"),
        (Reason::WitExportMissing, "wit_export_missing"),
        (Reason::ConsumesRequired, "consumes_required"),
        (Reason::ConsumesOnActionStage, "consumes_on_action_stage"),
        (Reason::UnknownConsumesPlatform, "unknown_consumes_platform"),
        (
            Reason::InvalidEventTypePattern,
            "invalid_event_type_pattern",
        ),
        (Reason::InvalidConsumesFilter, "invalid_consumes_filter"),
        (
            Reason::WildcardConsumesNotAllowed,
            "wildcard_consumes_not_allowed",
        ),
        (Reason::InvalidRoutesToTarget, "invalid_routes_to_target"),
        (Reason::UnknownRoutesToTarget, "unknown_routes_to_target"),
        (Reason::ForbiddenHostImport, "forbidden_host_import"),
    ]
}

#[test]
fn every_reason_as_str_and_display_match_the_stable_code() {
    let pairs = all_reasons_with_expected_strings();
    assert_eq!(
        pairs.len(),
        35,
        "expected all 35 distinct Reason variants to be listed"
    );

    for (reason, expected) in pairs {
        assert_eq!(reason.as_str(), expected);
        assert_eq!(reason.to_string(), expected);
        assert_eq!(format!("{reason}"), expected);
    }
}

#[test]
fn manifest_error_display_includes_reason_and_detail() {
    let err =
        penguin_bundle_host::manifest::ManifestError::new(Reason::BadSemver, "1.2 is not semver");
    let rendered = err.to_string();
    assert!(rendered.contains("bad_semver"));
    assert!(rendered.contains("1.2 is not semver"));
}

const VALID_YAML: &str = r#"
schema_version: 2
app_id: waddles.socials.music.default
name: Music Station
version: 3.0.0
feature: waddles.socials.music
module: socials
provider: builtin
language: python
artifact: source
stages:
  process:
    entry: "bundles.x:transform"
    consumes:
      - platform: twitch
        event_types: ["chat.message"]
"#;

#[test]
fn parse_yaml_succeeds_on_a_valid_document() {
    let manifest =
        parse_yaml(VALID_YAML, &ValidationContext::default()).expect("valid manifest parses");
    assert_eq!(manifest.app_id, "waddles.socials.music.default");
}

#[test]
fn parse_yaml_reports_a_syntax_error_before_validation_runs() {
    let malformed = "app_id: [this is not closed";
    let err =
        parse_yaml(malformed, &ValidationContext::default()).expect_err("malformed YAML must fail");
    assert!(matches!(err, ParseError::Syntax(_)));
}

#[test]
fn parse_yaml_reports_a_validation_error_for_well_formed_but_invalid_yaml() {
    let missing_name = VALID_YAML.replacen("name: Music Station\n", "", 1);
    let err = parse_yaml(&missing_name, &ValidationContext::default())
        .expect_err("well-formed YAML missing a required field must still fail");
    match err {
        ParseError::Validation(manifest_err) => {
            assert_eq!(manifest_err.reason, Reason::MissingField)
        }
        other => panic!("expected Validation, got {other:?}"),
    }
}
