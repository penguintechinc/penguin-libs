# Changelog

All notable changes to `penguin-logging` are documented here.

## [0.1.0] - 2026-09-14

### Added

- Initial release: sanitized structured logging (`tracing` + stdout JSON),
  OTLP logs/metrics/traces via `opentelemetry`/`opentelemetry-otlp`, a
  shared-meter Prometheus `/metrics` bridge (`opentelemetry-prometheus`),
  `/health`/`/healthz` endpoints, `waddles_dependency_up`/
  `waddles_dependency_check_total`/`waddles_insecure_transport` metric
  helpers, W3C `trace_context` propagation helpers, and a `testing`
  feature exposing in-memory exporters for downstream smoke tests.
