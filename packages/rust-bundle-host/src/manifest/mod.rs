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
/// this; a syntax error surfaces as [`serde_yaml_ng::Error`] before
/// validation ever runs, which is why this function returns a distinct
/// top-level error rather than folding it into [`ManifestError`].
pub fn parse_yaml(source: &str, ctx: &ValidationContext<'_>) -> Result<Manifest, ParseError> {
    let raw: RawManifest = serde_yaml_ng::from_str(source)?;
    Ok(validate(&raw, ctx)?)
}

/// Either half of loading a manifest can fail: the YAML can be malformed
/// before validation ever sees it, or a well-formed document can fail one
/// of the 31 rules.
#[derive(Debug, thiserror::Error)]
pub enum ParseError {
    #[error("bundle.yaml is not valid YAML: {0}")]
    Syntax(#[from] serde_yaml_ng::Error),

    #[error(transparent)]
    Validation(#[from] ManifestError),
}
