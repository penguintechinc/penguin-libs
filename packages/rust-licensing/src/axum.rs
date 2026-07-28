//! Axum 0.8 gating middleware. Mount with
//! `axum::middleware::from_fn_with_state` so the gate travels with the
//! router it protects. Ordering contract: authn (tenant → scope) runs
//! BEFORE these licensing gates.
//!
//! ```ignore
//! let gate = FlagGate::new(client.clone(), "skauswatch.icebox");
//! let router = icebox_router
//!     .layer(axum::middleware::from_fn_with_state(gate, flag_gate));
//! ```

use std::sync::Arc;

use axum::Json;
use axum::extract::{Request, State};
use axum::middleware::Next;
use axum::response::{IntoResponse, Response};
use http::StatusCode;

use crate::client::LicenseClient;
use crate::types::Tier;

/// State for [`flag_gate`]: denies requests while a PostHog feature flag
/// (`{product}.{feature}`) is disabled. Flags default OFF.
#[derive(Clone)]
pub struct FlagGate {
    /// Shared license/flag client.
    pub client: Arc<LicenseClient>,
    /// Fully-qualified flag key (`{product}.{feature}`).
    pub flag: String,
}

impl FlagGate {
    /// Creates a gate for `flag`.
    pub fn new(client: Arc<LicenseClient>, flag: impl Into<String>) -> Self {
        Self {
            client,
            flag: flag.into(),
        }
    }
}

/// Middleware fn: 403 `feature_disabled` while the flag is OFF.
pub async fn flag_gate(State(gate): State<FlagGate>, req: Request, next: Next) -> Response {
    if gate.client.flag_enabled(&gate.flag).await {
        next.run(req).await
    } else {
        deny("feature_disabled", "flag", &gate.flag)
    }
}

/// State for [`feature_gate`]: denies requests when the license does not
/// entitle a feature.
#[derive(Clone)]
pub struct FeatureGate {
    /// Shared license/flag client.
    pub client: Arc<LicenseClient>,
    /// License feature name.
    pub feature: String,
}

impl FeatureGate {
    /// Creates a gate for `feature`.
    pub fn new(client: Arc<LicenseClient>, feature: impl Into<String>) -> Self {
        Self {
            client,
            feature: feature.into(),
        }
    }
}

/// Middleware fn: 403 `feature_not_licensed` when entitlement is missing.
pub async fn feature_gate(State(gate): State<FeatureGate>, req: Request, next: Next) -> Response {
    if gate.client.check_feature(&gate.feature).await {
        next.run(req).await
    } else {
        deny("feature_not_licensed", "feature", &gate.feature)
    }
}

/// State for [`tier_gate`]: requires a minimum license tier.
#[derive(Clone)]
pub struct TierGate {
    /// Shared license/flag client.
    pub client: Arc<LicenseClient>,
    /// Minimum tier required.
    pub required: Tier,
}

impl TierGate {
    /// Creates a gate requiring `required` tier or higher.
    pub fn new(client: Arc<LicenseClient>, required: Tier) -> Self {
        Self { client, required }
    }
}

/// Middleware fn: 403 `tier_required` when the license tier is too low.
pub async fn tier_gate(State(gate): State<TierGate>, req: Request, next: Next) -> Response {
    if gate.client.check_tier(gate.required).await {
        next.run(req).await
    } else {
        let required = format!("{:?}", gate.required).to_lowercase();
        deny("tier_required", "required", &required)
    }
}

fn deny(error: &str, key: &str, value: &str) -> Response {
    (
        StatusCode::FORBIDDEN,
        Json(serde_json::json!({ "error": error, key: value })),
    )
        .into_response()
}
