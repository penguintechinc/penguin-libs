//! In-memory OTel exporters for a downstream service's own smoke tests,
//! asserting the `testing.md` Telemetry Validation gate (log records >= 1,
//! metric data points >= 1, histogram metrics >= 1, spans >= 1 where
//! applicable) without standing up a real OTLP collector. Gated by the
//! `testing` Cargo feature; also compiled under `cfg(test)` so this crate's
//! own test suite can use it.

use opentelemetry::logs::LoggerProvider as _;
use opentelemetry::trace::TracerProvider as _;
use opentelemetry_sdk::logs::{InMemoryLogExporter, SdkLoggerProvider};
use opentelemetry_sdk::metrics::data::{AggregatedMetrics, MetricData, ResourceMetrics};
use opentelemetry_sdk::metrics::{InMemoryMetricExporter, PeriodicReader, SdkMeterProvider};
use opentelemetry_sdk::trace::{InMemorySpanExporter, SdkTracerProvider};
use opentelemetry_sdk::Resource;
use tracing_subscriber::layer::SubscriberExt as _;
use tracing_subscriber::util::SubscriberInitExt as _;

use crate::layer::SanitizingLayer;

/// Counts of telemetry received by the in-memory exporters -- the
/// denominators `testing.md` Telemetry Validation requires a smoke test to
/// report; a zero count is a failure, not a pass.
#[derive(Debug, Clone, Copy, Default, PartialEq, Eq)]
pub struct TelemetryCounts {
    /// Number of emitted log records.
    pub log_records: usize,
    /// Number of metric data points, summed across every collected metric.
    pub metric_data_points: usize,
    /// Number of distinct histogram (or exponential histogram) metrics
    /// collected -- the load/latency signal spec §13.1 requires first.
    pub histogram_metrics: usize,
    /// Number of finished spans.
    pub spans: usize,
}

fn data_point_count_and_is_histogram<T>(data: &MetricData<T>) -> (usize, bool) {
    match data {
        MetricData::Gauge(g) => (g.data_points().count(), false),
        MetricData::Sum(s) => (s.data_points().count(), false),
        MetricData::Histogram(h) => (h.data_points().count(), true),
        MetricData::ExponentialHistogram(h) => (h.data_points().count(), true),
    }
}

fn count_metrics(resource_metrics: &[ResourceMetrics]) -> (usize, usize) {
    let mut total_points = 0usize;
    let mut histogram_metrics = 0usize;
    for rm in resource_metrics {
        for scope in rm.scope_metrics() {
            for metric in scope.metrics() {
                let (count, is_histogram) = match metric.data() {
                    AggregatedMetrics::F64(data) => data_point_count_and_is_histogram(data),
                    AggregatedMetrics::U64(data) => data_point_count_and_is_histogram(data),
                    AggregatedMetrics::I64(data) => data_point_count_and_is_histogram(data),
                };
                total_points += count;
                if is_histogram {
                    histogram_metrics += 1;
                }
            }
        }
    }
    (total_points, histogram_metrics)
}

/// Everything a downstream service's smoke test needs: the in-memory
/// exporters (for record-level assertions beyond [`TestTelemetry::counts`])
/// plus the provider handles keeping the pipeline alive for the life of the
/// test binary. Call [`init_test_telemetry`] exactly once per test binary,
/// before any `tracing` macro use.
pub struct TestTelemetry {
    /// The in-memory log exporter.
    pub logs: InMemoryLogExporter,
    /// The in-memory metric exporter. Call [`TestTelemetry::counts`] rather
    /// than reading this directly -- metrics require an explicit flush.
    pub metrics: InMemoryMetricExporter,
    /// The in-memory span exporter.
    pub spans: InMemorySpanExporter,
    meter_provider: SdkMeterProvider,
    // Held only to keep the pipelines alive for the test binary's lifetime;
    // never read directly, hence the leading underscores.
    _tracer_provider: SdkTracerProvider,
    _logger_provider: SdkLoggerProvider,
}

impl TestTelemetry {
    /// Forces the metric pipeline to collect pending data points (logs and
    /// spans land in their in-memory exporters as soon as they are
    /// emitted; metrics do not), then reports current counts across all
    /// three signals.
    pub fn counts(&self) -> TelemetryCounts {
        let _ = self.meter_provider.force_flush();
        let log_records = self
            .logs
            .get_emitted_logs()
            .map(|v| v.len())
            .unwrap_or_default();
        let spans = self
            .spans
            .get_finished_spans()
            .map(|v| v.len())
            .unwrap_or_default();
        let (metric_data_points, histogram_metrics) = self
            .metrics
            .get_finished_metrics()
            .map(|rm| count_metrics(&rm))
            .unwrap_or_default();
        TelemetryCounts {
            log_records,
            metric_data_points,
            histogram_metrics,
            spans,
        }
    }
}

/// Builds an in-memory-backed telemetry pipeline (sanitizing layer + OTel
/// logs/metrics/traces) and installs it as the global `tracing` subscriber,
/// exactly like [`crate::telemetry::init`] but without any network I/O.
/// Safe to call more than once per process (later calls are no-ops via
/// `try_init`), but only the *first* call's exporters actually receive
/// anything -- call it exactly once per test binary.
pub fn init_test_telemetry(service_name: &str) -> TestTelemetry {
    let log_exporter = InMemoryLogExporter::default();
    let metric_exporter = InMemoryMetricExporter::default();
    let span_exporter = InMemorySpanExporter::default();

    let res = Resource::builder()
        .with_service_name(service_name.to_string())
        .build();

    let logger_provider = SdkLoggerProvider::builder()
        .with_resource(res.clone())
        .with_simple_exporter(log_exporter.clone())
        .build();
    let tracer_provider = SdkTracerProvider::builder()
        .with_resource(res.clone())
        .with_simple_exporter(span_exporter.clone())
        .build();
    let meter_provider = SdkMeterProvider::builder()
        .with_resource(res)
        .with_reader(PeriodicReader::builder(metric_exporter.clone()).build())
        .build();
    // Mirrors crate::telemetry::init: instruments created via
    // `opentelemetry::global::meter(...)` (the idiomatic call site) only
    // reach this provider once it is registered globally.
    opentelemetry::global::set_meter_provider(meter_provider.clone());

    let otel_logger = logger_provider.logger(service_name.to_string());
    let sanitizing_layer = SanitizingLayer::new(Some(otel_logger));
    let tracer = tracer_provider.tracer(service_name.to_string());

    let subscriber = tracing_subscriber::registry()
        .with(sanitizing_layer)
        .with(tracing_opentelemetry::layer().with_tracer(tracer));
    // A test binary may exercise multiple `#[test]`/`#[tokio::test]`
    // functions; only the first `init_test_telemetry` call can install the
    // global default. `try_init` makes later calls a documented no-op
    // instead of a panic -- see this function's "call exactly once" note.
    let _ = subscriber.try_init();

    TestTelemetry {
        logs: log_exporter,
        metrics: metric_exporter,
        spans: span_exporter,
        meter_provider,
        _tracer_provider: tracer_provider,
        _logger_provider: logger_provider,
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn init_test_telemetry_captures_logs_metrics_and_spans() {
        let telemetry = init_test_telemetry("penguin-logging-testing-module-test");

        let meter = opentelemetry::global::meter("penguin-logging-test");
        let counter = meter.u64_counter("test_counter").build();
        counter.add(1, &[]);
        let histogram = meter.f64_histogram("test_histogram").build();
        histogram.record(1.5, &[]);

        tracing::info!(stage = "test", "telemetry smoke event");

        let counts = telemetry.counts();
        assert!(
            counts.log_records >= 1,
            "expected at least one log record: {counts:?}"
        );
        assert!(
            counts.metric_data_points >= 1,
            "expected at least one metric data point: {counts:?}"
        );
        assert!(
            counts.histogram_metrics >= 1,
            "expected at least one histogram metric: {counts:?}"
        );
    }

    #[test]
    fn telemetry_counts_default_is_all_zero() {
        assert_eq!(
            TelemetryCounts::default(),
            TelemetryCounts {
                log_records: 0,
                metric_data_points: 0,
                histogram_metrics: 0,
                spans: 0,
            }
        );
    }
}
