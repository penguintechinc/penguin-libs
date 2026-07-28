//! The license/flag client: lock-free cached reads over an atomically
//! swapped snapshot, single-flight background refresh, and fail-closed
//! gating semantics.
//!
//! Gating reads (`check_feature`, `flag_enabled`, `tier`) never perform
//! inline network I/O — they serve the current snapshot and, when it is
//! stale, schedule a background refresh. A slow or dead license server
//! therefore cannot stall request handling.

use std::collections::HashMap;
use std::sync::Arc;
use std::time::{Duration, Instant};

use arc_swap::ArcSwapOption;
use chrono::Utc;
use reqwest::header::{AUTHORIZATION, HeaderValue};
use serde_json::json;
use sha2::{Digest, Sha256};
use tokio::sync::Mutex;

use crate::config::LicenseConfig;
use crate::error::LicenseError;
use crate::types::{LicenseInfo, Snapshot, Tier};

/// HTTP statuses that mean "the server is having a bad day" rather than
/// "this license is not valid" — the only statuses for which a warm
/// snapshot is retained.
///
/// This is an **allowlist on purpose**: every status not listed here
/// (401/403/404 revocation, but equally 400, 418, or a stray 3xx) is an
/// answer we cannot interpret as continued entitlement, so it fails closed
/// to the community fallback. A denylist would silently grant Enterprise
/// on any status nobody thought to enumerate.
fn retains_cache(status: u16) -> bool {
    matches!(status, 408 | 429) || (500..=599).contains(&status)
}

/// Classifies a non-success response: transient outage (keep cache) or
/// definitive rejection (fail closed).
fn classify(status: u16) -> LicenseError {
    if retains_cache(status) {
        LicenseError::Status(status)
    } else {
        LicenseError::Rejected(status)
    }
}

/// Bookkeeping for refresh scheduling, guarded by a mutex so that
/// concurrent stale reads collapse into a single upstream request and the
/// snapshot swap cannot race.
#[derive(Debug, Default)]
struct RefreshState {
    last_attempt: Option<Instant>,
    consecutive_failures: u32,
}

/// Client for PenguinTech license entitlement and PostHog-compatible
/// feature flags. Cheap to clone via `Arc`; share one per service.
///
/// Requires a Tokio runtime: background refresh is spawned onto the
/// ambient runtime handle.
pub struct LicenseClient {
    cfg: LicenseConfig,
    http: reqwest::Client,
    /// Bearer credential, attached per-request to license-server calls
    /// only — never to the PostHog host, which may be a third party.
    auth: Option<HeaderValue>,
    snapshot: ArcSwapOption<Snapshot>,
    refresh_gate: Mutex<RefreshState>,
}

impl LicenseClient {
    /// Builds a client. Does not touch the network — call
    /// [`LicenseClient::refresh`] or [`LicenseClient::spawn_refresh`] at
    /// service startup.
    ///
    /// Fails if the configured URLs are not HTTPS (localhost excepted).
    pub fn new(cfg: LicenseConfig) -> Result<Arc<Self>, LicenseError> {
        cfg.validate_urls()?;
        let auth = match &cfg.license_key {
            Some(key) => {
                let mut value = HeaderValue::from_str(&format!("Bearer {key}"))
                    .map_err(|e| LicenseError::Config(e.to_string()))?;
                // Keeps the credential out of reqwest/hyper debug output.
                value.set_sensitive(true);
                Some(value)
            }
            None => None,
        };
        let http = reqwest::Client::builder()
            .timeout(cfg.timeout)
            .user_agent(format!(
                "penguin-licensing-rs/{}",
                env!("CARGO_PKG_VERSION")
            ))
            .build()
            .map_err(|e| LicenseError::Config(e.to_string()))?;
        Ok(Arc::new(Self {
            cfg,
            http,
            auth,
            snapshot: ArcSwapOption::empty(),
            refresh_gate: Mutex::new(RefreshState::default()),
        }))
    }

    /// The active configuration.
    pub fn config(&self) -> &LicenseConfig {
        &self.cfg
    }

    /// Whether gating is bypassed: the deployment domain is on the bypass
    /// list. Bypass means every feature, flag, and tier check evaluates as
    /// enabled/Enterprise.
    ///
    /// Bypass is domain-based ONLY — there is no environment variable,
    /// CLI flag, or build profile that disables enforcement.
    pub fn bypass_active(&self) -> bool {
        self.cfg.domain_bypassed()
    }

    /// The current snapshot, if one has ever been fetched.
    pub fn snapshot(&self) -> Option<Arc<Snapshot>> {
        self.snapshot.load_full()
    }

    /// Joins a relative endpoint onto a base URL, preserving both the path
    /// and the query string the base already carries:
    /// `https://host/lic?tenant=acme` + `api/v2/validate` →
    /// `https://host/lic/api/v2/validate?tenant=acme`.
    ///
    /// Base query parameters are prepended to the segment's own, so a
    /// routing/tenant parameter baked into `LICENSE_SERVER_URL` survives
    /// (`Url::join` alone would discard it).
    fn endpoint(base: &url::Url, segment: &str) -> Result<url::Url, LicenseError> {
        let mut root = base.clone();
        let path = root.path().to_owned();
        if !path.ends_with('/') {
            root.set_path(&format!("{path}/"));
        }
        let base_query = root.query().map(str::to_owned);
        let mut joined = root
            .join(segment.trim_start_matches('/'))
            .map_err(|e| LicenseError::Config(e.to_string()))?;
        if let Some(base_query) = base_query.filter(|q| !q.is_empty()) {
            let merged = match joined.query() {
                Some(q) if !q.is_empty() => format!("{base_query}&{q}"),
                _ => base_query,
            };
            joined.set_query(Some(&merged));
        }
        Ok(joined)
    }

    /// Attaches the license bearer credential. Only ever called for
    /// license-server requests.
    fn authed(&self, req: reqwest::RequestBuilder) -> reqwest::RequestBuilder {
        match &self.auth {
            Some(value) => req.header(AUTHORIZATION, value.clone()),
            None => req,
        }
    }

    async fn fetch_license(&self) -> Result<LicenseInfo, LicenseError> {
        if self.cfg.license_key.is_none() {
            return Ok(LicenseInfo::community_fallback(&self.cfg.product, None));
        }
        let url = Self::endpoint(&self.cfg.server_url, "api/v2/validate")?;
        let resp = self
            .authed(self.http.post(url))
            .json(&json!({ "product": self.cfg.product }))
            .send()
            .await?;
        if !resp.status().is_success() {
            return Err(classify(resp.status().as_u16()));
        }
        let mut info: LicenseInfo = resp
            .json()
            .await
            .map_err(|e| LicenseError::Decode(e.to_string()))?;
        // A 200 from the server means the license validated; the wire body
        // has no `valid` field (mirrors the Python client's behavior).
        info.valid = true;
        Ok(info)
    }

    fn distinct_id(&self) -> String {
        match &self.cfg.license_key {
            Some(key) => {
                let mut hasher = Sha256::new();
                hasher.update(key.as_bytes());
                format!("{:x}", hasher.finalize())
            }
            None => format!("{}-community", self.cfg.product),
        }
    }

    async fn fetch_flags(&self) -> Result<HashMap<String, bool>, LicenseError> {
        let Some(posthog_key) = &self.cfg.posthog_key else {
            return Ok(HashMap::new());
        };
        let url = Self::endpoint(&self.cfg.posthog_host, "decide/?v=3")?;
        // Deliberately unauthenticated: the PostHog host authenticates with
        // its own project key in the body, and may not be the license
        // server. Sending the license key here would leak it.
        let resp = self
            .http
            .post(url)
            .json(&json!({
                "api_key": posthog_key,
                "distinct_id": self.distinct_id(),
                "groups": { "product": self.cfg.product },
            }))
            .send()
            .await?;
        let status = resp.status();
        if !status.is_success() {
            return Err(LicenseError::Status(status.as_u16()));
        }
        let body: serde_json::Value = resp
            .json()
            .await
            .map_err(|e| LicenseError::Decode(e.to_string()))?;
        let mut flags = HashMap::new();
        if let Some(map) = body.get("featureFlags").and_then(|v| v.as_object()) {
            for (key, value) in map {
                // PostHog values are bool or a variant string; any variant
                // string counts as enabled.
                let enabled = match value {
                    serde_json::Value::Bool(b) => *b,
                    serde_json::Value::String(_) => true,
                    _ => false,
                };
                flags.insert(key.clone(), enabled);
            }
        }
        Ok(flags)
    }

    fn cached_flags(&self) -> HashMap<String, bool> {
        self.snapshot
            .load_full()
            .map(|s| s.flags.clone())
            .unwrap_or_default()
    }

    fn store(&self, info: LicenseInfo, flags: HashMap<String, bool>) {
        self.snapshot.store(Some(Arc::new(Snapshot {
            info,
            flags,
            fetched_at: Utc::now(),
        })));
    }

    /// Fetches license + flags and swaps in a new snapshot.
    ///
    /// Failure handling is asymmetric on purpose:
    /// - **Rejection** (401/402/403/404/410) is a definitive answer — the
    ///   snapshot is replaced with the community fallback, so a revoked or
    ///   expired key stops granting features immediately.
    /// - **Outage** (transport error, 5xx, 408, 429) keeps the previous
    ///   snapshot, so a license-server blip does not take a customer down.
    /// - A flag-only failure keeps the previous flag set.
    pub async fn refresh(&self) -> Result<(), LicenseError> {
        let mut state = self.refresh_gate.lock().await;
        self.refresh_locked(&mut state).await
    }

    async fn refresh_locked(&self, state: &mut RefreshState) -> Result<(), LicenseError> {
        state.last_attempt = Some(Instant::now());
        let info = match self.fetch_license().await {
            Ok(info) => {
                state.consecutive_failures = 0;
                info
            }
            Err(LicenseError::Rejected(status)) => {
                // A definitive answer, not an outage — no backoff needed.
                state.consecutive_failures = 0;
                tracing::warn!(
                    status,
                    "license rejected by server; failing closed to community tier"
                );
                // Cached flags are dropped too: a deployment whose license
                // was revoked must not keep flag-gated features alive on a
                // stale `/decide` result.
                self.store(
                    LicenseInfo::community_fallback(
                        &self.cfg.product,
                        Some(format!("license rejected by server (status {status})")),
                    ),
                    HashMap::new(),
                );
                return Err(LicenseError::Rejected(status));
            }
            Err(e) => {
                state.consecutive_failures = state.consecutive_failures.saturating_add(1);
                tracing::warn!(error = %e, "license refresh failed; keeping cached snapshot");
                return Err(e);
            }
        };
        let flags = match self.fetch_flags().await {
            Ok(flags) => flags,
            Err(e) => {
                tracing::warn!(error = %e, "flag refresh failed; keeping cached flags");
                self.cached_flags()
            }
        };
        self.store(info, flags);
        Ok(())
    }

    /// Whether the cached snapshot has aged past the configured TTL.
    fn is_stale(&self) -> bool {
        match self.snapshot.load_full() {
            Some(snap) => {
                let age = Utc::now().signed_duration_since(snap.fetched_at);
                age.to_std()
                    .map(|a| a >= self.cfg.cache_ttl)
                    .unwrap_or(true)
            }
            None => true,
        }
    }

    /// Exponential negative TTL after consecutive failures, so an
    /// unreachable server produces one retry per backoff window rather
    /// than one per request.
    fn backoff(&self, consecutive_failures: u32) -> Duration {
        if consecutive_failures == 0 {
            return Duration::ZERO;
        }
        let shift = (consecutive_failures - 1).min(16);
        self.cfg
            .refresh_backoff_min
            .saturating_mul(1u32 << shift)
            .min(self.cfg.refresh_backoff_max)
    }

    fn may_attempt(&self, state: &RefreshState) -> bool {
        match state.last_attempt {
            Some(at) => at.elapsed() >= self.backoff(state.consecutive_failures),
            None => true,
        }
    }

    /// Schedules a refresh when the snapshot is stale, without awaiting it.
    ///
    /// Single-flight: the refresh mutex is acquired with `try_lock`, so
    /// concurrent stale reads produce exactly one upstream request instead
    /// of a thundering herd. No-op outside a Tokio runtime.
    fn schedule_refresh(self: &Arc<Self>) {
        if !self.is_stale() {
            return;
        }
        let Ok(handle) = tokio::runtime::Handle::try_current() else {
            // No runtime to spawn onto; the caller drives refresh
            // explicitly. Never panic inside a gating read.
            return;
        };
        let client = Arc::clone(self);
        handle.spawn(async move {
            let Ok(mut state) = client.refresh_gate.try_lock() else {
                return; // a refresh is already in flight
            };
            // Re-check under the lock: the in-flight refresh that just
            // finished may have made us fresh, and backoff may still apply.
            if !client.is_stale() || !client.may_attempt(&state) {
                return;
            }
            let _ = client.refresh_locked(&mut state).await;
        });
    }

    /// Returns the current license state, scheduling a background refresh
    /// when the cache TTL has expired. Infallible and non-blocking: never
    /// performs inline network I/O, and falls back to community tier when
    /// nothing has ever been fetched or the license has expired past its
    /// grace window.
    pub async fn validate(self: &Arc<Self>) -> LicenseInfo {
        self.schedule_refresh();
        match self.snapshot.load_full() {
            Some(snap) => snap.info.enforce_expiry(self.cfg.offline_grace),
            None => LicenseInfo::community_fallback(
                &self.cfg.product,
                Some("license server unreachable".to_owned()),
            ),
        }
    }

    /// Whether the license entitles the named feature. Fail-closed:
    /// `false` when unknown, revoked, or expired past grace; `true` under
    /// domain bypass.
    pub async fn check_feature(self: &Arc<Self>, feature: &str) -> bool {
        if self.bypass_active() {
            return true;
        }
        self.validate().await.feature_entitled(feature)
    }

    /// Whether a PostHog flag (`{product}.{feature}`) is enabled.
    /// Fail-closed: never-seen flags are OFF; `true` under domain bypass.
    pub async fn flag_enabled(self: &Arc<Self>, key: &str) -> bool {
        if self.bypass_active() {
            return true;
        }
        self.schedule_refresh();
        match self.snapshot.load_full() {
            Some(snap) => snap.flags.get(key).copied().unwrap_or(false),
            None => false,
        }
    }

    /// The current tier (`Enterprise` under domain bypass, `Free` when
    /// unknown or expired past grace).
    pub async fn tier(self: &Arc<Self>) -> Tier {
        if self.bypass_active() {
            return Tier::Enterprise;
        }
        self.validate().await.tier
    }

    /// Whether the license meets `required` (tiers are cumulative).
    pub async fn check_tier(self: &Arc<Self>, required: Tier) -> bool {
        self.tier().await >= required
    }

    /// Sends a keepalive with the server-assigned id from the last
    /// validation. Silently succeeds when unlicensed (nothing to report).
    pub async fn keepalive(&self) -> Result<(), LicenseError> {
        if self.cfg.license_key.is_none() {
            return Ok(());
        }
        let Some(snap) = self.snapshot.load_full() else {
            return Ok(());
        };
        let Some(server_id) = snap.info.server_id().map(str::to_owned) else {
            return Ok(());
        };
        let url = Self::endpoint(&self.cfg.server_url, "api/v2/keepalive")?;
        let resp = self
            .authed(self.http.post(url))
            .json(&json!({ "product": self.cfg.product, "server_id": server_id }))
            .send()
            .await?;
        let status = resp.status();
        if status.is_success() {
            Ok(())
        } else {
            Err(classify(status.as_u16()))
        }
    }

    /// Spawns the background refresh + keepalive loop. Keep the handle to
    /// abort on shutdown; drop it to let the loop run for the process
    /// lifetime. Requires a Tokio runtime.
    pub fn spawn_refresh(self: &Arc<Self>) -> tokio::task::JoinHandle<()> {
        let client = Arc::clone(self);
        tokio::spawn(async move {
            loop {
                tokio::time::sleep(client.cfg.refresh_interval).await;
                if client.refresh().await.is_ok()
                    && let Err(e) = client.keepalive().await
                {
                    tracing::warn!(error = %e, "license keepalive failed");
                }
            }
        })
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn url(s: &str) -> url::Url {
        match url::Url::parse(s) {
            Ok(u) => u,
            Err(e) => panic!("url: {e}"),
        }
    }

    /// Regression: `Url::join("/api/v2/validate")` discarded any base path,
    /// silently retargeting a hosted-at-subpath license server.
    #[test]
    fn endpoint_preserves_base_path() {
        let joined = match LicenseClient::endpoint(&url("https://h.example/lic"), "api/v2/validate")
        {
            Ok(u) => u,
            Err(e) => panic!("join: {e}"),
        };
        assert_eq!(joined.as_str(), "https://h.example/lic/api/v2/validate");

        let joined =
            match LicenseClient::endpoint(&url("https://h.example/lic/"), "api/v2/validate") {
                Ok(u) => u,
                Err(e) => panic!("join: {e}"),
            };
        assert_eq!(joined.as_str(), "https://h.example/lic/api/v2/validate");

        let joined = match LicenseClient::endpoint(&url("https://h.example"), "decide/?v=3") {
            Ok(u) => u,
            Err(e) => panic!("join: {e}"),
        };
        assert_eq!(joined.as_str(), "https://h.example/decide/?v=3");
    }

    /// Regression: a query string on the configured base URL (tenant or
    /// routing parameter) was discarded by `Url::join`.
    #[test]
    fn endpoint_preserves_base_query() {
        let joined = match LicenseClient::endpoint(
            &url("https://h.example/lic?tenant=acme"),
            "api/v2/validate",
        ) {
            Ok(u) => u,
            Err(e) => panic!("join: {e}"),
        };
        assert_eq!(
            joined.as_str(),
            "https://h.example/lic/api/v2/validate?tenant=acme"
        );

        // Base query and segment query are merged, base first.
        let joined = match LicenseClient::endpoint(
            &url("https://h.example/ph?tenant=acme"),
            "decide/?v=3",
        ) {
            Ok(u) => u,
            Err(e) => panic!("join: {e}"),
        };
        assert_eq!(
            joined.as_str(),
            "https://h.example/ph/decide/?tenant=acme&v=3"
        );
    }

    /// Retention is an allowlist: only outage-shaped statuses keep the warm
    /// cache, everything else fails closed.
    #[test]
    fn only_outage_statuses_retain_the_cache() {
        for status in [408, 429, 500, 502, 503, 504, 599] {
            assert!(retains_cache(status), "{status} should retain cache");
            assert!(matches!(classify(status), LicenseError::Status(_)));
        }
        for status in [301, 302, 400, 401, 402, 403, 404, 410, 418, 422, 451] {
            assert!(!retains_cache(status), "{status} must fail closed");
            assert!(matches!(classify(status), LicenseError::Rejected(_)));
        }
    }
}
