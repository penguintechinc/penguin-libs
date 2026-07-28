//! Wire and domain types for license validation and feature flags.

use std::collections::HashMap;
use std::time::Duration;

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

    /// Whether the license is still usable at `now`, allowing `grace`
    /// beyond `expires_at`. A missing `expires_at` never expires.
    ///
    /// The grace window exists so a briefly unreachable license server
    /// cannot hard-cut a healthy customer at the moment of renewal; past
    /// it, entitlement fails closed.
    pub fn is_live_at(&self, now: DateTime<Utc>, grace: Duration) -> bool {
        let Some(expires_at) = self.expires_at else {
            return true;
        };
        match chrono::Duration::from_std(grace) {
            Ok(grace) => now <= expires_at + grace,
            // Absurd grace value: fall back to strict expiry.
            Err(_) => now <= expires_at,
        }
    }

    /// Whether the license is still usable now, allowing `grace` beyond
    /// `expires_at`. See [`LicenseInfo::is_live_at`].
    pub fn is_live(&self, grace: Duration) -> bool {
        self.is_live_at(Utc::now(), grace)
    }

    /// Returns this license if it is still live, else the community
    /// fallback. Applied on every entitlement read so an expired license
    /// cannot keep granting gated features.
    pub fn enforce_expiry(&self, grace: Duration) -> Self {
        if self.is_live(grace) {
            self.clone()
        } else {
            Self::community_fallback(
                &self.product,
                Some("license expired beyond offline grace period".to_owned()),
            )
        }
    }

    /// Whether the named feature is entitled on this license. An invalid
    /// license entitles nothing.
    ///
    /// # Warning — this does NOT check expiry
    ///
    /// This is the raw per-feature lookup: it ignores `expires_at`, so it
    /// returns `true` for a long-expired license. It is only safe on a
    /// value already passed through [`LicenseInfo::enforce_expiry`] (the
    /// grace window lives in [`crate::LicenseConfig::offline_grace`]).
    ///
    /// **For gating decisions use
    /// [`crate::LicenseClient::check_feature`] instead** — it applies
    /// expiry enforcement, revocation state, and domain bypass for you.
    /// Reach for this method only when you are inspecting a
    /// [`LicenseInfo`] you obtained yourself and have already enforced.
    pub fn feature_entitled(&self, name: &str) -> bool {
        self.valid && self.features.iter().any(|f| f.name == name && f.entitled)
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

    fn licensed(expires_at: Option<DateTime<Utc>>) -> LicenseInfo {
        LicenseInfo {
            valid: true,
            customer: "ACME".to_owned(),
            product: "skauswatch".to_owned(),
            tier: Tier::Enterprise,
            expires_at,
            issued_at: None,
            features: vec![Feature {
                name: "sso".to_owned(),
                entitled: true,
                units: -1,
                description: String::new(),
                metadata: serde_json::Value::Null,
            }],
            limits: serde_json::Value::Null,
            metadata: serde_json::Value::Null,
            message: None,
        }
    }

    /// Regression: `expires_at` used to be parsed and then ignored, so an
    /// expired license kept granting Enterprise features forever.
    #[test]
    fn expiry_is_enforced_past_the_grace_window() {
        let grace = Duration::from_secs(72 * 60 * 60);
        let now = Utc::now();
        let expired = licensed(Some(now - chrono::Duration::hours(100)));

        assert!(!expired.is_live(grace));
        let enforced = expired.enforce_expiry(grace);
        assert_eq!(enforced.tier, Tier::Free);
        assert!(!enforced.feature_entitled("sso"));
    }

    #[test]
    fn expiry_within_grace_still_entitles() {
        let grace = Duration::from_secs(72 * 60 * 60);
        let now = Utc::now();
        let just_expired = licensed(Some(now - chrono::Duration::hours(1)));

        assert!(just_expired.is_live(grace));
        assert!(just_expired.enforce_expiry(grace).feature_entitled("sso"));
    }

    #[test]
    fn live_license_and_never_expiring_license_are_entitled() {
        let grace = Duration::from_secs(0);
        let future = licensed(Some(Utc::now() + chrono::Duration::days(30)));
        assert!(future.is_live(grace));
        assert!(future.enforce_expiry(grace).feature_entitled("sso"));

        let perpetual = licensed(None);
        assert!(perpetual.is_live(grace));
        assert!(perpetual.enforce_expiry(grace).feature_entitled("sso"));
    }

    #[test]
    fn invalid_license_entitles_nothing() {
        let mut info = licensed(None);
        info.valid = false;
        assert!(!info.feature_entitled("sso"));
    }
}
