//! Network allowlist rules for the bundle manifest v-next `network:` block
//! (`ingress`/`egress`), plus the pure matcher that enforces them.
//!
//! A [`NetRule`] is one of: an exact FQDN, a leftmost-label wildcard FQDN
//! (validated against the bundled Public Suffix List so `*.com`,
//! `*.co.uk`, `*.github.io` can never be declared), an IPv4 CIDR (/24-/32
//! only) or an IPv6 CIDR (/120-/128 only). Parsing is strict and
//! fail-closed; matching ([`NetRule::host_matches`] /
//! [`NetRule::cidr_contains`]) is pure (no I/O, no DNS) so every
//! PenguinTech app can reuse it as the company-wide connection-library
//! network filter.
//!
//! The Public Suffix List is compiled into the binary by the `psl` crate:
//! there is no runtime fetch and no data file to go stale between releases.

use std::fmt;
use std::net::IpAddr;
use std::str::FromStr;

use serde::{Deserialize, Deserializer, Serialize, Serializer};

/// Narrowest IPv4 prefix accepted (a /24 is 256 addresses). Universal: no
/// rule or tier may declare a broader range.
pub const MIN_IPV4_PREFIX: u8 = 24;
/// Narrowest-allowed IPv6 prefix (a /120 is the 256-address analogue of an
/// IPv4 /24).
// TODO(confirm): IPv6 /120 cap
pub const MIN_IPV6_PREFIX: u8 = 120;

const MAX_HOST_LEN: usize = 253;
const MAX_LABEL_LEN: usize = 63;

/// Why a network rule string was rejected. Stable variants so callers (the
/// manifest validator, CLIs) can map them to a machine-checkable reason.
#[derive(Debug, Clone, PartialEq, Eq, thiserror::Error)]
pub enum NetRuleError {
    /// The rule is empty or contains whitespace.
    #[error("network rule is empty or contains whitespace")]
    Empty,
    /// The rule is not a well-formed FQDN, wildcard or CIDR (bare tokens,
    /// ports, paths, userinfo, bare IP literals, non-ASCII, ...).
    #[error("malformed network rule: {0}")]
    Malformed(&'static str),
    /// A `*` appears outside the leftmost label, or `**` is used.
    #[error("wildcard is only allowed in the leftmost label")]
    WildcardNotLeftmost,
    /// The wildcard's suffix is a public suffix itself (or above one), or
    /// is not a known public-suffix-list TLD, so it is not a registrable
    /// domain.
    #[error("wildcard suffix must be a registrable domain below a public suffix")]
    WildcardAtPublicSuffix,
    /// A CIDR prefix is broader than the allowed minimum.
    #[error("CIDR prefix /{prefix} is broader than the minimum /{min}")]
    PrefixTooBroad {
        /// The declared prefix length.
        prefix: u8,
        /// The minimum prefix length allowed for this address family.
        min: u8,
    },
    /// The CIDR address has host bits set (e.g. `10.0.0.1/24`), which is
    /// ambiguous and almost always a typo.
    #[error("CIDR address has host bits set below the prefix")]
    HostBitsSet,
}

/// Which family a parsed [`NetRule`] belongs to.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash)]
pub enum NetRuleKind {
    /// Exact FQDN such as `discord.com`.
    Fqdn,
    /// Leftmost-label wildcard such as `*.discord.com`.
    Wildcard,
    /// IPv4 CIDR with prefix /24-/32.
    Ipv4Cidr,
    /// IPv6 CIDR with prefix /120-/128.
    Ipv6Cidr,
}

#[derive(Debug, Clone, PartialEq, Eq, Hash)]
enum Repr {
    Fqdn(String),
    Wildcard { label: String, suffix: String },
    Cidr { addr: IpAddr, prefix: u8 },
}

/// One validated network allowlist entry (FQDN, wildcard FQDN or CIDR).
/// Only constructible through [`NetRule::parse`] / `FromStr` /
/// deserialization, so a value in hand has always passed every grammar and
/// public-suffix check. Serializes as its canonical string.
#[derive(Debug, Clone, PartialEq, Eq, Hash)]
pub struct NetRule {
    repr: Repr,
}

impl NetRule {
    /// Parses and validates one allowlist entry. Hostnames are lowercased;
    /// anything outside the documented grammar is rejected (fail-closed).
    pub fn parse(input: &str) -> Result<Self, NetRuleError> {
        if input.is_empty() || input.chars().any(char::is_whitespace) {
            return Err(NetRuleError::Empty);
        }
        if !input.is_ascii() {
            return Err(NetRuleError::Malformed("non-ASCII (use punycode)"));
        }
        if input.contains('/') {
            return parse_cidr(input);
        }
        parse_host(&input.to_ascii_lowercase())
    }

    /// The family of this rule.
    pub fn kind(&self) -> NetRuleKind {
        match &self.repr {
            Repr::Fqdn(_) => NetRuleKind::Fqdn,
            Repr::Wildcard { .. } => NetRuleKind::Wildcard,
            Repr::Cidr {
                addr: IpAddr::V4(_),
                ..
            } => NetRuleKind::Ipv4Cidr,
            Repr::Cidr {
                addr: IpAddr::V6(_),
                ..
            } => NetRuleKind::Ipv6Cidr,
        }
    }

    /// Whether `fqdn` is allowed by this (FQDN or wildcard) rule. Matching
    /// is on label boundaries, never substrings: `*.discord.com` matches
    /// `gateway.discord.com` and `a.b.discord.com` but not the apex
    /// `discord.com`, `notdiscord.com` or `discord.com.evil.com`. A bare
    /// `*` label matches one or more subdomain labels; a label with
    /// literal characters (`cdn-*`) matches exactly one label. Input is
    /// lowercased and one trailing dot is ignored; anything that is not a
    /// plain hostname (ports, paths, `@`, IP literals) never matches. Always
    /// `false` for CIDR rules.
    pub fn host_matches(&self, fqdn: &str) -> bool {
        let Some(host) = normalize_query_host(fqdn) else {
            return false;
        };
        match &self.repr {
            Repr::Fqdn(exact) => host == *exact,
            Repr::Wildcard { label, suffix } => {
                let Some(prefix) = host
                    .strip_suffix(suffix.as_str())
                    .and_then(|rest| rest.strip_suffix('.'))
                else {
                    return false;
                };
                if prefix.is_empty() {
                    return false;
                }
                if label == "*" {
                    true
                } else {
                    !prefix.contains('.') && glob_label(label, prefix)
                }
            }
            Repr::Cidr { .. } => false,
        }
    }

    /// Whether `ip` falls inside this CIDR rule. IPv4-mapped IPv6
    /// addresses (`::ffff:a.b.c.d`) are canonicalised first so they cannot
    /// bypass an IPv4 rule. Always `false` for FQDN/wildcard rules.
    pub fn cidr_contains(&self, ip: IpAddr) -> bool {
        let Repr::Cidr { addr, prefix } = &self.repr else {
            return false;
        };
        match (addr, ip.to_canonical()) {
            (IpAddr::V4(net), IpAddr::V4(candidate)) => {
                mask_v4(u32::from(*net), *prefix) == mask_v4(u32::from(candidate), *prefix)
            }
            (IpAddr::V6(net), IpAddr::V6(candidate)) => {
                mask_v6(u128::from(*net), *prefix) == mask_v6(u128::from(candidate), *prefix)
            }
            _ => false,
        }
    }
}

impl fmt::Display for NetRule {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match &self.repr {
            Repr::Fqdn(host) => f.write_str(host),
            Repr::Wildcard { label, suffix } => write!(f, "{label}.{suffix}"),
            Repr::Cidr { addr, prefix } => write!(f, "{addr}/{prefix}"),
        }
    }
}

impl FromStr for NetRule {
    type Err = NetRuleError;

    fn from_str(s: &str) -> Result<Self, Self::Err> {
        Self::parse(s)
    }
}

impl Serialize for NetRule {
    fn serialize<S: Serializer>(&self, serializer: S) -> Result<S::Ok, S::Error> {
        serializer.collect_str(self)
    }
}

impl<'de> Deserialize<'de> for NetRule {
    fn deserialize<D: Deserializer<'de>>(deserializer: D) -> Result<Self, D::Error> {
        let raw = String::deserialize(deserializer)?;
        Self::parse(&raw).map_err(serde::de::Error::custom)
    }
}

fn mask_v4(value: u32, prefix: u8) -> u32 {
    match prefix {
        0 => 0,
        p => value & (u32::MAX << (32 - u32::from(p.min(32)))),
    }
}

fn mask_v6(value: u128, prefix: u8) -> u128 {
    match prefix {
        0 => 0,
        p => value & (u128::MAX << (128 - u32::from(p.min(128)))),
    }
}

fn parse_cidr(input: &str) -> Result<NetRule, NetRuleError> {
    let (addr_str, prefix_str) = input
        .split_once('/')
        .ok_or(NetRuleError::Malformed("missing prefix"))?;
    if prefix_str.is_empty()
        || prefix_str.len() > 3
        || !prefix_str.bytes().all(|b| b.is_ascii_digit())
    {
        return Err(NetRuleError::Malformed("CIDR prefix is not a number"));
    }
    let prefix: u8 = prefix_str
        .parse()
        .map_err(|_| NetRuleError::Malformed("CIDR prefix out of range"))?;
    let addr = IpAddr::from_str(addr_str)
        .map_err(|_| NetRuleError::Malformed("CIDR address is not an IP literal"))?;
    match addr {
        IpAddr::V4(v4) => {
            if prefix > 32 {
                return Err(NetRuleError::Malformed("IPv4 prefix above /32"));
            }
            if prefix < MIN_IPV4_PREFIX {
                return Err(NetRuleError::PrefixTooBroad {
                    prefix,
                    min: MIN_IPV4_PREFIX,
                });
            }
            if mask_v4(u32::from(v4), prefix) != u32::from(v4) {
                return Err(NetRuleError::HostBitsSet);
            }
        }
        IpAddr::V6(v6) => {
            if prefix > 128 {
                return Err(NetRuleError::Malformed("IPv6 prefix above /128"));
            }
            if prefix < MIN_IPV6_PREFIX {
                return Err(NetRuleError::PrefixTooBroad {
                    prefix,
                    min: MIN_IPV6_PREFIX,
                });
            }
            if mask_v6(u128::from(v6), prefix) != u128::from(v6) {
                return Err(NetRuleError::HostBitsSet);
            }
        }
    }
    Ok(NetRule {
        repr: Repr::Cidr { addr, prefix },
    })
}

fn is_ldh_label(label: &str, allow_star: bool) -> bool {
    !label.is_empty()
        && label.len() <= MAX_LABEL_LEN
        && !label.starts_with('-')
        && !label.ends_with('-')
        && label.bytes().all(|b| {
            b.is_ascii_lowercase() || b.is_ascii_digit() || b == b'-' || (allow_star && b == b'*')
        })
}

fn parse_host(host: &str) -> Result<NetRule, NetRuleError> {
    if host.len() > MAX_HOST_LEN {
        return Err(NetRuleError::Malformed("hostname longer than 253 bytes"));
    }
    if host.contains(':') {
        return Err(NetRuleError::Malformed(
            "ports, IPv6 literals and bare IPs are not allowed (use a CIDR)",
        ));
    }
    if host.bytes().all(|b| b.is_ascii_digit() || b == b'.') {
        return Err(NetRuleError::Malformed(
            "bare IP literal (declare a /32 CIDR instead)",
        ));
    }
    let labels: Vec<&str> = host.split('.').collect();
    if labels.len() < 2 {
        return Err(NetRuleError::Malformed(
            "single-label token (need a fully-qualified domain)",
        ));
    }
    if labels[1..].iter().any(|l| l.contains('*')) {
        return Err(NetRuleError::WildcardNotLeftmost);
    }
    let first = labels[0];
    if first.contains("**") {
        return Err(NetRuleError::WildcardNotLeftmost);
    }
    if !is_ldh_label(first, true) || !labels[1..].iter().all(|l| is_ldh_label(l, false)) {
        return Err(NetRuleError::Malformed("invalid hostname label"));
    }
    if !first.contains('*') {
        return Ok(NetRule {
            repr: Repr::Fqdn(host.to_string()),
        });
    }
    let suffix = labels[1..].join(".");
    if !is_registrable(&suffix) {
        return Err(NetRuleError::WildcardAtPublicSuffix);
    }
    Ok(NetRule {
        repr: Repr::Wildcard {
            label: first.to_string(),
            suffix,
        },
    })
}

/// True when `name` has a known public suffix AND at least one label below
/// it (i.e. is an eTLD+1 or deeper). Unknown TLDs are rejected so a typo
/// cannot become an unbounded wildcard.
fn is_registrable(name: &str) -> bool {
    let known = psl::suffix(name.as_bytes()).is_some_and(|s| s.is_known());
    known && psl::domain_str(name).is_some()
}

fn normalize_query_host(fqdn: &str) -> Option<String> {
    let trimmed = fqdn.strip_suffix('.').unwrap_or(fqdn);
    if trimmed.is_empty() || trimmed.len() > MAX_HOST_LEN || !trimmed.is_ascii() {
        return None;
    }
    let lower = trimmed.to_ascii_lowercase();
    if !lower.split('.').all(|l| is_ldh_label(l, false)) {
        return None;
    }
    Some(lower)
}

/// Matches one DNS label against a glob where each `*` stands for one or
/// more characters (never a `.`; labels contain none).
fn glob_label(pattern: &str, text: &str) -> bool {
    let p = pattern.as_bytes();
    let t = text.as_bytes();
    let mut dp = vec![vec![false; t.len() + 1]; p.len() + 1];
    dp[0][0] = true;
    for i in 1..=p.len() {
        for j in 1..=t.len() {
            dp[i][j] = if p[i - 1] == b'*' {
                dp[i - 1][j - 1] || dp[i][j - 1]
            } else {
                p[i - 1] == t[j - 1] && dp[i - 1][j - 1]
            };
        }
    }
    dp[p.len()][t.len()]
}
