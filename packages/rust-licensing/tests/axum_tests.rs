//! Gating-middleware tests (feature = "axum").

#![cfg(feature = "axum")]
#![allow(clippy::unwrap_used, clippy::panic)]

use std::sync::Arc;
use std::time::Duration;

use axum::Router;
use axum::routing::get;
use penguin_licensing::axum::{FlagGate, TierGate, flag_gate, tier_gate};
use penguin_licensing::{LicenseClient, LicenseConfig, Tier};
use url::Url;

fn offline_client(release_mode: bool) -> Arc<LicenseClient> {
    let mut cfg = LicenseConfig::new("skauswatch").unwrap();
    cfg.release_mode = release_mode;
    cfg.server_url = Url::parse("http://127.0.0.1:1").unwrap();
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
            "/analytics",
            get(|| async { "ok" }).layer(axum::middleware::from_fn_with_state(
                TierGate::new(client, Tier::Enterprise),
                tier_gate,
            )),
        )
}

#[tokio::test]
async fn gates_deny_with_403_in_release_mode_when_unlicensed() {
    let server = axum_test::TestServer::new(app(offline_client(true)));
    let res = server.get("/icebox").await;
    res.assert_status(http::StatusCode::FORBIDDEN);
    res.assert_json_contains(&serde_json::json!({ "error": "feature_disabled" }));

    let res = server.get("/analytics").await;
    res.assert_status(http::StatusCode::FORBIDDEN);
    res.assert_json_contains(&serde_json::json!({ "error": "tier_required" }));
}

#[tokio::test]
async fn gates_allow_under_dev_bypass() {
    let server = axum_test::TestServer::new(app(offline_client(false)));
    server.get("/icebox").await.assert_status_ok();
    server.get("/analytics").await.assert_status_ok();
}
