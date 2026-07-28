//! PenguinTech licensing + feature-flag client for Rust services.
//!
//! One client, two concerns, one server (`license.penguintech.io`):
//! - **License entitlement** via `POST /api/v2/validate` / `/api/v2/features`
//!   semantics (tier + per-feature entitlement, 5-minute cache).
//! - **PostHog-compatible feature flags** via the `/decide` endpoint served
//!   by the license server's embedded PostHog (`POSTHOG_HOST`).
//!
//! Behavioral contract (mirrors `penguin-licensing` on PyPI):
//! - **Enforcement is always on.** No environment variable, CLI flag, or
//!   build profile disables license checking. The single bypass is the
//!   hardcoded domain suffix list, matched against a deployment domain
//!   that is itself set in code only
//!   ([`LicenseConfig::with_deployment_domain`]) — never from an env var.
//! - **Domain bypass**: deployments on PenguinTech-internal domains
//!   (`*.penguincloud.io`, `*.penguintech.cloud`, plus product `.app`
//!   domains registered in code with
//!   [`LicenseConfig::with_bypass_domain`]) bypass gating entirely — flags
//!   and features evaluate to enabled.
//! - **Fail-closed by default**: the cached snapshot is downgraded to
//!   community tier (and cached flags dropped) on *any* license-server
//!   response that is not a success and not an outage — explicit refusals
//!   (401/403/404) and equally anything unexpected (400, 418, a stray
//!   3xx). An expired `expires_at` does the same once the offline grace
//!   window (default 72h) elapses.
//! - **Graceful degradation on outage**: transport failures and exactly
//!   `5xx`/`408`/`429` keep serving the last cached snapshot; nothing
//!   cached → community/free tier with flags and gated features defaulting
//!   **OFF**.
//! - **Non-blocking**: gating reads never perform inline network I/O. They
//!   serve the current snapshot and schedule a single-flight background
//!   refresh when it is stale.
//! - Flag key convention: `{product}.{feature-name}`, default OFF.
//!
//! Requires a Tokio runtime (`rt`, `time`) — refresh work is spawned onto
//! the ambient runtime handle.

mod client;
mod config;
mod error;
mod types;

#[cfg(feature = "axum")]
pub mod axum;

pub use client::LicenseClient;
pub use config::LicenseConfig;
pub use error::LicenseError;
pub use types::{Feature, LicenseInfo, Snapshot, Tier};
