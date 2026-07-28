//! Gating-middleware tests (feature = "axum").

#![cfg(feature = "axum")]
#![allow(clippy::unwrap_used, clippy::panic)]

use std::sync::Arc;
use std::time::Duration;

use axum::Router;
use axum::routing::get;
use penguin_licensing::axum::{
    FeatureGate, FlagGate, TierGate, feature_gate, flag_gate, tier_gate,
};
use penguin_licensing::{LicenseClient, LicenseConfig, Tier};
use url::Url;

/// A client that can never reach a license server. `bypassed` selects an
/// internal deployment domain (gating off) versus a customer domain
/// (gating on) — the only bypass lever there is.
fn offline_client(bypassed: bool) -> Arc<LicenseClient> {
    let mut cfg = LicenseConfig::new("skauswatch").unwrap();
    cfg = if bypassed {
        cfg.with_deployment_domain("skauswatch.penguintech.cloud")
    } else {
        cfg.with_deployment_domain("customer.example.com")
    };
    cfg.server_url = Url::parse("http://127.0.0.1:1").unwrap();
    cfg.posthog_host = cfg.server_url.clone();
    cfg.cache_ttl = Duration::from_secs(300);
    LicenseClient::new(cfg).unwrap()
}

fn app(client: Arc<LicenseClient>) -> Router {
    Router::new()
        .route("/icebox", get(|| async { "ok" }))
        .layer(axum::middleware::from_fn_with_state(
            FlagGate::new(client.clone(), "skauswatch.icebox"),
            flag_gate,
        ))
        .route(
            "/sso",
            get(|| async { "ok" }).layer(axum::middleware::from_fn_with_state(
                FeatureGate::new(client.clone(), "sso"),
                feature_gate,
            )),
        )
        .route(
            "/analytics",
            get(|| async { "ok" }).layer(axum::middleware::from_fn_with_state(
                TierGate::new(client, Tier::Enterprise),
                tier_gate,
            )),
        )
}

#[tokio::test]
async fn gates_deny_with_403_when_unlicensed() {
    let server = axum_test::TestServer::new(app(offline_client(false)));
    let res = server.get("/icebox").await;
    res.assert_status(http::StatusCode::FORBIDDEN);
    res.assert_json_contains(&serde_json::json!({ "error": "feature_disabled" }));

    let res = server.get("/sso").await;
    res.assert_status(http::StatusCode::FORBIDDEN);
    res.assert_json_contains(&serde_json::json!({
        "error": "feature_not_licensed",
        "feature": "sso"
    }));

    let res = server.get("/analytics").await;
    res.assert_status(http::StatusCode::FORBIDDEN);
    res.assert_json_contains(&serde_json::json!({ "error": "tier_required" }));
}

#[tokio::test]
async fn gates_allow_under_domain_bypass() {
    let server = axum_test::TestServer::new(app(offline_client(true)));
    server.get("/icebox").await.assert_status_ok();
    server.get("/sso").await.assert_status_ok();
    server.get("/analytics").await.assert_status_ok();
}
