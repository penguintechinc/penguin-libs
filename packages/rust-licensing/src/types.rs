//! Wire and domain types for license validation and feature flags.

use std::collections::HashMap;

use chrono::{DateTime, Utc};
use serde::{Deserialize, Serialize};

/// License tiers, cumulative. `Free` is also spelled `community` by older
/// servers — both parse to `Tier::Free`.
#[derive(Debug, Clone, Copy, PartialEq, Eq, PartialOrd, Ord, Serialize)]
#[serde(rename_all = "lowercase")]
pub enum Tier {
    /// Core product, no license-gated functionality.
    Free,
    /// Adds whitelabelling, Google OAuth2 SSO.
    Professional,
    /// Adds SAML/OIDC SSO, audit/compliance, WaddleAI, advanced analytics.
    Enterprise,
}

impl Tier {
    /// Parses a server-supplied tier string; unknown values map to `Free`
    /// (fail-safe: never grant more than the server proved).
    pub fn parse(s: &str) -> Self {
        match s.trim().to_ascii_lowercase().as_str() {
            "professional" | "pro" => Tier::Professional,
            "enterprise" => Tier::Enterprise,
            _ => Tier::Free,
        }
    }
}

impl<'de> Deserialize<'de> for Tier {
    fn deserialize<D: serde::Deserializer<'de>>(d: D) -> Result<Self, D::Error> {
        let s = String::deserialize(d)?;
        Ok(Tier::parse(&s))
    }
}

/// One licensed feature with its entitlement decision.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Feature {
    /// Feature identifier (bare name, e.g. `sso`, or `{product}.{name}`).
    pub name: String,
    /// Whether this license is entitled to the feature.
    pub entitled: bool,
    /// Licensed units: 0 = unlimited, -1 = not applicable.
    #[serde(default = "default_units")]
    pub units: i64,
    /// Human-readable description.
    #[serde(default)]
    pub description: String,
    /// Server-supplied metadata.
    #[serde(default)]
    pub metadata: serde_json::Value,
}

fn default_units() -> i64 {
    -1
}

/// Validated license state, as returned by `POST /api/v2/validate`.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct LicenseInfo {
    /// Whether the license validated successfully.
    #[serde(default)]
    pub valid: bool,
    /// Customer display name.
    #[serde(default)]
    pub customer: String,
    /// Product this license applies to.
    #[serde(default)]
    pub product: String,
    /// Resolved tier.
    #[serde(default = "default_tier")]
    pub tier: Tier,
    /// Expiry timestamp.
    #[serde(default)]
    pub expires_at: Option<DateTime<Utc>>,
    /// Issue timestamp.
    #[serde(default)]
    pub issued_at: Option<DateTime<Utc>>,
    /// Per-feature entitlements.
    #[serde(default)]
    pub features: Vec<Feature>,
    /// Usage limits (product-specific shape).
    #[serde(default)]
    pub limits: serde_json::Value,
    /// Server metadata; `metadata.server_id` feeds keepalives.
    #[serde(default)]
    pub metadata: serde_json::Value,
    /// Optional server message (e.g. failure reason).
    #[serde(default)]
    pub message: Option<String>,
}

fn default_tier() -> Tier {
    Tier::Free
}

impl LicenseInfo {
    /// The community/free fallback used when no license key is configured
    /// or the server is unreachable with nothing cached. Valid, but no
    /// gated feature is entitled.
    pub fn community_fallback(product: &str, message: Option<String>) -> Self {
        Self {
            valid: true,
            customer: "Community User".to_owned(),
            product: product.to_owned(),
            tier: Tier::Free,
            expires_at: None,
            issued_at: Some(Utc::now()),
            features: Vec::new(),
            limits: serde_json::Value::Null,
            metadata: serde_json::Value::Null,
            message: Some(message.unwrap_or_else(|| "Community tier (no license)".to_owned())),
        }
    }

    /// Server-assigned id used for keepalive reporting, if present.
    pub fn server_id(&self) -> Option<&str> {
        self.metadata.get("server_id").and_then(|v| v.as_str())
    }

    /// Whether the named feature is entitled on this license.
    pub fn feature_entitled(&self, name: &str) -> bool {
        self.features.iter().any(|f| f.name == name && f.entitled)
    }
}

/// One coherent view of license + flags, swapped atomically on refresh.
#[derive(Debug, Clone)]
pub struct Snapshot {
    /// Last successfully fetched license state.
    pub info: LicenseInfo,
    /// Last successfully fetched flag decisions (PostHog `/decide`).
    pub flags: HashMap<String, bool>,
    /// When this snapshot was fetched.
    pub fetched_at: DateTime<Utc>,
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn tier_parsing_accepts_aliases_and_fails_safe() {
        assert_eq!(Tier::parse("community"), Tier::Free);
        assert_eq!(Tier::parse("free"), Tier::Free);
        assert_eq!(Tier::parse("Professional"), Tier::Professional);
        assert_eq!(Tier::parse("ENTERPRISE"), Tier::Enterprise);
        assert_eq!(Tier::parse("galactic"), Tier::Free);
    }

    #[test]
    fn tier_ordering_is_cumulative() {
        assert!(Tier::Enterprise > Tier::Professional);
        assert!(Tier::Professional > Tier::Free);
    }

    #[test]
    fn community_fallback_entitles_nothing() {
        let info = LicenseInfo::community_fallback("skauswatch", None);
        assert!(info.valid);
        assert_eq!(info.tier, Tier::Free);
        assert!(!info.feature_entitled("sso"));
    }
}
