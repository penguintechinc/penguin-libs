//! PenguinTech licensing + feature-flag client for Rust services.
//!
//! One client, two concerns, one server (`license.penguintech.io`):
//! - **License entitlement** via `POST /api/v2/validate` / `/api/v2/features`
//!   semantics (tier + per-feature entitlement, 5-minute cache).
//! - **PostHog-compatible feature flags** via the `/decide` endpoint served
//!   by the license server's embedded PostHog (`POSTHOG_HOST`).
//!
//! Behavioral contract (mirrors `penguin-licensing` on PyPI):
//! - **Fail-safe, never crash the host service**: server unreachable → last
//!   cached snapshot; nothing cached → community/free tier with flags and
//!   gated features defaulting **OFF**.
//! - **Domain bypass**: deployments on PenguinTech-internal domains (or with
//!   `RELEASE_MODE` unset/false) bypass gating entirely — flags and features
//!   evaluate to enabled. Bypass is domain-based only, never an env toggle.
//! - Flag key convention: `{product}.{feature-name}`, default OFF.

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
