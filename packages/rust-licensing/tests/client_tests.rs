//! Integration tests: license validation, flag evaluation, fail-safe
//! semantics, and bypass behavior against a mocked license server/PostHog.

#![allow(clippy::unwrap_used, clippy::panic)]

use std::time::Duration;

use penguin_licensing::{LicenseClient, LicenseConfig, Tier};
use url::Url;
use wiremock::matchers::{method, path};
use wiremock::{Mock, MockServer, ResponseTemplate};

fn test_config(server: &MockServer) -> LicenseConfig {
    let mut cfg = LicenseConfig::new("skauswatch").unwrap();
    cfg.license_key = Some("PENG-TEST-TEST-TEST-TEST-ABCD".to_owned());
    cfg.server_url = Url::parse(&server.uri()).unwrap();
    cfg.posthog_host = Url::parse(&server.uri()).unwrap();
    cfg.posthog_key = Some("phc_test".to_owned());
    cfg.release_mode = true; // enforcement on — bypass tests flip this
    cfg.cache_ttl = Duration::ZERO; // every read refreshes, so mocks drive state
    cfg
}

fn validate_body() -> serde_json::Value {
    serde_json::json!({
        "customer": "ACME Corp",
        "product": "skauswatch",
        "license_version": "2.0",
        "license_key": "PENG-TEST-TEST-TEST-TEST-ABCD",
        "expires_at": "2027-01-01T00:00:00Z",
        "issued_at": "2026-01-01T00:00:00Z",
        "tier": "enterprise",
        "features": [
            {"name": "sso", "entitled": true, "units": -1, "description": "", "metadata": {}},
            {"name": "waddleai", "entitled": false, "units": -1, "description": "", "metadata": {}}
        ],
        "limits": {},
        "metadata": {"server_id": "srv-42"}
    })
}

async fn mock_validate(server: &MockServer, body: serde_json::Value) {
    Mock::given(method("POST"))
        .and(path("/api/v2/validate"))
        .respond_with(ResponseTemplate::new(200).set_body_json(body))
        .mount(server)
        .await;
}

async fn mock_decide(server: &MockServer, flags: serde_json::Value) {
    Mock::given(method("POST"))
        .and(path("/decide/"))
        .respond_with(
            ResponseTemplate::new(200).set_body_json(serde_json::json!({ "featureFlags": flags })),
        )
        .mount(server)
        .await;
}

#[tokio::test]
async fn validate_parses_tier_and_features() {
    let server = MockServer::start().await;
    mock_validate(&server, validate_body()).await;
    mock_decide(&server, serde_json::json!({})).await;

    let client = LicenseClient::new(test_config(&server)).unwrap();
    let info = client.validate().await;

    assert!(info.valid);
    assert_eq!(info.tier, Tier::Enterprise);
    assert_eq!(info.customer, "ACME Corp");
    assert_eq!(info.server_id(), Some("srv-42"));
    assert!(client.check_feature("sso").await);
    assert!(!client.check_feature("waddleai").await);
    assert!(client.check_tier(Tier::Professional).await);
}

#[tokio::test]
async fn server_error_with_nothing_cached_fails_safe_to_community() {
    let server = MockServer::start().await;
    Mock::given(method("POST"))
        .and(path("/api/v2/validate"))
        .respond_with(ResponseTemplate::new(500))
        .mount(&server)
        .await;

    let client = LicenseClient::new(test_config(&server)).unwrap();
    let info = client.validate().await;

    assert_eq!(info.tier, Tier::Free);
    assert!(!client.check_feature("sso").await);
    assert!(!client.flag_enabled("skauswatch.s3-scan").await);
    assert_eq!(client.tier().await, Tier::Free);
}

#[tokio::test]
async fn cached_snapshot_survives_later_outage() {
    let server = MockServer::start().await;
    mock_validate(&server, validate_body()).await;
    mock_decide(&server, serde_json::json!({"skauswatch.s3-scan": true})).await;

    let client = LicenseClient::new(test_config(&server)).unwrap();
    client.refresh().await.unwrap();
    assert!(client.check_feature("sso").await);

    // Server goes dark: refresh fails but the snapshot is retained.
    server.reset().await;
    Mock::given(method("POST"))
        .respond_with(ResponseTemplate::new(500))
        .mount(&server)
        .await;

    assert!(client.refresh().await.is_err());
    assert!(client.check_feature("sso").await);
    assert!(client.flag_enabled("skauswatch.s3-scan").await);
}

#[tokio::test]
async fn flags_parse_bools_variants_and_default_off() {
    let server = MockServer::start().await;
    mock_validate(&server, validate_body()).await;
    mock_decide(
        &server,
        serde_json::json!({
            "skauswatch.s3-scan": true,
            "skauswatch.siem": false,
            "skauswatch.darwin": "variant-b"
        }),
    )
    .await;

    let client = LicenseClient::new(test_config(&server)).unwrap();
    assert!(client.flag_enabled("skauswatch.s3-scan").await);
    assert!(!client.flag_enabled("skauswatch.siem").await);
    assert!(client.flag_enabled("skauswatch.darwin").await); // variant = enabled
    assert!(!client.flag_enabled("skauswatch.never-created").await); // default OFF
}

#[tokio::test]
async fn dev_mode_bypasses_everything_without_network() {
    let mut cfg = LicenseConfig::new("skauswatch").unwrap();
    cfg.release_mode = false; // dev build
    cfg.server_url = Url::parse("http://127.0.0.1:1").unwrap(); // unroutable

    let client = LicenseClient::new(cfg).unwrap();
    assert!(client.check_feature("sso").await);
    assert!(client.flag_enabled("skauswatch.anything").await);
    assert_eq!(client.tier().await, Tier::Enterprise);
}

#[tokio::test]
async fn internal_domain_bypasses_in_release_mode() {
    let mut cfg = LicenseConfig::new("skauswatch").unwrap();
    cfg.release_mode = true;
    cfg.deployment_domain = Some("skauswatch.penguintech.cloud".to_owned());
    cfg.server_url = Url::parse("http://127.0.0.1:1").unwrap();

    let client = LicenseClient::new(cfg).unwrap();
    assert!(client.check_feature("sso").await);
    assert!(client.flag_enabled("skauswatch.icebox").await);
}

#[tokio::test]
async fn no_license_key_is_valid_community() {
    let server = MockServer::start().await;
    let mut cfg = test_config(&server);
    cfg.license_key = None;
    cfg.posthog_key = None;

    let client = LicenseClient::new(cfg).unwrap();
    let info = client.validate().await;
    assert!(info.valid);
    assert_eq!(info.tier, Tier::Free);
    assert!(!client.check_feature("sso").await);
    // keepalive is a silent no-op without a license
    client.keepalive().await.unwrap();
}
