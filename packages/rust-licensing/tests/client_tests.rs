//! Integration tests: license validation, flag evaluation, fail-closed
//! revocation/expiry semantics, non-blocking gating reads, credential
//! scoping, and domain bypass against a mocked license server/PostHog.

#![allow(clippy::unwrap_used, clippy::panic)]

use std::sync::Arc;
use std::time::Duration;

use penguin_licensing::{LicenseClient, LicenseConfig, LicenseError, Tier};
use url::Url;
use wiremock::matchers::{method, path};
use wiremock::{Mock, MockServer, ResponseTemplate};

fn test_config(server: &MockServer) -> LicenseConfig {
    let mut cfg = LicenseConfig::new("skauswatch").unwrap();
    cfg.license_key = Some("PENG-TEST-TEST-TEST-TEST-ABCD".to_owned());
    cfg.server_url = Url::parse(&server.uri()).unwrap();
    cfg.posthog_host = Url::parse(&server.uri()).unwrap();
    cfg.posthog_key = Some("phc_test".to_owned());
    cfg
}

/// A client that can never reach a server — proves gating decisions are
/// made without network access.
fn offline_config() -> LicenseConfig {
    let mut cfg = LicenseConfig::new("skauswatch").unwrap();
    cfg.server_url = Url::parse("http://127.0.0.1:1").unwrap();
    cfg.posthog_host = cfg.server_url.clone();
    cfg
}

fn validate_body() -> serde_json::Value {
    body_expiring("2027-01-01T00:00:00Z")
}

fn body_expiring(expires_at: &str) -> serde_json::Value {
    serde_json::json!({
        "customer": "ACME Corp",
        "product": "skauswatch",
        "license_version": "2.0",
        "license_key": "PENG-TEST-TEST-TEST-TEST-ABCD",
        "expires_at": expires_at,
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

async fn mock_validate_status(server: &MockServer, status: u16) {
    Mock::given(method("POST"))
        .and(path("/api/v2/validate"))
        .respond_with(ResponseTemplate::new(status))
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
    client.refresh().await.unwrap();
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
    mock_validate_status(&server, 500).await;

    let client = LicenseClient::new(test_config(&server)).unwrap();
    assert!(client.refresh().await.is_err());
    let info = client.validate().await;

    assert_eq!(info.tier, Tier::Free);
    assert!(!client.check_feature("sso").await);
    assert!(!client.flag_enabled("skauswatch.s3-scan").await);
    assert_eq!(client.tier().await, Tier::Free);
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
    client.refresh().await.unwrap();

    assert!(client.flag_enabled("skauswatch.s3-scan").await);
    assert!(!client.flag_enabled("skauswatch.siem").await);
    assert!(client.flag_enabled("skauswatch.darwin").await); // variant = enabled
    assert!(!client.flag_enabled("skauswatch.never-created").await); // default OFF
}

#[tokio::test]
async fn no_license_key_is_valid_community() {
    let server = MockServer::start().await;
    let mut cfg = test_config(&server);
    cfg.license_key = None;
    cfg.posthog_key = None;

    let client = LicenseClient::new(cfg).unwrap();
    client.refresh().await.unwrap();
    let info = client.validate().await;
    assert!(info.valid);
    assert_eq!(info.tier, Tier::Free);
    assert!(!client.check_feature("sso").await);
    // keepalive is a silent no-op without a license
    client.keepalive().await.unwrap();
}

// --- Finding 1: no env-var bypass -----------------------------------------

#[tokio::test]
async fn domain_bypass_grants_everything_without_network() {
    let cfg = offline_config().with_deployment_domain("skauswatch.penguintech.cloud");

    let client = LicenseClient::new(cfg).unwrap();
    assert!(client.bypass_active());
    assert!(client.check_feature("sso").await);
    assert!(client.flag_enabled("skauswatch.icebox").await);
    assert_eq!(client.tier().await, Tier::Enterprise);
}

#[tokio::test]
async fn unlisted_domain_is_enforced() {
    let cfg = offline_config().with_deployment_domain("customer.example.com");

    let client = LicenseClient::new(cfg).unwrap();
    assert!(!client.bypass_active());
    assert!(!client.check_feature("sso").await);
    assert!(!client.flag_enabled("skauswatch.icebox").await);
    assert_eq!(client.tier().await, Tier::Free);
}

/// Regression: no environment variable may switch enforcement off.
///
/// Two historical/near-miss bypasses are covered:
/// 1. `RELEASE_MODE` defaulting to false made `bypass_active()` true,
///    handing every Enterprise feature out for free.
/// 2. `DEPLOYMENT_DOMAIN`/`BASE_URL` fed the bypass-domain match straight
///    from the environment, which made a full Enterprise bypass one line
///    of deployment YAML (`DEPLOYMENT_DOMAIN: x.penguintech.cloud`).
///
/// Both must now be completely inert. This is the only env-mutating test
/// in the binary, so it cannot race another test's `set_var`.
#[tokio::test]
#[allow(unsafe_code)] // env mutation is unsafe in edition 2024; scoped to this test
async fn env_vars_cannot_grant_bypass() {
    for value in ["false", "0", "", "true"] {
        unsafe { std::env::set_var("RELEASE_MODE", value) };

        let client = LicenseClient::new(offline_config()).unwrap();
        assert!(
            !client.bypass_active(),
            "RELEASE_MODE={value} enabled bypass"
        );
        assert!(!client.check_feature("sso").await);
        assert!(!client.flag_enabled("skauswatch.anything").await);
        assert_eq!(client.tier().await, Tier::Free);
    }

    // A bypass-listed domain injected through the environment must not
    // reach `deployment_domain`, via either variable.
    unsafe {
        std::env::set_var("DEPLOYMENT_DOMAIN", "skauswatch.penguintech.cloud");
        std::env::set_var("BASE_URL", "https://skauswatch.penguincloud.io");
        // Pin the server URL so `from_env` is hermetic on a dev machine.
        std::env::set_var("LICENSE_SERVER_URL", "http://127.0.0.1:1");
    }

    let cfg = LicenseConfig::from_env("skauswatch").unwrap();
    assert_eq!(
        cfg.deployment_domain, None,
        "deployment domain was populated from the environment"
    );

    let client = LicenseClient::new(cfg).unwrap();
    assert!(!client.bypass_active(), "env var granted domain bypass");
    assert!(!client.check_feature("sso").await);
    assert!(!client.flag_enabled("skauswatch.anything").await);
    assert_eq!(client.tier().await, Tier::Free);

    unsafe {
        std::env::remove_var("RELEASE_MODE");
        std::env::remove_var("DEPLOYMENT_DOMAIN");
        std::env::remove_var("BASE_URL");
        std::env::remove_var("LICENSE_SERVER_URL");
    }
}

// --- Finding 2: license key is never sent to the PostHog host -------------

#[tokio::test]
async fn license_key_is_never_sent_to_the_posthog_host() {
    let license_server = MockServer::start().await;
    let posthog = MockServer::start().await;
    mock_validate(&license_server, validate_body()).await;
    Mock::given(method("POST"))
        .and(path("/api/v2/keepalive"))
        .respond_with(ResponseTemplate::new(200))
        .mount(&license_server)
        .await;
    mock_decide(&posthog, serde_json::json!({ "skauswatch.s3-scan": true })).await;

    let mut cfg = test_config(&license_server);
    cfg.posthog_host = Url::parse(&posthog.uri()).unwrap();

    let client = LicenseClient::new(cfg).unwrap();
    client.refresh().await.unwrap();
    client.keepalive().await.unwrap();

    let license_reqs = license_server.received_requests().await.unwrap();
    assert!(!license_reqs.is_empty(), "license server got no requests");
    for req in &license_reqs {
        let auth = req.headers.get("authorization");
        assert!(
            auth.is_some(),
            "license-server request {} lost its bearer credential",
            req.url
        );
    }

    let posthog_reqs = posthog.received_requests().await.unwrap();
    assert!(!posthog_reqs.is_empty(), "posthog got no requests");
    for req in &posthog_reqs {
        assert!(
            req.headers.get("authorization").is_none(),
            "license key leaked to posthog host in request to {}",
            req.url
        );
    }
}

// --- Finding 3: anything that is not success-or-outage fails closed -------

/// Warms an Enterprise cache (licence + an enabled flag), then makes the
/// server answer `status` and asserts the deployment drops to community.
async fn assert_fails_closed(status: u16) {
    let server = MockServer::start().await;
    mock_validate(&server, validate_body()).await;
    mock_decide(&server, serde_json::json!({ "skauswatch.s3-scan": true })).await;

    let client = LicenseClient::new(test_config(&server)).unwrap();
    client.refresh().await.unwrap();
    assert!(
        client.check_feature("sso").await,
        "setup: license should work"
    );
    assert!(
        client.flag_enabled("skauswatch.s3-scan").await,
        "setup: flag should be on"
    );

    // License is revoked / the server answers something uninterpretable.
    server.reset().await;
    mock_validate_status(&server, status).await;

    match client.refresh().await {
        Err(LicenseError::Rejected(code)) => assert_eq!(code, status),
        other => panic!("expected Rejected({status}), got {other:?}"),
    }

    let info = client.validate().await;
    assert_eq!(info.tier, Tier::Free, "status {status} kept the tier");
    assert!(
        !client.check_feature("sso").await,
        "status {status} still entitled sso"
    );
    assert!(!client.check_tier(Tier::Professional).await);
    // Flags must not outlive the licence that gated them.
    assert!(
        !client.flag_enabled("skauswatch.s3-scan").await,
        "status {status} left a stale flag enabled"
    );
}

#[tokio::test]
async fn revoked_license_401_fails_closed() {
    assert_fails_closed(401).await;
}

#[tokio::test]
async fn revoked_license_403_fails_closed() {
    assert_fails_closed(403).await;
}

#[tokio::test]
async fn unknown_license_404_fails_closed() {
    assert_fails_closed(404).await;
}

/// Retention is an allowlist, not a denylist: a status nobody enumerated
/// must not be mistaken for "keep serving Enterprise".
#[tokio::test]
async fn bad_request_400_fails_closed() {
    assert_fails_closed(400).await;
}

#[tokio::test]
async fn unexpected_418_fails_closed() {
    assert_fails_closed(418).await;
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

    match client.refresh().await {
        Err(LicenseError::Status(500)) => {}
        other => panic!("expected Status(500), got {other:?}"),
    }
    assert!(client.check_feature("sso").await);
    assert!(client.flag_enabled("skauswatch.s3-scan").await);
}

#[tokio::test]
async fn transport_error_retains_cached_snapshot() {
    let server = MockServer::start().await;
    mock_validate(&server, validate_body()).await;
    mock_decide(&server, serde_json::json!({"skauswatch.s3-scan": true})).await;

    let mut cfg = test_config(&server);
    cfg.timeout = Duration::from_millis(200);
    let client = LicenseClient::new(cfg).unwrap();
    client.refresh().await.unwrap();

    // Server stops answering in time — a transport-level failure, not a
    // verdict on the license.
    server.reset().await;
    Mock::given(method("POST"))
        .respond_with(ResponseTemplate::new(200).set_delay(Duration::from_secs(5)))
        .mount(&server)
        .await;

    match client.refresh().await {
        Err(LicenseError::Transport(_)) => {}
        other => panic!("expected Transport error, got {other:?}"),
    }
    assert!(
        client.check_feature("sso").await,
        "outage dropped the cache"
    );
    assert!(client.flag_enabled("skauswatch.s3-scan").await);
    assert_eq!(client.tier().await, Tier::Enterprise);
}

// --- Finding 4: expires_at is enforced with an offline grace window -------

#[tokio::test]
async fn expired_license_within_grace_is_still_entitled() {
    let server = MockServer::start().await;
    let expired_1h_ago = (chrono::Utc::now() - chrono::Duration::hours(1)).to_rfc3339();
    mock_validate(&server, body_expiring(&expired_1h_ago)).await;
    mock_decide(&server, serde_json::json!({})).await;

    let mut cfg = test_config(&server);
    cfg.offline_grace = Duration::from_secs(72 * 60 * 60);

    let client = LicenseClient::new(cfg).unwrap();
    client.refresh().await.unwrap();

    assert_eq!(client.tier().await, Tier::Enterprise);
    assert!(client.check_feature("sso").await);
}

#[tokio::test]
async fn expired_license_past_grace_falls_back_to_community() {
    let server = MockServer::start().await;
    let expired_100h_ago = (chrono::Utc::now() - chrono::Duration::hours(100)).to_rfc3339();
    mock_validate(&server, body_expiring(&expired_100h_ago)).await;
    mock_decide(&server, serde_json::json!({})).await;

    let mut cfg = test_config(&server);
    cfg.offline_grace = Duration::from_secs(72 * 60 * 60);

    let client = LicenseClient::new(cfg).unwrap();
    client.refresh().await.unwrap();

    let info = client.validate().await;
    assert_eq!(info.tier, Tier::Free, "expired license kept Enterprise");
    assert!(!client.check_feature("sso").await);
    assert!(!client.check_tier(Tier::Professional).await);
}

// --- Finding 5/8: non-blocking single-flight refresh ----------------------

/// Genuinely parallel: a multi-threaded runtime with the reads spawned as
/// independent tasks, so the `try_lock` single-flight path is exercised
/// under real thread contention rather than cooperative interleaving.
#[tokio::test(flavor = "multi_thread", worker_threads = 8)]
async fn concurrent_stale_reads_make_exactly_one_upstream_request() {
    let server = MockServer::start().await;
    Mock::given(method("POST"))
        .and(path("/api/v2/validate"))
        .respond_with(
            ResponseTemplate::new(200)
                .set_body_json(validate_body())
                .set_delay(Duration::from_millis(500)),
        )
        .expect(1)
        .mount(&server)
        .await;
    mock_decide(&server, serde_json::json!({})).await;

    let mut cfg = test_config(&server);
    cfg.cache_ttl = Duration::ZERO; // every read sees a stale snapshot

    let client = LicenseClient::new(cfg).unwrap();

    // 25 gating reads racing across 8 worker threads on an empty cache.
    let mut handles = Vec::new();
    for _ in 0..25 {
        let client: Arc<LicenseClient> = Arc::clone(&client);
        handles.push(tokio::spawn(
            async move { client.check_feature("sso").await },
        ));
    }
    let mut results = Vec::with_capacity(handles.len());
    for handle in handles {
        results.push(handle.await.unwrap());
    }
    assert!(
        results.iter().all(|entitled| !entitled),
        "reads must serve the (empty) snapshot, not await the refresh"
    );

    tokio::time::sleep(Duration::from_millis(1500)).await;

    let validates = server
        .received_requests()
        .await
        .unwrap()
        .into_iter()
        .filter(|r| r.url.path() == "/api/v2/validate")
        .count();
    assert_eq!(
        validates, 1,
        "single-flight collapsed to {validates} requests"
    );
}

#[tokio::test]
async fn gating_reads_do_not_wait_on_a_slow_server() {
    let server = MockServer::start().await;
    Mock::given(method("POST"))
        .and(path("/api/v2/validate"))
        .respond_with(
            ResponseTemplate::new(200)
                .set_body_json(validate_body())
                .set_delay(Duration::from_secs(5)),
        )
        .mount(&server)
        .await;

    let mut cfg = test_config(&server);
    cfg.cache_ttl = Duration::ZERO;
    cfg.timeout = Duration::from_secs(30);

    let client = LicenseClient::new(cfg).unwrap();

    let start = std::time::Instant::now();
    let entitled = client.check_feature("sso").await;
    let elapsed = start.elapsed();

    assert!(!entitled, "nothing cached must fail closed");
    assert!(
        elapsed < Duration::from_millis(500),
        "gating read blocked for {elapsed:?} on the license server"
    );
}

#[tokio::test]
async fn failed_refresh_backs_off_instead_of_retrying_per_read() {
    let server = MockServer::start().await;
    mock_validate_status(&server, 500).await;

    let mut cfg = test_config(&server);
    cfg.cache_ttl = Duration::ZERO;
    cfg.refresh_backoff_min = Duration::from_secs(30);

    let client = LicenseClient::new(cfg).unwrap();
    assert!(client.refresh().await.is_err()); // one failure, backoff armed

    for _ in 0..10 {
        assert!(!client.check_feature("sso").await);
    }
    tokio::time::sleep(Duration::from_millis(300)).await;

    let validates = server
        .received_requests()
        .await
        .unwrap()
        .into_iter()
        .filter(|r| r.url.path() == "/api/v2/validate")
        .count();
    assert_eq!(
        validates, 1,
        "backoff ignored: {validates} upstream retries"
    );
}

// --- Finding 7: transport security ----------------------------------------

#[test]
fn non_https_server_url_is_rejected() {
    let mut cfg = LicenseConfig::new("skauswatch").unwrap();
    cfg.server_url = Url::parse("http://license.example.com").unwrap();
    cfg.posthog_host = cfg.server_url.clone();
    assert!(matches!(
        LicenseClient::new(cfg),
        Err(LicenseError::Config(_))
    ));
}

#[test]
fn non_https_posthog_host_is_rejected() {
    let mut cfg = LicenseConfig::new("skauswatch").unwrap();
    cfg.posthog_host = Url::parse("http://posthog.example.com").unwrap();
    assert!(matches!(
        LicenseClient::new(cfg),
        Err(LicenseError::Config(_))
    ));
}

#[test]
fn https_and_loopback_http_are_accepted() {
    assert!(LicenseClient::new(LicenseConfig::new("skauswatch").unwrap()).is_ok());
    assert!(LicenseClient::new(offline_config()).is_ok());
}

// --- Finding 10: base paths survive URL joins -----------------------------

#[tokio::test]
async fn configured_base_path_is_preserved() {
    let server = MockServer::start().await;
    Mock::given(method("POST"))
        .and(path("/lic/api/v2/validate"))
        .respond_with(ResponseTemplate::new(200).set_body_json(validate_body()))
        .expect(1)
        .mount(&server)
        .await;
    Mock::given(method("POST"))
        .and(path("/ph/decide/"))
        .respond_with(
            ResponseTemplate::new(200)
                .set_body_json(serde_json::json!({ "featureFlags": {"skauswatch.s3-scan": true} })),
        )
        .expect(1)
        .mount(&server)
        .await;
    Mock::given(method("POST"))
        .and(path("/lic/api/v2/keepalive"))
        .respond_with(ResponseTemplate::new(200))
        .expect(1)
        .mount(&server)
        .await;

    let mut cfg = test_config(&server);
    cfg.server_url = Url::parse(&format!("{}/lic", server.uri())).unwrap();
    cfg.posthog_host = Url::parse(&format!("{}/ph", server.uri())).unwrap();

    let client = LicenseClient::new(cfg).unwrap();
    client.refresh().await.unwrap();
    client.keepalive().await.unwrap();

    assert!(client.check_feature("sso").await);
    assert!(client.flag_enabled("skauswatch.s3-scan").await);
}

/// A routing/tenant query parameter baked into the configured base URL
/// must survive onto every endpoint, and merge with the endpoint's own
/// query rather than replacing it.
#[tokio::test]
async fn configured_base_query_is_preserved() {
    let server = MockServer::start().await;
    mock_validate(&server, validate_body()).await;
    mock_decide(&server, serde_json::json!({ "skauswatch.s3-scan": true })).await;
    Mock::given(method("POST"))
        .and(path("/api/v2/keepalive"))
        .respond_with(ResponseTemplate::new(200))
        .mount(&server)
        .await;

    let mut cfg = test_config(&server);
    cfg.server_url = Url::parse(&format!("{}/?tenant=acme", server.uri())).unwrap();
    cfg.posthog_host = cfg.server_url.clone();

    let client = LicenseClient::new(cfg).unwrap();
    client.refresh().await.unwrap();
    client.keepalive().await.unwrap();

    let requests = server.received_requests().await.unwrap();
    let validate = requests
        .iter()
        .find(|r| r.url.path() == "/api/v2/validate")
        .expect("no validate request");
    assert_eq!(validate.url.query(), Some("tenant=acme"));

    let keepalive = requests
        .iter()
        .find(|r| r.url.path() == "/api/v2/keepalive")
        .expect("no keepalive request");
    assert_eq!(keepalive.url.query(), Some("tenant=acme"));

    // Base query merges with the endpoint's own `?v=3`, base first.
    let decide = requests
        .iter()
        .find(|r| r.url.path() == "/decide/")
        .expect("no decide request");
    assert_eq!(decide.url.query(), Some("tenant=acme&v=3"));
}
