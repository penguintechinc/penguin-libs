//! The shared `/health`, `/healthz`, `/metrics` HTTP surface every
//! Rust data-plane service mounts (spec §4.9, §13.4, §11.6.4). This crate
//! owns the envelope shape and the `transport:` computation; each service
//! supplies its own dependency/executor/spine details via a report
//! callback, since those are service-specific.

use std::collections::BTreeMap;
use std::sync::Arc;

use axum::extract::State;
use axum::http::StatusCode;
use axum::response::{IntoResponse, Json};
use axum::routing::get;
use axum::Router;
use serde::Serialize;

/// TLS/auth posture for one secured component (e.g. Valkey, Postgres), per
/// spec §11.6.4's `transport_detail` block.
#[derive(Debug, Clone, Copy, Serialize)]
pub struct TransportAspect {
    /// `true` when TLS is enabled for this component.
    pub tls: bool,
    /// `true` when authentication is enabled for this component.
    pub auth: bool,
}

/// Computes the top-level `transport` field: `"secure"` only when every
/// component/aspect reported is on, `"insecure"` otherwise -- the exact
/// D20 rule from spec §11.6.4.
pub fn overall_transport(detail: &BTreeMap<String, TransportAspect>) -> &'static str {
    let all_secure = detail.values().all(|aspect| aspect.tls && aspect.auth);
    if all_secure {
        "secure"
    } else {
        "insecure"
    }
}

/// The `/health` response body, matching spec §11.6.4's shape. `extra`
/// carries every service-specific field (`dependencies`, `executor`,
/// `spine`, `sandbox`, ...) flattened into the top-level JSON object, since
/// this crate cannot know a given service's own dependency set.
#[derive(Debug, Clone, Serialize)]
pub struct HealthReport {
    /// Free-form status text, e.g. `"ok"` -- the caller decides the exact
    /// vocabulary for its own degraded states.
    pub status: String,
    /// The service's own name (matches `OTEL_SERVICE_NAME`/`ServiceConfig::service_name`).
    pub service: String,
    /// The service's own version string (e.g. its crate/build version).
    pub version: String,
    /// `"secure"` or `"insecure"` -- see [`overall_transport`].
    pub transport: &'static str,
    /// Per-component TLS/auth posture, spec §11.6.4's `transport_detail`.
    pub transport_detail: BTreeMap<String, TransportAspect>,
    /// Every other service-specific field, flattened into the top-level
    /// object (`dependencies`, `executor`, `spine`, `sandbox`, ...).
    #[serde(flatten)]
    pub extra: serde_json::Map<String, serde_json::Value>,
    /// Not serialized -- only controls the HTTP status code (`200` when
    /// `true`, `503` otherwise), per spec §13.4's readiness rule.
    #[serde(skip)]
    pub ready: bool,
}

/// Signature of the callback a service registers to produce its own
/// [`HealthReport`] on demand -- called once per `/health` request.
type ReportFn = dyn Fn() -> HealthReport + Send + Sync;

/// Shared state backing the health/metrics router: a report callback plus
/// the Prometheus registry returned by [`crate::telemetry::init`].
#[derive(Clone)]
pub struct HealthState {
    report_fn: Arc<ReportFn>,
    metrics_registry: prometheus::Registry,
}

impl HealthState {
    /// Builds the shared state. `report_fn` is invoked on every `/health`
    /// request, so it should be cheap (read current values, not perform
    /// I/O) -- services that need a live dependency probe should cache the
    /// last probe result and have `report_fn` read the cache.
    pub fn new(
        metrics_registry: prometheus::Registry,
        report_fn: impl Fn() -> HealthReport + Send + Sync + 'static,
    ) -> Self {
        Self {
            report_fn: Arc::new(report_fn),
            metrics_registry,
        }
    }
}

async fn health_handler(State(state): State<HealthState>) -> impl IntoResponse {
    let report = (state.report_fn)();
    let status_code = if report.ready {
        StatusCode::OK
    } else {
        StatusCode::SERVICE_UNAVAILABLE
    };
    (status_code, Json(report))
}

/// Bare liveness probe for Kubernetes -- no JSON, no dependency checks.
async fn healthz_handler() -> &'static str {
    "ok"
}

async fn metrics_handler(State(state): State<HealthState>) -> impl IntoResponse {
    match crate::telemetry::render_metrics(&state.metrics_registry) {
        Ok(body) => (StatusCode::OK, body).into_response(),
        Err(err) => {
            tracing::error!(error = %err, "failed to render prometheus metrics");
            (StatusCode::INTERNAL_SERVER_ERROR, "metrics render failed").into_response()
        }
    }
}

/// Builds the `/health`, `/healthz`, `/metrics` router. Mount this directly
/// on the service's own `axum::Router` (e.g. via `.merge(...)`).
pub fn router(state: HealthState) -> Router {
    Router::new()
        .route("/health", get(health_handler))
        .route("/healthz", get(healthz_handler))
        .route("/metrics", get(metrics_handler))
        .with_state(state)
}

#[cfg(test)]
mod tests {
    use super::*;
    use axum_test::TestServer;

    fn sample_report(ready: bool) -> HealthReport {
        let mut transport_detail = BTreeMap::new();
        transport_detail.insert(
            "valkey".to_string(),
            TransportAspect {
                tls: true,
                auth: true,
            },
        );
        HealthReport {
            status: "ok".to_string(),
            service: "svc-process-test".to_string(),
            version: "3.0.0".to_string(),
            transport: overall_transport(&transport_detail),
            transport_detail,
            extra: serde_json::Map::new(),
            ready,
        }
    }

    #[rstest::rstest]
    #[case(true, true)]
    #[case(false, false)]
    fn overall_transport_is_secure_only_when_every_aspect_is_on(
        #[case] tls: bool,
        #[case] expected_secure: bool,
    ) {
        let mut detail = BTreeMap::new();
        detail.insert("postgres".to_string(), TransportAspect { tls, auth: true });
        assert_eq!(overall_transport(&detail) == "secure", expected_secure);
    }

    #[test]
    fn overall_transport_with_no_components_is_secure_vacuously() {
        assert_eq!(overall_transport(&BTreeMap::new()), "secure");
    }

    #[tokio::test]
    async fn healthz_is_bare_ok() {
        let state = HealthState::new(prometheus::Registry::new(), || sample_report(true));
        let server = TestServer::new(router(state));
        let response = server.get("/healthz").await;
        response.assert_status_ok();
        response.assert_text("ok");
    }

    #[tokio::test]
    async fn health_returns_200_when_ready() {
        let state = HealthState::new(prometheus::Registry::new(), || sample_report(true));
        let server = TestServer::new(router(state));
        let response = server.get("/health").await;
        response.assert_status_ok();
        let body: serde_json::Value = response.json();
        assert_eq!(body["service"], "svc-process-test");
        assert_eq!(body["transport"], "secure");
        assert!(
            body.get("ready").is_none(),
            "ready must not leak into the JSON body"
        );
    }

    #[tokio::test]
    async fn health_returns_503_when_not_ready() {
        let state = HealthState::new(prometheus::Registry::new(), || sample_report(false));
        let server = TestServer::new(router(state));
        let response = server.get("/health").await;
        response.assert_status(StatusCode::SERVICE_UNAVAILABLE);
    }

    #[tokio::test]
    async fn metrics_endpoint_renders_registered_series() {
        let registry = prometheus::Registry::new();
        let up = prometheus::IntGauge::new("test_up", "1 if up").expect("valid metric definition");
        registry
            .register(Box::new(up.clone()))
            .expect("register test_up");
        up.set(1);
        let state = HealthState::new(registry, || sample_report(true));
        let server = TestServer::new(router(state));
        let response = server.get("/metrics").await;
        response.assert_status_ok();
        response.assert_text_contains("test_up 1");
    }
}
