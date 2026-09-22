//! Telemetry bootstrap: `tracing` + [`crate::layer::SanitizingLayer`]
//! (stdout JSON + OTel logs) + OTel traces + OTel metrics bridged into a
//! `prometheus::Registry` for the secondary `/metrics` scrape surface --
//! see spec §4.9 and `rules/critical-rules.md` Observability.
//!
//! Modeled on `core/svc_streaming/src/telemetry.rs`: an unset
//! `OTEL_EXPORTER_OTLP_ENDPOINT` means OTLP export is skipped entirely
//! (stdout JSON and Prometheus `/metrics` keep working); a failed exporter
//! build is logged and downgrades to the next best thing, never panics or
//! propagates.

use opentelemetry::global;
use opentelemetry::logs::LoggerProvider as _;
use opentelemetry::trace::TracerProvider as _;
use opentelemetry_otlp::{ExporterBuildError, Protocol, WithExportConfig};
use opentelemetry_sdk::logs::SdkLoggerProvider;
use opentelemetry_sdk::metrics::SdkMeterProvider;
use opentelemetry_sdk::trace::SdkTracerProvider;
use opentelemetry_sdk::Resource;
use tracing_subscriber::filter::EnvFilter;
use tracing_subscriber::layer::SubscriberExt;
use tracing_subscriber::reload;
use tracing_subscriber::util::SubscriberInitExt;
use tracing_subscriber::Registry;

use crate::config::{OtlpProtocol, ServiceConfig};
use crate::error::MetricsRenderError;
use crate::layer::SanitizingLayer;
use crate::level::LevelHandle;

/// Holds every OTel provider handle that must be flushed/shut down at
/// process exit. Dropping this guard (or calling
/// [`TelemetryGuard::shutdown`]) flushes buffered spans/metrics/logs.
pub struct TelemetryGuard {
    tracer_provider: Option<SdkTracerProvider>,
    meter_provider: Option<SdkMeterProvider>,
    logger_provider: Option<SdkLoggerProvider>,
}

impl TelemetryGuard {
    /// Flushes and shuts down every active pipeline. Errors are logged to
    /// stderr, never propagated -- shutdown must not be able to fail the
    /// caller.
    pub fn shutdown(&mut self) {
        if let Some(provider) = self.tracer_provider.take() {
            if let Err(err) = provider.shutdown() {
                eprintln!("penguin-logging: otel tracer provider shutdown error: {err}");
            }
        }
        if let Some(provider) = self.meter_provider.take() {
            if let Err(err) = provider.shutdown() {
                eprintln!("penguin-logging: otel meter provider shutdown error: {err}");
            }
        }
        if let Some(provider) = self.logger_provider.take() {
            if let Err(err) = provider.shutdown() {
                eprintln!("penguin-logging: otel logger provider shutdown error: {err}");
            }
        }
    }
}

impl Drop for TelemetryGuard {
    fn drop(&mut self) {
        self.shutdown();
    }
}

fn to_otlp_protocol(protocol: OtlpProtocol) -> Protocol {
    match protocol {
        OtlpProtocol::Grpc => Protocol::Grpc,
        OtlpProtocol::HttpProtobuf => Protocol::HttpBinary,
    }
}

fn resource(service_name: &str) -> Resource {
    // `Resource::builder()` already layers in `EnvResourceDetector`, which
    // reads `OTEL_RESOURCE_ATTRIBUTES` -- we only set the name explicitly
    // so there is always a sane default.
    Resource::builder()
        .with_service_name(service_name.to_string())
        .build()
}

fn build_tracer_provider(
    endpoint: &str,
    protocol: Protocol,
    res: Resource,
) -> Result<SdkTracerProvider, ExporterBuildError> {
    let exporter = match protocol {
        Protocol::Grpc => opentelemetry_otlp::SpanExporter::builder()
            .with_tonic()
            .with_endpoint(endpoint)
            .build()?,
        _ => opentelemetry_otlp::SpanExporter::builder()
            .with_http()
            .with_endpoint(endpoint)
            .build()?,
    };
    Ok(SdkTracerProvider::builder()
        .with_batch_exporter(exporter)
        .with_resource(res)
        .build())
}

/// Builds only the push-based OTLP metric exporter, leaving provider
/// assembly to the caller -- see [`init`]'s meter-provider construction,
/// which always attaches the Prometheus reader too and must not lose it to
/// an early return if this build fails.
fn build_otlp_metric_exporter(
    endpoint: &str,
    protocol: Protocol,
) -> Result<opentelemetry_otlp::MetricExporter, ExporterBuildError> {
    match protocol {
        Protocol::Grpc => opentelemetry_otlp::MetricExporter::builder()
            .with_tonic()
            .with_endpoint(endpoint)
            .build(),
        _ => opentelemetry_otlp::MetricExporter::builder()
            .with_http()
            .with_endpoint(endpoint)
            .build(),
    }
}

fn build_logger_provider(
    endpoint: &str,
    protocol: Protocol,
    res: Resource,
) -> Result<SdkLoggerProvider, ExporterBuildError> {
    let exporter = match protocol {
        Protocol::Grpc => opentelemetry_otlp::LogExporter::builder()
            .with_tonic()
            .with_endpoint(endpoint)
            .build()?,
        _ => opentelemetry_otlp::LogExporter::builder()
            .with_http()
            .with_endpoint(endpoint)
            .build()?,
    };
    Ok(SdkLoggerProvider::builder()
        .with_batch_exporter(exporter)
        .with_resource(res)
        .build())
}

/// Builds a Prometheus reader bound to a fresh registry. Prometheus
/// `/metrics` must keep working even when OTLP export is unset or its
/// exporter fails to build, so this is always attempted independently.
fn build_prometheus_reader(
    registry: &prometheus::Registry,
) -> Option<opentelemetry_prometheus::PrometheusExporter> {
    opentelemetry_prometheus::exporter()
        .with_registry(registry.clone())
        .build()
        .inspect_err(|err| {
            eprintln!("penguin-logging: prometheus metric reader init failed, /metrics will be empty: {err}");
        })
        .ok()
}

/// Initializes `tracing` (env-filtered, [`SanitizingLayer`]-rendered) plus
/// best-effort OTLP log/trace/metric export, and returns a Prometheus
/// [`prometheus::Registry`] for the `/metrics` HTTP surface plus a
/// [`LevelHandle`] for runtime level changes. Must be called exactly once,
/// before any other `tracing` macro use -- see the crate README.
pub fn init(cfg: ServiceConfig) -> (TelemetryGuard, LevelHandle, prometheus::Registry) {
    let (guard, level_handle, registry, subscriber) = assemble(cfg);
    subscriber.init();
    (guard, level_handle, registry)
}

/// Does every bit of construction `init` needs -- resource/provider
/// wiring, the layer stack -- without installing anything as the global
/// default. Split out from `init` so tests can exercise the *entire*
/// construction path (both the `Some(endpoint)` and `None` branches)
/// deterministically via `tracing::subscriber::with_default`, instead of
/// racing every other test in the binary for the one-per-process global
/// subscriber slot that a real `.init()` call claims.
fn assemble(
    cfg: ServiceConfig,
) -> (
    TelemetryGuard,
    LevelHandle,
    prometheus::Registry,
    impl tracing::Subscriber + Send + Sync + 'static,
) {
    let prometheus_registry = prometheus::Registry::new();
    let prometheus_reader = build_prometheus_reader(&prometheus_registry);

    let initial_filter =
        EnvFilter::try_new(&cfg.log_level).unwrap_or_else(|_| EnvFilter::new("info"));
    let (filter_layer, reload_handle): (reload::Layer<EnvFilter, Registry>, _) =
        reload::Layer::new(initial_filter);

    let res = resource(&cfg.service_name);
    let protocol = to_otlp_protocol(cfg.otlp_protocol);

    // The Prometheus reader is attached unconditionally: `/metrics` must
    // keep working whether or not OTLP is configured, and whether or not
    // the OTLP metric exporter itself fails to build (spec §13.4).
    let mut meter_builder = SdkMeterProvider::builder().with_resource(res.clone());
    if let Some(reader) = prometheus_reader {
        meter_builder = meter_builder.with_reader(reader);
    }

    let (tracer_provider, logger_provider) = match &cfg.otlp_endpoint {
        Some(endpoint) => {
            let tracer = build_tracer_provider(endpoint, protocol, res.clone())
                .inspect_err(|err| {
                    eprintln!("penguin-logging: otel trace exporter init failed, continuing without traces: {err}");
                })
                .ok();
            match build_otlp_metric_exporter(endpoint, protocol) {
                Ok(exporter) => meter_builder = meter_builder.with_periodic_exporter(exporter),
                Err(err) => eprintln!(
                    "penguin-logging: otel metric exporter init failed, Prometheus /metrics remains available: {err}"
                ),
            }
            let logger = build_logger_provider(endpoint, protocol, res.clone())
                .inspect_err(|err| {
                    eprintln!("penguin-logging: otel log exporter init failed, continuing with stdout only: {err}");
                })
                .ok();
            (tracer, logger)
        }
        None => (None, None),
    };
    let meter_provider = Some(meter_builder.build());

    if let Some(provider) = &meter_provider {
        global::set_meter_provider(provider.clone());
    }

    let otel_logger = logger_provider
        .as_ref()
        .map(|provider| provider.logger(cfg.service_name.clone()));
    let sanitizing_layer = SanitizingLayer::new(otel_logger);

    // `Option<Layer>` itself implements `Layer` (`None` is a no-op
    // passthrough) -- this unifies the `Some(endpoint)`/`None` branches
    // into one concrete subscriber type instead of needing two separate
    // `.init()` call sites with divergent types, which is what let this
    // function be split out of `init` at all.
    let otel_trace_layer = tracer_provider.as_ref().map(|provider| {
        tracing_opentelemetry::layer().with_tracer(provider.tracer(cfg.service_name.clone()))
    });

    let subscriber = tracing_subscriber::registry()
        .with(filter_layer)
        .with(sanitizing_layer)
        .with(otel_trace_layer);

    (
        TelemetryGuard {
            tracer_provider,
            meter_provider,
            logger_provider,
        },
        LevelHandle::new(reload_handle),
        prometheus_registry,
        subscriber,
    )
}

/// Renders the Prometheus text-format exposition body for `/metrics`.
pub fn render_metrics(registry: &prometheus::Registry) -> Result<String, MetricsRenderError> {
    use prometheus::Encoder;
    let metric_families = registry.gather();
    let mut buf = Vec::new();
    prometheus::TextEncoder::new().encode(&metric_families, &mut buf)?;
    Ok(String::from_utf8(buf)?)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn to_otlp_protocol_maps_grpc_and_http() {
        assert!(matches!(
            to_otlp_protocol(OtlpProtocol::Grpc),
            Protocol::Grpc
        ));
        assert!(matches!(
            to_otlp_protocol(OtlpProtocol::HttpProtobuf),
            Protocol::HttpBinary
        ));
    }

    #[test]
    fn resource_carries_the_service_name() {
        let res = resource("svc-process-test");
        let value = res.get(&opentelemetry::Key::from_static_str("service.name"));
        assert_eq!(
            value.map(|v| v.to_string()),
            Some("svc-process-test".to_string())
        );
    }

    #[test]
    fn render_metrics_on_empty_registry_is_empty_string() {
        let registry = prometheus::Registry::new();
        let rendered = render_metrics(&registry).expect("empty registry still encodes");
        assert!(rendered.is_empty());
    }

    #[test]
    fn build_prometheus_reader_succeeds_on_a_fresh_registry() {
        let registry = prometheus::Registry::new();
        assert!(build_prometheus_reader(&registry).is_some());
    }

    // The `grpc-tonic`/`http-proto` transports build a *lazy* channel that
    // still touches the Tokio reactor at construction time (confirmed by
    // hand: a bare `#[test]` panics with "there is no reactor running"),
    // so every OTLP builder test below needs an active runtime.

    #[tokio::test]
    async fn build_tracer_provider_succeeds_for_grpc_and_http() {
        let res = resource("telemetry-builder-test");
        assert!(
            build_tracer_provider("http://localhost:4317", Protocol::Grpc, res.clone()).is_ok()
        );
        assert!(build_tracer_provider("http://localhost:4318", Protocol::HttpBinary, res).is_ok());
    }

    #[tokio::test]
    async fn build_tracer_provider_rejects_a_malformed_endpoint() {
        assert!(build_tracer_provider(
            "::::not a uri::::",
            Protocol::Grpc,
            resource("telemetry-builder-test")
        )
        .is_err());
    }

    #[tokio::test]
    async fn build_otlp_metric_exporter_succeeds_for_grpc_and_http() {
        assert!(build_otlp_metric_exporter("http://localhost:4317", Protocol::Grpc).is_ok());
        assert!(build_otlp_metric_exporter("http://localhost:4318", Protocol::HttpBinary).is_ok());
    }

    #[tokio::test]
    async fn build_otlp_metric_exporter_rejects_a_malformed_endpoint() {
        assert!(build_otlp_metric_exporter("::::not a uri::::", Protocol::Grpc).is_err());
    }

    #[tokio::test]
    async fn build_logger_provider_succeeds_for_grpc_and_http() {
        let res = resource("telemetry-builder-test");
        assert!(
            build_logger_provider("http://localhost:4317", Protocol::Grpc, res.clone()).is_ok()
        );
        assert!(build_logger_provider("http://localhost:4318", Protocol::HttpBinary, res).is_ok());
    }

    #[tokio::test]
    async fn build_logger_provider_rejects_a_malformed_endpoint() {
        assert!(build_logger_provider(
            "::::not a uri::::",
            Protocol::Grpc,
            resource("telemetry-builder-test")
        )
        .is_err());
    }

    #[tokio::test]
    async fn telemetry_guard_shutdown_is_idempotent_with_real_providers() {
        let res = resource("telemetry-guard-test");
        let tracer_provider =
            build_tracer_provider("http://localhost:4317", Protocol::Grpc, res.clone()).ok();
        let logger_provider =
            build_logger_provider("http://localhost:4317", Protocol::Grpc, res).ok();
        let mut guard = TelemetryGuard {
            tracer_provider,
            meter_provider: None,
            logger_provider,
        };
        // First shutdown drains the real providers; the second call (and
        // the eventual `Drop`) must be a no-op, not a double-free/panic.
        guard.shutdown();
        assert!(guard.tracer_provider.is_none());
        assert!(guard.logger_provider.is_none());
        guard.shutdown();
    }

    // `assemble` (not `init`) is what these tests exercise: `init` installs
    // the process-global `tracing` subscriber, which only one test in the
    // whole binary can ever win (see `testing::tests`, which legitimately
    // needs that slot to make its own assertions meaningful). Testing
    // `assemble` directly via `tracing::subscriber::with_default` covers
    // every branch of the construction logic deterministically, with zero
    // risk of stealing the global slot out from under another test.

    #[tokio::test]
    async fn assemble_without_otlp_endpoint_wires_a_working_pipeline() {
        let cfg = ServiceConfig {
            service_name: "telemetry-assemble-test-no-otlp".to_string(),
            otlp_endpoint: None,
            otlp_protocol: OtlpProtocol::Grpc,
            log_level: "debug".to_string(),
        };
        let (guard, level_handle, registry, subscriber) = assemble(cfg);
        assert!(guard.tracer_provider.is_none());
        assert!(guard.logger_provider.is_none());
        assert!(guard.meter_provider.is_some());
        assert!(level_handle.set_level("info").is_ok());
        assert!(render_metrics(&registry).is_ok());

        tracing::subscriber::with_default(subscriber, || {
            tracing::debug!(password = "should-be-redacted", "assembled pipeline event");
        });
    }

    #[tokio::test]
    async fn assemble_with_otlp_endpoint_wires_tracer_and_logger_providers() {
        let cfg = ServiceConfig {
            service_name: "telemetry-assemble-test-with-otlp".to_string(),
            otlp_endpoint: Some("http://localhost:4317".to_string()),
            otlp_protocol: OtlpProtocol::Grpc,
            log_level: "info".to_string(),
        };
        let (guard, _level_handle, _registry, subscriber) = assemble(cfg);
        assert!(guard.tracer_provider.is_some());
        assert!(guard.logger_provider.is_some());

        tracing::subscriber::with_default(subscriber, || {
            tracing::info!(stage = "process", "assembled pipeline event with otlp");
        });
    }

    #[tokio::test]
    async fn assemble_with_unbuildable_otlp_endpoint_degrades_gracefully() {
        let cfg = ServiceConfig {
            service_name: "telemetry-assemble-test-bad-otlp".to_string(),
            otlp_endpoint: Some("::::not a uri::::".to_string()),
            otlp_protocol: OtlpProtocol::Grpc,
            log_level: "info".to_string(),
        };
        // Every exporter build fails, but assemble must still hand back a
        // usable pipeline (stdout JSON + Prometheus), never panic.
        let (guard, _level_handle, registry, subscriber) = assemble(cfg);
        assert!(guard.tracer_provider.is_none());
        assert!(guard.logger_provider.is_none());
        assert!(render_metrics(&registry).is_ok());
        tracing::subscriber::with_default(subscriber, || {
            tracing::warn!("degraded pipeline still logs");
        });
    }
}
