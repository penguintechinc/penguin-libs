//! Bundle manifest v-next (`schema_version: 3`) additions: the bundle
//! `kind`, the declarative `network:` allowlist, and `requires:` service
//! dependencies with a SemVer minimum-version check.

use semver::Version;
use serde::{Deserialize, Serialize};

use crate::net::NetRule;

/// Whether a bundle is an app (user-facing, may `require` services) or a
/// service (shared infrastructure other bundles depend on). Defaults to
/// `App` when `kind` is absent.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash, Default, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum BundleKind {
    /// A regular app bundle.
    #[default]
    App,
    /// A service bundle other bundles may depend on.
    Service,
}

impl BundleKind {
    /// Parses the manifest `kind:` string; `None` for anything but
    /// `app`/`service` so the validator can report a stable reason.
    pub fn parse(value: &str) -> Option<Self> {
        match value {
            "app" => Some(Self::App),
            "service" => Some(Self::Service),
            _ => None,
        }
    }
}

/// The declared network surface of a bundle. Both lists default to empty,
/// which means no network access at all (fail-closed): a bundle can only
/// reach or be reached by what it explicitly lists.
#[derive(Debug, Clone, Default, PartialEq, Eq, Serialize, Deserialize)]
#[serde(default)]
pub struct NetworkPolicy {
    /// Sources allowed to connect in.
    pub ingress: Vec<NetRule>,
    /// Destinations the bundle may connect out to.
    pub egress: Vec<NetRule>,
}

impl NetworkPolicy {
    /// True when `fqdn` is allowed by any egress FQDN/wildcard rule.
    pub fn egress_allows_host(&self, fqdn: &str) -> bool {
        self.egress.iter().any(|r| r.host_matches(fqdn))
    }

    /// True when `ip` is allowed by any egress CIDR rule.
    pub fn egress_allows_ip(&self, ip: std::net::IpAddr) -> bool {
        self.egress.iter().any(|r| r.cidr_contains(ip))
    }
}

/// A dependency on another (service) bundle, optionally with a minimum
/// version. App bundles use this to declare the services they need.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct RequiredService {
    /// The required bundle's id.
    pub bundle: String,
    /// The lowest acceptable version; `None` accepts any version.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub min_version: Option<Version>,
}

impl RequiredService {
    /// Whether a candidate service bundle at `version` satisfies this
    /// requirement (see [`satisfies_min_version`]).
    pub fn is_satisfied_by(&self, version: &Version) -> bool {
        satisfies_min_version(version, self.min_version.as_ref())
    }
}

/// Compares a service bundle's `actual` version against an optional
/// `min_version`: no minimum accepts anything, otherwise `actual >= min`
/// by SemVer precedence (so `1.2.0-rc.1` does NOT satisfy a `1.2.0`
/// minimum; build metadata is ignored).
pub fn satisfies_min_version(actual: &Version, min_version: Option<&Version>) -> bool {
    min_version.is_none_or(|min| actual.cmp_precedence(min) != std::cmp::Ordering::Less)
}

/// `requires[]` entry exactly as deserialized (validation pending).
#[derive(Debug, Clone, Default, Deserialize)]
#[serde(default)]
pub struct RawRequiredService {
    pub bundle: Option<String>,
    pub min_version: Option<String>,
}

/// `network` exactly as deserialized (rule strings not yet parsed).
#[derive(Debug, Clone, Default, Deserialize)]
#[serde(default)]
pub struct RawNetworkPolicy {
    pub ingress: Vec<String>,
    pub egress: Vec<String>,
}
