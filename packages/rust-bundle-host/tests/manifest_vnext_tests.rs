//! Manifest v-next (`schema_version: 3`) tests: `kind`, `network`,
//! `requires`, the SemVer min-version helper, and the `Transport`
//! capability wire label.

#![allow(clippy::unwrap_used, clippy::expect_used)]

use penguin_bundle_host::manifest::{
    parse_yaml, satisfies_min_version, BundleKind, Reason, ValidationContext,
};
use penguin_bundle_host::net::NetRuleKind;
use penguin_bundle_host::wire::message::capability_from_str;
use penguin_bundle_host::wire::CapabilityKind;
use rstest::rstest;
use semver::Version;

const BASE: &str = "app_id: waddles.socials.music.default
name: Music
version: 3.0.0
feature: waddles.socials.music
module: socials
provider: builtin
language: python
artifact: source
stages:
  process:
    entry: \"bundles.x:transform\"
    consumes:
      - platform: twitch
        event_types: [\"chat.message\"]
";

fn doc(schema: u8, extra: &str) -> String {
    format!("schema_version: {schema}\n{BASE}{extra}")
}

fn reason_of(source: &str) -> Reason {
    match parse_yaml(source, &ValidationContext::default()) {
        Ok(_) => panic!("expected rejection for:\n{source}"),
        Err(penguin_bundle_host::manifest::ParseError::Validation(e)) => e.reason,
        Err(other) => panic!("unexpected syntax error: {other}"),
    }
}

#[test]
fn v3_without_new_fields_defaults_fail_closed() {
    let m = parse_yaml(&doc(3, ""), &ValidationContext::default()).unwrap();
    assert_eq!(m.schema_version, 3);
    assert_eq!(m.kind, BundleKind::App);
    assert!(m.network.ingress.is_empty() && m.network.egress.is_empty());
    assert!(m.requires.is_empty());
}

#[test]
fn v2_manifests_still_parse_with_defaults() {
    let m = parse_yaml(&doc(2, ""), &ValidationContext::default()).unwrap();
    assert_eq!(m.schema_version, 2);
    assert_eq!(m.kind, BundleKind::App);
    assert_eq!(m.network, Default::default());
}

#[test]
fn v3_full_document_round_trips_every_new_field() {
    let extra = "kind: service
network:
  ingress: [\"10.0.0.0/24\"]
  egress: [\"discord.com\", \"*.discord.com\", \"2001:db8::100/120\"]
requires:
  - bundle: waddles.core.kv
    min_version: 1.2.0
  - bundle: waddles.core.log
";
    let m = parse_yaml(&doc(3, extra), &ValidationContext::default()).unwrap();
    assert_eq!(m.kind, BundleKind::Service);
    assert_eq!(m.network.ingress.len(), 1);
    assert_eq!(m.network.egress.len(), 3);
    assert_eq!(m.network.egress[1].kind(), NetRuleKind::Wildcard);
    assert!(m.network.egress_allows_host("gateway.discord.com"));
    assert!(!m.network.egress_allows_host("evil.com"));
    assert!(m.network.egress_allows_ip("2001:db8::1ab".parse().unwrap()));
    assert!(!m.network.egress_allows_ip("10.0.0.9".parse().unwrap()));
    assert_eq!(m.requires.len(), 2);
    assert_eq!(m.requires[0].min_version, Some(Version::new(1, 2, 0)));
    assert_eq!(m.requires[1].min_version, None);
    assert!(m.requires[0].is_satisfied_by(&Version::new(1, 3, 0)));
    assert!(!m.requires[0].is_satisfied_by(&Version::new(1, 1, 9)));
}

#[rstest]
#[case::bad_kind("kind: daemon\n", Reason::InvalidBundleKind)]
#[case::wildcard_tld("network:\n  egress: [\"*.com\"]\n", Reason::InvalidNetworkRule)]
#[case::broad_cidr("network:\n  ingress: [\"10.0.0.0/8\"]\n", Reason::InvalidNetworkRule)]
#[case::bare_token("network:\n  egress: [\"discord\"]\n", Reason::InvalidNetworkRule)]
#[case::hex_ip("network:\n  egress: [\"0x7f.0.0.1\"]\n", Reason::InvalidNetworkRule)]
#[case::metadata_host(
    "network:\n  egress: [\"metadata.google.internal\"]\n",
    Reason::InvalidNetworkRule
)]
#[case::loopback_cidr("network:\n  egress: [\"127.0.0.0/24\"]\n", Reason::InvalidNetworkRule)]
#[case::imds_ingress(
    "network:\n  ingress: [\"169.254.169.254/32\"]\n",
    Reason::InvalidNetworkRule
)]
#[case::bad_requires_bundle("requires:\n  - bundle: Not A Bundle\n", Reason::InvalidRequires)]
#[case::missing_requires_bundle("requires:\n  - min_version: 1.0.0\n", Reason::InvalidRequires)]
#[case::bad_requires_semver(
    "requires:\n  - bundle: waddles.core.kv\n    min_version: one\n",
    Reason::InvalidRequires
)]
#[case::duplicate_requires(
    "requires:\n  - bundle: waddles.core.kv\n  - bundle: waddles.core.kv\n",
    Reason::InvalidRequires
)]
fn v3_rejects_bad_fields(#[case] extra: &str, #[case] reason: Reason) {
    assert_eq!(reason_of(&doc(3, extra)), reason);
}

#[rstest]
#[case("kind: app\n")]
#[case("network:\n  egress: [\"discord.com\"]\n")]
#[case("requires: []\n")]
fn v2_rejects_v3_only_fields(#[case] extra: &str) {
    assert_eq!(reason_of(&doc(2, extra)), Reason::UnsupportedSchemaVersion);
}

#[test]
fn schema_versions_outside_2_and_3_are_rejected() {
    for v in [0u8, 1, 4] {
        assert_eq!(reason_of(&doc(v, "")), Reason::UnsupportedSchemaVersion);
    }
}

#[rstest]
#[case("app", Some(BundleKind::App))]
#[case("service", Some(BundleKind::Service))]
#[case("App", None)]
#[case("", None)]
fn bundle_kind_parse(#[case] input: &str, #[case] expected: Option<BundleKind>) {
    assert_eq!(BundleKind::parse(input), expected);
}

#[rstest]
#[case("1.2.0", Some("1.2.0"), true)]
#[case("1.2.1", Some("1.2.0"), true)]
#[case("2.0.0", Some("1.9.9"), true)]
#[case("1.1.9", Some("1.2.0"), false)]
#[case("1.2.0-rc.1", Some("1.2.0"), false)]
#[case("1.2.0+build5", Some("1.2.0"), true)]
#[case("0.0.1", None, true)]
fn semver_min_version(#[case] actual: &str, #[case] min: Option<&str>, #[case] ok: bool) {
    let actual = Version::parse(actual).unwrap();
    let min = min.map(|m| Version::parse(m).unwrap());
    assert_eq!(satisfies_min_version(&actual, min.as_ref()), ok);
}

#[test]
fn transport_capability_has_a_stable_wire_label() {
    assert_eq!(
        capability_from_str("transport"),
        Some(CapabilityKind::Transport)
    );
    assert_eq!(
        serde_json::to_string(&CapabilityKind::Transport).unwrap(),
        "\"transport\""
    );
    assert_eq!(
        serde_json::from_str::<CapabilityKind>("\"transport\"").unwrap(),
        CapabilityKind::Transport
    );
    // Existing variants are untouched.
    assert_eq!(capability_from_str("http"), Some(CapabilityKind::Http));
}

fn reason_with_denylist(source: &str, denylist: &[String]) -> Result<(), Reason> {
    let ctx = ValidationContext {
        egress_denylist: denylist,
        ..Default::default()
    };
    match parse_yaml(source, &ctx) {
        Ok(_) => Ok(()),
        Err(penguin_bundle_host::manifest::ParseError::Validation(e)) => Err(e.reason),
        Err(other) => panic!("unexpected syntax error: {other}"),
    }
}

// regression: PR136 review finding 2 - `network.egress` must honour the
// tenant egress denylist (FQDN and wildcard that covers a denylisted host).
#[rstest]
#[case::exact_fqdn("blocked.example.com", "blocked.example.com")]
#[case::exact_under_wildcard_entry("x.blocked.example.com", "*.blocked.example.com")]
#[case::wildcard_covers_denied_host("*.example.com", "blocked.example.com")]
#[case::wildcard_covers_denied_wildcard("*.example.com", "*.blocked.example.com")]
#[case::wildcard_under_denied_wildcard("*.sub.blocked.example.com", "*.blocked.example.com")]
#[case::same_wildcard("*.blocked.example.com", "*.blocked.example.com")]
#[case::glob_label_under_denied_wildcard("cdn-*.blocked.example.com", "*.blocked.example.com")]
#[case::case_insensitive_entry("blocked.example.com", "Blocked.Example.COM")]
fn v3_network_egress_honours_the_denylist(#[case] rule: &str, #[case] denied: &str) {
    let extra = format!("network:\n  egress: [\"{rule}\"]\n");
    let denylist = vec![denied.to_string()];
    assert_eq!(
        reason_with_denylist(&doc(3, &extra), &denylist),
        Err(Reason::EgressHostDenylisted)
    );
}

#[rstest]
#[case::unrelated("ok.example.com", "blocked.example.com")]
#[case::sibling_wildcard("*.other.example.com", "*.blocked.example.com")]
#[case::suffix_lookalike("notblocked.example.com", "blocked.example.com")]
#[case::wildcard_does_not_cover_parent("*.blocked.example.com", "example.com")]
#[case::glob_does_not_cover_deeper("cdn-*.example.com", "x.blocked.example.com")]
fn v3_network_egress_allows_non_denylisted(#[case] rule: &str, #[case] denied: &str) {
    let extra = format!("network:\n  egress: [\"{rule}\"]\n");
    let denylist = vec![denied.to_string()];
    assert_eq!(reason_with_denylist(&doc(3, &extra), &denylist), Ok(()));
}

#[test]
fn v3_network_egress_cidr_and_ingress_ignore_the_hostname_denylist() {
    let extra = "network:\n  ingress: [\"blocked.example.com\"]\n  egress: [\"10.0.0.0/24\"]\n";
    let denylist = vec!["blocked.example.com".to_string()];
    assert_eq!(reason_with_denylist(&doc(3, extra), &denylist), Ok(()));
}
