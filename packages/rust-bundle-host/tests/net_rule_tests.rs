//! Table-driven grammar + matcher tests for `net::NetRule`
//! (manifest v-next network allowlist).

#![allow(clippy::unwrap_used, clippy::expect_used)]

use std::net::IpAddr;

use penguin_bundle_host::net::{NetRule, NetRuleError, NetRuleKind};
use rstest::rstest;

#[rstest]
#[case::exact_fqdn("discord.com", NetRuleKind::Fqdn, "discord.com")]
#[case::exact_deep("gateway.discord.com", NetRuleKind::Fqdn, "gateway.discord.com")]
#[case::exact_uppercase_normalized("Discord.COM", NetRuleKind::Fqdn, "discord.com")]
#[case::exact_punycode(
    "xn--bcher-kva.example.com",
    NetRuleKind::Fqdn,
    "xn--bcher-kva.example.com"
)]
#[case::exact_dev_tld_label("dev.example.com", NetRuleKind::Fqdn, "dev.example.com")]
#[case::v4_mapped_canonicalised("::ffff:10.0.0.0/120", NetRuleKind::Ipv4Cidr, "10.0.0.0/24")]
#[case::v4_mapped_host("::ffff:203.0.113.7/128", NetRuleKind::Ipv4Cidr, "203.0.113.7/32")]
#[case::wildcard_leftmost("*.discord.com", NetRuleKind::Wildcard, "*.discord.com")]
#[case::wildcard_prefix_glob("cdn-*.discord.com", NetRuleKind::Wildcard, "cdn-*.discord.com")]
#[case::wildcard_suffix_glob("*-cdn.discord.com", NetRuleKind::Wildcard, "*-cdn.discord.com")]
#[case::wildcard_mid_glob("a*b.discord.com", NetRuleKind::Wildcard, "a*b.discord.com")]
#[case::wildcard_multi_star("a*b*c.discord.com", NetRuleKind::Wildcard, "a*b*c.discord.com")]
#[case::wildcard_multi_label_suffix(
    "*.cdn.discord.com",
    NetRuleKind::Wildcard,
    "*.cdn.discord.com"
)]
#[case::wildcard_under_multi_part_suffix(
    "*.example.co.uk",
    NetRuleKind::Wildcard,
    "*.example.co.uk"
)]
#[case::wildcard_under_private_suffix(
    "*.mytenant.github.io",
    NetRuleKind::Wildcard,
    "*.mytenant.github.io"
)]
#[case::v4_24("10.0.0.0/24", NetRuleKind::Ipv4Cidr, "10.0.0.0/24")]
#[case::v4_25("10.0.0.128/25", NetRuleKind::Ipv4Cidr, "10.0.0.128/25")]
#[case::v4_32("203.0.113.7/32", NetRuleKind::Ipv4Cidr, "203.0.113.7/32")]
#[case::v6_120("2001:db8::100/120", NetRuleKind::Ipv6Cidr, "2001:db8::100/120")]
#[case::v6_128("2001:db8::1/128", NetRuleKind::Ipv6Cidr, "2001:db8::1/128")]
fn accepts_valid_rules(#[case] input: &str, #[case] kind: NetRuleKind, #[case] canonical: &str) {
    let rule = NetRule::parse(input).unwrap_or_else(|e| panic!("{input:?} must parse: {e}"));
    assert_eq!(rule.kind(), kind);
    assert_eq!(rule.to_string(), canonical);
    // Canonical form is a parse fixed point.
    assert_eq!(NetRule::parse(canonical).unwrap(), rule);
}

#[rstest]
#[case::empty("", NetRuleError::Empty)]
#[case::whitespace(" discord.com", NetRuleError::Empty)]
#[case::inner_whitespace("dis cord.com", NetRuleError::Empty)]
#[case::bare_token(
    "discord",
    NetRuleError::Malformed("single-label token (need a fully-qualified domain)")
)]
#[case::wildcard_alone_single_label(
    "*",
    NetRuleError::Malformed("single-label token (need a fully-qualified domain)")
)]
#[case::wildcard_tld_com("*.com", NetRuleError::WildcardAtPublicSuffix)]
#[case::wildcard_tld_cooluk("*.co.uk", NetRuleError::WildcardAtPublicSuffix)]
#[case::wildcard_private_suffix("*.github.io", NetRuleError::WildcardAtPublicSuffix)]
#[case::wildcard_unknown_tld("*.notarealtld", NetRuleError::WildcardAtPublicSuffix)]
#[case::wildcard_glob_at_suffix("a*.com", NetRuleError::WildcardAtPublicSuffix)]
#[case::wildcard_non_leftmost("a.*.discord.com", NetRuleError::WildcardNotLeftmost)]
#[case::wildcard_two_stars_labels("*.*.discord.com", NetRuleError::WildcardNotLeftmost)]
#[case::wildcard_in_apex("discord.*", NetRuleError::WildcardNotLeftmost)]
#[case::wildcard_double_star("**.discord.com", NetRuleError::WildcardNotLeftmost)]
#[case::wildcard_double_star_mid("a**b.discord.com", NetRuleError::WildcardNotLeftmost)]
#[case::trailing_dot("discord.com.", NetRuleError::Malformed("invalid hostname label"))]
#[case::leading_dot(".discord.com", NetRuleError::Malformed("invalid hostname label"))]
#[case::empty_label("a..discord.com", NetRuleError::Malformed("invalid hostname label"))]
#[case::leading_hyphen("-a.discord.com", NetRuleError::Malformed("invalid hostname label"))]
#[case::trailing_hyphen("a-.discord.com", NetRuleError::Malformed("invalid hostname label"))]
#[case::underscore("a_b.discord.com", NetRuleError::Malformed("invalid hostname label"))]
#[case::url(
    "https://discord.com",
    NetRuleError::Malformed("CIDR prefix is not a number")
)]
#[case::path(
    "discord.com/path",
    NetRuleError::Malformed("CIDR prefix is not a number")
)]
#[case::port(
    "discord.com:443",
    NetRuleError::Malformed("ports, IPv6 literals and bare IPs are not allowed (use a CIDR)")
)]
#[case::userinfo("user@discord.com", NetRuleError::Malformed("invalid hostname label"))]
#[case::non_ascii(
    "b\u{fc}cher.example.com",
    NetRuleError::Malformed("non-ASCII (use punycode)")
)]
#[case::bare_ipv4(
    "127.0.0.1",
    NetRuleError::Malformed("bare IP literal (declare a /32 CIDR instead)")
)]
#[case::bare_ipv6(
    "::1",
    NetRuleError::Malformed("ports, IPv6 literals and bare IPs are not allowed (use a CIDR)")
)]
#[case::numeric_dotted(
    "1.2.3",
    NetRuleError::Malformed("bare IP literal (declare a /32 CIDR instead)")
)]
#[case::too_long_label(
    "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa.discord.com",
    NetRuleError::Malformed("invalid hostname label")
)]
#[case::v4_23("10.0.0.0/23", NetRuleError::PrefixTooBroad { prefix: 23, min: 24 })]
#[case::v4_16("10.0.0.0/16", NetRuleError::PrefixTooBroad { prefix: 16, min: 24 })]
#[case::v4_8("10.0.0.0/8", NetRuleError::PrefixTooBroad { prefix: 8, min: 24 })]
#[case::v4_0("0.0.0.0/0", NetRuleError::PrefixTooBroad { prefix: 0, min: 24 })]
#[case::v4_33("10.0.0.0/33", NetRuleError::Malformed("IPv4 prefix above /32"))]
#[case::v4_host_bits("10.0.0.1/24", NetRuleError::HostBitsSet)]
#[case::v4_non_numeric_prefix(
    "10.0.0.0/ab",
    NetRuleError::Malformed("CIDR prefix is not a number")
)]
#[case::v4_empty_prefix("10.0.0.0/", NetRuleError::Malformed("CIDR prefix is not a number"))]
#[case::v4_negative_prefix("10.0.0.0/-1", NetRuleError::Malformed("CIDR prefix is not a number"))]
#[case::v4_huge_prefix("10.0.0.0/999", NetRuleError::Malformed("CIDR prefix out of range"))]
#[case::cidr_not_ip(
    "example.com/24",
    NetRuleError::Malformed("CIDR address is not an IP literal")
)]
#[case::v6_119("2001:db8::/119", NetRuleError::PrefixTooBroad { prefix: 119, min: 120 })]
#[case::v6_64("2001:db8::/64", NetRuleError::PrefixTooBroad { prefix: 64, min: 120 })]
#[case::v6_0("::/0", NetRuleError::PrefixTooBroad { prefix: 0, min: 120 })]
#[case::v6_129("2001:db8::1/129", NetRuleError::Malformed("IPv6 prefix above /128"))]
#[case::v6_host_bits("2001:db8::1/120", NetRuleError::HostBitsSet)]
// regression: PR136 review finding 3 (numeric / hex last label read as an IP)
#[case::hex_ip_dotted("0x7f.0.0.1", NetRuleError::Malformed(NUMERIC_LAST))]
#[case::hex_ip_short("0x7f.1", NetRuleError::Malformed(NUMERIC_LAST))]
#[case::hex_last_label("a.0x1", NetRuleError::Malformed(NUMERIC_LAST))]
#[case::hex_last_label_bare_prefix("a.0x", NetRuleError::Malformed(NUMERIC_LAST))]
#[case::decimal_last_label("a.123", NetRuleError::Malformed(NUMERIC_LAST))]
#[case::wildcard_numeric_last("*.example.0x1", NetRuleError::Malformed(NUMERIC_LAST))]
// regression: PR136 review finding 4 (internal-only names)
#[case::localhost_sub("a.localhost", NetRuleError::InternalHost)]
#[case::localhost_wildcard("*.localhost", NetRuleError::InternalHost)]
#[case::internal_tld("db.internal", NetRuleError::InternalHost)]
#[case::gcp_metadata("metadata.google.internal", NetRuleError::InternalHost)]
#[case::mdns_local("printer.local", NetRuleError::InternalHost)]
#[case::cluster_local("api.svc.cluster.local", NetRuleError::InternalHost)]
#[case::cluster_local_wildcard("*.svc.cluster.local", NetRuleError::InternalHost)]
#[case::home_arpa("x.home.arpa", NetRuleError::InternalHost)]
#[case::lan_tld("nas.lan", NetRuleError::InternalHost)]
// regression: PR136 review finding 4 (special-use CIDRs)
#[case::loopback_v4("127.0.0.0/24", NetRuleError::SpecialUseAddress)]
#[case::loopback_host_v4("127.0.0.1/32", NetRuleError::SpecialUseAddress)]
#[case::link_local_v4("169.254.169.0/24", NetRuleError::SpecialUseAddress)]
#[case::imds_v4("169.254.169.254/32", NetRuleError::SpecialUseAddress)]
#[case::this_network_v4("0.0.0.0/32", NetRuleError::SpecialUseAddress)]
#[case::this_network_24("0.0.1.0/24", NetRuleError::SpecialUseAddress)]
#[case::multicast_v4("224.0.0.0/24", NetRuleError::SpecialUseAddress)]
#[case::reserved_v4("240.0.0.0/24", NetRuleError::SpecialUseAddress)]
#[case::broadcast_v4("255.255.255.255/32", NetRuleError::SpecialUseAddress)]
#[case::loopback_v6("::1/128", NetRuleError::SpecialUseAddress)]
#[case::unspecified_v6("::/128", NetRuleError::SpecialUseAddress)]
#[case::link_local_v6("fe80::/120", NetRuleError::SpecialUseAddress)]
#[case::link_local_v6_high("febf::100/120", NetRuleError::SpecialUseAddress)]
#[case::multicast_v6("ff02::1:0/120", NetRuleError::SpecialUseAddress)]
#[case::unique_local_v6("fd00::100/120", NetRuleError::SpecialUseAddress)]
#[case::unique_local_v6_fc("fc00::/120", NetRuleError::SpecialUseAddress)]
#[case::nat64("64:ff9b::a00:0/120", NetRuleError::SpecialUseAddress)]
#[case::nat64_local_use("64:ff9b:1::/120", NetRuleError::SpecialUseAddress)]
#[case::mapped_loopback("::ffff:127.0.0.0/120", NetRuleError::SpecialUseAddress)]
#[case::mapped_link_local("::ffff:169.254.169.254/128", NetRuleError::SpecialUseAddress)]
#[case::ipv4_compatible("::7f00:0/120", NetRuleError::SpecialUseAddress)]
// regression: PR136 review finding 1 (wildcard at a nested public suffix is
// not matchable; see `wildcard_never_spans_a_nested_public_suffix`)
fn rejects_invalid_rules(#[case] input: &str, #[case] expected: NetRuleError) {
    assert_eq!(NetRule::parse(input), Err(expected), "input {input:?}");
}

const NUMERIC_LAST: &str = "last label is numeric (resolvers read it as an IP address)";

fn rule(s: &str) -> NetRule {
    NetRule::parse(s).unwrap_or_else(|e| panic!("{s:?} must parse: {e}"))
}

#[rstest]
// exact FQDN
#[case("discord.com", "discord.com", true)]
#[case("discord.com", "DISCORD.com", true)]
#[case("discord.com", "discord.com.", true)]
#[case("discord.com", "gateway.discord.com", false)]
#[case("discord.com", "notdiscord.com", false)]
#[case("discord.com", "discord.com.evil.com", false)]
// wildcard: label-boundary suffix, apex excluded, any depth for bare `*`
#[case("*.discord.com", "gateway.discord.com", true)]
#[case("*.discord.com", "a.b.discord.com", true)]
#[case("*.discord.com", "GATEWAY.Discord.Com.", true)]
#[case("*.discord.com", "discord.com", false)]
#[case("*.discord.com", "notdiscord.com", false)]
#[case("*.discord.com", "xdiscord.com", false)]
#[case("*.discord.com", ".discord.com", false)]
#[case("*.discord.com", "discord.com.evil.com", false)]
#[case("*.discord.com", "gateway.discord.com.evil.com", false)]
#[case("*.discord.com", "evil.com", false)]
#[case("*.discord.com", "gateway.discord.org", false)]
// intra-label globs: one label, `*` = 1+ chars, never crosses a dot
#[case("cdn-*.discord.com", "cdn-1.discord.com", true)]
#[case("cdn-*.discord.com", "cdn-.discord.com", false)]
#[case("cdn-*.discord.com", "cdn.discord.com", false)]
#[case("cdn-*.discord.com", "cdn-1.x.discord.com", false)]
#[case("cdn-*.discord.com", "x.cdn-1.discord.com", false)]
#[case("cdn-*.discord.com", "xcdn-1.discord.com", false)]
#[case("*-cdn.discord.com", "eu-cdn.discord.com", true)]
#[case("*-cdn.discord.com", "-cdn.discord.com", false)]
#[case("*-cdn.discord.com", "eu-cdn-x.discord.com", false)]
#[case("a*b.discord.com", "axb.discord.com", true)]
#[case("a*b.discord.com", "ab.discord.com", false)]
#[case("a*b*c.discord.com", "a1b2c.discord.com", true)]
#[case("a*b*c.discord.com", "a1bc.discord.com", false)]
// SSRF / smuggling shaped hosts never match anything
#[case("*.discord.com", "gateway.discord.com:443", false)]
#[case("*.discord.com", "gateway.discord.com/path", false)]
#[case("*.discord.com", "evil.com@gateway.discord.com", false)]
#[case("*.discord.com", "gateway.discord.com@evil.com", false)]
#[case("*.discord.com", "gateway.discord.com\\@evil.com", false)]
#[case("*.discord.com", "gateway.discord.com?x=.discord.com", false)]
#[case("*.discord.com", "gateway.discord.com%2eevil.com", false)]
#[case("*.discord.com", "a..discord.com", false)]
#[case("*.discord.com", "gateway.discord.com..", false)]
#[case("*.discord.com", "", false)]
#[case("*.discord.com", ".", false)]
#[case("*.discord.com", "gat\u{e9}way.discord.com", false)]
#[case("*.discord.com", "127.0.0.1", false)]
#[case("*.discord.com", "[::1]", false)]
#[case("*.discord.com", "localhost", false)]
#[case("discord.com", "discord.com:443", false)]
#[case("discord.com", "127.0.0.1", false)]
// ordinary subdomains that happen to be TLD-named still match
#[case("*.example.com", "dev.example.com", true)]
#[case("*.example.com", "a.app.example.com", true)]
#[case("*.mybucket.s3.amazonaws.com", "x.mybucket.s3.amazonaws.com", true)]
fn host_matching(#[case] pattern: &str, #[case] host: &str, #[case] expected: bool) {
    assert_eq!(
        rule(pattern).host_matches(host),
        expected,
        "{pattern:?} vs {host:?}"
    );
}

#[rstest]
#[case("10.0.0.0/24", "10.0.0.0", true)]
#[case("10.0.0.0/24", "10.0.0.255", true)]
#[case("10.0.0.0/24", "10.0.1.0", false)]
#[case("10.0.0.0/24", "9.255.255.255", false)]
#[case("10.0.0.128/25", "10.0.0.200", true)]
#[case("10.0.0.128/25", "10.0.0.127", false)]
#[case("203.0.113.7/32", "203.0.113.7", true)]
#[case("203.0.113.7/32", "203.0.113.8", false)]
// IPv4-mapped IPv6 cannot bypass a v4 rule, nor smuggle past it
#[case("10.0.0.0/24", "::ffff:10.0.0.5", true)]
#[case("10.0.0.0/24", "::ffff:10.0.1.5", false)]
#[case("10.0.0.0/24", "2001:db8::1", false)]
#[case("2001:db8::100/120", "2001:db8::1ff", true)]
#[case("2001:db8::100/120", "2001:db8::200", false)]
#[case("2001:db8::100/120", "2001:db8::ff", false)]
#[case("2001:db8::1/128", "2001:db8::1", true)]
#[case("2001:db8::1/128", "2001:db8::2", false)]
#[case("2001:db8::100/120", "10.0.0.1", false)]
fn cidr_matching(#[case] pattern: &str, #[case] ip: &str, #[case] expected: bool) {
    let ip: IpAddr = ip.parse().unwrap();
    assert_eq!(
        rule(pattern).cidr_contains(ip),
        expected,
        "{pattern:?} vs {ip}"
    );
}

#[test]
fn host_rules_never_match_ips_and_cidr_rules_never_match_hosts() {
    let ip: IpAddr = "10.0.0.5".parse().unwrap();
    assert!(!rule("discord.com").cidr_contains(ip));
    assert!(!rule("*.discord.com").cidr_contains(ip));
    assert!(!rule("10.0.0.0/24").host_matches("10.0.0.5"));
    assert!(!rule("10.0.0.0/24").host_matches("discord.com"));
}

#[test]
fn serde_round_trips_as_a_canonical_string_and_rejects_bad_rules() {
    let r = rule("*.Discord.com");
    let json = serde_json::to_string(&r).unwrap();
    assert_eq!(json, "\"*.discord.com\"");
    assert_eq!(serde_json::from_str::<NetRule>(&json).unwrap(), r);
    assert!(serde_json::from_str::<NetRule>("\"*.com\"").is_err());
    assert!(serde_json::from_str::<NetRule>("\"10.0.0.0/8\"").is_err());
    assert!(serde_json::from_str::<NetRule>("42").is_err());
}

#[test]
fn from_str_matches_parse() {
    assert_eq!(
        "discord.com".parse::<NetRule>().unwrap(),
        rule("discord.com")
    );
    assert!("*.com".parse::<NetRule>().is_err());
}

// regression: PR136 review finding 1 - a parent wildcard must not span a
// public suffix nested below it (private-section PSL entries).
#[rstest]
#[case("*.amazonaws.com", "attacker.s3.amazonaws.com")]
#[case("*.amazonaws.com", "s3.amazonaws.com")]
#[case("*.amazonaws.com", "a.b.s3.amazonaws.com")]
#[case("*.example.com", "a.github.io.example.com")]
#[case("*.example.com", "x.co.uk.example.com")]
fn wildcard_never_spans_a_nested_public_suffix(#[case] pattern: &str, #[case] host: &str) {
    let allowed = NetRule::parse(pattern).is_ok_and(|r| r.host_matches(host));
    assert!(!allowed, "{pattern:?} must not match {host:?}");
}

#[test]
fn shared_infra_must_be_listed_as_an_exact_fqdn() {
    assert!(rule("mybucket.s3.amazonaws.com").host_matches("mybucket.s3.amazonaws.com"));
    assert!(!rule("mybucket.s3.amazonaws.com").host_matches("attacker.s3.amazonaws.com"));
}

// regression: PR136 review finding 5 - a mapped rule must not be silently dead.
#[test]
fn ipv4_mapped_rule_is_canonicalised_and_live() {
    let r = rule("::ffff:10.0.0.0/120");
    assert_eq!(r, rule("10.0.0.0/24"));
    assert!(r.cidr_contains("10.0.0.5".parse().unwrap()));
    assert!(r.cidr_contains("::ffff:10.0.0.5".parse().unwrap()));
    assert!(!r.cidr_contains("10.0.1.5".parse().unwrap()));
}
