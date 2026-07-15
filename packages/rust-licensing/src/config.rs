//! Client configuration, loaded from the standard PenguinTech env vars:
//! `LICENSE_KEY`, `LICENSE_SERVER_URL`, `POSTHOG_HOST`, `POSTHOG_KEY`,
//! `RELEASE_MODE`, and `DEPLOYMENT_DOMAIN`/`BASE_URL` for domain bypass.

use std::time::Duration;

use url::Url;

use crate::error::LicenseError;

/// Default license + flag server.
pub const DEFAULT_SERVER_URL: &str = "https://license.penguintech.io";

/// Domain suffixes that always bypass license/flag gating — PenguinTech
/// internal deployments. Bypass is domain-based ONLY, never an env toggle.
pub const DEFAULT_BYPASS_DOMAINS: &[&str] = &["penguincloud.io", "penguintech.cloud"];

/// Configuration for [`crate::LicenseClient`].
#[derive(Debug, Clone)]
pub struct LicenseConfig {
    /// Product identifier (e.g. `skauswatch`) — also the flag key prefix.
    pub product: String,
    /// PenguinTech license key (`PENG-...`); `None` = community tier.
    pub license_key: Option<String>,
    /// License server base URL.
    pub server_url: Url,
    /// PostHog host for flag evaluation; defaults to the license server.
    pub posthog_host: Url,
    /// PostHog project API key; flags evaluate to default-OFF without it.
    pub posthog_key: Option<String>,
    /// `true` in released builds — enables enforcement. `false` (dev) means
    /// all features/flags evaluate enabled.
    pub release_mode: bool,
    /// The domain this deployment serves (e.g. `skauswatch.penguintech.cloud`).
    pub deployment_domain: Option<String>,
    /// Domain suffixes that bypass gating (internal deployments).
    pub bypass_domains: Vec<String>,
    /// Snapshot TTL before a read triggers refresh (default 5 minutes,
    /// matching the Python client).
    pub cache_ttl: Duration,
    /// Background refresh/keepalive interval (default 5 minutes).
    pub refresh_interval: Duration,
    /// Per-request HTTP timeout (default 10 seconds).
    pub timeout: Duration,
}

impl LicenseConfig {
    /// Builds a config for `product` with library defaults; callers layer
    /// overrides on the returned value.
    pub fn new(product: impl Into<String>) -> Result<Self, LicenseError> {
        let server_url =
            Url::parse(DEFAULT_SERVER_URL).map_err(|e| LicenseError::Config(e.to_string()))?;
        Ok(Self {
            product: product.into(),
            license_key: None,
            posthog_host: server_url.clone(),
            server_url,
            posthog_key: None,
            release_mode: false,
            deployment_domain: None,
            bypass_domains: DEFAULT_BYPASS_DOMAINS
                .iter()
                .map(|s| (*s).to_owned())
                .collect(),
            cache_ttl: Duration::from_secs(300),
            refresh_interval: Duration::from_secs(300),
            timeout: Duration::from_secs(10),
        })
    }

    /// Loads config for `product` from the standard environment variables.
    pub fn from_env(product: impl Into<String>) -> Result<Self, LicenseError> {
        let mut cfg = Self::new(product)?;
        if let Ok(key) = std::env::var("LICENSE_KEY")
            && !key.trim().is_empty()
        {
            cfg.license_key = Some(key);
        }
        if let Ok(u) = std::env::var("LICENSE_SERVER_URL") {
            cfg.server_url = Url::parse(&u).map_err(|e| LicenseError::Config(e.to_string()))?;
            cfg.posthog_host = cfg.server_url.clone();
        }
        if let Ok(u) = std::env::var("POSTHOG_HOST") {
            cfg.posthog_host = Url::parse(&u).map_err(|e| LicenseError::Config(e.to_string()))?;
        }
        if let Ok(k) = std::env::var("POSTHOG_KEY")
            && !k.trim().is_empty()
        {
            cfg.posthog_key = Some(k);
        }
        cfg.release_mode = std::env::var("RELEASE_MODE")
            .map(|v| matches!(v.trim().to_ascii_lowercase().as_str(), "true" | "1" | "yes"))
            .unwrap_or(false);
        cfg.deployment_domain = std::env::var("DEPLOYMENT_DOMAIN").ok().or_else(|| {
            std::env::var("BASE_URL")
                .ok()
                .and_then(|u| Url::parse(&u).ok())
                .and_then(|u| u.host_str().map(str::to_owned))
        });
        Ok(cfg)
    }

    /// Adds a bypass domain (e.g. the product's own `.app` domain).
    #[must_use]
    pub fn with_bypass_domain(mut self, domain: impl Into<String>) -> Self {
        self.bypass_domains.push(domain.into());
        self
    }

    /// Whether the configured deployment domain matches the bypass list
    /// (exact match or subdomain of a listed suffix).
    pub fn domain_bypassed(&self) -> bool {
        let Some(domain) = &self.deployment_domain else {
            return false;
        };
        let domain = domain.to_ascii_lowercase();
        self.bypass_domains.iter().any(|suffix| {
            let suffix = suffix.to_ascii_lowercase();
            domain == suffix || domain.ends_with(&format!(".{suffix}"))
        })
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn bypass_matches_suffix_and_exact() {
        let mut cfg = match LicenseConfig::new("skauswatch") {
            Ok(c) => c,
            Err(e) => panic!("config: {e}"),
        };
        cfg.deployment_domain = Some("skauswatch.penguintech.cloud".into());
        assert!(cfg.domain_bypassed());

        cfg.deployment_domain = Some("penguincloud.io".into());
        assert!(cfg.domain_bypassed());

        cfg.deployment_domain = Some("skauswatch.app".into());
        assert!(!cfg.domain_bypassed());
        let cfg = cfg.with_bypass_domain("skauswatch.app");
        assert!(cfg.domain_bypassed());
    }

    #[test]
    fn unrelated_domain_is_not_bypassed() {
        let mut cfg = match LicenseConfig::new("skauswatch") {
            Ok(c) => c,
            Err(e) => panic!("config: {e}"),
        };
        cfg.deployment_domain = Some("evilpenguintech.cloud".into());
        assert!(!cfg.domain_bypassed());
    }
}
