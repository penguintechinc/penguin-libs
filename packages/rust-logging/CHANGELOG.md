# Changelog

All notable changes to `penguin-logging` are documented here.

## [0.1.0] - 2026-09-22

### Added

- Initial release, closing the M1 `penguin-logging` deliverable of
  `docs/superpowers/specs/2026-09-14-rust-data-plane-design.md` §4.9/§16:
  - `sanitize::sanitize_object`: the `SENSITIVE_KEYS`/email-redaction
    contract ported verbatim from `python-utils`'
    `penguintechinc_utils.logging`, with tests proving known secrets never
    survive sanitization at any `tracing` level, DEBUG included.
  - `layer::SanitizingLayer`: a single `tracing_subscriber::Layer` that
    sanitizes every event's fields once and renders both the stdout JSON
    line and the OTel `LogRecord` from that same sanitized data --
    `opentelemetry-appender-tracing` is deliberately not a dependency,
    since its own field visitor has no sanitization hook.
  - `telemetry::init`/`telemetry::assemble`: `tracing` + OTel
    logs/metrics/traces wired to the standard OTLP env vars, plus a
    `prometheus::Registry` for the secondary `/metrics` surface (always
    populated, independent of whether OTLP is configured).
  - `level::LevelHandle`: runtime-reloadable `LOG_LEVEL`
    (`error`/`warn`/`info`/`debug`).
  - `health::{router, HealthReport, HealthState, overall_transport}`: the
    shared `/health`, `/healthz`, `/metrics` surface plus the §11.6.4
    `transport`/`transport_detail` computation; service-specific fields
    (`dependencies`, `executor`, `spine`, ...) are supplied by the caller.
  - `testing::{init_test_telemetry, TelemetryCounts}` (the `testing`
    feature): in-memory OTel exporters for a downstream service's own
    `testing.md` Telemetry Validation smoke tests.
- **Not yet implemented** (tracked as follow-up, not part of this M1 pass):
  named per-service Prometheus metrics from spec §13.1 (e.g.
  `waddles_dependency_up`, `waddles_insecure_transport`) and standalone
  W3C `traceparent` extract/inject helpers -- services register their own
  metrics against the registry this crate returns (see
  `core/svc_streaming/src/telemetry.rs::register_request_metrics` for the
  existing pattern), and `tracing-opentelemetry`'s span context already
  carries trace propagation within this crate's own pipeline.
