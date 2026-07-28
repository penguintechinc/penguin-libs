//! Client configuration, loaded from the standard PenguinTech env vars:
//! `LICENSE_KEY`, `LICENSE_SERVER_URL`, `POSTHOG_HOST`, `POSTHOG_KEY`.
//!
//! Enforcement is **always on**. There is deliberately no environment
//! variable that disables license checking: the only bypass is the
//! hardcoded domain suffix list in [`DEFAULT_BYPASS_DOMAINS`], extended
//! per-product in code via [`LicenseConfig::with_bypass_domain`], matched
//! against a deployment domain that is also set in code only
//! ([`LicenseConfig::with_deployment_domain`]) — never from the
//! environment.

use std::fmt;
use std::time::Duration;

use url::Url;

use crate::error::LicenseError;

/// Default license + flag server.
pub const DEFAULT_SERVER_URL: &str = "https://license.penguintech.io";

/// Domain suffixes that always bypass license/flag gating — PenguinTech
/// internal deployments. Bypass is domain-based ONLY, never an env toggle.
/// Product `.app` domains are added in code with
/// [`LicenseConfig::with_bypass_domain`].
pub const DEFAULT_BYPASS_DOMAINS: &[&str] = &["penguincloud.io", "penguintech.cloud"];

/// Grace period served beyond `expires_at` before a license is treated as
/// dead (72 hours). Keeps a briefly unreachable license server from
/// hard-cutting a healthy customer at the moment of renewal.
pub const DEFAULT_OFFLINE_GRACE: Duration = Duration::from_secs(72 * 60 * 60);

/// First retry delay after a failed refresh (negative TTL floor).
pub const DEFAULT_BACKOFF_MIN: Duration = Duration::from_secs(5);

/// Ceiling for the exponential refresh backoff.
pub const DEFAULT_BACKOFF_MAX: Duration = Duration::from_secs(300);

/// Configuration for [`crate::LicenseClient`].
///
/// `Debug` is hand-written and redacts `license_key`/`posthog_key`; the
/// derived form would print live credentials into logs.
#[derive(Clone)]
pub struct LicenseConfig {
    /// Product identifier (e.g. `skauswatch`) — also the flag key prefix.
    pub product: String,
    /// PenguinTech license key (`PENG-...`); `None` = community tier.
    pub license_key: Option<String>,
    /// License server base URL. Must be HTTPS unless it points at
    /// localhost (dev/test).
    pub server_url: Url,
    /// PostHog host for flag evaluation; defaults to the license server.
    /// Must be HTTPS unless it points at localhost (dev/test).
    pub posthog_host: Url,
    /// PostHog project API key; flags evaluate to default-OFF without it.
    pub posthog_key: Option<String>,
    /// The domain this deployment serves (e.g.
    /// `skauswatch.penguintech.cloud`). Set in code only — see
    /// [`LicenseConfig::with_deployment_domain`]. Never populated from the
    /// environment.
    pub deployment_domain: Option<String>,
    /// Domain suffixes that bypass gating (internal deployments).
    pub bypass_domains: Vec<String>,
    /// Snapshot TTL before a read schedules a background refresh (default
    /// 5 minutes, matching the Python client).
    pub cache_ttl: Duration,
    /// Background refresh/keepalive interval (default 5 minutes).
    pub refresh_interval: Duration,
    /// Per-request HTTP timeout (default 10 seconds).
    pub timeout: Duration,
    /// How long an expired license keeps working past `expires_at`
    /// (default [`DEFAULT_OFFLINE_GRACE`]). Past this, gating fails closed
    /// to community tier. Code-configurable only — never read from the
    /// environment, since that would be an entitlement bypass.
    pub offline_grace: Duration,
    /// First retry delay after a failed refresh (default
    /// [`DEFAULT_BACKOFF_MIN`]); doubles per consecutive failure.
    pub refresh_backoff_min: Duration,
    /// Ceiling for the refresh backoff (default [`DEFAULT_BACKOFF_MAX`]).
    pub refresh_backoff_max: Duration,
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
            deployment_domain: None,
            bypass_domains: DEFAULT_BYPASS_DOMAINS
                .iter()
                .map(|s| (*s).to_owned())
                .collect(),
            cache_ttl: Duration::from_secs(300),
            refresh_interval: Duration::from_secs(300),
            timeout: Duration::from_secs(10),
            offline_grace: DEFAULT_OFFLINE_GRACE,
            refresh_backoff_min: DEFAULT_BACKOFF_MIN,
            refresh_backoff_max: DEFAULT_BACKOFF_MAX,
        })
    }

    /// Loads config for `product` from the standard environment variables.
    ///
    /// Note the absence of any enforcement toggle: no environment variable
    /// can disable license checking.
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
        // `deployment_domain` is deliberately NOT read from the
        // environment — see `with_deployment_domain`.
        cfg.validate_urls()?;
        Ok(cfg)
    }

    /// Adds a bypass domain (e.g. the product's own `.app` domain).
    #[must_use]
    pub fn with_bypass_domain(mut self, domain: impl Into<String>) -> Self {
        self.bypass_domains.push(domain.into());
        self
    }

    /// Sets the domain this deployment serves, which is what
    /// [`LicenseConfig::domain_bypassed`] matches against.
    ///
    /// **Set this from your service's own canonical serving host config,
    /// never from an environment passthrough.** The deployment domain is
    /// the single lever that disables license enforcement, so sourcing it
    /// from `DEPLOYMENT_DOMAIN`/`BASE_URL` (or any other env var, CLI flag,
    /// or request header) would reduce an Enterprise bypass to one line of
    /// deployment YAML. It must come from a value the service itself
    /// controls and would have to be recompiled to change.
    #[must_use]
    pub fn with_deployment_domain(mut self, domain: impl Into<String>) -> Self {
        self.deployment_domain = Some(domain.into());
        self
    }

    /// Rejects credential-leaking transports: the license server and
    /// PostHog host must be HTTPS, except on localhost where plain HTTP is
    /// allowed for tests and local development.
    pub fn validate_urls(&self) -> Result<(), LicenseError> {
        require_secure_url(&self.server_url, "LICENSE_SERVER_URL")?;
        require_secure_url(&self.posthog_host, "POSTHOG_HOST")
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

/// Whether `host` is a loopback name that may be reached over plain HTTP.
fn is_local_host(host: &str) -> bool {
    matches!(host, "localhost" | "127.0.0.1" | "::1" | "[::1]") || host.ends_with(".localhost")
}

fn require_secure_url(url: &Url, what: &str) -> Result<(), LicenseError> {
    match url.scheme() {
        "https" => Ok(()),
        "http" if is_local_host(url.host_str().unwrap_or_default()) => Ok(()),
        "http" => Err(LicenseError::Config(format!(
            "{what} must use https (plain http is only allowed for localhost): {url}"
        ))),
        scheme => Err(LicenseError::Config(format!(
            "{what} has unsupported scheme {scheme:?}; expected https"
        ))),
    }
}

/// Masks a credential for log output: `PENG-****ABCD`. Anything short
/// enough that a prefix plus suffix would reveal most of it is fully
/// redacted.
fn mask_secret(secret: &str) -> String {
    if secret.chars().count() <= 8 {
        return "****".to_owned();
    }
    let prefix = match secret.find(['-', '_']) {
        Some(i) if i > 0 && i <= 8 => secret.get(..=i).unwrap_or_default(),
        _ => "",
    };
    let tail: String = secret.chars().rev().take(4).collect();
    let suffix: String = tail.chars().rev().collect();
    format!("{prefix}****{suffix}")
}

impl fmt::Debug for LicenseConfig {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.debug_struct("LicenseConfig")
            .field("product", &self.product)
            .field("license_key", &self.license_key.as_deref().map(mask_secret))
            .field("server_url", &self.server_url.as_str())
            .field("posthog_host", &self.posthog_host.as_str())
            .field("posthog_key", &self.posthog_key.as_deref().map(mask_secret))
            .field("deployment_domain", &self.deployment_domain)
            .field("bypass_domains", &self.bypass_domains)
            .field("cache_ttl", &self.cache_ttl)
            .field("refresh_interval", &self.refresh_interval)
            .field("timeout", &self.timeout)
            .field("offline_grace", &self.offline_grace)
            .field("refresh_backoff_min", &self.refresh_backoff_min)
            .field("refresh_backoff_max", &self.refresh_backoff_max)
            .finish()
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn cfg() -> LicenseConfig {
        match LicenseConfig::new("skauswatch") {
            Ok(c) => c,
            Err(e) => panic!("config: {e}"),
        }
    }

    fn url(s: &str) -> Url {
        match Url::parse(s) {
            Ok(u) => u,
            Err(e) => panic!("url: {e}"),
        }
    }

    #[test]
    fn bypass_matches_suffix_and_exact() {
        let mut cfg = cfg().with_deployment_domain("skauswatch.penguintech.cloud");
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
        let mut cfg = cfg();
        cfg.deployment_domain = Some("evilpenguintech.cloud".into());
        assert!(!cfg.domain_bypassed());
    }

    /// Regression: a default config enforces. `RELEASE_MODE` used to
    /// default enforcement OFF, which handed every Enterprise feature out
    /// for free; the only bypass lever left is the domain list.
    #[test]
    fn default_config_has_no_bypass() {
        assert!(!cfg().domain_bypassed());
    }

    #[test]
    fn https_is_required_off_localhost() {
        let mut cfg = cfg();
        cfg.server_url = url("http://license.example.com");
        cfg.posthog_host = url("https://license.penguintech.io");
        assert!(cfg.validate_urls().is_err());

        cfg.server_url = url("https://license.example.com");
        cfg.posthog_host = url("http://posthog.example.com");
        assert!(cfg.validate_urls().is_err());
    }

    #[test]
    fn plain_http_allowed_only_on_loopback() {
        let mut cfg = cfg();
        for host in [
            "http://127.0.0.1:8080",
            "http://localhost:9000",
            "http://[::1]:1",
        ] {
            cfg.server_url = url(host);
            cfg.posthog_host = url(host);
            assert!(cfg.validate_urls().is_ok(), "{host} should be allowed");
        }
    }

    #[test]
    fn non_http_schemes_are_rejected() {
        let mut cfg = cfg();
        cfg.server_url = url("ftp://license.example.com");
        assert!(cfg.validate_urls().is_err());
    }

    #[test]
    fn debug_redacts_credentials() {
        let mut cfg = cfg();
        cfg.license_key = Some("PENG-SECRET-SECRET-SECRET-ABCD".to_owned());
        cfg.posthog_key = Some("phc_supersecretvalue".to_owned());
        let rendered = format!("{cfg:?}");

        assert!(
            !rendered.contains("SECRET"),
            "license key leaked: {rendered}"
        );
        assert!(
            !rendered.contains("supersecret"),
            "posthog key leaked: {rendered}"
        );
        assert!(rendered.contains("PENG-****ABCD"), "bad mask: {rendered}");
        assert!(rendered.contains("phc_****alue"), "bad mask: {rendered}");
    }

    #[test]
    fn short_secrets_are_fully_masked() {
        assert_eq!(mask_secret("abcd"), "****");
        assert_eq!(mask_secret("PENG-123"), "****");
    }
}
