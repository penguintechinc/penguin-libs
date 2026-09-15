# penguin-logging

Structured, sanitized logging plus OpenTelemetry logs/metrics/traces and a
`/health`/`/healthz`/`/metrics` HTTP surface for Waddles/PenguinTech Rust
services. Closes the Rust logging gap recorded in `backend-rust.md`
("KNOWN GAP pending `rust-logging` package in penguin-libs").

## Usage

```rust
use penguin_logging::{ServiceConfig, init};

#[tokio::main]
async fn main() {
    let cfg = ServiceConfig::from_env("svc-process");
    let (_guard, level_handle, registry) = init(cfg);
    tracing::info!("svc-process starting");
    // ... build your axum app, mount penguin_logging::health::router(state) ...
}
```

## Environment variables

| Var | Default | Notes |
|---|---|---|
| `OTEL_EXPORTER_OTLP_ENDPOINT` | unset | Unset ⇒ OTLP export skipped entirely (stdout JSON only) |
| `OTEL_EXPORTER_OTLP_PROTOCOL` | `grpc` | `grpc` or `http/protobuf` |
| `OTEL_EXPORTER_OTLP_HEADERS` | unset | `key1=value1,key2=value2`, auth headers only, never logged |
| `OTEL_SERVICE_NAME` | the `default_service_name` argument | |
| `OTEL_RESOURCE_ATTRIBUTES` | unset | Read automatically by `opentelemetry_sdk`'s `EnvResourceDetector` |
| `LOG_LEVEL` | `info` | `error`\|`warn`\|`info`\|`debug`, reloadable at runtime via `LevelHandle::set_level` |

## Feature flags

- `testing` — exposes `penguin_logging::testing::{init_test_telemetry, TelemetryCounts}`, in-memory exporters for asserting the telemetry validation gate (`testing.md` Telemetry Validation) in a downstream service's own smoke tests.

## Development

All commands run inside the pinned `Dockerfile.ci` image — never bare host `cargo`:

```bash
make fmt lint deny audit test coverage build pre-commit
```
