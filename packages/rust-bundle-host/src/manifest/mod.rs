//! `bundle.yaml` v2 parsing and validation (spec §6.4): the schema types
//! deserialization produces (`schema`), the 31 numbered validation rules
//! (`rules`), and the stable `reason` codes a rejected manifest reports
//! (`error`).

pub mod error;
pub mod rules;
pub mod schema;

pub use error::{ManifestError, Reason};
pub use rules::{validate, ValidationContext};
pub use schema::{Manifest, RawManifest};

/// Parses `bundle.yaml` v2 source text and validates it in one step. A
/// YAML syntax error is reported the same way a JSON syntax error would be
/// (both feed the same [`RawManifest`] shape) — via
/// [`ManifestError::reason`] [`Reason::MissingField`] is never used for
/// this; a syntax error surfaces as [`serde_saphyr::Error`] before
/// validation ever runs, which is why this function returns a distinct
/// top-level error rather than folding it into [`ManifestError`].
pub fn parse_yaml(source: &str, ctx: &ValidationContext<'_>) -> Result<Manifest, ParseError> {
    let raw = parse_raw_yaml(source)?;
    Ok(validate(&raw, ctx)?)
}

/// Deserializes `bundle.yaml` source text into a [`RawManifest`] with no
/// validation. The parser options pin YAML 1.2 core semantics so the swap
/// from `serde_yaml_ng` to `serde-saphyr` stays behavior-preserving:
/// `strict_booleans` keeps `yes`/`no`/`on`/`off` plain strings (never
/// booleans, so a `consumes` filter of `[yes]` stays a string list), and
/// `merge_keys: AsOrdinary` keeps `<<` an ordinary key as `serde_yaml_ng`
/// did (no silent merge-key expansion); `reject_unsupported_tags` rejects
/// unknown `!tags` as `serde_yaml_ng` did; and
/// `reject_non_finite_typeless_float: false` keeps an unquoted `.inf`/`.nan`
/// in an untyped position a string rather than a hard error.
pub fn parse_raw_yaml(source: &str) -> Result<RawManifest, serde_saphyr::Error> {
    let options = serde_saphyr::options! {
        strict_booleans: true,
        merge_keys: serde_saphyr::MergeKeyPolicy::AsOrdinary,
        reject_unsupported_tags: true,
        reject_non_finite_typeless_float: false,
    };
    serde_saphyr::from_str_with_options(source, options)
}

/// Either half of loading a manifest can fail: the YAML can be malformed
/// before validation ever sees it, or a well-formed document can fail one
/// of the 31 rules.
#[derive(Debug, thiserror::Error)]
pub enum ParseError {
    #[error("bundle.yaml is not valid YAML: {0}")]
    Syntax(#[from] serde_saphyr::Error),

    #[error(transparent)]
    Validation(#[from] ManifestError),
}
