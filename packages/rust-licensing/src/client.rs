//! The license/flag client: lock-free cached reads over an atomically
//! swapped snapshot, background refresh, and fail-safe gating semantics.

use std::collections::HashMap;
use std::sync::Arc;

use arc_swap::ArcSwapOption;
use chrono::Utc;
use serde_json::json;
use sha2::{Digest, Sha256};

use crate::config::LicenseConfig;
use crate::error::LicenseError;
use crate::types::{LicenseInfo, Snapshot, Tier};

/// Client for PenguinTech license entitlement and PostHog-compatible
/// feature flags. Cheap to clone via `Arc`; share one per service.
pub struct LicenseClient {
    cfg: LicenseConfig,
    http: reqwest::Client,
    snapshot: ArcSwapOption<Snapshot>,
}

impl LicenseClient {
    /// Builds a client. Does not touch the network — call
    /// [`LicenseClient::refresh`] or [`LicenseClient::spawn_refresh`] at
    /// service startup.
    pub fn new(cfg: LicenseConfig) -> Result<Arc<Self>, LicenseError> {
        let mut headers = reqwest::header::HeaderMap::new();
        if let Some(key) = &cfg.license_key {
            let value = reqwest::header::HeaderValue::from_str(&format!("Bearer {key}"))
                .map_err(|e| LicenseError::Config(e.to_string()))?;
            headers.insert(reqwest::header::AUTHORIZATION, value);
        }
        let http = reqwest::Client::builder()
            .timeout(cfg.timeout)
            .default_headers(headers)
            .user_agent(format!(
                "penguin-licensing-rs/{}",
                env!("CARGO_PKG_VERSION")
            ))
            .build()
            .map_err(|e| LicenseError::Config(e.to_string()))?;
        Ok(Arc::new(Self {
            cfg,
            http,
            snapshot: ArcSwapOption::empty(),
        }))
    }

    /// The active configuration.
    pub fn config(&self) -> &LicenseConfig {
        &self.cfg
    }

    /// Whether gating is bypassed: dev builds (`release_mode == false`) or
    /// a deployment domain on the bypass list. Bypass means every feature,
    /// flag, and tier check evaluates as enabled/Enterprise.
    pub fn bypass_active(&self) -> bool {
        !self.cfg.release_mode || self.cfg.domain_bypassed()
    }

    /// The current snapshot, if one has ever been fetched.
    pub fn snapshot(&self) -> Option<Arc<Snapshot>> {
        self.snapshot.load_full()
    }

    async fn fetch_license(&self) -> Result<LicenseInfo, LicenseError> {
        if self.cfg.license_key.is_none() {
            return Ok(LicenseInfo::community_fallback(&self.cfg.product, None));
        }
        let url = self
            .cfg
            .server_url
            .join("/api/v2/validate")
            .map_err(|e| LicenseError::Config(e.to_string()))?;
        let resp = self
            .http
            .post(url)
            .json(&json!({ "product": self.cfg.product }))
            .send()
            .await?;
        let status = resp.status();
        if !status.is_success() {
            return Err(LicenseError::Status(status.as_u16()));
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
        let url = self
            .cfg
            .posthog_host
            .join("/decide/?v=3")
            .map_err(|e| LicenseError::Config(e.to_string()))?;
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

    /// Fetches license + flags and swaps in a new snapshot. On license
    /// failure the previous snapshot is kept (fail-safe) and the error is
    /// returned; a flag-only failure keeps the previous flag set.
    pub async fn refresh(&self) -> Result<(), LicenseError> {
        let info = match self.fetch_license().await {
            Ok(info) => info,
            Err(e) => {
                tracing::warn!(error = %e, "license refresh failed; keeping cached snapshot");
                return Err(e);
            }
        };
        let flags = match self.fetch_flags().await {
            Ok(flags) => flags,
            Err(e) => {
                tracing::warn!(error = %e, "flag refresh failed; keeping cached flags");
                self.snapshot
                    .load_full()
                    .map(|s| s.flags.clone())
                    .unwrap_or_default()
            }
        };
        self.snapshot.store(Some(Arc::new(Snapshot {
            info,
            flags,
            fetched_at: Utc::now(),
        })));
        Ok(())
    }

    async fn fresh_snapshot(&self) -> Option<Arc<Snapshot>> {
        let stale = match self.snapshot.load_full() {
            Some(snap) => {
                let age = Utc::now().signed_duration_since(snap.fetched_at);
                age.to_std()
                    .map(|a| a >= self.cfg.cache_ttl)
                    .unwrap_or(true)
            }
            None => true,
        };
        if stale {
            // Refresh errors are already logged; cached state is fail-safe.
            let _ = self.refresh().await;
        }
        self.snapshot.load_full()
    }

    /// Returns the current license state, refreshing when the cache TTL has
    /// expired. Infallible: falls back to community tier when nothing has
    /// ever been fetched.
    pub async fn validate(&self) -> LicenseInfo {
        match self.fresh_snapshot().await {
            Some(snap) => snap.info.clone(),
            None => LicenseInfo::community_fallback(
                &self.cfg.product,
                Some("license server unreachable".to_owned()),
            ),
        }
    }

    /// Whether the license entitles the named feature. Fail-safe: `false`
    /// when unknown, `true` under bypass.
    pub async fn check_feature(&self, feature: &str) -> bool {
        if self.bypass_active() {
            return true;
        }
        self.validate().await.feature_entitled(feature)
    }

    /// Whether a PostHog flag (`{product}.{feature}`) is enabled. Fail-safe:
    /// never-seen flags are OFF, `true` under bypass.
    pub async fn flag_enabled(&self, key: &str) -> bool {
        if self.bypass_active() {
            return true;
        }
        match self.fresh_snapshot().await {
            Some(snap) => snap.flags.get(key).copied().unwrap_or(false),
            None => false,
        }
    }

    /// The current tier (`Enterprise` under bypass, `Free` when unknown).
    pub async fn tier(&self) -> Tier {
        if self.bypass_active() {
            return Tier::Enterprise;
        }
        self.validate().await.tier
    }

    /// Whether the license meets `required` (tiers are cumulative).
    pub async fn check_tier(&self, required: Tier) -> bool {
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
        let url = self
            .cfg
            .server_url
            .join("/api/v2/keepalive")
            .map_err(|e| LicenseError::Config(e.to_string()))?;
        let resp = self
            .http
            .post(url)
            .json(&json!({ "product": self.cfg.product, "server_id": server_id }))
            .send()
            .await?;
        let status = resp.status();
        if status.is_success() {
            Ok(())
        } else {
            Err(LicenseError::Status(status.as_u16()))
        }
    }

    /// Spawns the background refresh + keepalive loop. Keep the handle to
    /// abort on shutdown; drop it to let the loop run for the process
    /// lifetime.
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
