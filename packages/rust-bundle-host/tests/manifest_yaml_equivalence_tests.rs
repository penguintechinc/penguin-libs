//! YAML parse-equivalence regression suite for the `serde_yaml_ng` ->
//! `serde-saphyr` swap (RUSTSEC-2024-0449). Pins what
//! [`penguin_bundle_host::manifest::parse_raw_yaml`] produces for a corpus of
//! representative and adversarial `bundle.yaml` inputs, so a future parser
//! upgrade or option change that alters manifest semantics fails loudly.
//!
//! Corpus: every `tests/fixtures/manifests/{valid,invalid}/*.yaml` fixture
//! (parse-without-error) plus the hand-written `equivalence/*.yaml` cases
//! (digest-exact against the expected values below), plus the BOM/CRLF
//! cases built in code.
//!
//! Dual-parse against `serde_yaml_ng` is deliberately NOT done here: adding
//! it as a dev-dependency would put `unsafe-libyaml` back in `Cargo.lock`
//! and `cargo deny` (which scans dev-dependencies) would reintroduce
//! RUSTSEC-2024-0449. Instead the expected digests below were reviewed
//! against a one-off, out-of-tree differential run of both parsers over this
//! same corpus (plus 40 extra `consumes` filter-value probes). Result: every
//! case is identical except the INTENTIONAL differences listed below, which
//! each carry an `intentional_diff` note in the table and are pinned to the
//! new behavior. `parse_raw_yaml` sets `strict_booleans`,
//! `merge_keys: AsOrdinary`, `reject_unsupported_tags` and
//! `reject_non_finite_typeless_float: false` to stay on yaml_ng's YAML 1.2
//! core semantics; without them `yes/no/on/off` and `<<` diverged.
//!
//! Intentional / accepted differences (all in the lenient direction except
//! the last three, which fail closed):
//! - Quoted `"true"` -> bool, quoted `"2"` -> i64 and `2_000` -> i64 are
//!   accepted (yaml_ng: type error). A valid manifest keeps the same value.
//! - A UTF-8 BOM prefix is accepted (yaml_ng: bogus "multiple documents").
//! - A `null` element inside a `Vec<String>` is rejected (yaml_ng: accepted).
//! - In a `consumes` filter list (untyped `serde_json::Value`) unquoted
//!   `0123`, `007`, `1_000` are numbers (yaml_ng: strings), so V29 rejects
//!   them; quote them to keep them strings. `.inf` stays the string ".inf"
//!   (yaml_ng: null).
//! - Duplicate-key and syntax error *messages* differ; both parsers reject.
//! - Pre-existing and parser-independent: `Manifest.stages` order follows
//!   `HashMap` iteration, so this suite always compares stage names sorted.
#![allow(clippy::unwrap_used, clippy::expect_used, clippy::panic)]

use std::collections::BTreeMap;
use std::fs;
use std::path::Path;

use penguin_bundle_host::manifest::{
    parse_raw_yaml, schema::RawManifest, validate, Manifest, ValidationContext,
};

const VALID_DIR: &str = "tests/fixtures/manifests/valid";
const INVALID_DIR: &str = "tests/fixtures/manifests/invalid";
const EQUIV_DIR: &str = "tests/fixtures/manifests/equivalence";

/// One corpus file, its expected digest (`None` = must fail to parse), and
/// the note explaining any intentional divergence from `serde_yaml_ng`.
struct Case {
    file: &'static str,
    expected: Option<&'static str>,
    intentional_diff: Option<&'static str>,
}

/// Stable, order-independent rendering of every field a manifest parse
/// produces, so one string comparison pins the whole [`RawManifest`].
fn digest(m: &RawManifest) -> String {
    let mut stages: Vec<_> = m.stages.keys().cloned().collect();
    stages.sort();
    let mut filters: Vec<String> = Vec::new();
    let mut by_name: Vec<_> = m.stages.iter().collect();
    by_name.sort_by_key(|(k, _)| (*k).clone());
    for (stage, st) in by_name {
        for (i, c) in st.consumes.iter().enumerate() {
            let f: BTreeMap<_, _> = c.filters.iter().collect();
            if !f.is_empty() {
                filters.push(format!(
                    "{stage}[{i}]={}",
                    serde_json::to_string(&f).unwrap()
                ));
            }
        }
    }
    format!(
        "name={:?} version={:?} schema_version={:?} is_default={} stages={:?} limits=({},{},{}) permissions={:?} requires_scopes={:?} compatible_with={:?} incompatible_with={:?} egress={} filters={:?}",
        m.name, m.version, m.schema_version, m.is_default, stages,
        m.limits.timeout_ms, m.limits.memory_mb, m.limits.egress_rps,
        m.permissions, m.requires_scopes, m.compatible_with, m.incompatible_with,
        m.egress.len(), filters
    )
}

fn read(dir: &str, name: &str) -> String {
    let path = Path::new(dir).join(name);
    fs::read_to_string(&path).unwrap_or_else(|err| panic!("read {path:?}: {err}"))
}

fn yaml_files(dir: &str) -> Vec<String> {
    let mut names: Vec<String> = fs::read_dir(dir)
        .unwrap_or_else(|err| panic!("read_dir {dir}: {err}"))
        .map(|e| e.unwrap().file_name().to_string_lossy().into_owned())
        .filter(|n| n.ends_with(".yaml"))
        .collect();
    names.sort();
    names
}

const CASES: &[Case] = &[
    Case {
        file: "anchor_scalar.yaml",
        expected: Some(
            r#"name=Some("Music") version=Some("3.0.0") schema_version=Some(2) is_default=false stages=["action"] limits=(2000,64,10) permissions=[] requires_scopes=None compatible_with=[] incompatible_with=[] egress=0 filters=[]"#,
        ),
        intentional_diff: None,
    },
    Case {
        file: "anchors_aliases.yaml",
        expected: Some(
            r#"name=Some("Music") version=Some("3.0.0") schema_version=Some(2) is_default=false stages=["action"] limits=(2000,64,10) permissions=[] requires_scopes=None compatible_with=["waddles.socials.other.default"] incompatible_with=["waddles.socials.other.default"] egress=0 filters=[]"#,
        ),
        intentional_diff: None,
    },
    Case {
        file: "bad_indent_syntax.yaml",
        expected: None,
        intentional_diff: None,
    },
    Case {
        file: "block_folded.yaml",
        expected: Some(
            r#"name=Some("folded text") version=Some("3.0.0") schema_version=Some(2) is_default=false stages=["action"] limits=(2000,64,10) permissions=[] requires_scopes=None compatible_with=[] incompatible_with=[] egress=0 filters=[]"#,
        ),
        intentional_diff: None,
    },
    Case {
        file: "block_literal.yaml",
        expected: Some(
            r#"name=Some("line one\nline two\n") version=Some("3.0.0") schema_version=Some(2) is_default=false stages=["action"] limits=(2000,64,10) permissions=[] requires_scopes=None compatible_with=[] incompatible_with=[] egress=0 filters=[]"#,
        ),
        intentional_diff: None,
    },
    Case {
        file: "bool_variants_in_string_field.yaml",
        expected: Some(
            r#"name=Some("Off") version=Some("3.0.0") schema_version=Some(2) is_default=false stages=["action"] limits=(2000,64,10) permissions=[] requires_scopes=None compatible_with=[] incompatible_with=[] egress=0 filters=[]"#,
        ),
        intentional_diff: None,
    },
    Case {
        file: "colon_in_plain.yaml",
        expected: Some(
            r#"name=Some("a:b") version=Some("3.0.0") schema_version=Some(2) is_default=false stages=["action"] limits=(2000,64,10) permissions=[] requires_scopes=None compatible_with=[] incompatible_with=[] egress=0 filters=[]"#,
        ),
        intentional_diff: None,
    },
    Case {
        file: "comments.yaml",
        expected: Some(
            r#"name=Some("Music") version=Some("3.0.0") schema_version=Some(2) is_default=false stages=["action"] limits=(2000,64,10) permissions=[] requires_scopes=None compatible_with=[] incompatible_with=[] egress=0 filters=[]"#,
        ),
        intentional_diff: None,
    },
    Case {
        file: "doc_end_marker.yaml",
        expected: Some(
            r#"name=Some("Music") version=Some("3.0.0") schema_version=Some(2) is_default=false stages=["action"] limits=(2000,64,10) permissions=[] requires_scopes=None compatible_with=[] incompatible_with=[] egress=0 filters=[]"#,
        ),
        intentional_diff: None,
    },
    Case {
        file: "doc_start_marker.yaml",
        expected: Some(
            r#"name=Some("Music") version=Some("3.0.0") schema_version=Some(2) is_default=false stages=["action"] limits=(2000,64,10) permissions=[] requires_scopes=None compatible_with=[] incompatible_with=[] egress=0 filters=[]"#,
        ),
        intentional_diff: None,
    },
    Case {
        file: "duplicate_key.yaml",
        expected: None,
        intentional_diff: None,
    },
    Case {
        file: "egress_null.yaml",
        expected: Some(
            r#"name=Some("Music") version=Some("3.0.0") schema_version=Some(2) is_default=false stages=["action"] limits=(2000,64,10) permissions=[] requires_scopes=None compatible_with=[] incompatible_with=[] egress=0 filters=[]"#,
        ),
        intentional_diff: None,
    },
    Case {
        file: "egress_variants.yaml",
        expected: Some(
            r#"name=Some("Music") version=Some("3.0.0") schema_version=Some(2) is_default=false stages=["action"] limits=(2000,64,10) permissions=[] requires_scopes=None compatible_with=[] incompatible_with=[] egress=4 filters=[]"#,
        ),
        intentional_diff: None,
    },
    Case {
        file: "empty_collections.yaml",
        expected: Some(
            r#"name=Some("Music") version=Some("3.0.0") schema_version=Some(2) is_default=false stages=[] limits=(2000,64,10) permissions=[] requires_scopes=Some([]) compatible_with=[] incompatible_with=[] egress=0 filters=[]"#,
        ),
        intentional_diff: None,
    },
    Case {
        file: "empty_input.yaml",
        expected: Some(
            r#"name=None version=None schema_version=None is_default=false stages=[] limits=(2000,64,10) permissions=[] requires_scopes=None compatible_with=[] incompatible_with=[] egress=0 filters=[]"#,
        ),
        intentional_diff: None,
    },
    Case {
        file: "filter_bang.yaml",
        expected: Some(
            r#"name=Some("Music") version=Some("3.0.0") schema_version=Some(2) is_default=false stages=["process"] limits=(2000,64,10) permissions=[] requires_scopes=None compatible_with=[] incompatible_with=[] egress=0 filters=["process[0]={\"actor_roles\":[\"moderator\"],\"command_prefix\":[\"!sr\",\"!song\"]}"]"#,
        ),
        intentional_diff: None,
    },
    Case {
        file: "filter_custom_tag.yaml",
        expected: None,
        intentional_diff: None,
    },
    Case {
        file: "filter_date.yaml",
        expected: Some(
            r#"name=Some("Music") version=Some("3.0.0") schema_version=Some(2) is_default=false stages=["process"] limits=(2000,64,10) permissions=[] requires_scopes=None compatible_with=[] incompatible_with=[] egress=0 filters=["process[0]={\"actor_roles\":[\"moderator\"],\"command_prefix\":[\"2024-01-02\"]}"]"#,
        ),
        intentional_diff: None,
    },
    Case {
        file: "filter_dotfive.yaml",
        expected: Some(
            r#"name=Some("Music") version=Some("3.0.0") schema_version=Some(2) is_default=false stages=["process"] limits=(2000,64,10) permissions=[] requires_scopes=None compatible_with=[] incompatible_with=[] egress=0 filters=["process[0]={\"actor_roles\":[\"moderator\"],\"command_prefix\":[0.5]}"]"#,
        ),
        intentional_diff: None,
    },
    Case {
        file: "filter_hex.yaml",
        expected: Some(
            r#"name=Some("Music") version=Some("3.0.0") schema_version=Some(2) is_default=false stages=["process"] limits=(2000,64,10) permissions=[] requires_scopes=None compatible_with=[] incompatible_with=[] egress=0 filters=["process[0]={\"actor_roles\":[\"moderator\"],\"command_prefix\":[31]}"]"#,
        ),
        intentional_diff: None,
    },
    Case {
        file: "filter_inf.yaml",
        expected: Some(
            r#"name=Some("Music") version=Some("3.0.0") schema_version=Some(2) is_default=false stages=["process"] limits=(2000,64,10) permissions=[] requires_scopes=None compatible_with=[] incompatible_with=[] egress=0 filters=["process[0]={\"actor_roles\":[\"moderator\"],\"command_prefix\":[\".inf\"]}"]"#,
        ),
        intentional_diff: Some("untyped `.inf` stays the string '.inf' in saphyr (yaml_ng: null)"),
    },
    Case {
        file: "filter_int.yaml",
        expected: Some(
            r#"name=Some("Music") version=Some("3.0.0") schema_version=Some(2) is_default=false stages=["process"] limits=(2000,64,10) permissions=[] requires_scopes=None compatible_with=[] incompatible_with=[] egress=0 filters=["process[0]={\"actor_roles\":[\"moderator\"],\"command_prefix\":[5]}"]"#,
        ),
        intentional_diff: None,
    },
    Case {
        file: "filter_lead0.yaml",
        expected: Some(
            r#"name=Some("Music") version=Some("3.0.0") schema_version=Some(2) is_default=false stages=["process"] limits=(2000,64,10) permissions=[] requires_scopes=None compatible_with=[] incompatible_with=[] egress=0 filters=["process[0]={\"actor_roles\":[\"moderator\"],\"command_prefix\":[123.0]}"]"#,
        ),
        intentional_diff: Some(
            "untyped `0123` is a number in saphyr, string in yaml_ng; V29 rejects (fail-closed)",
        ),
    },
    Case {
        file: "filter_lead00.yaml",
        expected: Some(
            r#"name=Some("Music") version=Some("3.0.0") schema_version=Some(2) is_default=false stages=["process"] limits=(2000,64,10) permissions=[] requires_scopes=None compatible_with=[] incompatible_with=[] egress=0 filters=["process[0]={\"actor_roles\":[\"moderator\"],\"command_prefix\":[7.0]}"]"#,
        ),
        intentional_diff: Some(
            "untyped `007` is a number in saphyr, string in yaml_ng; V29 rejects (fail-closed)",
        ),
    },
    Case {
        file: "filter_no.yaml",
        expected: Some(
            r#"name=Some("Music") version=Some("3.0.0") schema_version=Some(2) is_default=false stages=["process"] limits=(2000,64,10) permissions=[] requires_scopes=None compatible_with=[] incompatible_with=[] egress=0 filters=["process[0]={\"actor_roles\":[\"moderator\"],\"command_prefix\":[\"no\"]}"]"#,
        ),
        intentional_diff: None,
    },
    Case {
        file: "filter_null.yaml",
        expected: Some(
            r#"name=Some("Music") version=Some("3.0.0") schema_version=Some(2) is_default=false stages=["process"] limits=(2000,64,10) permissions=[] requires_scopes=None compatible_with=[] incompatible_with=[] egress=0 filters=["process[0]={\"actor_roles\":[\"moderator\"],\"command_prefix\":[null]}"]"#,
        ),
        intentional_diff: None,
    },
    Case {
        file: "filter_off.yaml",
        expected: Some(
            r#"name=Some("Music") version=Some("3.0.0") schema_version=Some(2) is_default=false stages=["process"] limits=(2000,64,10) permissions=[] requires_scopes=None compatible_with=[] incompatible_with=[] egress=0 filters=["process[0]={\"actor_roles\":[\"moderator\"],\"command_prefix\":[\"off\"]}"]"#,
        ),
        intentional_diff: None,
    },
    Case {
        file: "filter_on.yaml",
        expected: Some(
            r#"name=Some("Music") version=Some("3.0.0") schema_version=Some(2) is_default=false stages=["process"] limits=(2000,64,10) permissions=[] requires_scopes=None compatible_with=[] incompatible_with=[] egress=0 filters=["process[0]={\"actor_roles\":[\"moderator\"],\"command_prefix\":[\"on\"]}"]"#,
        ),
        intentional_diff: None,
    },
    Case {
        file: "filter_tilde.yaml",
        expected: Some(
            r#"name=Some("Music") version=Some("3.0.0") schema_version=Some(2) is_default=false stages=["process"] limits=(2000,64,10) permissions=[] requires_scopes=None compatible_with=[] incompatible_with=[] egress=0 filters=["process[0]={\"actor_roles\":[\"moderator\"],\"command_prefix\":[null]}"]"#,
        ),
        intentional_diff: None,
    },
    Case {
        file: "filter_true.yaml",
        expected: Some(
            r#"name=Some("Music") version=Some("3.0.0") schema_version=Some(2) is_default=false stages=["process"] limits=(2000,64,10) permissions=[] requires_scopes=None compatible_with=[] incompatible_with=[] egress=0 filters=["process[0]={\"actor_roles\":[\"moderator\"],\"command_prefix\":[true]}"]"#,
        ),
        intentional_diff: None,
    },
    Case {
        file: "filter_under.yaml",
        expected: Some(
            r#"name=Some("Music") version=Some("3.0.0") schema_version=Some(2) is_default=false stages=["process"] limits=(2000,64,10) permissions=[] requires_scopes=None compatible_with=[] incompatible_with=[] egress=0 filters=["process[0]={\"actor_roles\":[\"moderator\"],\"command_prefix\":[1000]}"]"#,
        ),
        intentional_diff: Some(
            "untyped `1_000` is a number in saphyr, string in yaml_ng; V29 rejects (fail-closed)",
        ),
    },
    Case {
        file: "filter_y.yaml",
        expected: Some(
            r#"name=Some("Music") version=Some("3.0.0") schema_version=Some(2) is_default=false stages=["process"] limits=(2000,64,10) permissions=[] requires_scopes=None compatible_with=[] incompatible_with=[] egress=0 filters=["process[0]={\"actor_roles\":[\"moderator\"],\"command_prefix\":[\"y\"]}"]"#,
        ),
        intentional_diff: None,
    },
    Case {
        file: "filter_yes.yaml",
        expected: Some(
            r#"name=Some("Music") version=Some("3.0.0") schema_version=Some(2) is_default=false stages=["process"] limits=(2000,64,10) permissions=[] requires_scopes=None compatible_with=[] incompatible_with=[] egress=0 filters=["process[0]={\"actor_roles\":[\"moderator\"],\"command_prefix\":[\"yes\"]}"]"#,
        ),
        intentional_diff: None,
    },
    Case {
        file: "filters_nonstring_keys.yaml",
        expected: Some(
            r#"name=Some("Music") version=Some("3.0.0") schema_version=Some(2) is_default=false stages=["process"] limits=(2000,64,10) permissions=[] requires_scopes=None compatible_with=[] incompatible_with=[] egress=0 filters=["process[0]={\"1\":[\"a\"],\"true\":[\"b\"]}"]"#,
        ),
        intentional_diff: None,
    },
    Case {
        file: "flow_style_document.yaml",
        expected: Some(
            r#"name=Some("Music") version=Some("3.0.0") schema_version=Some(2) is_default=false stages=["action"] limits=(2000,64,10) permissions=[] requires_scopes=None compatible_with=[] incompatible_with=[] egress=0 filters=[]"#,
        ),
        intentional_diff: None,
    },
    Case {
        file: "hash_in_plain.yaml",
        expected: Some(
            r#"name=Some("a#b") version=Some("3.0.0") schema_version=Some(2) is_default=false stages=["action"] limits=(2000,64,10) permissions=[] requires_scopes=None compatible_with=[] incompatible_with=[] egress=0 filters=[]"#,
        ),
        intentional_diff: None,
    },
    Case {
        file: "is_default_TRUE.yaml",
        expected: Some(
            r#"name=Some("Music") version=Some("3.0.0") schema_version=Some(2) is_default=true stages=["action"] limits=(2000,64,10) permissions=[] requires_scopes=None compatible_with=[] incompatible_with=[] egress=0 filters=[]"#,
        ),
        intentional_diff: None,
    },
    Case {
        file: "is_default_True.yaml",
        expected: Some(
            r#"name=Some("Music") version=Some("3.0.0") schema_version=Some(2) is_default=true stages=["action"] limits=(2000,64,10) permissions=[] requires_scopes=None compatible_with=[] incompatible_with=[] egress=0 filters=[]"#,
        ),
        intentional_diff: None,
    },
    Case {
        file: "is_default_no.yaml",
        expected: None,
        intentional_diff: None,
    },
    Case {
        file: "is_default_null.yaml",
        expected: None,
        intentional_diff: None,
    },
    Case {
        file: "is_default_on.yaml",
        expected: None,
        intentional_diff: None,
    },
    Case {
        file: "is_default_quoted_true.yaml",
        expected: Some(
            r#"name=Some("Music") version=Some("3.0.0") schema_version=Some(2) is_default=true stages=["action"] limits=(2000,64,10) permissions=[] requires_scopes=None compatible_with=[] incompatible_with=[] egress=0 filters=[]"#,
        ),
        intentional_diff: Some("saphyr coerces quoted 'true' to bool (yaml_ng: type error)"),
    },
    Case {
        file: "is_default_true.yaml",
        expected: Some(
            r#"name=Some("Music") version=Some("3.0.0") schema_version=Some(2) is_default=true stages=["action"] limits=(2000,64,10) permissions=[] requires_scopes=None compatible_with=[] incompatible_with=[] egress=0 filters=[]"#,
        ),
        intentional_diff: None,
    },
    Case {
        file: "is_default_yes.yaml",
        expected: None,
        intentional_diff: None,
    },
    Case {
        file: "limits_negative.yaml",
        expected: Some(
            r#"name=Some("Music") version=Some("3.0.0") schema_version=Some(2) is_default=false stages=["action"] limits=(-5,64,10) permissions=[] requires_scopes=None compatible_with=[] incompatible_with=[] egress=0 filters=[]"#,
        ),
        intentional_diff: None,
    },
    Case {
        file: "limits_null.yaml",
        expected: Some(
            r#"name=Some("Music") version=Some("3.0.0") schema_version=Some(2) is_default=false stages=["action"] limits=(2000,64,10) permissions=[] requires_scopes=None compatible_with=[] incompatible_with=[] egress=0 filters=[]"#,
        ),
        intentional_diff: None,
    },
    Case {
        file: "limits_overflow.yaml",
        expected: None,
        intentional_diff: None,
    },
    Case {
        file: "limits_partial.yaml",
        expected: Some(
            r#"name=Some("Music") version=Some("3.0.0") schema_version=Some(2) is_default=false stages=["action"] limits=(2000,128,10) permissions=[] requires_scopes=None compatible_with=[] incompatible_with=[] egress=0 filters=[]"#,
        ),
        intentional_diff: None,
    },
    Case {
        file: "limits_underscore.yaml",
        expected: Some(
            r#"name=Some("Music") version=Some("3.0.0") schema_version=Some(2) is_default=false stages=["action"] limits=(2000,64,10) permissions=[] requires_scopes=None compatible_with=[] incompatible_with=[] egress=0 filters=[]"#,
        ),
        intentional_diff: Some("saphyr accepts `2_000` for an i64 (yaml_ng: type error)"),
    },
    Case {
        file: "long_string_key_order.yaml",
        expected: Some(
            r#"name=Some("Music") version=Some("3.0.0") schema_version=Some(2) is_default=false stages=["action"] limits=(2000,64,10) permissions=[] requires_scopes=None compatible_with=[] incompatible_with=[] egress=0 filters=[]"#,
        ),
        intentional_diff: None,
    },
    Case {
        file: "merge_key.yaml",
        expected: Some(
            r#"name=Some("Music") version=Some("3.0.0") schema_version=Some(2) is_default=false stages=["action"] limits=(2000,64,10) permissions=[] requires_scopes=None compatible_with=[] incompatible_with=[] egress=0 filters=[]"#,
        ),
        intentional_diff: None,
    },
    Case {
        file: "merge_key_override.yaml",
        expected: Some(
            r#"name=Some("Music") version=Some("3.0.0") schema_version=Some(2) is_default=false stages=["action"] limits=(2000,64,10) permissions=[] requires_scopes=None compatible_with=[] incompatible_with=[] egress=0 filters=[]"#,
        ),
        intentional_diff: None,
    },
    Case {
        file: "multi_doc.yaml",
        expected: None,
        intentional_diff: None,
    },
    Case {
        file: "multiline_plain.yaml",
        expected: Some(
            r#"name=Some("spans two lines") version=Some("3.0.0") schema_version=Some(2) is_default=false stages=["action"] limits=(2000,64,10) permissions=[] requires_scopes=None compatible_with=[] incompatible_with=[] egress=0 filters=[]"#,
        ),
        intentional_diff: None,
    },
    Case {
        file: "name_empty.yaml",
        expected: Some(
            r#"name=None version=Some("3.0.0") schema_version=Some(2) is_default=false stages=["action"] limits=(2000,64,10) permissions=[] requires_scopes=None compatible_with=[] incompatible_with=[] egress=0 filters=[]"#,
        ),
        intentional_diff: None,
    },
    Case {
        file: "name_null_word.yaml",
        expected: Some(
            r#"name=None version=Some("3.0.0") schema_version=Some(2) is_default=false stages=["action"] limits=(2000,64,10) permissions=[] requires_scopes=None compatible_with=[] incompatible_with=[] egress=0 filters=[]"#,
        ),
        intentional_diff: None,
    },
    Case {
        file: "name_number_leading_zero.yaml",
        expected: Some(
            r#"name=Some("0123") version=Some("3.0.0") schema_version=Some(2) is_default=false stages=["action"] limits=(2000,64,10) permissions=[] requires_scopes=None compatible_with=[] incompatible_with=[] egress=0 filters=[]"#,
        ),
        intentional_diff: None,
    },
    Case {
        file: "name_tag_str.yaml",
        expected: Some(
            r#"name=Some("42") version=Some("3.0.0") schema_version=Some(2) is_default=false stages=["action"] limits=(2000,64,10) permissions=[] requires_scopes=None compatible_with=[] incompatible_with=[] egress=0 filters=[]"#,
        ),
        intentional_diff: None,
    },
    Case {
        file: "name_tilde.yaml",
        expected: Some(
            r#"name=None version=Some("3.0.0") schema_version=Some(2) is_default=false stages=["action"] limits=(2000,64,10) permissions=[] requires_scopes=None compatible_with=[] incompatible_with=[] egress=0 filters=[]"#,
        ),
        intentional_diff: None,
    },
    Case {
        file: "name_true.yaml",
        expected: Some(
            r#"name=Some("true") version=Some("3.0.0") schema_version=Some(2) is_default=false stages=["action"] limits=(2000,64,10) permissions=[] requires_scopes=None compatible_with=[] incompatible_with=[] egress=0 filters=[]"#,
        ),
        intentional_diff: None,
    },
    Case {
        file: "name_yes.yaml",
        expected: Some(
            r#"name=Some("yes") version=Some("3.0.0") schema_version=Some(2) is_default=false stages=["action"] limits=(2000,64,10) permissions=[] requires_scopes=None compatible_with=[] incompatible_with=[] egress=0 filters=[]"#,
        ),
        intentional_diff: None,
    },
    Case {
        file: "nested_consumes_filters.yaml",
        expected: Some(
            r#"name=Some("Music") version=Some("3.0.0") schema_version=Some(2) is_default=false stages=["presentation", "process"] limits=(2000,64,10) permissions=[] requires_scopes=None compatible_with=[] incompatible_with=[] egress=0 filters=["process[0]={\"actor_roles\":[\"moderator\",\"vip\"],\"command_prefix\":[\"!sr\",\"!song\"]}"]"#,
        ),
        intentional_diff: None,
    },
    Case {
        file: "only_comment.yaml",
        expected: Some(
            r#"name=None version=None schema_version=None is_default=false stages=[] limits=(2000,64,10) permissions=[] requires_scopes=None compatible_with=[] incompatible_with=[] egress=0 filters=[]"#,
        ),
        intentional_diff: None,
    },
    Case {
        file: "only_doc_marker.yaml",
        expected: Some(
            r#"name=None version=None schema_version=None is_default=false stages=[] limits=(2000,64,10) permissions=[] requires_scopes=None compatible_with=[] incompatible_with=[] egress=0 filters=[]"#,
        ),
        intentional_diff: None,
    },
    Case {
        file: "permissions_alias.yaml",
        expected: Some(
            r#"name=Some("Music") version=Some("3.0.0") schema_version=Some(2) is_default=false stages=["action"] limits=(2000,64,10) permissions=[] requires_scopes=Some(["storage.kv", "net.http"]) compatible_with=[] incompatible_with=[] egress=0 filters=[]"#,
        ),
        intentional_diff: None,
    },
    Case {
        file: "platform_compat.yaml",
        expected: Some(
            r#"name=Some("Music") version=Some("3.0.0") schema_version=Some(2) is_default=false stages=["action"] limits=(2000,64,10) permissions=[] requires_scopes=None compatible_with=[] incompatible_with=[] egress=0 filters=[]"#,
        ),
        intentional_diff: None,
    },
    Case {
        file: "quoted_scalars.yaml",
        expected: Some(
            r#"name=Some("it's: a \"quoted\" # name") version=Some("3.0.0") schema_version=Some(2) is_default=false stages=["action"] limits=(2000,64,10) permissions=[] requires_scopes=None compatible_with=[] incompatible_with=[] egress=0 filters=[]"#,
        ),
        intentional_diff: None,
    },
    Case {
        file: "schema_version_float.yaml",
        expected: None,
        intentional_diff: None,
    },
    Case {
        file: "schema_version_hex.yaml",
        expected: Some(
            r#"name=Some("Music") version=Some("3.0.0") schema_version=Some(2) is_default=false stages=["action"] limits=(2000,64,10) permissions=[] requires_scopes=None compatible_with=[] incompatible_with=[] egress=0 filters=[]"#,
        ),
        intentional_diff: None,
    },
    Case {
        file: "schema_version_null.yaml",
        expected: Some(
            r#"name=Some("Music") version=Some("3.0.0") schema_version=None is_default=false stages=["action"] limits=(2000,64,10) permissions=[] requires_scopes=None compatible_with=[] incompatible_with=[] egress=0 filters=[]"#,
        ),
        intentional_diff: None,
    },
    Case {
        file: "schema_version_quoted.yaml",
        expected: Some(
            r#"name=Some("Music") version=Some("3.0.0") schema_version=Some(2) is_default=false stages=["action"] limits=(2000,64,10) permissions=[] requires_scopes=None compatible_with=[] incompatible_with=[] egress=0 filters=[]"#,
        ),
        intentional_diff: Some("saphyr coerces quoted '2' to i64 (yaml_ng: type error)"),
    },
    Case {
        file: "sequence_of_mixed_scalars_to_strings.yaml",
        expected: None,
        intentional_diff: Some("saphyr rejects a null element in Vec<String> (yaml_ng: accepted)"),
    },
    Case {
        file: "special_floats.yaml",
        expected: Some(
            r#"name=Some(".inf") version=Some("3.0.0") schema_version=Some(2) is_default=false stages=["action"] limits=(2000,64,10) permissions=[] requires_scopes=None compatible_with=[] incompatible_with=[] egress=0 filters=[]"#,
        ),
        intentional_diff: None,
    },
    Case {
        file: "stages_null.yaml",
        expected: Some(
            r#"name=Some("Music") version=Some("3.0.0") schema_version=Some(2) is_default=false stages=[] limits=(2000,64,10) permissions=[] requires_scopes=None compatible_with=[] incompatible_with=[] egress=0 filters=[]"#,
        ),
        intentional_diff: None,
    },
    Case {
        file: "tab_indent_error.yaml",
        expected: None,
        intentional_diff: None,
    },
    Case {
        file: "top_level_scalar.yaml",
        expected: None,
        intentional_diff: None,
    },
    Case {
        file: "top_level_sequence.yaml",
        expected: None,
        intentional_diff: None,
    },
    Case {
        file: "unicode.yaml",
        expected: Some(
            r#"name=Some("Ünïcode 🐧 станция 音楽") version=Some("3.0.0") schema_version=Some(2) is_default=false stages=["action"] limits=(2000,64,10) permissions=[] requires_scopes=None compatible_with=[] incompatible_with=[] egress=0 filters=[]"#,
        ),
        intentional_diff: None,
    },
    Case {
        file: "unicode_escapes_dq.yaml",
        expected: Some(
            r#"name=Some("café 🐧 tab\there") version=Some("3.0.0") schema_version=Some(2) is_default=false stages=["action"] limits=(2000,64,10) permissions=[] requires_scopes=None compatible_with=[] incompatible_with=[] egress=0 filters=[]"#,
        ),
        intentional_diff: None,
    },
    Case {
        file: "unknown_fields_ignored.yaml",
        expected: Some(
            r#"name=Some("Music") version=Some("3.0.0") schema_version=Some(2) is_default=false stages=["action"] limits=(2000,64,10) permissions=[] requires_scopes=None compatible_with=[] incompatible_with=[] egress=0 filters=[]"#,
        ),
        intentional_diff: None,
    },
    Case {
        file: "unterminated_quote.yaml",
        expected: None,
        intentional_diff: None,
    },
    Case {
        file: "version_float_like.yaml",
        expected: Some(
            r#"name=Some("Music") version=Some("3.0") schema_version=Some(2) is_default=false stages=["action"] limits=(2000,64,10) permissions=[] requires_scopes=None compatible_with=[] incompatible_with=[] egress=0 filters=[]"#,
        ),
        intentional_diff: None,
    },
    Case {
        file: "version_int_like.yaml",
        expected: Some(
            r#"name=Some("Music") version=Some("3") schema_version=Some(2) is_default=false stages=["action"] limits=(2000,64,10) permissions=[] requires_scopes=None compatible_with=[] incompatible_with=[] egress=0 filters=[]"#,
        ),
        intentional_diff: None,
    },
    Case {
        file: "version_octal.yaml",
        expected: Some(
            r#"name=Some("Music") version=Some("0o17") schema_version=Some(2) is_default=false stages=["action"] limits=(2000,64,10) permissions=[] requires_scopes=None compatible_with=[] incompatible_with=[] egress=0 filters=[]"#,
        ),
        intentional_diff: None,
    },
    Case {
        file: "version_scientific.yaml",
        expected: Some(
            r#"name=Some("Music") version=Some("1e3") schema_version=Some(2) is_default=false stages=["action"] limits=(2000,64,10) permissions=[] requires_scopes=None compatible_with=[] incompatible_with=[] egress=0 filters=[]"#,
        ),
        intentional_diff: None,
    },
    Case {
        file: "version_with_v_prefix.yaml",
        expected: Some(
            r#"name=Some("Music") version=Some("v3.0.0") schema_version=Some(2) is_default=false stages=["action"] limits=(2000,64,10) permissions=[] requires_scopes=None compatible_with=[] incompatible_with=[] egress=0 filters=[]"#,
        ),
        intentional_diff: None,
    },
];

#[test]
fn hand_written_corpus_matches_expected_digests() {
    let mut failures = Vec::new();
    for case in CASES {
        let source = read(EQUIV_DIR, case.file);
        let actual = parse_raw_yaml(&source).map(|m| digest(&m)).ok();
        if actual.as_deref() != case.expected {
            failures.push(format!(
                "{} (intentional_diff={:?})\n  expected: {:?}\n  actual:   {:?}",
                case.file, case.intentional_diff, case.expected, actual
            ));
        }
    }
    assert!(
        failures.is_empty(),
        "{} mismatches:\n{}",
        failures.len(),
        failures.join("\n")
    );
}

#[test]
fn table_covers_every_equivalence_fixture_exactly_once() {
    let on_disk = yaml_files(EQUIV_DIR);
    let mut in_table: Vec<String> = CASES.iter().map(|c| c.file.to_string()).collect();
    in_table.sort();
    assert!(
        on_disk.len() >= 80,
        "corpus shrank: only {} files",
        on_disk.len()
    );
    assert_eq!(on_disk, in_table, "fixture dir and CASES table diverged");
    let intentional = CASES
        .iter()
        .filter(|c| c.intentional_diff.is_some())
        .count();
    assert_eq!(
        intentional, 8,
        "intentional-difference list changed; update the module doc"
    );
}

#[test]
fn every_existing_manifest_fixture_parses() {
    let mut parsed = 0;
    for dir in [VALID_DIR, INVALID_DIR] {
        for name in yaml_files(dir) {
            parse_raw_yaml(&read(dir, &name))
                .unwrap_or_else(|err| panic!("{dir}/{name} must parse: {err}"));
            parsed += 1;
        }
    }
    assert!(parsed >= 37, "expected >= 37 fixtures, parsed {parsed}");
}

#[test]
fn basic_fixture_parses_and_validates_to_the_expected_manifest() {
    let raw = parse_raw_yaml(&read(VALID_DIR, "basic.yaml")).unwrap();
    assert_eq!(
        digest(&raw),
        r#"name=Some("Music Station Song Request") version=Some("3.0.0") schema_version=Some(2) is_default=true stages=["action", "process"] limits=(2000,64,10) permissions=["music:read"] requires_scopes=None compatible_with=[] incompatible_with=[] egress=2 filters=["process[0]={\"command_prefix\":[\"!sr\"]}"]"#
    );
    let mut manifest = validate(&raw, &ValidationContext::default()).unwrap();
    manifest.stages.sort();
    let all_methods = ["GET", "HEAD", "POST", "PUT", "PATCH", "DELETE"]
        .map(String::from)
        .to_vec();
    assert_eq!(
        manifest,
        Manifest {
            schema_version: 2,
            app_id: "waddles.socials.music.default".into(),
            name: "Music Station Song Request".into(),
            version: "3.0.0".into(),
            feature: "waddles.socials.music".into(),
            module: "socials".into(),
            provider: "builtin".into(),
            language: "python".into(),
            artifact: "source".into(),
            execution_model: "native".into(),
            is_default: true,
            stages: vec!["action".into(), "process".into()],
            egress: vec![
                ("api.spotify.com".into(), vec!["GET".into(), "POST".into()]),
                ("*.googleapis.com".into(), all_methods),
            ],
            data_tables: vec!["music_queue".into()],
            timeout_ms: 2000,
            memory_mb: 64,
            egress_rps: 10,
            permissions: vec!["music:read".into()],
            routes_to: vec![],
            compatible_with: vec![],
            incompatible_with: vec![],
        }
    );
}

#[test]
fn bom_prefix_and_crlf_line_endings_parse_like_plain_lf() {
    let basic = read(VALID_DIR, "basic.yaml");
    let expected = digest(&parse_raw_yaml(&basic).unwrap());
    let crlf = basic.replace('\n', "\r\n");
    assert_eq!(digest(&parse_raw_yaml(&crlf).unwrap()), expected);
    let bom = format!("\u{feff}{basic}");
    assert_eq!(digest(&parse_raw_yaml(&bom).unwrap()), expected);
}

#[test]
fn yaml_1_1_booleans_stay_strings_in_untyped_filter_lists() {
    // regression guard for the parser options: with serde-saphyr defaults
    // `[yes]` became a bool and V29 rejected a manifest yaml_ng accepted.
    for file in [
        "filter_yes.yaml",
        "filter_no.yaml",
        "filter_on.yaml",
        "filter_off.yaml",
    ] {
        let raw = parse_raw_yaml(&read(EQUIV_DIR, file)).unwrap();
        validate(&raw, &ValidationContext::default())
            .unwrap_or_else(|err| panic!("{file} must validate: {err}"));
    }
}

#[test]
fn merge_key_is_an_ordinary_key_not_expanded() {
    let raw = parse_raw_yaml(&read(EQUIV_DIR, "merge_key.yaml")).unwrap();
    assert_eq!(raw.stages["action"].entry, None);
}

#[test]
fn yaml_1_1_booleans_are_rejected_for_typed_bool_fields() {
    for file in [
        "is_default_yes.yaml",
        "is_default_no.yaml",
        "is_default_on.yaml",
    ] {
        assert!(
            parse_raw_yaml(&read(EQUIV_DIR, file)).is_err(),
            "{file} must not parse"
        );
    }
}
