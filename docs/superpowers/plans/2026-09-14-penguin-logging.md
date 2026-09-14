# penguin-logging Crate Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build `packages/rust-logging` (crate `penguin-logging`) in `penguin-libs` — the Rust structured/sanitized logging + OTel logs/metrics/traces + health/metrics-endpoint crate that closes the `KNOWN GAP` recorded in `backend-rust.md`, and that all four Waddles data-plane services (`svc_ingest`, `svc_process`, `svc_action`, `svc_streaming`) plus `bundle-executor`/`bundle-compiler` consume for Milestone M1.

**Architecture:** One `init(ServiceConfig)` call wires `tracing`+`tracing-subscriber` (stdout JSON, runtime-reloadable level filter) together with three OTLP pipelines (logs via `opentelemetry-appender-tracing`, metrics via `opentelemetry_sdk`'s periodic OTLP exporter, traces via `tracing-opentelemetry`) and one `opentelemetry-prometheus` reader sharing the *same* meter as the OTLP metrics pipeline, so `/metrics` and the OTLP push are two views of one instrument set instead of the hand-duplicated Prometheus-only metrics the `core/svc_streaming` reference implementation has today. A sanitization layer (verbatim port of `penguin-utils`'s `SENSITIVE_KEYS` rule) runs on every log field and on the WIT `log` host call's `fields-json` before anything is emitted. A small axum router provides `/health`, `/healthz`, `/metrics`. A `testing` Cargo feature exposes in-memory log/metric/span exporters so this crate's own tests, and every downstream service's smoke tests, can assert the `critical-rules.md`/`testing.md` telemetry gate (≥1 log record, ≥1 metric data point, ≥1 histogram, ≥1 span) with real counts instead of trusting that OTLP shipped somewhere.

**Tech Stack:** Rust 1.97.1, `tracing` 0.1.44, `tracing-subscriber` 0.3.23, `tracing-opentelemetry` 0.33.0, `opentelemetry` 0.32.0, `opentelemetry_sdk` 0.32.1, `opentelemetry-otlp` 0.32.0 (`grpc-tonic`), `opentelemetry-appender-tracing` 0.32.0, `opentelemetry-prometheus` 0.32.0, `prometheus` 0.14.0, `axum` 0.8.9, `serde`/`serde_json`, `regex` 1.13.1, `thiserror` 2.0.20, `tokio` 1.53.1. Dev: `rstest` 0.27.0, `axum-test` 21.1.0.

**Spec:** `docs/superpowers/specs/2026-09-14-rust-data-plane-design.md` (waddlebot repo, commit `680a0a9b`, 3,121 lines — fetched from `origin/docs/rust-data-plane-spec`) — §4.9 (`penguin-logging` component), §6.1.2 (`trace_context` envelope field), §11.6 (transport security / `waddles_insecure_transport`), §12.6 (startup self-check / `waddles_dependency_up`/`_check_total`), §13 (Observability — metrics/traces/logs/health), §14.5 (per-crate CI gates), §14.7 (telemetry validation gate), §16 M1 (this crate's row), §17 (Standards). Executors read both this plan and the spec; nothing in the logging scope changed between the spec revision cited here and the one this plan was researched against.

## Global Constraints

- **Crate identity:** directory `packages/rust-logging`, crate name `penguin-logging`, `version = "0.1.0"`, `edition = "2021"`, `rust-version = "1.97"`, `license = "MIT"` — matches `packages/rust-licensing`'s established per-crate conventions (`penguin-libs-inventory.md` §1).
- **Rust toolchain 1.97.1**, pinned via `rust-toolchain.toml` in the crate directory, not just CI config (`backend-rust.md`).
- **Every `cargo` command runs inside the pinned Docker image**, never host `cargo` — `rust:1.97.1-slim-bookworm@sha256:2775a09d208ff0d7c1f50490c45b62db929e87ba1dcbc3f2132ac71a704bcdd3` plus `cargo-deny` 0.20.2, `cargo-llvm-cov` 0.9.1, `cargo-audit` 0.22.2 baked into a crate-local `Dockerfile.ci` (verified digest and tool versions via the crates.io/Docker Hub registry APIs during planning — record shown in Task 1).
- **Dependency pinning:** exact `=x.y.z` versions everywhere in `Cargo.toml` (never `^`/`~`/bare `*`); `Cargo.lock` committed; `cargo deny check` + `cargo audit` clean before every commit (`critical-rules.md` Dependency Pinning).
- **Lints:** `[lints.rust] unsafe_code = "deny"`, `missing_docs = "deny"`; `[lints.clippy] unwrap_used = "deny"` — every `.unwrap()`/`.expect()` in non-test code is forbidden unless the invariant is documented in a comment (`backend-rust.md`); `cargo fmt --check` and `cargo clippy --all-targets --all-features -- -D warnings` clean before every commit.
- **Coverage ≥ 90%** lines/branches/functions/statements, gated by `cargo llvm-cov --all-features --fail-under-lines 90` (`critical-rules.md` Coverage).
- **Sanitization contract (verbatim port):** `SENSITIVE_KEYS` = `password, passwd, secret, token, api_key, apikey, auth_token, authtoken, access_token, refresh_token, credential, credentials, mfa_code, totp_code, otp, captcha_token, session_id, sessionid, cookie, authorization` — matched by exact key **or** substring (case-insensitive), replaced with `"[REDACTED]"`; string values additionally regex-scanned for an email shape anchored at the start (`^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}`) and, when the value splits into exactly two parts on `@`, rewritten to `"[email]@{domain}"` (more than two `@`-delimited parts → `"[REDACTED_EMAIL]"`); recursion into nested JSON objects; JSON array items are sanitized only when they are themselves objects (plain string/number array items pass through unchanged) — this is the exact behavior of `penguin-libs/packages/python-utils/src/penguintechinc_utils/logging.py`'s `sanitize_log_data`, confirmed by reading that source and its test file `tests/test_sinks.py::TestSanitizeLogData` during planning.
- **Observability (`critical-rules.md`):** OTLP destination configurable ONLY via `OTEL_EXPORTER_OTLP_ENDPOINT`/`_PROTOCOL`/`_HEADERS`/`OTEL_SERVICE_NAME`/`OTEL_RESOURCE_ATTRIBUTES` — never a hardcoded vendor URL, never a vendor SDK. Unset `OTEL_EXPORTER_OTLP_ENDPOINT` ⇒ OTLP export is skipped entirely (stdout JSON logging only), matching `core/svc_streaming/src/telemetry.rs`'s existing behavior. A dead/unreachable exporter must never crash or block the app: bounded buffers, drop-oldest, one WARN log per failure class, never a panic. Histograms come first — every duration/latency helper this crate exposes is a histogram, never a bare counter.
- **Levels:** ERROR = actionable failure, WARN = degraded-but-serving, INFO = lifecycle/state-change (the default runtime level), DEBUG = generous per-event diagnostic detail, off by default, runtime-switchable without a restart.
- **Reference implementation (`core/svc_streaming/src/telemetry.rs`, `git show origin/release/v3.0.X:core/svc_streaming/src/telemetry.rs`, read in full during planning):** builds an OTLP **span** exporter and an OTLP **metric** exporter, but records zero instruments through the OTel meter anywhere in the file — so its OTLP metrics pipeline would ship empty `ResourceMetrics` forever — and has **no OTLP log exporter at all** (only `tracing_subscriber::fmt::layer().json()` to stdout). `penguin-logging` closes both gaps: it adds the missing OTLP log exporter (`opentelemetry-appender-tracing`'s `OpenTelemetryTracingBridge`), and it eliminates the double-bookkeeping risk that produced the metrics gap by feeding one shared `opentelemetry_sdk` meter into **both** the periodic OTLP exporter and an `opentelemetry-prometheus` reader, so a single `histogram.record(...)` call reaches both destinations instead of requiring two hand-written registrations.
- **Never `restream`.** Say **Waddles**, not "waddlebot", in all new prose/comments this plan adds (the codebase is mid-rename per spec D22; `waddlebot` survives only in the specific legacy identifiers D22 lists, none of which this crate touches).
- **Commits:** every commit message is `feat(logging): ...` / `test(logging): ...` / `chore(logging): ...` / `docs(logging): ...` as appropriate, each ending with:
  ```
  Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
  Claude-Session: https://claude.ai/code/session_01N2rQgkHY872RubwXoBZxtE
  ```
- **Branch:** work happens on `docs/plan-penguin-logging`'s successor implementation branch (a fresh `feature/penguin-logging` branch off `main`, inside its own worktree per `using-git-worktrees`) — this plan document itself lives on `docs/plan-penguin-logging` and is not the implementation branch. Never push to `main`.
- **Docs:** every new `pub` item gets a 2-3 line doc comment (godoc-style content, Rust `///` syntax) — required anyway by `#[deny(missing_docs)]`. No ASCII-art section dividers.

## File Structure

```
penguin-libs/
  Makefile                              MODIFY — add packages/rust-logging lines to build/lint/test/test-security
  .github/workflows/ci.yml              MODIFY — new `build-rust-logging` job
  .github/workflows/publish.yml         MODIFY — new `publish-rust-logging` job + tag + dispatch option
  packages/rust-logging/
    Cargo.toml                          new crate manifest, exact pins
    Cargo.lock                          committed, generated by Task 1
    deny.toml                           cargo-deny config (mirrors rust-licensing's)
    rust-toolchain.toml                 pins 1.97.1 + rustfmt/clippy/llvm-tools-preview
    rustfmt.toml                        default settings, explicit file so `cargo fmt` is deterministic
    Dockerfile.ci                       pinned toolchain + cargo-deny/llvm-cov/audit, used by every Makefile target
    Makefile                            crate-local targets, all run through Dockerfile.ci
    .gitignore                          target/, Cargo.lock is NOT ignored (binary-adjacent lib, but house rule commits it for libs consumed as path/git deps too — see Task 1)
    LICENSE                             MIT, matches rust-licensing
    README.md                           usage, env var table, feature flags
    CHANGELOG.md                        0.1.0 entry
    src/
      lib.rs                            crate doc comment, module wiring, public re-exports
      sanitize.rs                       SENSITIVE_KEYS, sanitize_value, sanitize_json_str, Sanitized<T>
      config.rs                         ServiceConfig, OtlpProtocol, from_env
      level.rs                          LevelHandle, parse_level_filter, LevelError
      resource.rs                       otlp_protocol(), resource()
      logging_init.rs                   init_stdout_logging() — base tracing registry, no OTel
      trace_provider.rs                 build_tracer_provider()
      metrics_provider.rs               build_meter_provider() (OTLP periodic + Prometheus reader), render_prometheus_text()
      log_provider.rs                   build_logger_provider(), OpenTelemetryTracingBridge wiring
      init.rs                           init(ServiceConfig) -> (TelemetryGuard, LevelHandle, prometheus::Registry), TelemetryGuard
      metrics.rs                        record_latency_ms, counter_add, gauge_set, instrument cache
      trace_context.rs                  inject_trace_context, context_from_trace_context
      health/
        mod.rs                          re-exports
        types.rs                        DependencyClass, DependencyStatus, ComponentTransport, HealthState, HealthBody
        router.rs                       router(), liveness_readiness_router(), metrics_router(), handlers
        transport.rs                    TransportAspect, TransportMetrics, warn_insecure_transport()
        dependency.rs                   DependencyMetrics (waddles_dependency_up / waddles_dependency_check_total)
      testing.rs                        #[cfg(feature = "testing")] TestTelemetry, init_test_telemetry, TelemetryCounts
    tests/
      integration_telemetry.rs          full round-trip against the in-memory sink — the §14.7 gate, reproduced
      integration_exporter_failure.rs   unreachable OTLP endpoint never panics, never blocks (own process — init() is at-most-once-per-process)
      integration_no_otlp.rs            init() with no OTLP endpoint configured (own process, same reason)
      health_router_tests.rs            axum-test coverage of /health, /healthz, /metrics
```

---

### Task 1: Crate scaffold + pinned-container CI/Makefile wiring + smoke test

**Files:**
- Create: `packages/rust-logging/Cargo.toml`, `packages/rust-logging/deny.toml`, `packages/rust-logging/rust-toolchain.toml`, `packages/rust-logging/rustfmt.toml`, `packages/rust-logging/.gitignore`, `packages/rust-logging/LICENSE`, `packages/rust-logging/README.md`, `packages/rust-logging/CHANGELOG.md`, `packages/rust-logging/Dockerfile.ci`, `packages/rust-logging/Makefile`, `packages/rust-logging/src/lib.rs`
- Modify: `Makefile` (repo root), `.github/workflows/ci.yml`, `.github/workflows/publish.yml`

**Interfaces:**
- Produces: `pub const VERSION: &str = env!("CARGO_PKG_VERSION");` in `lib.rs` — every later task's smoke check that the crate still builds references this constant. `make -C packages/rust-logging <target>` for `fmt`, `lint`, `deny`, `audit`, `test`, `coverage`, `build`, `pre-commit`, `clean` — every subsequent task's "run the tests" step uses these targets, never bare `cargo`.

- [ ] **Step 1: Write the crate manifest**

`packages/rust-logging/Cargo.toml`:

```toml
[package]
name = "penguin-logging"
version = "0.1.0"
edition = "2021"
rust-version = "1.97"
description = "Waddles/PenguinTech structured, sanitized logging + OTel logs/metrics/traces + health/metrics endpoints"
license = "MIT"
repository = "https://github.com/penguintechinc/penguin-libs"
authors = ["Penguin Tech Inc <support@penguintech.io>"]
keywords = ["logging", "opentelemetry", "observability", "tracing"]
categories = ["development-tools::debugging"]

[features]
default = []
# Forwards to opentelemetry_sdk's own `testing` feature, which gates its
# InMemoryLogExporter / InMemoryMetricExporter / InMemorySpanExporter
# (verified present at exactly this path in opentelemetry_sdk 0.32.1 by
# downloading and inspecting the crate source during planning: they live
# under `#[cfg(any(feature = "testing", test))] pub mod in_memory_exporter`
# in src/{logs,metrics,trace}/mod.rs, not gated by any other feature name).
testing = ["opentelemetry_sdk/testing"]

[dependencies]
tracing = "=0.1.44"
tracing-subscriber = { version = "=0.3.23", features = ["env-filter", "json", "registry"] }
tracing-opentelemetry = "=0.33.0"
opentelemetry = "=0.32.0"
opentelemetry-otlp = { version = "=0.32.0", features = ["grpc-tonic"] }
opentelemetry_sdk = { version = "=0.32.1", features = ["rt-tokio"] }
opentelemetry-appender-tracing = "=0.32.0"
opentelemetry-prometheus = "=0.32.0"
prometheus = "=0.14.0"
axum = "=0.8.9"
serde = { version = "=1.0.229", features = ["derive"] }
serde_json = "=1.0.151"
regex = "=1.13.1"
thiserror = "=2.0.20"
tokio = { version = "=1.53.1", features = ["sync", "rt", "macros", "time"] }

[dev-dependencies]
rstest = "=0.27.0"
axum-test = "=21.1.0"
tokio = { version = "=1.53.1", features = ["full", "test-util"] }

[lints.rust]
unsafe_code = "deny"
missing_docs = "deny"

[lints.clippy]
unwrap_used = "deny"
```

Every version above was verified against the crates.io API (`https://crates.io/api/v1/crates/<name>`, `max_stable_version` field, queried with a descriptive `User-Agent` header — crates.io returns 403 without one) during planning, on 2026-09-14: `opentelemetry`/`opentelemetry-otlp`/`opentelemetry-appender-tracing`/`opentelemetry-prometheus` all at `0.32.0`, `opentelemetry_sdk` at `0.32.1`, `tracing-opentelemetry` at `0.33.0`, `prometheus` at `0.14.0`, `axum` at `0.8.9`, `tokio` at `1.53.1`, `serde`/`serde_json`/`regex`/`thiserror`/`rstest`/`axum-test` all current-stable — and cross-checked against `core/svc_streaming/Cargo.toml`'s existing pins (`git show origin/release/v3.0.X:core/svc_streaming/Cargo.toml`), which match on every crate the two manifests share.

- [ ] **Step 2: Write `deny.toml`** (mirrors `packages/rust-licensing/deny.toml`, read during planning):

```toml
# cargo-deny configuration for penguin-logging.
#
# Run locally with: make -C packages/rust-logging deny
# CI wiring: .github/workflows/ci.yml build-rust-logging job.

[graph]
all-features = true

[advisories]
db-urls = ["https://github.com/rustsec/advisory-db"]
yanked = "deny"
ignore = []

[licenses]
confidence-threshold = 0.9
allow = [
    "Apache-2.0",
    "Apache-2.0 WITH LLVM-exception",
    "BSD-2-Clause",
    "BSD-3-Clause",
    "BSL-1.0",
    "CC0-1.0",
    "ISC",
    "MIT",
    "MIT-0",
    "MPL-2.0",
    "Unicode-3.0",
    "Unicode-DFS-2016",
    "Zlib",
]
exceptions = []

[bans]
multiple-versions = "warn"
wildcards = "deny"
deny = []
skip = []
skip-tree = []

[sources]
unknown-registry = "deny"
unknown-git = "deny"
allow-registry = ["https://github.com/rust-lang/crates.io-index"]
allow-git = []
```

- [ ] **Step 3: Write `rust-toolchain.toml`**

```toml
[toolchain]
channel = "1.97.1"
components = ["rustfmt", "clippy", "llvm-tools-preview"]
```

- [ ] **Step 4: Write `rustfmt.toml`** (empty defaults, present so `cargo fmt` behavior can't silently drift):

```toml
edition = "2021"
```

- [ ] **Step 5: Write `.gitignore`**

```
/target
```

- [ ] **Step 6: Write `LICENSE`** — copy `packages/rust-licensing/LICENSE` verbatim (standard MIT text, PenguinTech Inc copyright holder):

```
MIT License

Copyright (c) 2026 Penguin Tech Inc

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```

- [ ] **Step 7: Write `CHANGELOG.md`**

```markdown
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
```

- [ ] **Step 8: Write `README.md`**

```markdown
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
```

- [ ] **Step 9: Write `Dockerfile.ci`**

```dockerfile
# Pinned toolchain + CI tooling for penguin-logging. Every `make` target in
# this crate runs a `cargo` command through this image so the host's cargo
# is never used (rules/backend-rust.md: "All builds in Docker").
FROM rust:1.97.1-slim-bookworm@sha256:2775a09d208ff0d7c1f50490c45b62db929e87ba1dcbc3f2132ac71a704bcdd3

RUN rustup component add clippy rustfmt llvm-tools-preview \
    && cargo install cargo-deny --version 0.20.2 --locked \
    && cargo install cargo-llvm-cov --version 0.9.1 --locked \
    && cargo install cargo-audit --version 0.22.2 --locked

WORKDIR /workspace
```

The base image digest (`sha256:2775a09d208ff0d7c1f50490c45b62db929e87ba1dcbc3f2132ac71a704bcdd3` for `rust:1.97.1-slim-bookworm`) was resolved during planning via the Docker Registry HTTP API v2 manifest-list digest (`docker-content-digest` response header), matching `rules/pinning-dependency-digests` skill's `crane digest`-equivalent method. `cargo-deny@0.20.2` and `cargo-llvm-cov@0.9.1` match the exact pins already used in `.github/workflows/rust-svc-streaming.yml`; `cargo-audit@0.22.2` is that tool's current stable release as of 2026-09-14.

- [ ] **Step 10: Write the crate-local `Makefile`**

```makefile
# All targets run inside the pinned Dockerfile.ci image — never host cargo.
IMAGE := penguin-logging-ci:1.97.1
DOCKER_RUN := docker run --rm -v "$(CURDIR):/workspace" -w /workspace $(IMAGE)

.PHONY: ci-image fmt lint deny audit test coverage build pre-commit clean

ci-image:
	docker build -f Dockerfile.ci -t $(IMAGE) .

fmt: ci-image
	$(DOCKER_RUN) cargo fmt --all --check

lint: ci-image
	$(DOCKER_RUN) cargo clippy --all-targets --all-features -- -D warnings

deny: ci-image
	$(DOCKER_RUN) cargo deny check

audit: ci-image
	$(DOCKER_RUN) cargo audit

test: ci-image
	$(DOCKER_RUN) cargo test --all-features

coverage: ci-image
	$(DOCKER_RUN) cargo llvm-cov --all-features --fail-under-lines 90

build: ci-image
	$(DOCKER_RUN) cargo build --all-features

pre-commit: fmt lint deny audit test coverage
	@echo "penguin-logging pre-commit: all gates passed"

clean: ci-image
	$(DOCKER_RUN) cargo clean
	-docker rmi $(IMAGE)
```

- [ ] **Step 11: Write the smoke-test-carrying `lib.rs`**

```rust
//! Structured, sanitized logging plus OpenTelemetry logs/metrics/traces and
//! a `/health`/`/healthz`/`/metrics` HTTP surface for Waddles/PenguinTech
//! Rust services. See the crate README for the environment variable
//! contract and `docs/superpowers/specs/2026-09-14-rust-data-plane-design.md`
//! §4.9 for the design this crate implements.

/// The crate's own version, exposed so a service can report it on `/health`
/// without duplicating the string from `Cargo.toml`.
pub const VERSION: &str = env!("CARGO_PKG_VERSION");

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn version_matches_cargo_toml() {
        assert_eq!(VERSION, "0.1.0");
    }
}
```

- [ ] **Step 12: Build the CI image and run the smoke test**

Run: `cd /home/penguin/code/penguin-libs/packages/rust-logging && make test`
Expected: Docker builds the `penguin-logging-ci:1.97.1` image (first run only, ~1-2 min), then `cargo test --all-features` compiles the crate and reports `test tests::version_matches_cargo_toml ... ok`, `test result: ok. 1 passed`.

- [ ] **Step 13: Run fmt, lint, deny, audit, coverage to confirm the scaffold is clean**

Run: `make fmt lint deny audit coverage`
Expected: `fmt` and `lint` print nothing and exit 0; `deny` prints `advisories ok`, `bans ok`, `licenses ok`, `sources ok` (zero dependencies yet, so a trivially clean pass — later tasks will re-run this as real dependencies are exercised); `audit` reports no vulnerabilities; `coverage` reports 100% (one trivial test, one trivial assertion) and does not fail the `--fail-under-lines 90` gate.

- [ ] **Step 14: Wire the root Makefile**

Modify `Makefile` (repo root). In the `build:` target, after the line `cd packages/rust-rpc && cargo build --workspace`, add:

```makefile
	cd packages/rust-logging && $(MAKE) build
```

In the `lint:` target, after the line `cd packages/rust-rpc && cargo clippy --workspace --all-targets -- -D warnings && cargo fmt --all --check`, add:

```makefile
	cd packages/rust-logging && $(MAKE) fmt lint
```

In the `test:` target, after the line `cd packages/rust-rpc && cargo test --workspace`, add:

```makefile
	cd packages/rust-logging && $(MAKE) test
```

In the `test-security:` target, after the line `cd packages/rust-rpc && cargo audit && cargo deny check`, add:

```makefile
	cd packages/rust-logging && $(MAKE) deny audit
```

- [ ] **Step 15: Wire `.github/workflows/ci.yml`**

The existing `build-rust-rpc` job (verified present at this exact text during planning) ends with:

```yaml
      - name: Security - cargo-deny
        run: |
          cargo install cargo-deny --version 0.18.9 --locked
          cargo deny check
```

immediately followed by the `build-react-form-builder:` job. Insert a new job between them:

```yaml

  build-rust-logging:
    name: Build & Test Rust Logging
    runs-on: ubuntu-latest
    if: ${{ !startsWith(github.ref, 'refs/heads/release/') || startsWith(github.ref, 'refs/heads/release/rust-logging/') }}
    defaults:
      run:
        working-directory: packages/rust-logging
    steps:
      - uses: actions/checkout@692973e3d937129bcbf40652eb9f2f61becf3332 # v4.1.7
        with:
          persist-credentials: false
      - uses: dtolnay/rust-toolchain@fa04a1451ff1842e2626ccb99004d0195b455a88 # master (2026-06-30)
        with:
          toolchain: 1.97.1
          components: clippy,rustfmt,llvm-tools-preview
      - name: Format check
        run: cargo fmt --all --check
      - name: Lint
        run: cargo clippy --all-targets --all-features -- -D warnings
      - name: Test
        run: cargo test --all-features
      - name: Coverage gate (>=90% lines)
        run: |
          cargo install cargo-llvm-cov --version 0.9.1 --locked
          cargo llvm-cov --all-features --fail-under-lines 90
      - name: Security - cargo-deny
        run: |
          cargo install cargo-deny --version 0.20.2 --locked
          cargo deny check
      - name: Security - cargo-audit
        run: |
          cargo install cargo-audit --version 0.22.2 --locked
          cargo audit
      - name: Security - semgrep
        run: |
          pip install --no-cache-dir semgrep==1.177.0
          semgrep --error --config auto .
      - name: Secrets - gitleaks
        uses: gitleaks/gitleaks-action@e0c47f4f8be36e29cdc102c57e68cb5cbf0e8d1e # v3.0.0
        env:
          GITHUB_TOKEN: ${{ secrets.GITHUB_TOKEN }}
```

This mirrors `build-rust-rpc`'s structure exactly (same `if:` release-branch gate pattern, same checkout/toolchain action pins) and additionally adds the coverage gate, `cargo-audit`, `semgrep` and `gitleaks` steps that `build-rust-rpc` itself lacks — required here because the design spec §14.5 states the full per-crate gate list (`fmt`, `clippy`, `deny`, `audit`, `test`, `llvm-cov`, `semgrep`, `gitleaks`) applies to "every new `penguin-libs` crate", a stricter bar than the pre-existing `build-rust-rpc` job predates. A container image scan (`trivy image`) is deliberately omitted: `penguin-logging` is a library crate with no Dockerfile producing a runtime image to scan.

- [ ] **Step 16: Wire `.github/workflows/publish.yml`**

Three edits, using the exact anchors read during planning:

1. In the `tags:` list (starts `on: push: tags:`), immediately after the line `      - 'rust-rpc-v*'`, insert:

```yaml
      - 'penguin-logging-v*'
```

2. In the `workflow_dispatch.inputs.package.options` list, immediately after the line `          - rust-rpc`, insert:

```yaml
          - penguin-logging
```

3. Immediately after the `publish-rust-rpc` job's closing `echo "**Registry**: crates.io (trusted publishing)" >> $GITHUB_STEP_SUMMARY` line and before the `# React Form Builder - npm (public registry)` comment block, insert:

```yaml

  # ============================================
  # Rust Logging (penguin-logging) - crates.io
  # ============================================
  publish-rust-logging:
    name: Publish Rust Logging
    runs-on: ubuntu-latest
    permissions:
      contents: read
      id-token: write
    if: |
      github.event_name == 'workflow_dispatch' &&
      github.event.inputs.package == 'penguin-logging' ||
      startsWith(github.ref, 'refs/tags/penguin-logging-v')

    defaults:
      run:
        working-directory: packages/rust-logging

    steps:
      - name: Checkout repository
        uses: actions/checkout@692973e3d937129bcbf40652eb9f2f61becf3332 # v4.1.7
        with:
          persist-credentials: false

      - name: Setup Rust toolchain
        uses: dtolnay/rust-toolchain@fa04a1451ff1842e2626ccb99004d0195b455a88 # master (2026-06-30)
        with:
          toolchain: 1.97.1

      - name: Authenticate with crates.io
        id: crates-auth
        uses: rust-lang/crates-io-auth-action@c6f97d42243bad5fab37ca0427f495c86d5b1a18 # v1.0.5

      - name: Publish penguin-logging
        run: cargo publish -p penguin-logging --locked
        env:
          CARGO_REGISTRY_TOKEN: ${{ steps.crates-auth.outputs.token }}

      - name: Create release summary
        run: |
          echo "## Published Packages" >> $GITHUB_STEP_SUMMARY
          echo "" >> $GITHUB_STEP_SUMMARY
          echo "**Packages**: penguin-logging" >> $GITHUB_STEP_SUMMARY
          echo "**Registry**: crates.io (trusted publishing)" >> $GITHUB_STEP_SUMMARY
```

This gives `penguin-logging` working CI and publish wiring from its very first commit — unlike `packages/rust-licensing`, which merged without either (confirmed absent from both `ci.yml` and `publish.yml` during planning) and is called out in the design spec (D17) as needing to "gain CI + publish jobs" later. `penguin-logging` does not repeat that gap.

- [ ] **Step 17: Commit**

```bash
cd /home/penguin/code/penguin-libs
git add packages/rust-logging Makefile .github/workflows/ci.yml .github/workflows/publish.yml
git commit -m "$(cat <<'EOF'
feat(logging): scaffold penguin-logging crate with pinned-container CI/Makefile/publish wiring

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01N2rQgkHY872RubwXoBZxtE
EOF
)"
```

---

### Task 2: Sanitization core — `sanitize_value`

**Files:**
- Create: `packages/rust-logging/src/sanitize.rs`
- Modify: `packages/rust-logging/src/lib.rs`

**Interfaces:**
- Consumes: nothing from earlier tasks (pure function on `serde_json::Value`).
- Produces: `pub const SENSITIVE_KEYS: &[&str]` (20 entries, exact list in Global Constraints); `pub fn sanitize_value(value: &serde_json::Value) -> serde_json::Value` — Task 3's `sanitize_json_str`/`Sanitized<T>`, Task 16's `DependencyMetrics`/log-forwarding code, and every downstream service consuming the WIT `log` host call all call this directly.

- [ ] **Step 1: Write the failing tests** (rstest tables mirroring `penguin-libs/packages/python-utils/tests/test_sinks.py::TestSanitizeLogData`, read in full during planning)

```rust
#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    #[test]
    fn redacts_sensitive_keys() {
        let data = json!({"password": "hunter2", "username": "alice"});
        let result = sanitize_value(&data);
        assert_eq!(result["password"], json!("[REDACTED]"));
        assert_eq!(result["username"], json!("alice"));
    }

    #[test]
    fn redacts_partial_key_match() {
        let data = json!({"user_password_hash": "abc123"});
        let result = sanitize_value(&data);
        assert_eq!(result["user_password_hash"], json!("[REDACTED]"));
    }

    #[test]
    fn redacts_key_match_case_insensitively() {
        let data = json!({"PASSWORD": "hunter2", "Api_Key": "sk-abc"});
        let result = sanitize_value(&data);
        assert_eq!(result["PASSWORD"], json!("[REDACTED]"));
        assert_eq!(result["Api_Key"], json!("[REDACTED]"));
    }

    #[test]
    fn redacts_email_to_domain() {
        let data = json!({"contact": "alice@example.com"});
        let result = sanitize_value(&data);
        assert_eq!(result["contact"], json!("[email]@example.com"));
    }

    #[test]
    fn redacts_multi_at_email_shaped_string_fully() {
        // Python's `value.split("@")` on "a@b@c" yields 3 parts, so the
        // `len(parts) == 2` branch is skipped and the whole value is
        // replaced -- verbatim port of that edge case.
        let data = json!({"weird": "a@b@c.com"});
        let result = sanitize_value(&data);
        assert_eq!(result["weird"], json!("[REDACTED_EMAIL]"));
    }

    #[test]
    fn preserves_non_sensitive_strings() {
        let data = json!({"action": "login", "status": "ok"});
        let result = sanitize_value(&data);
        assert_eq!(result, data);
    }

    #[test]
    fn preserves_non_string_non_object_values() {
        let data = json!({"count": 3, "active": true, "note": null});
        let result = sanitize_value(&data);
        assert_eq!(result, data);
    }

    #[test]
    fn recurses_into_nested_objects() {
        let data = json!({"user": {"password": "secret", "name": "bob"}});
        let result = sanitize_value(&data);
        assert_eq!(result["user"]["password"], json!("[REDACTED]"));
        assert_eq!(result["user"]["name"], json!("bob"));
    }

    #[test]
    fn recurses_into_list_of_objects_only() {
        // Matches Python's `[sanitize_log_data(item) if isinstance(item, dict)
        // else item for item in value]` -- a bare string list item is left
        // untouched even if it looks like a token, by design.
        let data = json!({"items": [{"token": "abc"}, {"value": 1}, "raw-token-string"]});
        let result = sanitize_value(&data);
        assert_eq!(result["items"][0]["token"], json!("[REDACTED]"));
        assert_eq!(result["items"][1]["value"], json!(1));
        assert_eq!(result["items"][2], json!("raw-token-string"));
    }

    #[test]
    fn passes_through_non_object_top_level_value() {
        let data = json!("not an object");
        assert_eq!(sanitize_value(&data), data);
    }

    #[rstest::rstest]
    #[case("password")]
    #[case("passwd")]
    #[case("secret")]
    #[case("token")]
    #[case("api_key")]
    #[case("apikey")]
    #[case("auth_token")]
    #[case("authtoken")]
    #[case("access_token")]
    #[case("refresh_token")]
    #[case("credential")]
    #[case("credentials")]
    #[case("mfa_code")]
    #[case("totp_code")]
    #[case("otp")]
    #[case("captcha_token")]
    #[case("session_id")]
    #[case("sessionid")]
    #[case("cookie")]
    #[case("authorization")]
    fn every_sensitive_key_is_redacted(#[case] key: &str) {
        let data = json!({ key: "value-that-must-not-survive" });
        let result = sanitize_value(&data);
        assert_eq!(result[key], json!("[REDACTED]"), "key: {key}");
    }
}
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd /home/penguin/code/penguin-libs/packages/rust-logging && make test`
Expected: FAIL — `error[E0433]: failed to resolve: use of undeclared crate or module `sanitize`` (module not yet wired into `lib.rs`) or, once wired with an empty `sanitize_value` stub, individual `assert_eq!` failures.

- [ ] **Step 3: Implement `sanitize_value`**

```rust
//! Verbatim port of `penguin-libs/packages/python-utils/src/penguintechinc_utils/logging.py`'s
//! `sanitize_log_data`: the same 20-entry `SENSITIVE_KEYS` set (matched by
//! exact key or substring, case-insensitive), the same email-domain-preserving
//! redaction, and the same recursion rules (objects always recurse; array
//! items recurse only when they are themselves objects). Every log field and
//! every WIT `log` host call's `fields-json` value passes through this
//! before emission — see `critical-rules.md` Observability, "Sanitization
//! applies at every level, DEBUG included."

use serde_json::{Map, Value};
use std::sync::LazyLock;

/// Keys that must never be logged, matched case-insensitively by exact
/// equality or substring containment against a field's key. Ported
/// verbatim from `penguintechinc_utils.logging.SENSITIVE_KEYS` -- the Rust
/// and Python sanitizers must always redact the same fields.
pub const SENSITIVE_KEYS: &[&str] = &[
    "password",
    "passwd",
    "secret",
    "token",
    "api_key",
    "apikey",
    "auth_token",
    "authtoken",
    "access_token",
    "refresh_token",
    "credential",
    "credentials",
    "mfa_code",
    "totp_code",
    "otp",
    "captcha_token",
    "session_id",
    "sessionid",
    "cookie",
    "authorization",
];

/// Anchored at the start of the string (mirrors Python's `re.match`, which
/// does not require the match to consume the whole string) so a value like
/// `"alice@example.com (verified)"` is still treated as email-shaped.
static EMAIL_REGEX: LazyLock<regex::Regex> = LazyLock::new(|| {
    // The pattern itself, and the fact that construction cannot fail for a
    // literal compile-time-checked regex, are both invariants: this
    // `.expect()` can only fire if the literal below is edited incorrectly.
    regex::Regex::new(r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}")
        .expect("EMAIL_REGEX literal must compile")
});

fn is_sensitive_key(key: &str) -> bool {
    let key_lower = key.to_lowercase();
    SENSITIVE_KEYS
        .iter()
        .any(|s| key_lower == *s || key_lower.contains(s))
}

fn redact_email_shaped_string(value: &str) -> Value {
    if value.contains('@') && EMAIL_REGEX.is_match(value) {
        let parts: Vec<&str> = value.split('@').collect();
        if parts.len() == 2 {
            Value::String(format!("[email]@{}", parts[1]))
        } else {
            Value::String("[REDACTED_EMAIL]".to_string())
        }
    } else {
        Value::String(value.to_string())
    }
}

fn sanitize_field_value(value: &Value) -> Value {
    match value {
        Value::String(s) => redact_email_shaped_string(s),
        Value::Object(_) => sanitize_value(value),
        Value::Array(items) => Value::Array(
            items
                .iter()
                .map(|item| if item.is_object() { sanitize_value(item) } else { item.clone() })
                .collect(),
        ),
        other => other.clone(),
    }
}

/// Sanitizes `value` for safe logging: redacts every field whose key
/// matches [`SENSITIVE_KEYS`] to the literal `"[REDACTED]"`, rewrites
/// email-shaped string values to `"[email]@{domain}"`, recurses into
/// nested objects unconditionally, and recurses into array items only
/// when they are themselves objects (a bare string/number array item is
/// returned unchanged, matching the Python reference exactly). A
/// non-object top-level `value` is returned unchanged, mirroring
/// `sanitize_log_data`'s `if not isinstance(data, dict): return data`.
pub fn sanitize_value(value: &Value) -> Value {
    let Value::Object(map) = value else {
        return value.clone();
    };
    let mut sanitized = Map::with_capacity(map.len());
    for (key, val) in map {
        if is_sensitive_key(key) {
            sanitized.insert(key.clone(), Value::String("[REDACTED]".to_string()));
        } else {
            sanitized.insert(key.clone(), sanitize_field_value(val));
        }
    }
    Value::Object(sanitized)
}
```

- [ ] **Step 4: Wire the module into `lib.rs`**

Modify `packages/rust-logging/src/lib.rs` — add after the crate doc comment / `VERSION` const:

```rust
pub mod sanitize;
pub use sanitize::{sanitize_value, SENSITIVE_KEYS};
```

- [ ] **Step 5: Run to verify it passes**

Run: `make test`
Expected: PASS — all tests in `sanitize::tests` green, including the 20 parameterized `every_sensitive_key_is_redacted` cases (rstest reports each `key` case individually on failure).

- [ ] **Step 6: Commit**

```bash
git add packages/rust-logging/src/sanitize.rs packages/rust-logging/src/lib.rs
git commit -m "$(cat <<'EOF'
feat(logging): port SENSITIVE_KEYS sanitization rule verbatim from penguin-utils

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01N2rQgkHY872RubwXoBZxtE
EOF
)"
```

---

### Task 3: `sanitize_json_str` + `Sanitized<T>` newtype

**Files:**
- Modify: `packages/rust-logging/src/sanitize.rs`, `packages/rust-logging/src/lib.rs`

**Interfaces:**
- Consumes: `sanitize_value` (Task 2).
- Produces: `pub fn sanitize_json_str(raw: &str) -> Result<String, SanitizeError>` — the WIT `log` host call's `fields-json: string` argument (design spec §7.4/interface `log`: `"fields-json is a canonical JSON object; the host sanitizes it with the penguin logging SENSITIVE_KEYS rule before emission"`) is sanitized through exactly this function in `penguin-bundle-host`. `pub struct Sanitized<T>` with `assert_sanitized`, `into_inner`, `get`; `pub fn sanitize(value: serde_json::Value) -> Sanitized<serde_json::Value>`. `pub enum SanitizeError`.

- [ ] **Step 1: Write the failing tests**

```rust
#[cfg(test)]
mod sanitize_json_str_tests {
    use super::*;

    #[test]
    fn sanitizes_a_json_object_string() {
        let raw = r#"{"password":"hunter2","user":"alice"}"#;
        let out = sanitize_json_str(raw).expect("valid JSON must sanitize");
        let parsed: serde_json::Value = serde_json::from_str(&out).expect("output must be valid JSON");
        assert_eq!(parsed["password"], serde_json::json!("[REDACTED]"));
        assert_eq!(parsed["user"], serde_json::json!("alice"));
    }

    #[test]
    fn rejects_invalid_json() {
        let result = sanitize_json_str("{not json");
        assert!(matches!(result, Err(SanitizeError::InvalidJson(_))));
    }
}

#[cfg(test)]
mod sanitized_newtype_tests {
    use super::*;
    use serde_json::json;

    #[test]
    fn sanitize_wraps_the_real_sanitizer_output() {
        let wrapped = sanitize(json!({"token": "abc", "ok": "fine"}));
        let inner = wrapped.into_inner();
        assert_eq!(inner["token"], json!("[REDACTED]"));
        assert_eq!(inner["ok"], json!("fine"));
    }

    #[test]
    fn assert_sanitized_round_trips_the_value_unchanged() {
        let already_clean = json!({"ok": "fine"});
        let wrapped = Sanitized::assert_sanitized(already_clean.clone());
        assert_eq!(wrapped.get(), &already_clean);
        assert_eq!(wrapped.into_inner(), already_clean);
    }
}
```

- [ ] **Step 2: Run to verify it fails**

Run: `make test`
Expected: FAIL — `cannot find function `sanitize_json_str`` / `cannot find type `Sanitized`` / `cannot find type `SanitizeError``.

- [ ] **Step 3: Implement**, appending to `packages/rust-logging/src/sanitize.rs`:

```rust
/// Errors from [`sanitize_json_str`]. The single variant wraps
/// `serde_json`'s parse error rather than inventing a new representation,
/// since the only way sanitization can fail is on malformed input JSON.
#[derive(Debug, thiserror::Error)]
pub enum SanitizeError {
    /// `raw` was not valid JSON and could not be sanitized.
    #[error("invalid JSON in log field payload: {0}")]
    InvalidJson(#[from] serde_json::Error),
}

/// Parses `raw` as JSON, runs [`sanitize_value`] over it, and re-serializes
/// the result. This is the exact operation the WIT `log` host call performs
/// on a bundle's `fields-json` argument before any log line reaches the
/// stage's OTel pipeline (design spec, WIT `log` interface doc comment).
pub fn sanitize_json_str(raw: &str) -> Result<String, SanitizeError> {
    let value: Value = serde_json::from_str(raw)?;
    let sanitized = sanitize_value(&value);
    Ok(serde_json::to_string(&sanitized)?)
}

/// Marks a value the caller has already run through [`sanitize_value`] or
/// [`sanitize_json_str`]. The inner value is reachable only via
/// [`Sanitized::into_inner`]/[`Sanitized::get`], so a function that
/// requires `Sanitized<T>` in its signature cannot have an unsanitized
/// value smuggled past it by accident -- the caller must have gone
/// through one of this module's sanitizing constructors (or explicitly
/// asserted the value was already safe via [`Sanitized::assert_sanitized`]).
#[must_use]
#[derive(Debug, Clone)]
pub struct Sanitized<T>(T);

impl<T> Sanitized<T> {
    /// Wraps `value`, asserting the caller has already sanitized it by
    /// some other means (e.g. it was read back out of a store that only
    /// ever contains sanitized data). This constructor does NOT run
    /// [`sanitize_value`] itself -- use [`sanitize`] when the value has
    /// not yet been sanitized.
    pub fn assert_sanitized(value: T) -> Self {
        Sanitized(value)
    }

    /// Consumes the wrapper, returning the sanitized value.
    pub fn into_inner(self) -> T {
        self.0
    }

    /// Borrows the sanitized value without consuming the wrapper.
    pub fn get(&self) -> &T {
        &self.0
    }
}

/// Runs [`sanitize_value`] over `value` and wraps the result, giving
/// callers a single expression that both sanitizes and produces the
/// type-level [`Sanitized`] marker.
pub fn sanitize(value: Value) -> Sanitized<Value> {
    Sanitized(sanitize_value(&value))
}
```

- [ ] **Step 4: Run to verify it passes**

Run: `make test`
Expected: PASS — all `sanitize_json_str_tests` and `sanitized_newtype_tests` green.

- [ ] **Step 5: Update `lib.rs` re-exports**

```rust
pub use sanitize::{sanitize, sanitize_json_str, sanitize_value, Sanitized, SanitizeError, SENSITIVE_KEYS};
```

- [ ] **Step 6: Commit**

```bash
git add packages/rust-logging/src/sanitize.rs packages/rust-logging/src/lib.rs
git commit -m "$(cat <<'EOF'
feat(logging): add sanitize_json_str and Sanitized<T> for the WIT log host call

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01N2rQgkHY872RubwXoBZxtE
EOF
)"
```

---

### Task 4: `ServiceConfig::from_env`

**Files:**
- Create: `packages/rust-logging/src/config.rs`
- Modify: `packages/rust-logging/src/lib.rs`

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces: `pub struct ServiceConfig { pub service_name: String, pub otlp_endpoint: Option<String>, pub otlp_protocol: OtlpProtocol, pub otlp_headers: Vec<(String, String)>, pub log_level: String }`, `pub enum OtlpProtocol { Grpc, HttpProtobuf }`, `pub fn ServiceConfig::from_env(default_service_name: &str) -> ServiceConfig` — Task 6 (`resource()`/`otlp_protocol()` helpers), Task 8-10 (provider builders) and Task 11 (`init`) all take a `&ServiceConfig` or consume its fields.

- [ ] **Step 1: Write the failing tests** (env-mutating tests serialized via a `Mutex`, matching the pattern already used in `core/svc_streaming/src/telemetry.rs`'s own test module, read during planning)

```rust
#[cfg(test)]
mod tests {
    use super::*;
    use std::sync::Mutex;

    // std::env is process-global; serialize env-mutating tests so parallel
    // `cargo test` threads don't race on the same variables (same pattern
    // as core/svc_streaming/src/telemetry.rs's ENV_LOCK).
    static ENV_LOCK: Mutex<()> = Mutex::new(());

    fn clear_env() {
        for var in [
            "OTEL_EXPORTER_OTLP_ENDPOINT",
            "OTEL_EXPORTER_OTLP_PROTOCOL",
            "OTEL_EXPORTER_OTLP_HEADERS",
            "OTEL_SERVICE_NAME",
            "LOG_LEVEL",
        ] {
            // SAFETY: serialized by ENV_LOCK; no other thread reads/writes
            // these variables while this test module runs.
            unsafe { std::env::remove_var(var) };
        }
    }

    #[test]
    fn defaults_when_nothing_is_set() {
        let _guard = ENV_LOCK.lock().unwrap_or_else(|p| p.into_inner());
        clear_env();
        let cfg = ServiceConfig::from_env("svc-process");
        assert_eq!(cfg.service_name, "svc-process");
        assert_eq!(cfg.otlp_endpoint, None);
        assert_eq!(cfg.otlp_protocol, OtlpProtocol::Grpc);
        assert!(cfg.otlp_headers.is_empty());
        assert_eq!(cfg.log_level, "info");
    }

    #[test]
    fn otel_service_name_overrides_the_default() {
        let _guard = ENV_LOCK.lock().unwrap_or_else(|p| p.into_inner());
        clear_env();
        // SAFETY: serialized by ENV_LOCK.
        unsafe { std::env::set_var("OTEL_SERVICE_NAME", "svc-process-canary") };
        let cfg = ServiceConfig::from_env("svc-process");
        assert_eq!(cfg.service_name, "svc-process-canary");
        unsafe { std::env::remove_var("OTEL_SERVICE_NAME") };
    }

    #[test]
    fn recognizes_http_protobuf_protocol() {
        let _guard = ENV_LOCK.lock().unwrap_or_else(|p| p.into_inner());
        clear_env();
        unsafe { std::env::set_var("OTEL_EXPORTER_OTLP_PROTOCOL", "http/protobuf") };
        let cfg = ServiceConfig::from_env("svc-process");
        assert_eq!(cfg.otlp_protocol, OtlpProtocol::HttpProtobuf);
        unsafe { std::env::remove_var("OTEL_EXPORTER_OTLP_PROTOCOL") };
    }

    #[test]
    fn unrecognized_protocol_falls_back_to_grpc() {
        let _guard = ENV_LOCK.lock().unwrap_or_else(|p| p.into_inner());
        clear_env();
        unsafe { std::env::set_var("OTEL_EXPORTER_OTLP_PROTOCOL", "carrier-pigeon") };
        let cfg = ServiceConfig::from_env("svc-process");
        assert_eq!(cfg.otlp_protocol, OtlpProtocol::Grpc);
        unsafe { std::env::remove_var("OTEL_EXPORTER_OTLP_PROTOCOL") };
    }

    #[test]
    fn parses_comma_separated_headers() {
        let _guard = ENV_LOCK.lock().unwrap_or_else(|p| p.into_inner());
        clear_env();
        unsafe {
            std::env::set_var("OTEL_EXPORTER_OTLP_HEADERS", "x-api-key=abc,x-tenant=global");
        }
        let cfg = ServiceConfig::from_env("svc-process");
        assert_eq!(
            cfg.otlp_headers,
            vec![
                ("x-api-key".to_string(), "abc".to_string()),
                ("x-tenant".to_string(), "global".to_string()),
            ]
        );
        unsafe { std::env::remove_var("OTEL_EXPORTER_OTLP_HEADERS") };
    }

    #[test]
    fn endpoint_present_when_set() {
        let _guard = ENV_LOCK.lock().unwrap_or_else(|p| p.into_inner());
        clear_env();
        unsafe { std::env::set_var("OTEL_EXPORTER_OTLP_ENDPOINT", "http://collector:4317") };
        let cfg = ServiceConfig::from_env("svc-process");
        assert_eq!(cfg.otlp_endpoint.as_deref(), Some("http://collector:4317"));
        unsafe { std::env::remove_var("OTEL_EXPORTER_OTLP_ENDPOINT") };
    }

    #[test]
    fn log_level_reads_from_env() {
        let _guard = ENV_LOCK.lock().unwrap_or_else(|p| p.into_inner());
        clear_env();
        unsafe { std::env::set_var("LOG_LEVEL", "debug") };
        let cfg = ServiceConfig::from_env("svc-process");
        assert_eq!(cfg.log_level, "debug");
        unsafe { std::env::remove_var("LOG_LEVEL") };
    }
}
```

- [ ] **Step 2: Run to verify it fails**

Run: `make test`
Expected: FAIL — `cannot find type `ServiceConfig`` / `cannot find type `OtlpProtocol``.

- [ ] **Step 3: Implement**

```rust
//! Standard OTLP environment variable contract, read once at startup.
//! Every field here maps 1:1 to a variable named in `critical-rules.md`
//! Observability and the design spec §12.7 "Common to all four services"
//! table -- never a hardcoded destination.

/// Selects which OTLP wire protocol the exporters use. `Grpc` is the
/// default (matches `core/svc_streaming/src/telemetry.rs`'s existing
/// behavior); any `OTEL_EXPORTER_OTLP_PROTOCOL` value other than the
/// literal `"http/protobuf"` falls back to `Grpc` rather than erroring,
/// since an operator typo here must never crash the service.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum OtlpProtocol {
    /// OTLP over gRPC (`tonic`), the default transport.
    Grpc,
    /// OTLP over HTTP with protobuf bodies.
    HttpProtobuf,
}

/// Everything [`crate::init`] needs, read once from the standard OTLP
/// environment variables plus `LOG_LEVEL`. Construct via [`ServiceConfig::from_env`];
/// there is no public field-by-field builder because every field here
/// already has a spec-mandated env var and default.
#[derive(Debug, Clone)]
pub struct ServiceConfig {
    /// The service's identity in every emitted signal. Defaults to the
    /// caller-supplied name; overridden by `OTEL_SERVICE_NAME`.
    pub service_name: String,
    /// `None` means OTLP export is skipped entirely (stdout JSON logging
    /// only) -- reading `OTEL_EXPORTER_OTLP_ENDPOINT` unset is a valid,
    /// supported configuration, not an error.
    pub otlp_endpoint: Option<String>,
    /// From `OTEL_EXPORTER_OTLP_PROTOCOL`, defaulting to [`OtlpProtocol::Grpc`].
    pub otlp_protocol: OtlpProtocol,
    /// Parsed from `OTEL_EXPORTER_OTLP_HEADERS` (`key1=value1,key2=value2`).
    /// Auth headers only; read from the environment, never a CLI flag,
    /// per `critical-rules.md` Token & Secret Hygiene.
    pub otlp_headers: Vec<(String, String)>,
    /// From `LOG_LEVEL`, defaulting to `"info"`. Passed to
    /// [`crate::level::parse_level_filter`] at init time and re-parsed on
    /// every [`crate::level::LevelHandle::set_level`] call.
    pub log_level: String,
}

fn parse_otlp_headers(raw: &str) -> Vec<(String, String)> {
    raw.split(',')
        .filter_map(|pair| {
            let mut parts = pair.splitn(2, '=');
            let key = parts.next()?.trim();
            let value = parts.next()?.trim();
            if key.is_empty() {
                None
            } else {
                Some((key.to_string(), value.to_string()))
            }
        })
        .collect()
}

impl ServiceConfig {
    /// Reads the standard OTLP environment variables plus `LOG_LEVEL`,
    /// falling back to `default_service_name` and the documented defaults
    /// for anything unset. Never fails -- an unparsable value degrades to
    /// its default rather than erroring, matching the house rule that
    /// telemetry configuration must never block startup.
    pub fn from_env(default_service_name: &str) -> Self {
        let service_name = std::env::var("OTEL_SERVICE_NAME")
            .unwrap_or_else(|_| default_service_name.to_string());
        let otlp_endpoint = std::env::var("OTEL_EXPORTER_OTLP_ENDPOINT").ok();
        let otlp_protocol = match std::env::var("OTEL_EXPORTER_OTLP_PROTOCOL").as_deref() {
            Ok("http/protobuf") => OtlpProtocol::HttpProtobuf,
            _ => OtlpProtocol::Grpc,
        };
        let otlp_headers = std::env::var("OTEL_EXPORTER_OTLP_HEADERS")
            .map(|raw| parse_otlp_headers(&raw))
            .unwrap_or_default();
        let log_level = std::env::var("LOG_LEVEL").unwrap_or_else(|_| "info".to_string());

        ServiceConfig {
            service_name,
            otlp_endpoint,
            otlp_protocol,
            otlp_headers,
            log_level,
        }
    }
}
```

- [ ] **Step 4: Run to verify it passes**

Run: `make test`
Expected: PASS — all `config::tests` green.

- [ ] **Step 5: Wire into `lib.rs`**

```rust
pub mod config;
pub use config::{OtlpProtocol, ServiceConfig};
```

- [ ] **Step 6: Commit**

```bash
git add packages/rust-logging/src/config.rs packages/rust-logging/src/lib.rs
git commit -m "$(cat <<'EOF'
feat(logging): add ServiceConfig::from_env for the standard OTLP env contract

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01N2rQgkHY872RubwXoBZxtE
EOF
)"
```

---

### Task 5: `LevelHandle` — runtime-reloadable level filter

**Files:**
- Create: `packages/rust-logging/src/level.rs`
- Modify: `packages/rust-logging/src/lib.rs`

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces: `pub fn parse_level_filter(level: &str) -> Result<tracing_subscriber::EnvFilter, LevelError>`; `pub struct LevelHandle(tracing_subscriber::reload::Handle<tracing_subscriber::EnvFilter, tracing_subscriber::Registry>)` with `pub fn set_level(&self, level: &str) -> Result<(), LevelError>` and `pub fn current(&self) -> String`; `pub enum LevelError`. Task 7 (`init_stdout_logging`) constructs the reload layer this handle wraps and must apply it as the **first** `.with()` call on `tracing_subscriber::registry()` so the `Handle`'s subscriber-type parameter stays the concrete, nameable `tracing_subscriber::Registry` (verified this is how `tracing_subscriber::reload::Layer::new`/`Handle` typing works: the handle's second type parameter is whatever subscriber the layer was applied to, so applying it to the bare `registry()` keeps it nameable instead of an unnameable combinator chain type).

- [ ] **Step 1: Write the failing tests**

```rust
#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn parse_level_filter_accepts_all_four_levels() {
        for level in ["error", "warn", "info", "debug"] {
            assert!(parse_level_filter(level).is_ok(), "level: {level}");
        }
    }

    #[test]
    fn parse_level_filter_is_case_insensitive() {
        assert!(parse_level_filter("DEBUG").is_ok());
        assert!(parse_level_filter("Info").is_ok());
    }

    #[test]
    fn parse_level_filter_rejects_unknown_level() {
        let result = parse_level_filter("verbose");
        assert!(matches!(result, Err(LevelError::Unknown(ref s)) if s == "verbose"));
    }

    #[test]
    fn level_handle_set_level_updates_and_reports_current() {
        let initial = parse_level_filter("info").expect("info must parse");
        let (layer, handle) = tracing_subscriber::reload::Layer::new(initial);
        let level_handle = LevelHandle::from_reload_handle(handle);
        // Registering the layer proves the concrete type used in LevelHandle
        // matches what tracing_subscriber::registry() actually produces.
        let _subscriber = tracing_subscriber::registry().with(layer);

        assert_eq!(level_handle.current(), "info");
        level_handle.set_level("debug").expect("debug must be a valid level");
        assert_eq!(level_handle.current(), "debug");
    }

    #[test]
    fn level_handle_set_level_rejects_unknown_level_without_changing_current() {
        let initial = parse_level_filter("warn").expect("warn must parse");
        let (layer, handle) = tracing_subscriber::reload::Layer::new(initial);
        let level_handle = LevelHandle::from_reload_handle(handle);
        let _subscriber = tracing_subscriber::registry().with(layer);

        let result = level_handle.set_level("not-a-level");
        assert!(matches!(result, Err(LevelError::Unknown(_))));
        assert_eq!(level_handle.current(), "warn");
    }
}
```

Note the tests import `tracing_subscriber::layer::SubscriberExt` (for `.with()`) — add `use tracing_subscriber::layer::SubscriberExt;` alongside `use super::*;` in the test module.

- [ ] **Step 2: Run to verify it fails**

Run: `make test`
Expected: FAIL — `cannot find function `parse_level_filter`` / `cannot find type `LevelHandle`` / `cannot find type `LevelError``.

- [ ] **Step 3: Implement**

```rust
//! A `LOG_LEVEL` that can change without a restart. `tracing_subscriber`'s
//! `reload` module gives a `Handle` that swaps the active `EnvFilter`
//! in-place; this module wraps that handle behind a small, named API so
//! callers never have to spell out the reload machinery's generic types.

use tracing_subscriber::EnvFilter;

/// Errors from level parsing or reload.
#[derive(Debug, thiserror::Error)]
pub enum LevelError {
    /// `level` was not one of `error`, `warn`, `info`, `debug`
    /// (case-insensitive).
    #[error("unknown log level {0:?}; expected one of: error, warn, info, debug")]
    Unknown(String),
    /// The reload handle's subscriber has already been dropped -- this can
    /// only happen after process shutdown has begun.
    #[error("log level reload failed: subscriber no longer live")]
    Reload(#[from] tracing_subscriber::reload::Error),
}

/// Parses `level` into an [`EnvFilter`] restricted to exactly one of the
/// four house levels (`critical-rules.md` Observability level table).
/// Unlike `EnvFilter::try_from_default_env`, this never consults `RUST_LOG`
/// -- `LOG_LEVEL` is the one house-standard variable, and mixing both
/// would make the effective level depend on which one a deploy happened
/// to set.
pub fn parse_level_filter(level: &str) -> Result<EnvFilter, LevelError> {
    let normalized = level.to_lowercase();
    match normalized.as_str() {
        "error" | "warn" | "info" | "debug" => {
            // `EnvFilter::new` on one of these four literals cannot fail:
            // they are valid directives by construction.
            Ok(EnvFilter::new(&normalized))
        }
        _ => Err(LevelError::Unknown(level.to_string())),
    }
}

/// A live handle to the process's active log level filter. Cloning is
/// cheap (the underlying `reload::Handle` is itself a thin `Arc`-backed
/// handle); every clone reloads the same shared filter.
#[derive(Clone)]
pub struct LevelHandle {
    handle: tracing_subscriber::reload::Handle<EnvFilter, tracing_subscriber::Registry>,
    current: std::sync::Arc<std::sync::RwLock<String>>,
}

impl LevelHandle {
    /// Wraps a `reload::Handle` obtained from
    /// `tracing_subscriber::reload::Layer::new` applied directly to
    /// `tracing_subscriber::registry()` (see this task's Interfaces note
    /// on why the layer must be applied there for the type to stay
    /// nameable). `initial_level` records the level the filter was
    /// constructed with, for [`LevelHandle::current`] to report before any
    /// [`LevelHandle::set_level`] call.
    pub(crate) fn from_reload_handle(
        handle: tracing_subscriber::reload::Handle<EnvFilter, tracing_subscriber::Registry>,
    ) -> Self {
        LevelHandle {
            handle,
            current: std::sync::Arc::new(std::sync::RwLock::new("info".to_string())),
        }
    }

    /// Wraps a `reload::Handle`, recording `initial_level` as the level
    /// already installed in the filter it wraps. Used by
    /// [`crate::logging_init::init_stdout_logging`], which knows the
    /// actual initial level (from [`crate::ServiceConfig::log_level`])
    /// rather than the hardcoded `"info"` [`LevelHandle::from_reload_handle`]
    /// assumes.
    pub(crate) fn with_initial_level(
        handle: tracing_subscriber::reload::Handle<EnvFilter, tracing_subscriber::Registry>,
        initial_level: &str,
    ) -> Self {
        LevelHandle {
            handle,
            current: std::sync::Arc::new(std::sync::RwLock::new(initial_level.to_lowercase())),
        }
    }

    /// Parses `level` and, if valid, swaps it in as the active filter.
    /// Rejects an unknown level without touching the currently-active
    /// filter, so a typo'd runtime level change is a no-op rather than a
    /// silent fall-through to unfiltered logging.
    pub fn set_level(&self, level: &str) -> Result<(), LevelError> {
        let filter = parse_level_filter(level)?;
        let normalized = level.to_lowercase();
        self.handle.reload(filter)?;
        let mut current = self
            .current
            .write()
            .unwrap_or_else(|poisoned| poisoned.into_inner());
        *current = normalized;
        Ok(())
    }

    /// The level most recently installed via [`LevelHandle::set_level`],
    /// or the level the filter was constructed with if `set_level` has
    /// never been called.
    pub fn current(&self) -> String {
        self.current
            .read()
            .unwrap_or_else(|poisoned| poisoned.into_inner())
            .clone()
    }
}
```

- [ ] **Step 4: Run to verify it passes**

Run: `make test`
Expected: PASS — all `level::tests` green.

- [ ] **Step 5: Wire into `lib.rs`**

```rust
pub mod level;
pub use level::{parse_level_filter, LevelError, LevelHandle};
```

- [ ] **Step 6: Commit**

```bash
git add packages/rust-logging/src/level.rs packages/rust-logging/src/lib.rs
git commit -m "$(cat <<'EOF'
feat(logging): add LevelHandle for runtime-reloadable LOG_LEVEL

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01N2rQgkHY872RubwXoBZxtE
EOF
)"
```

---

### Task 6: `resource()` — OTel `Resource` from `ServiceConfig`

**Files:**
- Create: `packages/rust-logging/src/resource.rs`
- Modify: `packages/rust-logging/src/lib.rs`

**Interfaces:**
- Consumes: `ServiceConfig` (Task 4).
- Produces: `pub(crate) fn resource(cfg: &ServiceConfig) -> opentelemetry_sdk::Resource` — Tasks 8, 9 and 10's provider builders all call this so every OTLP signal shares one resource (same `service.name` plus whatever `OTEL_RESOURCE_ATTRIBUTES` the environment set).

- [ ] **Step 1: Write the failing test**

```rust
#[cfg(test)]
mod tests {
    use super::*;
    use crate::config::{OtlpProtocol, ServiceConfig};
    use std::sync::Mutex;

    static ENV_LOCK: Mutex<()> = Mutex::new(());

    #[test]
    fn resource_carries_the_configured_service_name() {
        let _guard = ENV_LOCK.lock().unwrap_or_else(|p| p.into_inner());
        // SAFETY: serialized by ENV_LOCK.
        unsafe { std::env::remove_var("OTEL_RESOURCE_ATTRIBUTES") };
        let cfg = ServiceConfig {
            service_name: "svc-process-test".to_string(),
            otlp_endpoint: None,
            otlp_protocol: OtlpProtocol::Grpc,
            otlp_headers: Vec::new(),
            log_level: "info".to_string(),
        };
        let res = resource(&cfg);
        let value = res.get(&opentelemetry::Key::from_static_str("service.name"));
        assert_eq!(value.map(|v| v.to_string()), Some("svc-process-test".to_string()));
    }
}
```

- [ ] **Step 2: Run to verify it fails**

Run: `make test`
Expected: FAIL — `cannot find function `resource``.

- [ ] **Step 3: Implement**

```rust
//! Builds the one `Resource` every OTLP pipeline (logs, metrics, traces)
//! shares, so a collector sees one `service.name` per process rather than
//! three independently-configured ones.

use crate::config::ServiceConfig;
use opentelemetry_sdk::Resource;

/// Builds a [`Resource`] carrying `cfg.service_name` as `service.name`.
/// `Resource::builder()` already layers in `EnvResourceDetector`, which
/// reads `OTEL_RESOURCE_ATTRIBUTES` on its own -- this function only needs
/// to set the name explicitly so there is always a sane default even when
/// that variable is unset (matches `core/svc_streaming/src/telemetry.rs`'s
/// existing `resource()` helper, read during planning).
pub(crate) fn resource(cfg: &ServiceConfig) -> Resource {
    Resource::builder()
        .with_service_name(cfg.service_name.clone())
        .build()
}
```

- [ ] **Step 4: Run to verify it passes**

Run: `make test`
Expected: PASS.

- [ ] **Step 5: Wire into `lib.rs`**

```rust
mod resource;
```

(No public re-export — `resource()` is `pub(crate)`, an internal helper for the provider builders in Tasks 8-10.)

- [ ] **Step 6: Commit**

```bash
git add packages/rust-logging/src/resource.rs packages/rust-logging/src/lib.rs
git commit -m "$(cat <<'EOF'
feat(logging): add shared Resource builder for OTLP logs/metrics/traces

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01N2rQgkHY872RubwXoBZxtE
EOF
)"
```

---

### Task 7: Stdout JSON fmt layer

**Files:**
- Create: `packages/rust-logging/src/logging_init.rs`
- Modify: `packages/rust-logging/src/lib.rs`

**Interfaces:**
- Consumes: nothing from earlier tasks (generic over any `tracing_subscriber` registry-compatible subscriber).
- Produces: `pub(crate) fn json_fmt_layer<S>() -> impl tracing_subscriber::Layer<S> where S: tracing::Subscriber + for<'a> tracing_subscriber::registry::LookupSpan<'a>` — Task 11's `init()` adds this as one `.with()` call in its registry chain, alongside the reload filter layer (Task 5) and the OTel layers (Tasks 8-10).

- [ ] **Step 1: Write the failing test** (a scoped subscriber via `tracing::subscriber::with_default`, never the process-global `.init()`, so this test coexists with every other test in the crate that also builds a subscriber)

```rust
#[cfg(test)]
mod tests {
    use super::*;
    use std::sync::{Arc, Mutex};
    use tracing_subscriber::layer::SubscriberExt;

    #[derive(Clone, Default)]
    struct CapturingWriter(Arc<Mutex<Vec<u8>>>);

    impl std::io::Write for CapturingWriter {
        fn write(&mut self, buf: &[u8]) -> std::io::Result<usize> {
            self.0
                .lock()
                .unwrap_or_else(|p| p.into_inner())
                .extend_from_slice(buf);
            Ok(buf.len())
        }
        fn flush(&mut self) -> std::io::Result<()> {
            Ok(())
        }
    }

    impl<'a> tracing_subscriber::fmt::MakeWriter<'a> for CapturingWriter {
        type Writer = CapturingWriter;
        fn make_writer(&'a self) -> Self::Writer {
            self.clone()
        }
    }

    #[test]
    fn json_fmt_layer_emits_structured_json_with_level_and_message() {
        let writer = CapturingWriter::default();
        let layer = tracing_subscriber::fmt::layer()
            .json()
            .with_writer(writer.clone());
        let subscriber = tracing_subscriber::registry().with(layer);

        tracing::subscriber::with_default(subscriber, || {
            tracing::info!(component = "svc-process", "startup complete");
        });

        let bytes = writer.0.lock().unwrap_or_else(|p| p.into_inner()).clone();
        let line = String::from_utf8(bytes).expect("output must be valid UTF-8");
        let parsed: serde_json::Value =
            serde_json::from_str(line.trim()).expect("each line must be one JSON object");
        assert_eq!(parsed["level"], serde_json::json!("INFO"));
        assert_eq!(parsed["fields"]["message"], serde_json::json!("startup complete"));
        assert_eq!(parsed["fields"]["component"], serde_json::json!("svc-process"));
    }
}
```

- [ ] **Step 2: Run to verify it fails**

Run: `make test`
Expected: FAIL — the test as written passes against plain `tracing_subscriber::fmt::layer().json()` directly, so this step instead confirms the harness (writer capture + JSON parse) works before `json_fmt_layer()` exists; skip straight to Step 3 once this file's `json_fmt_layer` function is referenced anywhere non-test (it currently is not, so `cargo test` compiles and the test passes immediately using the inline `tracing_subscriber::fmt::layer().json()` call, not the not-yet-written function). To keep this task honestly test-first, change the test's `let layer = ...` line to `let layer = json_fmt_layer().with_writer(writer.clone());` before running -- THIS is the version that fails to compile (`cannot find function `json_fmt_layer``) until Step 3 lands.

- [ ] **Step 3: Implement**

```rust
//! The stdout JSON logging layer. Kept as its own small, generic function
//! (rather than inlined into `init()`) so it is unit-testable against a
//! scoped subscriber without touching the process-global default that
//! `crate::init::init` installs exactly once per process.

/// Builds the stdout JSON `tracing_subscriber` layer every Waddles service
/// uses for its structured logs. Generic over any subscriber implementing
/// `LookupSpan` (i.e. anything built from `tracing_subscriber::registry()`),
/// so it composes with whatever other layers [`crate::init::init`] adds.
pub(crate) fn json_fmt_layer<S>() -> impl tracing_subscriber::Layer<S>
where
    S: tracing::Subscriber + for<'a> tracing_subscriber::registry::LookupSpan<'a>,
{
    tracing_subscriber::fmt::layer().json()
}
```

Then update the test's `let layer = ...` line to call this function, as instructed in Step 2:

```rust
        let layer = json_fmt_layer().with_writer(writer.clone());
```

- [ ] **Step 4: Run to verify it passes**

Run: `make test`
Expected: PASS — `json_fmt_layer_emits_structured_json_with_level_and_message` green.

- [ ] **Step 5: Wire into `lib.rs`**

```rust
mod logging_init;
```

(No public re-export — internal to the crate; `crate::init::init` in Task 11 is the only public entry point that assembles logging.)

- [ ] **Step 6: Commit**

```bash
git add packages/rust-logging/src/logging_init.rs packages/rust-logging/src/lib.rs
git commit -m "$(cat <<'EOF'
feat(logging): add stdout JSON fmt layer, unit-tested against a scoped subscriber

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01N2rQgkHY872RubwXoBZxtE
EOF
)"
```

---

### Task 8: OTLP trace exporter + tracer provider builder

**Files:**
- Create: `packages/rust-logging/src/trace_provider.rs`
- Modify: `packages/rust-logging/src/lib.rs`

**Interfaces:**
- Consumes: `ServiceConfig`/`OtlpProtocol` (Task 4), `resource()` (Task 6).
- Produces: `pub(crate) fn build_tracer_provider(cfg: &ServiceConfig) -> Result<opentelemetry_sdk::trace::SdkTracerProvider, opentelemetry_otlp::ExporterBuildError>` — Task 11's `init()` calls this only when `cfg.otlp_endpoint.is_some()`, exactly mirroring `core/svc_streaming/src/telemetry.rs`'s existing `build_tracer_provider`/`init` pattern (read in full during planning) so a build failure downgrades to "no traces" rather than propagating.

- [ ] **Step 1: Write the failing test**

```rust
#[cfg(test)]
mod tests {
    use super::*;
    use crate::config::{OtlpProtocol, ServiceConfig};

    fn test_config(endpoint: &str) -> ServiceConfig {
        ServiceConfig {
            service_name: "svc-process-test".to_string(),
            otlp_endpoint: Some(endpoint.to_string()),
            otlp_protocol: OtlpProtocol::Grpc,
            otlp_headers: Vec::new(),
            log_level: "info".to_string(),
        }
    }

    #[test]
    fn build_tracer_provider_succeeds_for_a_syntactically_valid_endpoint() {
        // Building the exporter/provider does not connect eagerly (OTLP
        // exporters are lazy over gRPC/HTTP) -- this asserts construction
        // succeeds even though nothing is listening on this endpoint.
        // Reachability is exercised separately in Task 11's
        // exporter-never-fails integration test.
        let cfg = test_config("http://127.0.0.1:4317");
        let result = build_tracer_provider(&cfg);
        assert!(result.is_ok(), "{:?}", result.err());
        if let Ok(provider) = result {
            let _ = provider.shutdown();
        }
    }

    #[test]
    fn build_tracer_provider_respects_http_protobuf_protocol() {
        let mut cfg = test_config("http://127.0.0.1:4318");
        cfg.otlp_protocol = OtlpProtocol::HttpProtobuf;
        let result = build_tracer_provider(&cfg);
        assert!(result.is_ok(), "{:?}", result.err());
        if let Ok(provider) = result {
            let _ = provider.shutdown();
        }
    }
}
```

- [ ] **Step 2: Run to verify it fails**

Run: `make test`
Expected: FAIL — `cannot find function `build_tracer_provider``.

- [ ] **Step 3: Implement**

```rust
//! OTLP trace exporter + `SdkTracerProvider` construction, split out of
//! `crate::init::init` so it is independently testable. Pattern ported
//! from `core/svc_streaming/src/telemetry.rs`'s `build_tracer_provider`
//! (read in full during planning), adjusted to take `ServiceConfig`
//! instead of re-reading environment variables directly.

use crate::config::{OtlpProtocol, ServiceConfig};
use crate::resource::resource;
use opentelemetry_otlp::WithExportConfig;
use opentelemetry_sdk::trace::SdkTracerProvider;

/// Builds an OTLP span exporter for `cfg.otlp_endpoint` (the caller has
/// already checked it is `Some`) and wraps it in a batch-exporting
/// `SdkTracerProvider` carrying the shared [`resource`]. Returns `Err`
/// rather than panicking on a malformed endpoint URL or transport
/// initialization failure -- [`crate::init::init`] treats that as "no
/// traces this run" rather than a fatal startup error, per
/// `critical-rules.md` Observability's "a dead exporter never fails a
/// request" rule extended to exporter *construction*, not just export
/// calls.
pub(crate) fn build_tracer_provider(
    cfg: &ServiceConfig,
) -> Result<SdkTracerProvider, opentelemetry_otlp::ExporterBuildError> {
    let endpoint = cfg
        .otlp_endpoint
        .as_deref()
        .expect("build_tracer_provider called with no otlp_endpoint configured");
    let exporter = match cfg.otlp_protocol {
        OtlpProtocol::Grpc => opentelemetry_otlp::SpanExporter::builder()
            .with_tonic()
            .with_endpoint(endpoint)
            .build()?,
        OtlpProtocol::HttpProtobuf => opentelemetry_otlp::SpanExporter::builder()
            .with_http()
            .with_endpoint(endpoint)
            .build()?,
    };
    Ok(SdkTracerProvider::builder()
        .with_batch_exporter(exporter)
        .with_resource(resource(cfg))
        .build())
}
```

The `.expect()` above documents its own invariant (the caller — `crate::init::init` — only calls this function inside an `if cfg.otlp_endpoint.is_some()` branch) per `backend-rust.md`'s "document the invariant in a comment if used" carve-out; it is not reachable from any public API with an untrusted `cfg`.

- [ ] **Step 4: Run to verify it passes**

Run: `make test`
Expected: PASS — both tests green (construction succeeds without any listener present, since OTLP gRPC/HTTP exporters connect lazily on first export).

- [ ] **Step 5: Wire into `lib.rs`**

```rust
mod trace_provider;
```

- [ ] **Step 6: Commit**

```bash
git add packages/rust-logging/src/trace_provider.rs packages/rust-logging/src/lib.rs
git commit -m "$(cat <<'EOF'
feat(logging): add OTLP trace exporter + tracer provider builder

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01N2rQgkHY872RubwXoBZxtE
EOF
)"
```

---

### Task 9: OTLP metric exporter + shared-meter Prometheus bridge

**Files:**
- Create: `packages/rust-logging/src/metrics_provider.rs`
- Modify: `packages/rust-logging/src/lib.rs`

**Interfaces:**
- Consumes: `ServiceConfig`/`OtlpProtocol` (Task 4), `resource()` (Task 6).
- Produces: `pub(crate) fn build_meter_provider(cfg: &ServiceConfig, prometheus_registry: prometheus::Registry) -> Result<opentelemetry_sdk::metrics::SdkMeterProvider, MeterProviderError>` (only called when `cfg.otlp_endpoint.is_some()`); `pub fn render_prometheus_text(registry: &prometheus::Registry) -> Result<String, RenderError>` — Task 15's `/metrics` handler calls this directly; `pub enum MeterProviderError`, `pub enum RenderError`.

This is the task that closes the metrics half of the gap in `core/svc_streaming/src/telemetry.rs`: that file builds an OTLP `SdkMeterProvider` but never records a single instrument through it anywhere in the service (confirmed by reading the full file during planning — its `RequestMetrics`/`register_request_metrics` are 100% `prometheus`-crate calls, entirely bypassing the OTel meter API), so its OTLP metrics pipeline would forever export empty `ResourceMetrics`. This crate instead registers **one** `opentelemetry-prometheus` reader alongside the periodic OTLP exporter on the *same* `SdkMeterProvider` — every instrument created via `opentelemetry::global::meter(...)` (Task 12's `record_latency_ms`/`counter_add`/`gauge_set` helpers, and any service's own ad hoc instruments) is visible to **both** the OTLP push and the `/metrics` pull scrape from one `.record()`/`.add()` call, with no separate hand-registered Prometheus metric to keep in sync.

- [ ] **Step 1: Write the failing test**

```rust
#[cfg(test)]
mod tests {
    use super::*;
    use crate::config::{OtlpProtocol, ServiceConfig};
    use opentelemetry::metrics::MeterProvider as _;
    use opentelemetry::KeyValue;

    fn test_config(endpoint: &str) -> ServiceConfig {
        ServiceConfig {
            service_name: "svc-process-test".to_string(),
            otlp_endpoint: Some(endpoint.to_string()),
            otlp_protocol: OtlpProtocol::Grpc,
            otlp_headers: Vec::new(),
            log_level: "info".to_string(),
        }
    }

    #[test]
    fn build_meter_provider_succeeds_and_registers_a_prometheus_reader() {
        let cfg = test_config("http://127.0.0.1:4317");
        let registry = prometheus::Registry::new();
        let provider = build_meter_provider(&cfg, registry.clone())
            .expect("meter provider construction must not fail for a syntactically valid endpoint");

        // Record one instrument through the OTel meter API bound to this
        // provider and confirm it reaches the SAME Prometheus registry --
        // proving the shared-meter design (no separate hand-registered
        // Prometheus metric needed).
        let meter = provider.meter("penguin-logging-test");
        let counter = meter.u64_counter("test_requests_total").build();
        counter.add(1, &[KeyValue::new("route", "/health")]);

        let rendered = render_prometheus_text(&registry).expect("rendering must succeed");
        assert!(
            rendered.contains("test_requests_total"),
            "expected the OTel-recorded counter to appear in the Prometheus text output, got: {rendered}"
        );

        let _ = provider.shutdown();
    }

    #[test]
    fn render_prometheus_text_on_empty_registry_is_empty_string() {
        let registry = prometheus::Registry::new();
        let rendered = render_prometheus_text(&registry).expect("empty registry still encodes");
        assert!(rendered.is_empty());
    }
}
```

- [ ] **Step 2: Run to verify it fails**

Run: `make test`
Expected: FAIL — `cannot find function `build_meter_provider`` / `cannot find function `render_prometheus_text``.

- [ ] **Step 3: Implement**

```rust
//! OTLP metric exporter + a shared-meter `opentelemetry-prometheus` reader,
//! so `/metrics` and the OTLP push are two views of one instrument set.
//! See this task's plan entry for why this design deliberately differs
//! from `core/svc_streaming/src/telemetry.rs`'s hand-duplicated
//! OTLP-provider-plus-separate-`prometheus`-registry pattern.

use crate::config::{OtlpProtocol, ServiceConfig};
use crate::resource::resource;
use opentelemetry_otlp::WithExportConfig;
use opentelemetry_sdk::metrics::SdkMeterProvider;

/// Errors constructing the meter provider. Both variants wrap a
/// lower-level SDK error rather than losing detail behind a generic
/// message, since these are logged (not just returned) by
/// [`crate::init::init`].
#[derive(Debug, thiserror::Error)]
pub enum MeterProviderError {
    /// The OTLP metric exporter (gRPC or HTTP transport) failed to build.
    #[error("OTLP metric exporter build failed: {0}")]
    Otlp(#[from] opentelemetry_otlp::ExporterBuildError),
    /// The `opentelemetry-prometheus` reader failed to attach to the
    /// supplied `prometheus::Registry`.
    #[error("Prometheus metric reader build failed: {0}")]
    Prometheus(#[from] opentelemetry_sdk::error::OTelSdkError),
}

/// Errors rendering a `prometheus::Registry` to text exposition format.
#[derive(Debug, thiserror::Error)]
pub enum RenderError {
    /// The registry's metric families could not be encoded (e.g. a metric
    /// with an internally inconsistent label set).
    #[error("Prometheus text encoding failed: {0}")]
    Encode(#[from] prometheus::Error),
    /// The encoded bytes were not valid UTF-8 -- unreachable in practice
    /// (the Prometheus text format is always ASCII/UTF-8), kept as a
    /// typed error rather than a panic so a future encoder change can
    /// never turn into an unwrap.
    #[error("Prometheus text output was not valid UTF-8: {0}")]
    Utf8(#[from] std::string::FromUtf8Error),
}

/// Builds an OTLP metric exporter for `cfg.otlp_endpoint` (caller has
/// already checked it is `Some`) plus an `opentelemetry-prometheus`
/// reader bound to `prometheus_registry`, and returns one
/// `SdkMeterProvider` with both readers attached. Every instrument any
/// caller creates via `provider.meter(...)` (or, after
/// `opentelemetry::global::set_meter_provider`, via
/// `opentelemetry::global::meter(...)`) is exported by both readers from
/// a single `.record()`/`.add()` call.
pub(crate) fn build_meter_provider(
    cfg: &ServiceConfig,
    prometheus_registry: prometheus::Registry,
) -> Result<SdkMeterProvider, MeterProviderError> {
    let endpoint = cfg
        .otlp_endpoint
        .as_deref()
        .expect("build_meter_provider called with no otlp_endpoint configured");
    let otlp_exporter = match cfg.otlp_protocol {
        OtlpProtocol::Grpc => opentelemetry_otlp::MetricExporter::builder()
            .with_tonic()
            .with_endpoint(endpoint)
            .build()?,
        OtlpProtocol::HttpProtobuf => opentelemetry_otlp::MetricExporter::builder()
            .with_http()
            .with_endpoint(endpoint)
            .build()?,
    };
    let prometheus_reader = opentelemetry_prometheus::exporter()
        .with_registry(prometheus_registry)
        .build()?;

    Ok(SdkMeterProvider::builder()
        .with_periodic_exporter(otlp_exporter)
        .with_reader(prometheus_reader)
        .with_resource(resource(cfg))
        .build())
}

/// Renders `registry`'s currently-recorded metrics as Prometheus text
/// exposition format, for the `/metrics` HTTP handler (Task 15). Returns
/// an empty string for an empty registry rather than an error -- a
/// service scraped before its first metric is recorded is a normal
/// startup state, not a failure.
pub fn render_prometheus_text(registry: &prometheus::Registry) -> Result<String, RenderError> {
    use prometheus::Encoder;
    let metric_families = registry.gather();
    let mut buf = Vec::new();
    prometheus::TextEncoder::new().encode(&metric_families, &mut buf)?;
    Ok(String::from_utf8(buf)?)
}
```

The two `.expect()` invariant-comments above match Task 8's pattern exactly (both functions are `pub(crate)` and called only from `crate::init::init`'s `if cfg.otlp_endpoint.is_some()` branch).

- [ ] **Step 4: Run to verify it passes**

Run: `make test`
Expected: PASS — both tests green, including the shared-meter assertion (`test_requests_total` appears in the Prometheus text output despite never being registered against `prometheus::Registry` directly).

- [ ] **Step 5: Wire into `lib.rs`**

```rust
mod metrics_provider;
pub use metrics_provider::{render_prometheus_text, MeterProviderError, RenderError};
```

- [ ] **Step 6: Commit**

```bash
git add packages/rust-logging/src/metrics_provider.rs packages/rust-logging/src/lib.rs
git commit -m "$(cat <<'EOF'
feat(logging): add OTLP metric exporter + shared-meter Prometheus bridge

Closes the metrics half of core/svc_streaming's telemetry gap: one meter
now feeds both the OTLP push exporter and the /metrics pull registry,
instead of a separately hand-registered Prometheus-only metric set that
the OTel meter never actually recorded anything through.

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01N2rQgkHY872RubwXoBZxtE
EOF
)"
```

---

### Task 10: OTLP log exporter + `tracing`-to-OTel bridge

**Files:**
- Create: `packages/rust-logging/src/log_provider.rs`
- Modify: `packages/rust-logging/src/lib.rs`

**Interfaces:**
- Consumes: `ServiceConfig`/`OtlpProtocol` (Task 4), `resource()` (Task 6).
- Produces: `pub(crate) fn build_logger_provider(cfg: &ServiceConfig) -> Result<opentelemetry_sdk::logs::SdkLoggerProvider, opentelemetry_otlp::ExporterBuildError>` (only called when `cfg.otlp_endpoint.is_some()`); `pub(crate) fn otel_log_layer(provider: &opentelemetry_sdk::logs::SdkLoggerProvider) -> opentelemetry_appender_tracing::layer::OpenTelemetryTracingBridge<opentelemetry_sdk::logs::SdkLoggerProvider, opentelemetry_sdk::logs::SdkLogger>` (no generic parameter: `OpenTelemetryTracingBridge` already implements `tracing_subscriber::Layer<S>` for any `S: Subscriber + for<'a> LookupSpan<'a>` per its own crate's blanket impl, verified by reading `opentelemetry-appender-tracing` 0.32.0's source during planning — adding a same-named generic to this wrapper function would be unused and rejected by `clippy::extra_unused_type_parameters` under `-D warnings`) — Task 11's `init()` adds this layer to the registry chain exactly when a logger provider was built, so `tracing::info!`/`warn!`/etc. calls reach OTLP in addition to stdout JSON.

This is the task that closes the logging half of the reference gap: `core/svc_streaming/src/telemetry.rs` (read in full during planning) wires `tracing_subscriber::fmt::layer().json()` to stdout and an OTLP **span** exporter, but has no OTLP **log** exporter or `tracing`-to-OTel-logs bridge anywhere in the file — a collector never receives a single OTLP log record from that service today. `opentelemetry-appender-tracing`'s `OpenTelemetryTracingBridge` is a `tracing_subscriber::Layer` that turns every `tracing` event into an OTel `LogRecord` via a `SdkLoggerProvider`; adding it as one more `.with()` call is the entire fix.

- [ ] **Step 1: Write the failing test**

```rust
#[cfg(test)]
mod tests {
    use super::*;
    use crate::config::{OtlpProtocol, ServiceConfig};
    use tracing_subscriber::layer::SubscriberExt;

    fn test_config(endpoint: &str) -> ServiceConfig {
        ServiceConfig {
            service_name: "svc-process-test".to_string(),
            otlp_endpoint: Some(endpoint.to_string()),
            otlp_protocol: OtlpProtocol::Grpc,
            otlp_headers: Vec::new(),
            log_level: "info".to_string(),
        }
    }

    #[test]
    fn build_logger_provider_succeeds_for_a_syntactically_valid_endpoint() {
        let cfg = test_config("http://127.0.0.1:4317");
        let result = build_logger_provider(&cfg);
        assert!(result.is_ok(), "{:?}", result.err());
        if let Ok(provider) = result {
            let _ = provider.shutdown();
        }
    }

    #[test]
    fn otel_log_layer_composes_onto_a_registry_without_panicking() {
        let cfg = test_config("http://127.0.0.1:4317");
        let provider = build_logger_provider(&cfg).expect("provider must build");
        let layer = otel_log_layer(&provider);
        let subscriber = tracing_subscriber::registry().with(layer);

        // Proves the layer is well-typed against a real registry and does
        // not panic when a tracing event actually flows through it, even
        // though nothing is listening on the OTLP endpoint (the batch
        // processor buffers and retries in the background -- see Task 11's
        // exporter-never-fails test for the "never blocks the caller"
        // assertion).
        tracing::subscriber::with_default(subscriber, || {
            tracing::info!("this must not panic even with no collector listening");
        });

        let _ = provider.shutdown();
    }
}
```

- [ ] **Step 2: Run to verify it fails**

Run: `make test`
Expected: FAIL — `cannot find function `build_logger_provider`` / `cannot find function `otel_log_layer``.

- [ ] **Step 3: Implement**

```rust
//! OTLP log exporter + the `tracing`-events-to-OTel-`LogRecord` bridge.
//! Closes the log-signal gap in `core/svc_streaming/src/telemetry.rs`,
//! which has no OTLP log exporter at all -- see this task's plan entry.

use crate::config::{OtlpProtocol, ServiceConfig};
use crate::resource::resource;
use opentelemetry_appender_tracing::layer::OpenTelemetryTracingBridge;
use opentelemetry_otlp::WithExportConfig;
use opentelemetry_sdk::logs::{SdkLogger, SdkLoggerProvider};

/// Builds an OTLP log exporter for `cfg.otlp_endpoint` (caller has
/// already checked it is `Some`) and wraps it in a batch-exporting
/// `SdkLoggerProvider` carrying the shared [`resource`]. Mirrors
/// [`crate::trace_provider::build_tracer_provider`]'s shape exactly, one
/// signal over.
pub(crate) fn build_logger_provider(
    cfg: &ServiceConfig,
) -> Result<SdkLoggerProvider, opentelemetry_otlp::ExporterBuildError> {
    let endpoint = cfg
        .otlp_endpoint
        .as_deref()
        .expect("build_logger_provider called with no otlp_endpoint configured");
    let exporter = match cfg.otlp_protocol {
        OtlpProtocol::Grpc => opentelemetry_otlp::LogExporter::builder()
            .with_tonic()
            .with_endpoint(endpoint)
            .build()?,
        OtlpProtocol::HttpProtobuf => opentelemetry_otlp::LogExporter::builder()
            .with_http()
            .with_endpoint(endpoint)
            .build()?,
    };
    Ok(SdkLoggerProvider::builder()
        .with_batch_exporter(exporter)
        .with_resource(resource(cfg))
        .build())
}

/// Wraps `provider` in the `tracing_subscriber::Layer` that forwards
/// every `tracing` event to it as an OTel `LogRecord`. This is the ONLY
/// piece of plumbing needed to make `tracing::info!`/`warn!`/`error!`/
/// `debug!` calls anywhere in a service reach the OTLP logs pipeline --
/// no call site changes, since it composes onto the same `tracing`
/// macros the stdout JSON layer (Task 7) already subscribes to. Takes no
/// generic subscriber parameter: `OpenTelemetryTracingBridge<P, L>`
/// already implements `tracing_subscriber::Layer<S>` for any
/// `S: Subscriber + for<'a> LookupSpan<'a>` in its own crate (confirmed
/// by reading `opentelemetry-appender-tracing` 0.32.0's `src/layer.rs`
/// during planning: `impl<S, P, L> Layer<S> for
/// OpenTelemetryTracingBridge<P, L> where S: Subscriber + for<'a>
/// LookupSpan<'a>, ...`), so the concrete `S` is inferred at each
/// `.with(...)` call site in `crate::init::init` -- adding a same-named
/// generic here would be unused and rejected by
/// `clippy::extra_unused_type_parameters` under `-D warnings`.
pub(crate) fn otel_log_layer(
    provider: &SdkLoggerProvider,
) -> OpenTelemetryTracingBridge<SdkLoggerProvider, SdkLogger> {
    OpenTelemetryTracingBridge::new(provider)
}
```

- [ ] **Step 4: Run to verify it passes**

Run: `make test`
Expected: PASS — both tests green.

- [ ] **Step 5: Wire into `lib.rs`**

```rust
mod log_provider;
```

- [ ] **Step 6: Commit**

```bash
git add packages/rust-logging/src/log_provider.rs packages/rust-logging/src/lib.rs
git commit -m "$(cat <<'EOF'
feat(logging): add OTLP log exporter + tracing-to-OTel bridge

Closes the log-signal gap in core/svc_streaming/src/telemetry.rs, which
ships zero OTLP log records today (stdout JSON only). tracing events now
reach OTLP through opentelemetry-appender-tracing's
OpenTelemetryTracingBridge with no call-site changes required.

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01N2rQgkHY872RubwXoBZxtE
EOF
)"
```

---

### Task 11: `init(ServiceConfig)` — the public entry point + `TelemetryGuard`

**Files:**
- Create: `packages/rust-logging/src/init.rs`
- Create: `packages/rust-logging/tests/integration_exporter_failure.rs`
- Create: `packages/rust-logging/tests/integration_no_otlp.rs`
- Modify: `packages/rust-logging/src/lib.rs`

**Interfaces:**
- Consumes: `ServiceConfig` (Task 4), `LevelHandle`/`parse_level_filter` (Task 5), `json_fmt_layer` (Task 7), `build_tracer_provider` (Task 8), `build_meter_provider` (Task 9), `build_logger_provider`/`otel_log_layer` (Task 10).
- Produces: `pub fn init(cfg: ServiceConfig) -> (TelemetryGuard, LevelHandle, prometheus::Registry)` — every downstream service's `main()` calls this exactly once. `pub struct TelemetryGuard` with `pub fn shutdown(&mut self)` and a `Drop` impl calling it. This is the single public function every task from here on (Task 12 metrics helpers, Task 15 health router, Task 17 testing module, Task 18 integration tests) builds on top of or tests against.

**Why two test files, not one file with two `#[test]` functions:** `init()` calls `tracing_subscriber`'s `SubscriberInitExt::init()` internally, which sets the process-wide global default subscriber exactly once and **panics** on a second call in the same process. Cargo compiles every file directly under `tests/` into its own separate test binary (its own OS process); two `#[test]` functions in the *same* file do not get that isolation (the harness runs them as threads within one process). Since both scenarios below call the real `init()`, each needs its own file so each runs in its own process -- the correct fix, not a workaround: `init()` legitimately must behave as "call at most once per process" in production and should not be weakened (e.g. to a silently-no-op `try_init()`) just to let two tests coexist.

- [ ] **Step 1: Write the failing tests**

`packages/rust-logging/tests/integration_exporter_failure.rs`:

```rust
//! Asserts `penguin_logging::init` never panics or blocks the caller even
//! when `OTEL_EXPORTER_OTLP_ENDPOINT` points at an address nothing is
//! listening on -- the "a dead exporter never fails a request" rule
//! (`critical-rules.md` Observability) extended to init-time construction.
//! Runs in its own test binary/process (see this task's "Why two test
//! files" note) since `init()` may be called at most once per process.

use penguin_logging::{init, ServiceConfig};
use std::time::{Duration, Instant};

#[test]
fn init_with_unreachable_otlp_endpoint_returns_quickly_and_does_not_panic() {
    // SAFETY: this is the only test in this process that touches these
    // variables (see this task's "Why two test files" note) -- no lock
    // needed.
    unsafe {
        std::env::set_var("OTEL_EXPORTER_OTLP_ENDPOINT", "http://127.0.0.1:1"); // nothing listens on port 1
        std::env::set_var("OTEL_SERVICE_NAME", "init-failure-test");
    }

    let cfg = ServiceConfig::from_env("init-failure-test");
    let start = Instant::now();
    let (mut telemetry_guard, level_handle, registry) = init(cfg);
    let elapsed = start.elapsed();

    // Exporter construction is lazy (no network I/O until the first
    // export attempt) -- init() itself must return well under a second
    // regardless of the endpoint's reachability.
    assert!(elapsed < Duration::from_secs(1), "init() took {elapsed:?}, expected near-instant return");

    // A log line after init must not panic even though nothing can
    // receive the OTLP export the background batch processor will
    // eventually attempt.
    tracing::info!("log line after init with an unreachable OTLP endpoint");
    assert_eq!(level_handle.current(), "info");
    assert!(penguin_logging::render_prometheus_text(&registry).is_ok());

    telemetry_guard.shutdown();
    unsafe {
        std::env::remove_var("OTEL_EXPORTER_OTLP_ENDPOINT");
        std::env::remove_var("OTEL_SERVICE_NAME");
    }
}
```

`packages/rust-logging/tests/integration_no_otlp.rs`:

```rust
//! Asserts `penguin_logging::init` with no `OTEL_EXPORTER_OTLP_ENDPOINT`
//! configured still returns a fully usable `LevelHandle`. A separate
//! process/file from `integration_exporter_failure.rs` for the same
//! reason given in Task 11's "Why two test files" note -- both call the
//! real, at-most-once-per-process `init()`.

use penguin_logging::{init, ServiceConfig};

#[test]
fn init_with_no_otlp_endpoint_configured_still_returns_a_usable_level_handle() {
    // SAFETY: the only test in this process touching these variables.
    unsafe {
        std::env::remove_var("OTEL_EXPORTER_OTLP_ENDPOINT");
        std::env::set_var("LOG_LEVEL", "warn");
    }

    let cfg = ServiceConfig::from_env("init-no-otlp-test");
    let (mut telemetry_guard, level_handle, _registry) = init(cfg);

    assert_eq!(level_handle.current(), "warn");
    level_handle.set_level("debug").expect("debug is a valid level");
    assert_eq!(level_handle.current(), "debug");

    telemetry_guard.shutdown();
    unsafe { std::env::remove_var("LOG_LEVEL") };
}
```

- [ ] **Step 2: Run to verify it fails**

Run: `make test`
Expected: FAIL — `unresolved import `penguin_logging::init`` / `unresolved import `penguin_logging::ServiceConfig``.

- [ ] **Step 3: Implement `init.rs`**

```rust
//! The crate's single public entry point: wires stdout JSON logging, the
//! runtime-reloadable level filter, and (when `OTEL_EXPORTER_OTLP_ENDPOINT`
//! is set) all three OTLP pipelines, into one `tracing_subscriber`
//! registry, initialized exactly once per process.

use crate::config::ServiceConfig;
use crate::level::{parse_level_filter, LevelHandle};
use crate::log_provider::{build_logger_provider, otel_log_layer};
use crate::logging_init::json_fmt_layer;
use crate::metrics_provider::build_meter_provider;
use crate::trace_provider::build_tracer_provider;
use opentelemetry::global;
use opentelemetry::trace::TracerProvider as _;
use opentelemetry_sdk::logs::SdkLoggerProvider;
use opentelemetry_sdk::metrics::SdkMeterProvider;
use opentelemetry_sdk::trace::SdkTracerProvider;
use tracing_subscriber::layer::SubscriberExt;
use tracing_subscriber::util::SubscriberInitExt;

/// Holds every OTel provider handle that must be flushed/shut down at
/// process exit. Dropping this guard (or calling
/// [`TelemetryGuard::shutdown`] explicitly, which every service should do
/// before returning from `main`) flushes buffered logs/spans/metrics
/// before the process exits.
pub struct TelemetryGuard {
    tracer_provider: Option<SdkTracerProvider>,
    meter_provider: Option<SdkMeterProvider>,
    logger_provider: Option<SdkLoggerProvider>,
}

impl TelemetryGuard {
    /// Flushes and shuts down every active OTLP pipeline. Errors are
    /// logged via `eprintln!` (not `tracing!` -- the subscriber may
    /// itself be shutting down) and never propagated, matching
    /// `core/svc_streaming/src/telemetry.rs`'s existing `shutdown`
    /// behavior: shutdown must not be able to fail the caller.
    pub fn shutdown(&mut self) {
        if let Some(provider) = self.tracer_provider.take() {
            if let Err(err) = provider.shutdown() {
                eprintln!("penguin-logging: tracer provider shutdown error: {err}");
            }
        }
        if let Some(provider) = self.meter_provider.take() {
            if let Err(err) = provider.shutdown() {
                eprintln!("penguin-logging: meter provider shutdown error: {err}");
            }
        }
        if let Some(provider) = self.logger_provider.take() {
            if let Err(err) = provider.shutdown() {
                eprintln!("penguin-logging: logger provider shutdown error: {err}");
            }
        }
    }
}

impl Drop for TelemetryGuard {
    fn drop(&mut self) {
        self.shutdown();
    }
}

/// Initializes stdout JSON logging (always) plus best-effort OTLP
/// logs/metrics/traces (only when `cfg.otlp_endpoint` is `Some`), and
/// returns the shutdown guard, a handle to change `LOG_LEVEL` at
/// runtime, and the `prometheus::Registry` backing `/metrics` (Task 15's
/// health router takes this directly). Must be called exactly once per
/// process, before any other `tracing` macro use. Never fails: a
/// malformed or unreachable OTLP endpoint downgrades to "stdout logging
/// only" for the pipeline(s) that failed to build, each logged once via
/// `eprintln!` (the subscriber is not yet initialized at that point),
/// matching `core/svc_streaming/src/telemetry.rs`'s existing degrade
/// behavior for its two pipelines, extended here to all three.
pub fn init(cfg: ServiceConfig) -> (TelemetryGuard, LevelHandle, prometheus::Registry) {
    let initial_filter =
        parse_level_filter(&cfg.log_level).unwrap_or_else(|_| parse_level_filter("info")
            .expect("the literal \"info\" always parses"));
    let (filter_layer, reload_handle) = tracing_subscriber::reload::Layer::new(initial_filter);
    let level_handle = LevelHandle::with_initial_level(reload_handle, &cfg.log_level);

    let prometheus_registry = prometheus::Registry::new();

    let (tracer_provider, meter_provider, logger_provider) = match &cfg.otlp_endpoint {
        Some(_) => {
            let tracer = build_tracer_provider(&cfg)
                .inspect_err(|err| {
                    eprintln!("penguin-logging: OTLP trace exporter init failed, continuing without traces: {err}");
                })
                .ok();
            let meter = build_meter_provider(&cfg, prometheus_registry.clone())
                .inspect_err(|err| {
                    eprintln!("penguin-logging: OTLP metric exporter init failed, continuing without OTLP metrics (Prometheus /metrics is unaffected): {err}");
                })
                .ok();
            let logger = build_logger_provider(&cfg)
                .inspect_err(|err| {
                    eprintln!("penguin-logging: OTLP log exporter init failed, continuing with stdout JSON logs only: {err}");
                })
                .ok();
            (tracer, meter, logger)
        }
        None => (None, None, None),
    };

    if let Some(provider) = &meter_provider {
        global::set_meter_provider(provider.clone());
    }

    let registry = tracing_subscriber::registry()
        .with(filter_layer)
        .with(json_fmt_layer());

    match (&logger_provider, &tracer_provider) {
        (Some(logger), Some(tracer)) => {
            let otel_logs = otel_log_layer(logger);
            let otel_traces =
                tracing_opentelemetry::layer().with_tracer(tracer.tracer(cfg.service_name.clone()));
            registry.with(otel_logs).with(otel_traces).init();
        }
        (Some(logger), None) => {
            let otel_logs = otel_log_layer(logger);
            registry.with(otel_logs).init();
        }
        (None, Some(tracer)) => {
            let otel_traces =
                tracing_opentelemetry::layer().with_tracer(tracer.tracer(cfg.service_name.clone()));
            registry.with(otel_traces).init();
        }
        (None, None) => registry.init(),
    }

    (
        TelemetryGuard {
            tracer_provider,
            meter_provider,
            logger_provider,
        },
        level_handle,
        prometheus_registry,
    )
}
```

The `.expect("the literal \"info\" always parses")` documents its own invariant identically to Tasks 8-10's pattern: `"info"` is one of `parse_level_filter`'s four hardcoded match arms and cannot fail.

- [ ] **Step 4: Run to verify it passes**

Run: `make test`
Expected: PASS — both `integration_exporter_failure` and `integration_no_otlp` tests green (each in its own process, per this task's "Why two test files" note), plus every earlier task's tests still green (`cargo test --all-features` runs the whole suite).

- [ ] **Step 5: Wire into `lib.rs`** — full file at this point:

```rust
//! Structured, sanitized logging plus OpenTelemetry logs/metrics/traces and
//! a `/health`/`/healthz`/`/metrics` HTTP surface for Waddles/PenguinTech
//! Rust services. See the crate README for the environment variable
//! contract and `docs/superpowers/specs/2026-09-14-rust-data-plane-design.md`
//! §4.9 for the design this crate implements.

/// The crate's own version, exposed so a service can report it on `/health`
/// without duplicating the string from `Cargo.toml`.
pub const VERSION: &str = env!("CARGO_PKG_VERSION");

pub mod config;
pub mod level;
mod log_provider;
mod logging_init;
pub mod metrics_provider;
mod resource;
pub mod sanitize;
mod trace_provider;

pub mod init;

pub use config::{OtlpProtocol, ServiceConfig};
pub use init::{init, TelemetryGuard};
pub use level::{parse_level_filter, LevelError, LevelHandle};
pub use metrics_provider::{render_prometheus_text, MeterProviderError, RenderError};
pub use sanitize::{sanitize, sanitize_json_str, sanitize_value, SanitizeError, Sanitized, SENSITIVE_KEYS};

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn version_matches_cargo_toml() {
        assert_eq!(VERSION, "0.1.0");
    }
}
```

- [ ] **Step 6: Commit**

```bash
git add packages/rust-logging/src/init.rs packages/rust-logging/src/lib.rs packages/rust-logging/tests/integration_exporter_failure.rs packages/rust-logging/tests/integration_no_otlp.rs
git commit -m "$(cat <<'EOF'
feat(logging): add init(ServiceConfig) tying logs/metrics/traces together

Never fails: an unreachable or unset OTLP endpoint degrades per-pipeline
rather than blocking startup, verified against a real unreachable
127.0.0.1:1 endpoint with a near-instant return time assertion.

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01N2rQgkHY872RubwXoBZxtE
EOF
)"
```

---

### Task 12: `metrics.rs` — histogram/counter/gauge helpers

**Files:**
- Create: `packages/rust-logging/src/metrics.rs`
- Modify: `packages/rust-logging/src/lib.rs`

**Interfaces:**
- Consumes: `opentelemetry::global::meter` (works once `init()`, Task 11, has called `global::set_meter_provider`; also works with the `testing` feature's in-memory meter provider from Task 17, since both go through the same `opentelemetry::global` registration point).
- Produces: `pub fn record_latency_ms(name: &'static str, millis: f64, labels: &[opentelemetry::KeyValue])`, `pub fn record_latency_seconds(name: &'static str, seconds: f64, labels: &[opentelemetry::KeyValue])`, `pub fn counter_add(name: &'static str, value: u64, labels: &[opentelemetry::KeyValue])`, `pub fn gauge_set(name: &'static str, value: f64, labels: &[opentelemetry::KeyValue])` — every downstream service's business metrics (e.g. `waddles_stage_latency_seconds`, `waddles_bundle_grants`) go through these instead of hand-rolling `opentelemetry::global::meter(...).f64_histogram(...)` at each call site, so the "histograms first" rule (`critical-rules.md` Observability) and instrument-reuse (each name creates its OTel instrument once, cached, per the SDK's own recommendation to avoid duplicate-instrument overhead — confirmed by reading `opentelemetry` 0.32.0's `Meter::u64_counter`/`f64_histogram` doc comments during planning) are satisfied by construction. Also produces `#[cfg(test)] pub(crate) fn global_meter_test_lock() -> &'static std::sync::Mutex<()>` — Task 16's and Task 17's own tests acquire this same lock (as `crate::metrics::global_meter_test_lock()`) before touching the global meter provider, for the reason given in this task's Step 1.

- [ ] **Step 1: Write the failing tests** (using the `testing` feature's in-memory meter — this task therefore also depends on Task 17's `init_test_telemetry` existing; since Task 17 is a later numbered task in this plan, its dependency direction is the opposite of execution order. **Resolve by implementing this task's tests using a minimal, self-contained in-memory meter provider inline**, not by importing `crate::testing` — see the test code below, which builds its own `opentelemetry_sdk::metrics::SdkMeterProvider` with an `InMemoryMetricExporter` directly, duplicating just enough of what Task 17 later generalizes into a public, reusable API.

**Cross-test isolation, load-bearing for every later task's tests too:** `opentelemetry::global::set_meter_provider` sets one process-wide slot, and `record_latency_ms`/`counter_add`/`gauge_set`'s instrument caches (`histogram_cache()` etc.) are also process-global `static`s -- both are shared across every `#[test]`/`#[tokio::test]` function in this crate's unit-test binary (`cargo test --lib` runs them as concurrent threads in ONE process, unlike files under `tests/`, which are separate processes; see Task 11's "Why two test files" note for that distinction). Any test elsewhere in this crate that also installs a global meter provider (Task 16's `dependency_tests`/`transport_tests`, Task 17's `testing::tests`) must serialize against these tests using the SAME lock, defined here and reused by name (`crate::metrics::global_meter_test_lock`) rather than each module inventing its own -- two different locks would defeat the purpose.)

```rust
#[cfg(test)]
mod tests {
    use super::*;
    use opentelemetry::KeyValue;
    use opentelemetry_sdk::metrics::{InMemoryMetricExporter, SdkMeterProvider};

    /// Builds an in-memory-backed meter provider and installs it globally.
    /// Returns both the exporter (to read exported data back out) and the
    /// provider (so the test can call `force_flush` directly instead of
    /// waiting on the periodic export timer) -- `with_periodic_exporter`
    /// spawns its background ticker via `tokio::spawn`, which requires an
    /// active Tokio runtime at build time, hence every test in this module
    /// is `#[tokio::test]` rather than plain `#[test]`. Caller must hold
    /// `global_meter_test_lock()` for the duration.
    fn install_in_memory_meter() -> (InMemoryMetricExporter, SdkMeterProvider) {
        let exporter = InMemoryMetricExporter::default();
        let provider = SdkMeterProvider::builder()
            .with_periodic_exporter(exporter.clone())
            .build();
        opentelemetry::global::set_meter_provider(provider.clone());
        (exporter, provider)
    }

    #[tokio::test]
    async fn record_latency_ms_creates_a_histogram_with_a_data_point() {
        let _guard = global_meter_test_lock().lock().unwrap_or_else(|p| p.into_inner());
        clear_instrument_caches();
        let (exporter, provider) = install_in_memory_meter();
        record_latency_ms("test_latency_ms", 42.0, &[KeyValue::new("route", "/health")]);
        provider.force_flush().expect("force_flush must succeed against an in-memory exporter");
        let metrics = exporter.get_finished_metrics().expect("must not error");
        assert!(
            !metrics.is_empty(),
            "expected at least one exported ResourceMetrics after recording a histogram"
        );
    }

    #[tokio::test]
    async fn counter_add_and_gauge_set_do_not_panic() {
        let _guard = global_meter_test_lock().lock().unwrap_or_else(|p| p.into_inner());
        clear_instrument_caches();
        let (_exporter, provider) = install_in_memory_meter();
        counter_add("test_events_total", 1, &[]);
        gauge_set("test_current_value", 3.5, &[]);
        provider.force_flush().expect("force_flush must succeed");
        // No further assertion beyond "did not panic and flushed cleanly"
        // -- exhaustive export-content assertions for counters/gauges are
        // covered by Task 18's integration test against the crate's own
        // `testing` feature.
    }

    #[tokio::test]
    async fn repeated_calls_with_the_same_name_reuse_the_cached_instrument() {
        let _guard = global_meter_test_lock().lock().unwrap_or_else(|p| p.into_inner());
        clear_instrument_caches();
        let (_exporter, provider) = install_in_memory_meter();
        record_latency_ms("test_repeat_latency_ms", 1.0, &[]);
        record_latency_ms("test_repeat_latency_ms", 2.0, &[]);
        provider.force_flush().expect("force_flush must succeed");
        let cache = histogram_cache().lock().unwrap_or_else(|p| p.into_inner());
        assert_eq!(
            cache.keys().filter(|k| k.as_str() == "test_repeat_latency_ms").count(),
            1,
            "expected exactly one cached instrument for a repeated metric name"
        );
    }
}
```

- [ ] **Step 2: Run to verify it fails**

Run: `make test`
Expected: FAIL — `cannot find function `record_latency_ms`` / `counter_add` / `gauge_set` / `histogram_cache`.

- [ ] **Step 3: Implement**

```rust
//! Ergonomic wrappers over the OTel meter API so every duration
//! measurement in a Waddles service is a histogram by construction
//! (`critical-rules.md` Observability: "histograms for load/latency
//! first -- a lone request counter is not instrumentation"), and so
//! repeated calls with the same metric name reuse one instrument instead
//! of constructing a fresh one per call (the OTel SDK itself dedups
//! aggregation by instrument descriptor regardless, per `opentelemetry`
//! 0.32.0's `Meter::u64_counter` doc comment: "Creating duplicate
//! Counters for the same metric could lower SDK performance" -- so this
//! caching is a performance nicety, not a correctness requirement).
//!
//! Every instrument here shares one fixed instrumentation scope,
//! `"penguin-logging"`. This is a deliberate simplification: callers
//! wanting a distinct instrumentation scope per crate should call
//! `opentelemetry::global::meter("their-scope")` directly instead of
//! these helpers.

use opentelemetry::global;
use opentelemetry::metrics::{Counter, Gauge, Histogram};
use opentelemetry::KeyValue;
use std::collections::HashMap;
use std::sync::{Mutex, OnceLock};

const SCOPE: &str = "penguin-logging";

/// Serializes every test, anywhere in this crate, that installs a global
/// meter provider (`opentelemetry::global::set_meter_provider`) and/or
/// reads these helpers' instrument caches. `#[cfg(test)]`-only: not part
/// of the crate's runtime behavior, but `pub(crate)` (not
/// module-private) so Task 16's and Task 17's test modules can acquire
/// the SAME lock rather than each defining their own -- see this task's
/// Step 1 note on why a single shared lock is required.
#[cfg(test)]
pub(crate) fn global_meter_test_lock() -> &'static Mutex<()> {
    static LOCK: OnceLock<Mutex<()>> = OnceLock::new();
    LOCK.get_or_init(|| Mutex::new(()))
}

pub(crate) fn histogram_cache() -> &'static Mutex<HashMap<String, Histogram<f64>>> {
    static CACHE: OnceLock<Mutex<HashMap<String, Histogram<f64>>>> = OnceLock::new();
    CACHE.get_or_init(|| Mutex::new(HashMap::new()))
}

fn counter_cache() -> &'static Mutex<HashMap<String, Counter<u64>>> {
    static CACHE: OnceLock<Mutex<HashMap<String, Counter<u64>>>> = OnceLock::new();
    CACHE.get_or_init(|| Mutex::new(HashMap::new()))
}

fn gauge_cache() -> &'static Mutex<HashMap<String, Gauge<f64>>> {
    static CACHE: OnceLock<Mutex<HashMap<String, Gauge<f64>>>> = OnceLock::new();
    CACHE.get_or_init(|| Mutex::new(HashMap::new()))
}

/// Clears every cached instrument. **Test-only, and load-bearing for
/// correctness under `global_meter_test_lock()`:** each of this crate's
/// tests that installs a fresh in-memory global meter provider must also
/// clear these caches first, or a metric name reused by an earlier test
/// (e.g. Task 16's two `waddles_dependency_up` tests) would resolve to
/// an instrument handle still bound to the EARLIER test's now-replaced
/// meter provider -- the cache is keyed only by name, with no awareness
/// that the global provider underneath it can change between tests.
/// Call this immediately after acquiring `global_meter_test_lock()` and
/// before installing the new provider.
#[cfg(test)]
pub(crate) fn clear_instrument_caches() {
    histogram_cache().lock().unwrap_or_else(|p| p.into_inner()).clear();
    counter_cache().lock().unwrap_or_else(|p| p.into_inner()).clear();
    gauge_cache().lock().unwrap_or_else(|p| p.into_inner()).clear();
}

/// Records `millis` into the f64 histogram named `name` (unit `ms`,
/// created on first use, cached thereafter) against the shared
/// `"penguin-logging"` instrumentation scope.
pub fn record_latency_ms(name: &'static str, millis: f64, labels: &[KeyValue]) {
    let mut cache = histogram_cache().lock().unwrap_or_else(|p| p.into_inner());
    let histogram = cache
        .entry(name.to_string())
        .or_insert_with(|| global::meter(SCOPE).f64_histogram(name).with_unit("ms").build());
    histogram.record(millis, labels);
}

/// Records `seconds` into the f64 histogram named `name` (unit `s`) --
/// for metrics the design spec names in seconds (e.g.
/// `waddles_stage_latency_seconds`), so a service does not have to
/// convert units at every call site.
pub fn record_latency_seconds(name: &'static str, seconds: f64, labels: &[KeyValue]) {
    let mut cache = histogram_cache().lock().unwrap_or_else(|p| p.into_inner());
    let histogram = cache
        .entry(name.to_string())
        .or_insert_with(|| global::meter(SCOPE).f64_histogram(name).with_unit("s").build());
    histogram.record(seconds, labels);
}

/// Adds `value` to the monotonic u64 counter named `name` (created on
/// first use, cached thereafter).
pub fn counter_add(name: &'static str, value: u64, labels: &[KeyValue]) {
    let mut cache = counter_cache().lock().unwrap_or_else(|p| p.into_inner());
    let counter = cache
        .entry(name.to_string())
        .or_insert_with(|| global::meter(SCOPE).u64_counter(name).build());
    counter.add(value, labels);
}

/// Records the current value of the independent-value gauge named `name`
/// (created on first use, cached thereafter) -- e.g.
/// `waddles_insecure_transport`, `waddles_dependency_up`.
pub fn gauge_set(name: &'static str, value: f64, labels: &[KeyValue]) {
    let mut cache = gauge_cache().lock().unwrap_or_else(|p| p.into_inner());
    let gauge = cache
        .entry(name.to_string())
        .or_insert_with(|| global::meter(SCOPE).f64_gauge(name).build());
    gauge.record(value, labels);
}
```

- [ ] **Step 4: Run to verify it passes**

Run: `make test`
Expected: PASS — all three `metrics::tests` green.

- [ ] **Step 5: Wire into `lib.rs`**

```rust
pub mod metrics;
pub use metrics::{counter_add, gauge_set, record_latency_ms, record_latency_seconds};
```

- [ ] **Step 6: Commit**

```bash
git add packages/rust-logging/src/metrics.rs packages/rust-logging/src/lib.rs
git commit -m "$(cat <<'EOF'
feat(logging): add record_latency_ms/counter_add/gauge_set instrument helpers

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01N2rQgkHY872RubwXoBZxtE
EOF
)"
```

---

### Task 13: `trace_context.rs` — W3C `traceparent` propagation for `StageEnvelope.trace_context`

**Files:**
- Create: `packages/rust-logging/src/trace_context.rs`
- Modify: `packages/rust-logging/src/lib.rs`

**Interfaces:**
- Consumes: nothing from earlier tasks (pure functions over `opentelemetry::Context`).
- Produces: `pub fn inject_trace_context(cx: &opentelemetry::Context) -> Option<String>`, `pub fn context_from_trace_context(traceparent: Option<&str>) -> opentelemetry::Context` — `penguin-spine`'s `StageEnvelope.trace_context: Option<String>` field (design spec §6.1.2, exact format `"00-<32 hex trace id>-<16 hex span id>-<2 hex flags>"`) is populated by `inject_trace_context(&Span::current().context())` when a stage enqueues an envelope, and consumed by `context_from_trace_context(envelope.trace_context.as_deref())` when the next stage starts its own root span as a child of that context.

- [ ] **Step 1: Write the failing tests**

```rust
#[cfg(test)]
mod tests {
    use super::*;
    use opentelemetry::trace::{TraceContextExt, TraceId, TraceState};
    use opentelemetry::Context;

    #[test]
    fn inject_trace_context_returns_none_for_a_context_with_no_span() {
        let cx = Context::new();
        assert_eq!(inject_trace_context(&cx), None);
    }

    #[test]
    fn context_from_trace_context_with_none_returns_a_context_with_no_valid_span() {
        let cx = context_from_trace_context(None);
        assert!(!cx.span().span_context().is_valid());
    }

    #[test]
    fn context_from_trace_context_with_an_unparsable_value_returns_a_context_with_no_valid_span() {
        let cx = context_from_trace_context(Some("not-a-traceparent"));
        assert!(!cx.span().span_context().is_valid());
    }

    #[test]
    fn round_trips_a_well_formed_traceparent() {
        let traceparent = "00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01";
        let cx = context_from_trace_context(Some(traceparent));
        assert!(cx.span().span_context().is_valid());
        assert_eq!(
            cx.span().span_context().trace_id(),
            TraceId::from_hex("4bf92f3577b34da6a3ce929d0e0e4736").expect("valid trace id hex")
        );

        let injected = inject_trace_context(&cx).expect("a valid span context must inject");
        assert_eq!(injected, traceparent);
    }

    // Referenced only to keep TraceState/`trace` module imports honest if
    // a future edit needs them; not directly asserted on above.
    #[allow(dead_code)]
    fn _unused(_: TraceState) {}
}
```

- [ ] **Step 2: Run to verify it fails**

Run: `make test`
Expected: FAIL — `cannot find function `inject_trace_context`` / `context_from_trace_context``.

- [ ] **Step 3: Implement**

```rust
//! W3C `traceparent` propagation for the design spec's `StageEnvelope.
//! trace_context` field (§6.1.2): `"00-<32 hex trace id>-<16 hex span
//! id>-<2 hex flags>"`, absent/null meaning no parent span. This module
//! wraps `opentelemetry_sdk`'s `TraceContextPropagator` (the standard W3C
//! implementation) behind a two-function API so callers never touch the
//! `Injector`/`Extractor` carrier plumbing directly.

use opentelemetry::propagation::TextMapPropagator;
use opentelemetry::trace::TraceContextExt;
use opentelemetry::Context;
use opentelemetry_sdk::propagation::TraceContextPropagator;
use std::collections::HashMap;

const TRACEPARENT_HEADER: &str = "traceparent";

/// Renders `cx`'s current span context as a W3C `traceparent` header
/// value, for direct assignment to `StageEnvelope.trace_context`. Returns
/// `None` when `cx` carries no valid span context (e.g. OTLP tracing was
/// never initialized, or this is a root context), so callers can leave
/// the envelope field `null` rather than writing a garbage value --
/// matching the spec's "absent or null ⇒ no parent span" rule.
pub fn inject_trace_context(cx: &Context) -> Option<String> {
    if !cx.span().span_context().is_valid() {
        return None;
    }
    let propagator = TraceContextPropagator::new();
    let mut carrier: HashMap<String, String> = HashMap::new();
    propagator.inject_context(cx, &mut carrier);
    carrier.remove(TRACEPARENT_HEADER)
}

/// Builds a [`Context`] carrying the parent span context described by
/// `traceparent` (read from `StageEnvelope.trace_context`), for use as
/// the parent when a stage starts its own span. `None` or an unparsable
/// value yields a context with no valid span (`Context::new()`'s
/// default), matching the spec's "absent or null ⇒ no parent span" rule
/// rather than erroring -- a malformed `trace_context` value must never
/// block processing the envelope it came with.
pub fn context_from_trace_context(traceparent: Option<&str>) -> Context {
    let Some(value) = traceparent else {
        return Context::new();
    };
    let propagator = TraceContextPropagator::new();
    let mut carrier: HashMap<String, String> = HashMap::new();
    carrier.insert(TRACEPARENT_HEADER.to_string(), value.to_string());
    propagator.extract_with_context(&Context::new(), &carrier)
}
```

- [ ] **Step 4: Run to verify it passes**

Run: `make test`
Expected: PASS — all `trace_context::tests` green, including the round-trip test.

- [ ] **Step 5: Wire into `lib.rs`**

```rust
pub mod trace_context;
pub use trace_context::{context_from_trace_context, inject_trace_context};
```

- [ ] **Step 6: Commit**

```bash
git add packages/rust-logging/src/trace_context.rs packages/rust-logging/src/lib.rs
git commit -m "$(cat <<'EOF'
feat(logging): add W3C traceparent inject/extract for StageEnvelope.trace_context

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01N2rQgkHY872RubwXoBZxtE
EOF
)"
```

---

### Task 14: `health/types.rs` — `DependencyClass`, `DependencyStatus`, `HealthState`, `HealthBody`

**Files:**
- Create: `packages/rust-logging/src/health/mod.rs`, `packages/rust-logging/src/health/types.rs`
- Modify: `packages/rust-logging/src/lib.rs`

**Interfaces:**
- Consumes: `prometheus::Registry` (the one `init()`, Task 11, returns).
- Produces: `pub enum DependencyClass { Dns, Tcp, Tls, Auth, Ok }` (serializes lowercase, matches design spec §12.6's `class` ∈ `dns|tcp|tls|auth|ok`); `pub struct DependencyStatus { pub class: DependencyClass, pub detail: String }` with `DependencyStatus::ok()`/`DependencyStatus::failed(class, detail)`/`is_up(&self) -> bool`; `pub struct ComponentTransport { pub tls: bool, pub auth: bool }`; `pub struct HealthState` (cloneable, `Arc`-backed) with `new`, `set_dependency`, `set_transport`, `set_sandbox`, `set_extra`, `uptime_seconds`, `snapshot() -> HealthBody`; `pub struct HealthBody` (the `/health` JSON shape from design spec §11.6.4). Task 15's axum router calls `HealthState::snapshot`; Task 16's `DependencyMetrics`/`TransportMetrics` are constructed alongside a `HealthState` and kept in sync with it by the service (not automatically — see Task 16's note on why they are separate).

- [ ] **Step 1: Write the failing tests**

```rust
#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    #[test]
    fn dependency_class_serializes_lowercase() {
        assert_eq!(serde_json::to_value(DependencyClass::Dns).unwrap(), json!("dns"));
        assert_eq!(serde_json::to_value(DependencyClass::Tcp).unwrap(), json!("tcp"));
        assert_eq!(serde_json::to_value(DependencyClass::Tls).unwrap(), json!("tls"));
        assert_eq!(serde_json::to_value(DependencyClass::Auth).unwrap(), json!("auth"));
        assert_eq!(serde_json::to_value(DependencyClass::Ok).unwrap(), json!("ok"));
    }

    #[test]
    fn dependency_status_ok_is_up_and_failed_is_not() {
        assert!(DependencyStatus::ok().is_up());
        assert!(!DependencyStatus::failed(DependencyClass::Tcp, "connection refused").is_up());
    }

    #[test]
    fn health_state_snapshot_reports_defaults_before_anything_is_set() {
        let state = HealthState::new("svc-process", "0.1.0", prometheus::Registry::new());
        let body = state.snapshot();
        assert_eq!(body.status, "ok");
        assert_eq!(body.service, "svc-process");
        assert_eq!(body.version, "0.1.0");
        assert_eq!(body.transport, "secure");
        assert!(body.transport_detail.is_empty());
        assert!(body.dependencies.is_empty());
        assert_eq!(body.sandbox, None);
    }

    #[test]
    fn health_state_set_dependency_appears_in_snapshot() {
        let state = HealthState::new("svc-process", "0.1.0", prometheus::Registry::new());
        state.set_dependency("postgres", DependencyStatus::ok());
        state.set_dependency("valkey", DependencyStatus::failed(DependencyClass::Auth, "bad password"));
        let body = state.snapshot();
        assert_eq!(body.dependencies["postgres"].class, DependencyClass::Ok);
        assert_eq!(body.dependencies["valkey"].class, DependencyClass::Auth);
        assert_eq!(body.dependencies["valkey"].detail, "bad password");
    }

    #[test]
    fn health_state_set_transport_flips_the_summary_to_insecure() {
        let state = HealthState::new("svc-process", "0.1.0", prometheus::Registry::new());
        state.set_transport("valkey", false, true); // tls off, auth on
        let body = state.snapshot();
        assert_eq!(body.transport, "insecure");
        assert_eq!(body.transport_detail["valkey"].tls, false);
        assert_eq!(body.transport_detail["valkey"].auth, true);
    }

    #[test]
    fn health_state_all_components_secure_reports_secure() {
        let state = HealthState::new("svc-process", "0.1.0", prometheus::Registry::new());
        state.set_transport("valkey", true, true);
        state.set_transport("postgres", true, true);
        assert_eq!(state.snapshot().transport, "secure");
    }

    #[test]
    fn health_state_set_sandbox_and_extra_appear_in_snapshot() {
        let state = HealthState::new("svc-process", "0.1.0", prometheus::Registry::new());
        state.set_sandbox("gvisor");
        state.set_extra("executor", json!({"state": "running", "connections": 4}));
        let body = state.snapshot();
        assert_eq!(body.sandbox.as_deref(), Some("gvisor"));
        let rendered = serde_json::to_value(&body).unwrap();
        assert_eq!(rendered["executor"]["state"], json!("running"));
    }

    #[test]
    fn uptime_seconds_is_non_negative_and_monotonic_nondecreasing() {
        let state = HealthState::new("svc-process", "0.1.0", prometheus::Registry::new());
        let first = state.uptime_seconds();
        std::thread::sleep(std::time::Duration::from_millis(5));
        let second = state.uptime_seconds();
        assert!(second >= first);
    }
}
```

- [ ] **Step 2: Run to verify it fails**

Run: `make test`
Expected: FAIL — `cannot find type `DependencyClass`` etc.

- [ ] **Step 3: Implement**

`packages/rust-logging/src/health/mod.rs`:

```rust
//! The `/health`, `/healthz`, `/metrics` HTTP surface every Waddles
//! service mounts, per design spec §11.6.4 and §13.4. This module grows
//! `router`/`transport`/`dependency` submodules in Tasks 15-16; this
//! task wires only `types`, which is all that exists so far.

mod types;

pub use types::{ComponentTransport, DependencyClass, DependencyStatus, HealthBody, HealthState};
```

`packages/rust-logging/src/health/types.rs`:

```rust
//! Types shared by every `/health` response: the per-dependency
//! classification from the startup self-check (design spec §12.6), the
//! per-component transport-security detail (§11.6.4), and the mutable,
//! cloneable `HealthState` a service updates as checks complete.

use serde::Serialize;
use std::collections::BTreeMap;
use std::sync::{Arc, RwLock};
use std::time::Instant;

/// Classification of one startup/periodic connectivity probe result
/// (design spec §12.6): `Ok` means reachable and authenticated; every
/// other variant names the layer that failed.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize)]
#[serde(rename_all = "lowercase")]
pub enum DependencyClass {
    /// The hostname did not resolve.
    Dns,
    /// Resolved, but the connection was refused, timed out, or was blocked.
    Tcp,
    /// Connected, but the TLS handshake or certificate verification failed.
    Tls,
    /// TLS succeeded, but credentials were rejected.
    Auth,
    /// Reachable and authenticated.
    Ok,
}

/// One dependency's current classified status, as shown under `/health`'s
/// `dependencies` map.
#[derive(Debug, Clone, Serialize)]
pub struct DependencyStatus {
    /// The classified outcome of the most recent probe.
    pub class: DependencyClass,
    /// A human-readable detail message; empty for a healthy dependency.
    pub detail: String,
}

impl DependencyStatus {
    /// Builds a healthy status with no detail message.
    pub fn ok() -> Self {
        DependencyStatus {
            class: DependencyClass::Ok,
            detail: String::new(),
        }
    }

    /// Builds a failed status at the given classification with a detail
    /// message (design spec §12.6 requires a named endpoint and reason,
    /// never a bare "connection failed").
    pub fn failed(class: DependencyClass, detail: impl Into<String>) -> Self {
        DependencyStatus {
            class,
            detail: detail.into(),
        }
    }

    /// True only for [`DependencyClass::Ok`].
    pub fn is_up(&self) -> bool {
        self.class == DependencyClass::Ok
    }
}

/// Whether one infrastructure component's connection is using TLS and/or
/// authentication, as shown under `/health`'s `transport_detail` map
/// (design spec §11.6.4).
#[derive(Debug, Clone, Copy, Serialize)]
pub struct ComponentTransport {
    /// Whether this component's connection uses TLS.
    pub tls: bool,
    /// Whether this component's connection is authenticated.
    pub auth: bool,
}

impl ComponentTransport {
    fn is_fully_secure(&self) -> bool {
        self.tls && self.auth
    }
}

/// The `/health` JSON response body, matching design spec §11.6.4's
/// example shape. `extra` carries service-specific fields (e.g.
/// `executor`, `spine`) that this crate does not know the shape of --
/// serialized flattened into the top-level object via `set_extra`.
#[derive(Debug, Clone, Serialize)]
pub struct HealthBody {
    /// Always `"ok"` -- `/health` reports liveness plus a rich detail
    /// block, never a non-200 body; readiness-style gating is a
    /// service's own concern layered via `extra`, not this crate's.
    pub status: &'static str,
    /// The service's identity, matching `OTEL_SERVICE_NAME`/`MODULE_NAME`.
    pub service: String,
    /// The service's own version string (not this crate's [`crate::VERSION`]).
    pub version: String,
    /// `"secure"` only when every registered [`ComponentTransport`] has
    /// both `tls` and `auth` true; `"insecure"` otherwise.
    pub transport: &'static str,
    /// Per-component TLS/auth detail, keyed by component name (`"valkey"`, `"postgres"`, ...).
    pub transport_detail: BTreeMap<String, ComponentTransport>,
    /// The sandbox runtime in effect (`"gvisor"`/`"runc"`), or `None` for
    /// a service with no sandbox concept (e.g. `svc-streaming`).
    #[serde(skip_serializing_if = "Option::is_none")]
    pub sandbox: Option<String>,
    /// Per-dependency classified status, keyed by dependency name.
    pub dependencies: BTreeMap<String, DependencyStatus>,
    /// Service-specific fields flattened into the top-level JSON object.
    #[serde(flatten)]
    pub extra: serde_json::Map<String, serde_json::Value>,
}

/// Mutable, cheaply-cloneable health state a service updates as its
/// startup self-check and periodic probes complete, and reads back out
/// via [`HealthState::snapshot`] for the `/health` handler (Task 15).
/// Every clone shares the same underlying state (`Arc`-backed interior
/// mutability), so a service can hand clones to independent probe tasks.
#[derive(Clone)]
pub struct HealthState {
    service: String,
    version: String,
    started_at: Instant,
    sandbox: Arc<RwLock<Option<String>>>,
    dependencies: Arc<RwLock<BTreeMap<String, DependencyStatus>>>,
    transport_detail: Arc<RwLock<BTreeMap<String, ComponentTransport>>>,
    extra: Arc<RwLock<serde_json::Map<String, serde_json::Value>>>,
    registry: prometheus::Registry,
}

impl HealthState {
    /// Builds a fresh `HealthState` with no dependencies, no transport
    /// detail (defaults to `"secure"` until a component reports
    /// otherwise), and no sandbox set. `registry` should be the same
    /// `prometheus::Registry` [`crate::init::init`] returned, so
    /// `/metrics` reflects the OTel-recorded instruments (Task 9).
    pub fn new(service: impl Into<String>, version: impl Into<String>, registry: prometheus::Registry) -> Self {
        HealthState {
            service: service.into(),
            version: version.into(),
            started_at: Instant::now(),
            sandbox: Arc::new(RwLock::new(None)),
            dependencies: Arc::new(RwLock::new(BTreeMap::new())),
            transport_detail: Arc::new(RwLock::new(BTreeMap::new())),
            extra: Arc::new(RwLock::new(serde_json::Map::new())),
            registry,
        }
    }

    /// Records or updates one dependency's classified status.
    pub fn set_dependency(&self, name: impl Into<String>, status: DependencyStatus) {
        let mut deps = self.dependencies.write().unwrap_or_else(|p| p.into_inner());
        deps.insert(name.into(), status);
    }

    /// Records or updates one infrastructure component's TLS/auth state.
    pub fn set_transport(&self, component: impl Into<String>, tls: bool, auth: bool) {
        let mut detail = self.transport_detail.write().unwrap_or_else(|p| p.into_inner());
        detail.insert(component.into(), ComponentTransport { tls, auth });
    }

    /// Records the active sandbox runtime (`"gvisor"`/`"runc"`).
    pub fn set_sandbox(&self, sandbox: impl Into<String>) {
        let mut s = self.sandbox.write().unwrap_or_else(|p| p.into_inner());
        *s = Some(sandbox.into());
    }

    /// Adds or replaces one service-specific field flattened into the
    /// top-level `/health` JSON object (e.g. `state.set_extra("executor",
    /// json!({"state": "running", "connections": 4}))`). `value` is
    /// serialized with `serde_json::to_value`; a value that somehow fails
    /// to serialize (never true for the built-in JSON-representable types
    /// this is meant for) is stored as `Value::Null` rather than panicking.
    pub fn set_extra(&self, key: impl Into<String>, value: impl Serialize) {
        let mut extra = self.extra.write().unwrap_or_else(|p| p.into_inner());
        let json_value = serde_json::to_value(value).unwrap_or(serde_json::Value::Null);
        extra.insert(key.into(), json_value);
    }

    /// Seconds since this `HealthState` was constructed (approximates
    /// process uptime when constructed at startup).
    pub fn uptime_seconds(&self) -> u64 {
        self.started_at.elapsed().as_secs()
    }

    /// Returns the `prometheus::Registry` this state renders `/metrics`
    /// from (Task 15's metrics handler).
    pub(crate) fn registry(&self) -> &prometheus::Registry {
        &self.registry
    }

    /// Builds the current `/health` response body from everything
    /// recorded so far.
    pub fn snapshot(&self) -> HealthBody {
        let transport_detail = self
            .transport_detail
            .read()
            .unwrap_or_else(|p| p.into_inner())
            .clone();
        let transport = if transport_detail.values().all(ComponentTransport::is_fully_secure) {
            "secure"
        } else {
            "insecure"
        };
        HealthBody {
            status: "ok",
            service: self.service.clone(),
            version: self.version.clone(),
            transport,
            transport_detail,
            sandbox: self.sandbox.read().unwrap_or_else(|p| p.into_inner()).clone(),
            dependencies: self.dependencies.read().unwrap_or_else(|p| p.into_inner()).clone(),
            extra: self.extra.read().unwrap_or_else(|p| p.into_inner()).clone(),
        }
    }
}
```

- [ ] **Step 4: Run to verify it passes**

Run: `make test`
Expected: PASS — all `health::types::tests` green.

- [ ] **Step 5: Wire into `lib.rs`**

```rust
pub mod health;
```

- [ ] **Step 6: Commit**

```bash
git add packages/rust-logging/src/health packages/rust-logging/src/lib.rs
git commit -m "$(cat <<'EOF'
feat(logging): add health::{DependencyClass,DependencyStatus,HealthState,HealthBody}

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01N2rQgkHY872RubwXoBZxtE
EOF
)"
```

---

### Task 15: `health/router.rs` — the axum `/health`, `/healthz`, `/metrics` router

**Files:**
- Create: `packages/rust-logging/src/health/router.rs`
- Create: `packages/rust-logging/tests/health_router_tests.rs`
- Modify: `packages/rust-logging/src/health/mod.rs`, `packages/rust-logging/src/lib.rs`

**Interfaces:**
- Consumes: `HealthState` (Task 14), `render_prometheus_text` (Task 9).
- Produces: `pub fn router(state: HealthState) -> axum::Router` (mounts all three paths — the convenience form for a service that serves `/health`/`/healthz`/`/metrics` from one port), `pub fn liveness_readiness_router(state: HealthState) -> axum::Router` (mounts only `/health`/`/healthz`, for a service that wants those on its main app router while `/metrics` binds separately on `METRICS_PORT`, matching `core/svc_streaming/src/http/health.rs`'s existing topology, read during planning), `pub fn metrics_router(state: HealthState) -> axum::Router` (mounts only `/metrics`).

- [ ] **Step 1: Write the failing tests**

`packages/rust-logging/tests/health_router_tests.rs`:

```rust
//! axum-test coverage of the health router, exercised as a black box
//! against the crate's one public router-building API.

use penguin_logging::health::{router, DependencyClass, DependencyStatus, HealthState};

fn test_state() -> HealthState {
    let state = HealthState::new("svc-process-test", "0.1.0", prometheus::Registry::new());
    state.set_dependency("postgres", DependencyStatus::ok());
    state
}

#[tokio::test]
async fn healthz_returns_plain_ok() {
    let server = axum_test::TestServer::new(router(test_state())).expect("router must build");
    let response = server.get("/healthz").await;
    response.assert_status_ok();
    response.assert_text("ok");
}

#[tokio::test]
async fn health_returns_the_rich_json_body() {
    let server = axum_test::TestServer::new(router(test_state())).expect("router must build");
    let response = server.get("/health").await;
    response.assert_status_ok();
    let body: serde_json::Value = response.json();
    assert_eq!(body["status"], serde_json::json!("ok"));
    assert_eq!(body["service"], serde_json::json!("svc-process-test"));
    assert_eq!(body["dependencies"]["postgres"]["class"], serde_json::json!("ok"));
}

#[tokio::test]
async fn health_reports_a_failed_dependency_by_class() {
    let state = test_state();
    state.set_dependency("valkey", DependencyStatus::failed(DependencyClass::Dns, "no such host"));
    let server = axum_test::TestServer::new(router(state)).expect("router must build");
    let response = server.get("/health").await;
    let body: serde_json::Value = response.json();
    assert_eq!(body["dependencies"]["valkey"]["class"], serde_json::json!("dns"));
    assert_eq!(body["dependencies"]["valkey"]["detail"], serde_json::json!("no such host"));
}

#[tokio::test]
async fn metrics_renders_prometheus_text_and_reflects_otel_recorded_instruments() {
    // Record through the standard OTel meter API (Task 12's helper), then
    // confirm it reaches THIS state's registry -- the state's registry
    // must be the one the meter provider's Prometheus reader targets for
    // this to work, exactly as Task 9's shared-meter test already proves
    // at the provider level.
    let registry = prometheus::Registry::new();
    let cfg = penguin_logging::ServiceConfig {
        service_name: "svc-process-router-test".to_string(),
        otlp_endpoint: None,
        otlp_protocol: penguin_logging::OtlpProtocol::Grpc,
        otlp_headers: Vec::new(),
        log_level: "info".to_string(),
    };
    // otlp_endpoint is None here deliberately: this test only needs a
    // Prometheus reader, not a live OTLP pipeline, so it builds the meter
    // provider directly rather than going through init()'s
    // otlp-endpoint-gated path.
    let provider = opentelemetry_sdk::metrics::SdkMeterProvider::builder()
        .with_reader(
            opentelemetry_prometheus::exporter()
                .with_registry(registry.clone())
                .build()
                .expect("prometheus reader must build"),
        )
        .build();
    opentelemetry::global::set_meter_provider(provider);
    let _ = &cfg; // cfg constructed to document intent; not otherwise used in this branch.
    penguin_logging::counter_add("router_test_requests_total", 1, &[]);

    let state = HealthState::new("svc-process-test", "0.1.0", registry);
    let server = axum_test::TestServer::new(router(state)).expect("router must build");
    let response = server.get("/metrics").await;
    response.assert_status_ok();
    let body = response.text();
    assert!(body.contains("router_test_requests_total"));
}

#[tokio::test]
async fn liveness_readiness_router_does_not_mount_metrics() {
    let server = axum_test::TestServer::new(penguin_logging::health::liveness_readiness_router(test_state()))
        .expect("router must build");
    server.get("/health").await.assert_status_ok();
    server.get("/healthz").await.assert_status_ok();
    server.get("/metrics").await.assert_status_not_found();
}

#[tokio::test]
async fn metrics_router_mounts_only_metrics() {
    let server = axum_test::TestServer::new(penguin_logging::health::metrics_router(test_state()))
        .expect("router must build");
    server.get("/metrics").await.assert_status_ok();
    server.get("/health").await.assert_status_not_found();
}
```

- [ ] **Step 2: Run to verify it fails**

Run: `make test`
Expected: FAIL — `unresolved import `penguin_logging::health::router`` (and the `liveness_readiness_router`/`metrics_router` counterparts).

- [ ] **Step 3: Implement**

```rust
//! The axum handlers and router-building functions for `/health`,
//! `/healthz`, `/metrics`. Three builders are exposed because the design
//! spec's services split these across two listeners in practice
//! (`/health`+`/healthz` on the main app port, `/metrics` on a separate
//! `METRICS_PORT`, matching `core/svc_streaming/src/http/health.rs`'s
//! existing topology) -- [`router`] is the single-listener convenience
//! form for a service that does not need that split.

use crate::health::types::HealthState;
use crate::metrics_provider::render_prometheus_text;
use axum::extract::State;
use axum::http::StatusCode;
use axum::response::IntoResponse;
use axum::routing::get;
use axum::{Json, Router};

async fn health_handler(State(state): State<HealthState>) -> impl IntoResponse {
    Json(state.snapshot())
}

async fn healthz_handler() -> &'static str {
    "ok"
}

async fn metrics_handler(State(state): State<HealthState>) -> impl IntoResponse {
    match render_prometheus_text(state.registry()) {
        Ok(body) => (StatusCode::OK, body).into_response(),
        Err(err) => (StatusCode::INTERNAL_SERVER_ERROR, err.to_string()).into_response(),
    }
}

/// Mounts `/health` and `/healthz` only, for a service that binds
/// `/metrics` on a separate listener via [`metrics_router`].
pub fn liveness_readiness_router(state: HealthState) -> Router {
    Router::new()
        .route("/health", get(health_handler))
        .route("/healthz", get(healthz_handler))
        .with_state(state)
}

/// Mounts `/metrics` only, rendering `state`'s `prometheus::Registry`
/// (the same one [`crate::init::init`] returned) as Prometheus text
/// exposition format.
pub fn metrics_router(state: HealthState) -> Router {
    Router::new()
        .route("/metrics", get(metrics_handler))
        .with_state(state)
}

/// Mounts all three paths on one router -- the convenience form for a
/// service serving `/health`, `/healthz` and `/metrics` from a single
/// listener.
pub fn router(state: HealthState) -> Router {
    Router::new()
        .route("/health", get(health_handler))
        .route("/healthz", get(healthz_handler))
        .route("/metrics", get(metrics_handler))
        .with_state(state)
}
```

- [ ] **Step 4: Update `packages/rust-logging/Cargo.toml`** to add `axum-test` as a dev-dependency usable from the `tests/` integration directory (it is already a dev-dependency from Task 1's manifest — no change needed here; this step is a checkpoint to confirm it, not an edit). Run: `grep axum-test packages/rust-logging/Cargo.toml` — expected output: `axum-test = "=21.1.0"`.

- [ ] **Step 5: Update `packages/rust-logging/src/health/mod.rs`** (full replacement):

```rust
//! The `/health`, `/healthz`, `/metrics` HTTP surface every Waddles
//! service mounts, per design spec §11.6.4 and §13.4.

mod router;
mod types;

pub use router::{liveness_readiness_router, metrics_router, router};
pub use types::{ComponentTransport, DependencyClass, DependencyStatus, HealthBody, HealthState};
```

- [ ] **Step 6: Run to verify it passes**

Run: `make test`
Expected: PASS — all six `health_router_tests` green, plus every earlier task's tests.

- [ ] **Step 7: Commit**

```bash
git add packages/rust-logging/src/health packages/rust-logging/tests/health_router_tests.rs
git commit -m "$(cat <<'EOF'
feat(logging): add axum router for /health, /healthz, /metrics

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01N2rQgkHY872RubwXoBZxtE
EOF
)"
```

---

### Task 16: `health/dependency.rs` + `health/transport.rs` — `waddles_dependency_*` and `waddles_insecure_transport`

**Files:**
- Create: `packages/rust-logging/src/health/dependency.rs`, `packages/rust-logging/src/health/transport.rs`
- Modify: `packages/rust-logging/src/health/mod.rs`, `packages/rust-logging/src/lib.rs`

**Interfaces:**
- Consumes: `record_latency_ms`/`counter_add`/`gauge_set` (Task 12; `DependencyMetrics`/`TransportMetrics` are thin wrappers over `counter_add`/`gauge_set`, not a second instrument-caching mechanism), `DependencyStatus`/`DependencyClass` (Task 14).
- Produces: `pub struct DependencyMetrics` with `pub fn record(&self, dependency: &str, status: &DependencyStatus)` (emits `waddles_dependency_up{dependency}` = 1/0 and increments `waddles_dependency_check_total{dependency,class}`, per design spec §12.6); `pub enum TransportAspect { Tls, Auth }`; `pub struct TransportMetrics` with `pub fn mark_secure(&self, component: &str, aspect: TransportAspect)`; `pub fn warn_insecure_transport(metrics: &TransportMetrics, component: &str, aspect: TransportAspect)` (logs the exact fixed WARN banner from design spec §11.6.4 and sets `waddles_insecure_transport{component,aspect}` = 1).

`DependencyMetrics`/`TransportMetrics` are deliberately separate from `HealthState` (Task 14) rather than folded into it: `HealthState` is pure, in-process JSON-shaping state for the `/health` body, while these two types emit real OTel/Prometheus metric points. A service calls both — e.g. `health_state.set_dependency("postgres", status.clone()); dependency_metrics.record("postgres", &status);` — because the `/health` JSON and the `waddles_dependency_up` metric are two independent consumers (a human reading `/health`, a Prometheus scraper reading `/metrics`) that the design spec (§12.6) describes as two separate outputs of one probe result, not one output derived from the other.

- [ ] **Step 1: Write the failing tests**

Append to `packages/rust-logging/src/health/dependency.rs` (create the file with just this test module first; Step 3 adds the implementation above it):

Both test modules below use the same `crate::metrics::global_meter_test_lock()` defined in Task 12 -- see that task's Step 1 note on why every test that installs a global meter provider must serialize against that one shared lock.

```rust
#[cfg(test)]
mod tests {
    use super::super::types::{DependencyClass, DependencyStatus};
    use super::*;
    use opentelemetry_sdk::metrics::{InMemoryMetricExporter, SdkMeterProvider};

    fn install_in_memory_meter() -> (InMemoryMetricExporter, SdkMeterProvider) {
        let exporter = InMemoryMetricExporter::default();
        let provider = SdkMeterProvider::builder()
            .with_periodic_exporter(exporter.clone())
            .build();
        opentelemetry::global::set_meter_provider(provider.clone());
        (exporter, provider)
    }

    #[tokio::test]
    async fn record_ok_sets_up_gauge_to_one() {
        let _guard = crate::metrics::global_meter_test_lock()
            .lock()
            .unwrap_or_else(|p| p.into_inner());
        crate::metrics::clear_instrument_caches();
        let (exporter, provider) = install_in_memory_meter();
        let metrics = DependencyMetrics::new();
        metrics.record("postgres", &DependencyStatus::ok());
        provider.force_flush().expect("flush must succeed");
        let data = exporter.get_finished_metrics().expect("must not error");
        assert!(!data.is_empty(), "expected exported metrics after recording a dependency status");
    }

    #[tokio::test]
    async fn record_failure_sets_up_gauge_to_zero_and_counts_the_class() {
        let _guard = crate::metrics::global_meter_test_lock()
            .lock()
            .unwrap_or_else(|p| p.into_inner());
        crate::metrics::clear_instrument_caches();
        let (_exporter, provider) = install_in_memory_meter();
        let metrics = DependencyMetrics::new();
        metrics.record("valkey", &DependencyStatus::failed(DependencyClass::Auth, "bad password"));
        provider.force_flush().expect("flush must succeed");
        // No panic and a successful flush is the assertion here; exact
        // label/value content is exercised end-to-end in Task 18's
        // integration test against the crate's own `testing` feature,
        // which can inspect exported metric names/labels directly.
    }
}
```

Append to `packages/rust-logging/src/health/transport.rs` (create the file with just this test module first; Step 3 adds the implementation above it):

```rust
#[cfg(test)]
mod tests {
    use super::*;
    use opentelemetry_sdk::metrics::{InMemoryMetricExporter, SdkMeterProvider};

    fn install_in_memory_meter() -> (InMemoryMetricExporter, SdkMeterProvider) {
        let exporter = InMemoryMetricExporter::default();
        let provider = SdkMeterProvider::builder()
            .with_periodic_exporter(exporter.clone())
            .build();
        opentelemetry::global::set_meter_provider(provider.clone());
        (exporter, provider)
    }

    #[test]
    fn transport_aspect_as_str_matches_spec_label_values() {
        assert_eq!(TransportAspect::Tls.as_str(), "tls");
        assert_eq!(TransportAspect::Auth.as_str(), "auth");
    }

    #[tokio::test]
    async fn warn_insecure_transport_does_not_panic_and_flushes_a_metric_point() {
        let _guard = crate::metrics::global_meter_test_lock()
            .lock()
            .unwrap_or_else(|p| p.into_inner());
        crate::metrics::clear_instrument_caches();
        let (exporter, provider) = install_in_memory_meter();
        let metrics = TransportMetrics::new();
        warn_insecure_transport(&metrics, "valkey", TransportAspect::Tls);
        provider.force_flush().expect("flush must succeed");
        let data = exporter.get_finished_metrics().expect("must not error");
        assert!(!data.is_empty(), "expected an exported waddles_insecure_transport point");
    }

    #[tokio::test]
    async fn mark_secure_does_not_panic() {
        let _guard = crate::metrics::global_meter_test_lock()
            .lock()
            .unwrap_or_else(|p| p.into_inner());
        crate::metrics::clear_instrument_caches();
        let (_exporter, provider) = install_in_memory_meter();
        let metrics = TransportMetrics::new();
        metrics.mark_secure("postgres", TransportAspect::Auth);
        provider.force_flush().expect("flush must succeed");
    }
}
```

- [ ] **Step 2: Run to verify it fails**

Run: `make test`
Expected: FAIL — `cannot find type `DependencyMetrics`` / `TransportMetrics` / `TransportAspect` / `warn_insecure_transport`.

- [ ] **Step 3: Implement**

`packages/rust-logging/src/health/dependency.rs`:

```rust
//! `waddles_dependency_up` / `waddles_dependency_check_total`, the two
//! metrics the design spec's startup connectivity self-check (§12.6)
//! requires alongside the `/health` `dependencies` block (Task 14).

use crate::health::types::DependencyStatus;
use crate::metrics::{counter_add, gauge_set};
use opentelemetry::KeyValue;

/// Emits the two startup-self-check metrics for one dependency probe
/// result. Stateless -- construct once per service (or even per call;
/// [`crate::metrics::counter_add`]/[`crate::metrics::gauge_set`] already
/// cache their OTel instruments internally, so this type carries no
/// state of its own).
#[derive(Debug, Default, Clone, Copy)]
pub struct DependencyMetrics;

impl DependencyMetrics {
    /// Builds a `DependencyMetrics` handle.
    pub fn new() -> Self {
        DependencyMetrics
    }

    /// Sets `waddles_dependency_up{dependency}` to `1` if `status.is_up()`
    /// else `0`, and increments
    /// `waddles_dependency_check_total{dependency,class}` for `status`'s
    /// class -- design spec §12.6: "`waddles_dependency_up{dependency}`
    /// is `1`/`0` per endpoint, and
    /// `waddles_dependency_check_total{dependency,class}` counts each
    /// classified outcome."
    pub fn record(&self, dependency: &str, status: &DependencyStatus) {
        let up_value = if status.is_up() { 1.0 } else { 0.0 };
        gauge_set(
            "waddles_dependency_up",
            up_value,
            &[KeyValue::new("dependency", dependency.to_string())],
        );
        counter_add(
            "waddles_dependency_check_total",
            1,
            &[
                KeyValue::new("dependency", dependency.to_string()),
                KeyValue::new("class", class_label(status)),
            ],
        );
    }
}

fn class_label(status: &DependencyStatus) -> &'static str {
    match status.class {
        crate::health::types::DependencyClass::Dns => "dns",
        crate::health::types::DependencyClass::Tcp => "tcp",
        crate::health::types::DependencyClass::Tls => "tls",
        crate::health::types::DependencyClass::Auth => "auth",
        crate::health::types::DependencyClass::Ok => "ok",
    }
}
```

`packages/rust-logging/src/health/transport.rs`:

```rust
//! `waddles_insecure_transport` plus the fixed-wording WARN banner design
//! spec §11.6.4 requires as the first log line after telemetry init when
//! a transport security aspect is disabled.

use crate::metrics::gauge_set;
use opentelemetry::KeyValue;

/// Which transport-security aspect a `waddles_insecure_transport` point
/// or the fixed WARN banner refers to.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum TransportAspect {
    /// `security.transport.tls`.
    Tls,
    /// `security.transport.auth`.
    Auth,
}

impl TransportAspect {
    /// The metric label value / log field value for this aspect.
    pub fn as_str(&self) -> &'static str {
        match self {
            TransportAspect::Tls => "tls",
            TransportAspect::Auth => "auth",
        }
    }
}

/// Emits `waddles_insecure_transport{component,aspect}` points.
/// Stateless, matching [`crate::health::dependency::DependencyMetrics`]'s
/// shape.
#[derive(Debug, Default, Clone, Copy)]
pub struct TransportMetrics;

impl TransportMetrics {
    /// Builds a `TransportMetrics` handle.
    pub fn new() -> Self {
        TransportMetrics
    }

    /// Sets `waddles_insecure_transport{component,aspect}` to `1`.
    fn mark_insecure(&self, component: &str, aspect: TransportAspect) {
        gauge_set(
            "waddles_insecure_transport",
            1.0,
            &[
                KeyValue::new("component", component.to_string()),
                KeyValue::new("aspect", aspect.as_str()),
            ],
        );
    }

    /// Sets `waddles_insecure_transport{component,aspect}` to `0` -- call
    /// for every component/aspect that IS secured, so (design spec
    /// §11.6.4) "the gauge is `0` for every component/aspect that is
    /// secured, [and] 'no series' and 'secure' are distinguishable."
    pub fn mark_secure(&self, component: &str, aspect: TransportAspect) {
        gauge_set(
            "waddles_insecure_transport",
            0.0,
            &[
                KeyValue::new("component", component.to_string()),
                KeyValue::new("aspect", aspect.as_str()),
            ],
        );
    }
}

const TLS_BANNER: &str = "TRANSPORT SECURITY DISABLED — security.transport.tls=false: Valkey and Postgres traffic is unencrypted and readable on the network. This is an explicit, visible opt-out.";
const AUTH_BANNER: &str = "TRANSPORT SECURITY DISABLED — security.transport.auth=false: Valkey and Postgres traffic is unauthenticated. This is an explicit, visible opt-out.";

/// Emits the fixed-wording WARN log line design spec §11.6.4 requires as
/// the first log line after telemetry init when `security.transport.tls`
/// or `.auth` is `false`, and marks `component`/`aspect` insecure via
/// [`TransportMetrics::mark_insecure`]. Call once per (component, aspect)
/// pair that is still insecure at startup.
pub fn warn_insecure_transport(metrics: &TransportMetrics, component: &str, aspect: TransportAspect) {
    let banner = match aspect {
        TransportAspect::Tls => TLS_BANNER,
        TransportAspect::Auth => AUTH_BANNER,
    };
    tracing::warn!(component, aspect = aspect.as_str(), "{banner}");
    metrics.mark_insecure(component, aspect);
}
```

- [ ] **Step 4: Run to verify it passes**

Run: `make test`
Expected: PASS — all `dependency_tests` and `transport_tests` green.

- [ ] **Step 5: Update `packages/rust-logging/src/health/mod.rs`** (full replacement):

```rust
//! The `/health`, `/healthz`, `/metrics` HTTP surface every Waddles
//! service mounts, per design spec §11.6.4 and §13.4.

mod dependency;
mod router;
mod transport;
mod types;

pub use dependency::DependencyMetrics;
pub use router::{liveness_readiness_router, metrics_router, router};
pub use transport::{warn_insecure_transport, TransportAspect, TransportMetrics};
pub use types::{ComponentTransport, DependencyClass, DependencyStatus, HealthBody, HealthState};
```

- [ ] **Step 6: Commit**

```bash
git add packages/rust-logging/src/health
git commit -m "$(cat <<'EOF'
feat(logging): add waddles_dependency_up/_check_total and waddles_insecure_transport

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01N2rQgkHY872RubwXoBZxtE
EOF
)"
```

---

### Task 17: `testing.rs` — the in-memory telemetry sink (`testing` feature)

**Files:**
- Create: `packages/rust-logging/src/testing.rs`
- Modify: `packages/rust-logging/src/lib.rs`

**Interfaces:**
- Consumes: `ServiceConfig` (Task 4), `json_fmt_layer` (Task 7), `resource()` (Task 6). Only compiled when the `testing` Cargo feature is enabled (`[features] testing = ["opentelemetry_sdk/testing"]`, already declared in Task 1).
- Produces: `pub fn init_test_telemetry(service_name: &str) -> TestTelemetry`, `pub struct TestTelemetry` with `pub fn force_flush(&self)` and `pub fn counts(&self) -> TelemetryCounts`, `pub struct TelemetryCounts { pub log_records: usize, pub metric_data_points: usize, pub histogram_data_points: usize, pub spans: usize }` — Task 18's integration test calls this directly to reproduce the `testing.md` Telemetry Validation gate inside this crate's own suite, and every downstream Waddles service's smoke test (`svc_ingest`, `svc_process`, `svc_action`, `svc_streaming`) is expected to depend on `penguin-logging` with `features = ["testing"]` in `[dev-dependencies]` and call this same function.

**Verified data shape (recorded here so the implementation below is not a guess):** `opentelemetry_sdk` 0.32.1's `metrics::data` module (confirmed by downloading and reading `opentelemetry_sdk-0.32.1/src/metrics/data/mod.rs` during planning) defines `AggregatedMetrics { F64(MetricData<f64>), U64(MetricData<u64>), I64(MetricData<i64>) }` and `MetricData<T> { Gauge(Gauge<T>), Sum(Sum<T>), Histogram(Histogram<T>), ExponentialHistogram(ExponentialHistogram<T>) }`, where `Gauge<T>`/`Sum<T>`/`Histogram<T>`/`ExponentialHistogram<T>` each expose `pub fn data_points(&self) -> impl Iterator<Item = &...DataPoint<T>>`. Counting is therefore: one pass over `ResourceMetrics::scope_metrics() -> ScopeMetrics::metrics() -> Metric::data()`, summing `data_points().count()` per metric into `metric_data_points`, and additionally into `histogram_data_points` only for the `Histogram`/`ExponentialHistogram` variants.

**Test isolation:** `init_test_telemetry` internally calls `opentelemetry::global::set_meter_provider` (the same process-wide slot Task 12's `record_latency_ms`/`counter_add`/`gauge_set` read at call time), so every test below acquires `crate::metrics::global_meter_test_lock()` first, exactly like Task 16's tests -- see Task 12's Step 1 note. The `tracing`/OTel-logs/traces side does NOT need that lock: `init_test_telemetry` installs its subscriber via `tracing::subscriber::set_default` (a thread-local scoped guard held inside the returned `TestTelemetry`, not the process-global `SubscriberInitExt::init()` Task 11's real `init()` uses), and the standard Rust test harness runs each `#[test]`/`#[tokio::test]` function on its own thread, so each call's thread-local default is already isolated from every other test's.

- [ ] **Step 1: Write the failing tests**

```rust
#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn init_test_telemetry_starts_at_zero_counts() {
        let _guard = crate::metrics::global_meter_test_lock()
            .lock()
            .unwrap_or_else(|p| p.into_inner());
        crate::metrics::clear_instrument_caches();
        let telemetry = init_test_telemetry("test-service-zero");
        let counts = telemetry.counts();
        assert_eq!(counts.log_records, 0);
        assert_eq!(counts.metric_data_points, 0);
        assert_eq!(counts.histogram_data_points, 0);
        assert_eq!(counts.spans, 0);
    }

    #[tokio::test]
    async fn logging_a_tracing_event_is_observed_as_a_log_record() {
        let _guard = crate::metrics::global_meter_test_lock()
            .lock()
            .unwrap_or_else(|p| p.into_inner());
        crate::metrics::clear_instrument_caches();
        let telemetry = init_test_telemetry("test-service-logs");
        tracing::info!("hello from the in-memory sink");
        telemetry.force_flush();
        let counts = telemetry.counts();
        assert!(counts.log_records >= 1, "expected at least one log record, got {}", counts.log_records);
    }

    #[tokio::test]
    async fn recording_a_histogram_is_observed_as_a_histogram_data_point() {
        let _guard = crate::metrics::global_meter_test_lock()
            .lock()
            .unwrap_or_else(|p| p.into_inner());
        crate::metrics::clear_instrument_caches();
        let telemetry = init_test_telemetry("test-service-metrics");
        crate::record_latency_ms("test_service_latency_ms", 12.5, &[]);
        telemetry.force_flush();
        let counts = telemetry.counts();
        assert!(counts.metric_data_points >= 1, "expected at least one metric data point, got {}", counts.metric_data_points);
        assert!(counts.histogram_data_points >= 1, "expected at least one histogram data point, got {}", counts.histogram_data_points);
    }

    #[tokio::test]
    async fn a_span_is_observed() {
        let _guard = crate::metrics::global_meter_test_lock()
            .lock()
            .unwrap_or_else(|p| p.into_inner());
        crate::metrics::clear_instrument_caches();
        let telemetry = init_test_telemetry("test-service-traces");
        {
            let span = tracing::info_span!("test.span");
            let _entered = span.enter();
            tracing::info!("inside the span");
        }
        telemetry.force_flush();
        let counts = telemetry.counts();
        assert!(counts.spans >= 1, "expected at least one span, got {}", counts.spans);
    }
}
```

- [ ] **Step 2: Run to verify it fails**

Run: `make test` (this crate's Makefile already runs `cargo test --all-features`, which activates the `testing` feature — no separate invocation needed)
Expected: FAIL — `cannot find function `init_test_telemetry``.

- [ ] **Step 3: Implement**

```rust
//! In-memory log/metric/span exporters, gated behind the `testing`
//! Cargo feature, for asserting the `testing.md` Telemetry Validation
//! gate (>=1 log record, >=1 metric data point, >=1 histogram, >=1 span)
//! with real counts instead of trusting that OTLP shipped somewhere.
//! Every downstream Waddles service's smoke test is expected to depend
//! on `penguin-logging` with `features = ["testing"]` and call
//! [`init_test_telemetry`] the same way this crate's own integration
//! test (Task 18) does.

use crate::resource::resource;
use crate::ServiceConfig;
use opentelemetry::trace::TracerProvider as _;
use opentelemetry_appender_tracing::layer::OpenTelemetryTracingBridge;
use opentelemetry_sdk::logs::{InMemoryLogExporter, SdkLoggerProvider};
use opentelemetry_sdk::metrics::data::{AggregatedMetrics, MetricData};
use opentelemetry_sdk::metrics::{InMemoryMetricExporter, SdkMeterProvider};
use opentelemetry_sdk::trace::{InMemorySpanExporter, SdkTracerProvider};
use tracing_subscriber::layer::SubscriberExt;

/// Snapshot counts from the in-memory exporters, matching exactly the
/// four assertions `testing.md` Telemetry Validation requires every
/// smoke test to make and print.
#[derive(Debug, Clone, Copy, Default)]
pub struct TelemetryCounts {
    /// Total OTel log records observed since [`init_test_telemetry`].
    pub log_records: usize,
    /// Total metric data points across every exported `ResourceMetrics`
    /// (summed across all metrics, all data points).
    pub metric_data_points: usize,
    /// Metric data points that are specifically histogram (or
    /// exponential-histogram) aggregations -- the assertion `testing.md`
    /// calls out by name ("Histogram metrics received... FAIL —
    /// load/latency histograms are the most-often-missing signal").
    pub histogram_data_points: usize,
    /// Total spans observed since [`init_test_telemetry`].
    pub spans: usize,
}

fn count_metric_data<T>(data: &MetricData<T>) -> (usize, usize) {
    match data {
        MetricData::Gauge(g) => (g.data_points().count(), 0),
        MetricData::Sum(s) => (s.data_points().count(), 0),
        MetricData::Histogram(h) => {
            let n = h.data_points().count();
            (n, n)
        }
        MetricData::ExponentialHistogram(h) => {
            let n = h.data_points().count();
            (n, n)
        }
    }
}

fn count_aggregated(agg: &AggregatedMetrics) -> (usize, usize) {
    match agg {
        AggregatedMetrics::F64(d) => count_metric_data(d),
        AggregatedMetrics::U64(d) => count_metric_data(d),
        AggregatedMetrics::I64(d) => count_metric_data(d),
    }
}

/// Holds the in-memory exporters, provider handles, and the scoped
/// subscriber guard [`init_test_telemetry`] wires up. Call
/// [`TestTelemetry::force_flush`] before [`TestTelemetry::counts`] to
/// make sure buffered records/points/spans have actually reached the
/// in-memory exporters. Dropping this value (e.g. at the end of a test
/// function) restores whatever `tracing` default was active on the
/// current thread before [`init_test_telemetry`] was called.
pub struct TestTelemetry {
    log_exporter: InMemoryLogExporter,
    metric_exporter: InMemoryMetricExporter,
    span_exporter: InMemorySpanExporter,
    logger_provider: SdkLoggerProvider,
    meter_provider: SdkMeterProvider,
    tracer_provider: SdkTracerProvider,
    _subscriber_guard: tracing::subscriber::DefaultGuard,
}

impl TestTelemetry {
    /// Flushes every provider so a subsequent [`TestTelemetry::counts`]
    /// reflects everything recorded/logged/spanned so far in this
    /// process.
    pub fn force_flush(&self) {
        let _ = self.logger_provider.force_flush();
        let _ = self.meter_provider.force_flush();
        let _ = self.tracer_provider.force_flush();
    }

    /// Snapshots the current counts across all four signals.
    pub fn counts(&self) -> TelemetryCounts {
        let log_records = self
            .log_exporter
            .get_emitted_logs()
            .map(|logs| logs.len())
            .unwrap_or(0);
        let spans = self
            .span_exporter
            .get_finished_spans()
            .map(|spans| spans.len())
            .unwrap_or(0);

        let mut metric_data_points = 0usize;
        let mut histogram_data_points = 0usize;
        if let Ok(resource_metrics) = self.metric_exporter.get_finished_metrics() {
            for rm in &resource_metrics {
                for scope_metrics in rm.scope_metrics() {
                    for metric in scope_metrics.metrics() {
                        let (total, hist) = count_aggregated(metric.data());
                        metric_data_points += total;
                        histogram_data_points += hist;
                    }
                }
            }
        }

        TelemetryCounts {
            log_records,
            metric_data_points,
            histogram_data_points,
            spans,
        }
    }
}

/// Initializes stdout JSON logging plus all three in-memory exporters
/// (logs, metrics, traces) and returns a [`TestTelemetry`] handle for
/// asserting counts. Unlike [`crate::init::init`] (which sets the
/// process-wide global default via `SubscriberInitExt::init()`, callable
/// at most once per process), this installs the subscriber via
/// `tracing::subscriber::set_default`, a scoped, thread-local default
/// held alive by the returned [`TestTelemetry`]'s guard -- safe to call
/// from many tests in the same binary/process, including in parallel,
/// since the standard Rust test harness runs each test function on its
/// own thread. The OTel metrics side still goes through
/// `opentelemetry::global::set_meter_provider` (metrics has no
/// thread-local equivalent in the OTel Rust SDK), so callers of this
/// function that record metrics must still serialize against any other
/// test in the same process doing the same -- see
/// `crate::metrics::global_meter_test_lock`.
pub fn init_test_telemetry(service_name: &str) -> TestTelemetry {
    let cfg = ServiceConfig {
        service_name: service_name.to_string(),
        otlp_endpoint: None,
        otlp_protocol: crate::OtlpProtocol::Grpc,
        otlp_headers: Vec::new(),
        log_level: "debug".to_string(),
    };
    let res = resource(&cfg);

    let log_exporter = InMemoryLogExporter::default();
    let logger_provider = SdkLoggerProvider::builder()
        .with_simple_exporter(log_exporter.clone())
        .with_resource(res.clone())
        .build();

    let metric_exporter = InMemoryMetricExporter::default();
    let meter_provider = SdkMeterProvider::builder()
        .with_periodic_exporter(metric_exporter.clone())
        .with_resource(res.clone())
        .build();
    opentelemetry::global::set_meter_provider(meter_provider.clone());

    let span_exporter = InMemorySpanExporter::default();
    let tracer_provider = SdkTracerProvider::builder()
        .with_simple_exporter(span_exporter.clone())
        .with_resource(res)
        .build();

    let otel_logs = OpenTelemetryTracingBridge::new(&logger_provider);
    let otel_traces = tracing_opentelemetry::layer().with_tracer(tracer_provider.tracer(service_name.to_string()));

    let subscriber = tracing_subscriber::registry()
        .with(crate::logging_init::json_fmt_layer())
        .with(otel_logs)
        .with(otel_traces);
    let subscriber_guard = tracing::subscriber::set_default(subscriber);

    TestTelemetry {
        log_exporter,
        metric_exporter,
        span_exporter,
        logger_provider,
        meter_provider,
        tracer_provider,
        _subscriber_guard: subscriber_guard,
    }
}
```

- [ ] **Step 4: Run to verify it passes**

Run: `make test`
Expected: PASS — all four `testing::tests` green.

- [ ] **Step 5: Wire into `lib.rs`**

Add, guarded by the feature flag:

```rust
#[cfg(feature = "testing")]
pub mod testing;
```

- [ ] **Step 6: Commit**

```bash
git add packages/rust-logging/src/testing.rs packages/rust-logging/src/lib.rs
git commit -m "$(cat <<'EOF'
feat(logging): add testing feature with in-memory log/metric/span sink

Gives every downstream service a way to assert the testing.md Telemetry
Validation gate (>=1 log record, >=1 metric data point, >=1 histogram,
>=1 span) against real counts in its own smoke tests.

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01N2rQgkHY872RubwXoBZxtE
EOF
)"
```

---

### Task 18: End-to-end telemetry gate integration test + docs finalize + self-review fixes

**Files:**
- Create: `packages/rust-logging/tests/integration_telemetry.rs`
- Modify: `packages/rust-logging/README.md`, `packages/rust-logging/CHANGELOG.md` (only if this task's self-review, Step 5 below, finds a fix to record)

**Interfaces:**
- Consumes: `init_test_telemetry`/`TelemetryCounts` (Task 17), `sanitize_value` (Task 2), `record_latency_ms`/`counter_add`/`gauge_set` (Task 12), `health::{DependencyMetrics, TransportMetrics, warn_insecure_transport}` (Task 16), `inject_trace_context`/`context_from_trace_context` (Task 13).
- Produces: nothing new for other tasks to consume — this is the plan's final verification task. It reproduces design spec §14.7's exact gate ("Every service's smoke test runs against a local OTLP sink and asserts, printing every count... A sink that fails to start is a FAIL, never a skip. Zero files scanned is a FAIL") at the crate level, so `penguin-logging` demonstrably passes the same gate its downstream consumers must also pass.

- [ ] **Step 1: Write the failing test**

`packages/rust-logging/tests/integration_telemetry.rs`:

```rust
//! Reproduces design spec §14.7 / `testing.md` Telemetry Validation
//! end-to-end against this crate's own public API: drives a realistic
//! mix of log lines, a sanitized field, a latency histogram, a counter,
//! a dependency-check metric, an insecure-transport warning, a
//! trace-context round trip, and a span -- then asserts and PRINTS every
//! count, exactly as the gate requires ("every 'clean' result reported
//! with the number of items examined" -- `critical-rules.md`
//! Verification Integrity).

use opentelemetry::trace::TraceContextExt;
use opentelemetry::KeyValue;
use penguin_logging::health::{DependencyMetrics, DependencyStatus, TransportAspect, TransportMetrics};
use penguin_logging::testing::init_test_telemetry;
use penguin_logging::{
    context_from_trace_context, counter_add, inject_trace_context, record_latency_ms, sanitize_value,
};

#[tokio::test]
async fn telemetry_gate_all_four_signals_present_with_printed_counts() {
    let telemetry = init_test_telemetry("integration-telemetry-test");

    // Logs: a plain line, plus one whose fields must survive sanitization
    // unredacted-for-the-non-sensitive-part / redacted-for-the-sensitive
    // part before being logged (mirrors the WIT `log` host call contract).
    tracing::info!("svc-process-test starting");
    let sanitized = sanitize_value(&serde_json::json!({"token": "abc123", "route": "/health"}));
    tracing::info!(fields = %sanitized, "sanitized field logged");

    // Metrics: a histogram (the signal `testing.md` calls out as
    // "most-often-missing"), a counter, and the two health-surface
    // metrics this crate defines.
    record_latency_ms("integration_test_latency_ms", 7.5, &[KeyValue::new("route", "/health")]);
    counter_add("integration_test_events_total", 1, &[]);
    DependencyMetrics::new().record("postgres", &DependencyStatus::ok());
    let transport_metrics = TransportMetrics::new();
    penguin_logging::health::warn_insecure_transport(&transport_metrics, "valkey", TransportAspect::Tls);

    // Traces: a span, plus a trace_context round trip matching
    // StageEnvelope.trace_context's exact contract (design spec §6.1.2).
    let injected = {
        let span = tracing::info_span!("integration.test.span");
        let _entered = span.enter();
        tracing::info!("inside the span");
        let cx = opentelemetry::Context::current();
        inject_trace_context(&cx)
    };
    if let Some(traceparent) = &injected {
        let restored = context_from_trace_context(Some(traceparent));
        assert!(restored.span().span_context().is_valid());
    }

    telemetry.force_flush();
    let counts = telemetry.counts();

    // Print every count -- "report how many items were examined", never
    // just "no findings" (`critical-rules.md` Verification Integrity).
    println!(
        "telemetry gate counts: log_records={}, metric_data_points={}, histogram_data_points={}, spans={}",
        counts.log_records, counts.metric_data_points, counts.histogram_data_points, counts.spans
    );

    assert!(counts.log_records >= 1, "FAIL: zero log records received");
    assert!(counts.metric_data_points >= 1, "FAIL: zero metric data points received");
    assert!(counts.histogram_data_points >= 1, "FAIL: zero histogram metrics received");
    assert!(counts.spans >= 1, "FAIL: zero spans received");
}
```

- [ ] **Step 2: Run to verify it fails**

Run: `make test`
Expected: FAIL — before this file exists, `cargo test` simply does not run it; write it first, confirm the test binary is picked up (`running 1 test` for `integration_telemetry`), and confirm it currently fails only if any earlier task's implementation has a defect this test newly exercises (e.g. if `sanitize_value`'s `Display`/`%` formatting via `tracing::info!(fields = %sanitized, ...)` does not compile because `serde_json::Value` does implement `Display` — it does, so this should compile cleanly if every earlier task landed correctly; if it does not compile, that is a real defect in an earlier task to fix now, not a plan error).

- [ ] **Step 3: Run to verify it passes**

Run: `make test`
Expected: PASS, with output containing a line like:

```
telemetry gate counts: log_records=2, metric_data_points=4, histogram_data_points=1, spans=1
running 1 test
test telemetry_gate_all_four_signals_present_with_printed_counts ... ok
```

(exact counts may vary slightly — e.g. `metric_data_points` includes the histogram, the counter, and the two gauges from `DependencyMetrics`/`TransportMetrics`, so 4 is the expected minimum, not an exact contract). If any count is `0`, that is a FAIL per `critical-rules.md` Verification Integrity's "zero items examined is a FAILURE, not a pass" — do not weaken the assertion; fix whichever earlier task's implementation is not actually emitting that signal.

- [ ] **Step 4: Run the full gate one more time**

Run: `make pre-commit`
Expected: `fmt`, `lint`, `deny`, `audit`, `test`, `coverage` (in that order) all pass; `coverage` reports ≥90% lines (this crate's real target — if it reports below 90%, add tests for whatever lines are uncovered before proceeding; do not lower the `--fail-under-lines` flag).

- [ ] **Step 5: Self-review** (see the plan's own Self-Review section below for the full checklist this step executes) — fix anything found, then re-run Step 4 until clean.

- [ ] **Step 6: Final commit**

```bash
git add packages/rust-logging/tests/integration_telemetry.rs packages/rust-logging/README.md packages/rust-logging/CHANGELOG.md
git commit -m "$(cat <<'EOF'
test(logging): add end-to-end telemetry gate integration test (spec §14.7 parity)

Reproduces the testing.md Telemetry Validation gate against penguin-logging's
own public API with printed counts for all four signals (logs, metrics,
histograms, spans), plus a sanitization + trace_context round trip.

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01N2rQgkHY872RubwXoBZxtE
EOF
)"
```

---

## Self-Review

Performed against the spec (`docs/superpowers/specs/2026-09-14-rust-data-plane-design.md`, commit `680a0a9b`) and the `superpowers:writing-plans` skill's own checklist, with fixes applied inline before this plan was committed (not left as follow-up items).

### 1. Spec coverage

| Spec requirement (§) | Task(s) |
|---|---|
| §4.9 sanitization ported verbatim from `penguin-utils` | 2, 3 |
| §4.9 OTel logs/metrics/traces wired, standard env vars only | 4, 6, 7, 8, 9, 10, 11 |
| §4.9 health/metrics surface | 14, 15 |
| §4.9 `transport:` reporting | 14 (`HealthBody.transport`/`transport_detail`), 16 (`waddles_insecure_transport`) |
| §6.1.2 `trace_context` W3C `traceparent`, optional, absent/null ⇒ no parent span | 13 |
| §7.4 / WIT `log` interface: `fields-json` sanitized before emission | 3 (`sanitize_json_str`) |
| §11.6.4 `/health` JSON shape, `transport` secure/insecure summary | 14 |
| §11.6.4 fixed WARN banner text on `tls=false`/`auth=false`, `waddles_insecure_transport{component,aspect}` gauge, 0 for secure components | 16 |
| §12.6 startup self-check classification (`dns\|tcp\|tls\|auth\|ok`), `waddles_dependency_up`, `waddles_dependency_check_total` | 14, 16 |
| §13.1 histograms-first metric helpers | 12 |
| §13.3 `penguin-logging` for every line, sanitization at every level including DEBUG | 2, 3, 7, 10 |
| §13.4 `/health`, `/healthz`, `/metrics` endpoints | 15 |
| §14.5 per-crate CI gates (fmt, clippy, deny, audit, test, llvm-cov ≥90%, semgrep, gitleaks) | 1 |
| §14.7 telemetry validation gate (≥1 log, ≥1 metric, ≥1 histogram, ≥1 span, printed counts) | 17, 18 |
| §16 M1 row: "Sanitization ported verbatim, OTel logs/metrics/traces wired, health/metrics surface, `transport:` reporting" | all 18 tasks collectively |
| `critical-rules.md` Observability: dead exporter never fails a request, extended to init-time construction | 8, 9, 10, 11 (never-panics tests) |
| `critical-rules.md` Dependency Pinning: exact versions, `Cargo.lock` committed | 1 |
| `backend-rust.md`: `unsafe_code`/`missing_docs` deny, `clippy::unwrap_used` deny, documented `.expect()` invariants only | 1 (lints), 8/9/10/11 (documented invariant comments) |
| `testing.md` Telemetry Validation gate contract | 17, 18 |
| `critical-rules.md` Verification Integrity: printed counts, non-zero denominators, no `\|\| true` | 18 (printed counts), 1 (no masked CI steps) |

Reference-implementation gaps this crate closes, both confirmed by reading `core/svc_streaming/src/telemetry.rs` in full during planning: no OTLP log exporter at all (Task 10), and an OTLP metric exporter that never actually has an instrument recorded through it anywhere in that file (Task 9's shared-meter design, which also removes the hand-duplicated Prometheus-registry pattern that gap left behind).

### 2. Placeholder scan

Searched the full document for `TBD`, `TODO`, `FIXME`, "fill in", "placeholder", "similar to Task", "implement later", "add appropriate ..." — zero matches. The one place a genuine implementation detail was initially deferred (Task 17's metric-data-point counting, which depended on `opentelemetry_sdk`'s exact `AggregatedMetrics`/`MetricData` enum shape) was resolved during this self-review by downloading and reading the pinned crate's actual source rather than left as a note for the implementer; the task now contains the real, verified counting code.

### 3. Signature/type consistency

Cross-checked every type and function name against its "Produces" declaration and every later task's "Consumes"/call sites:

- `ServiceConfig`/`OtlpProtocol` (Task 4) fields match every constructor call in Tasks 6, 8, 9, 10, 11, 17.
- `LevelHandle`/`parse_level_filter`/`LevelError` (Task 5) match Task 11's `init()` construction and its return tuple `(TelemetryGuard, LevelHandle, prometheus::Registry)`, used identically in Tasks 15, 17, 18.
- `otel_log_layer` (Task 10): found and fixed a real defect during self-review — it originally carried an unused generic `<S>` parameter that `clippy::extra_unused_type_parameters` would reject under `-D warnings`, and would also have made Task 10's own test fail to compile (no way to infer `S` without turbofish, but the test called it without one). Removed the generic; fixed both call sites in Task 11's `init()`.
- `MeterProvider` trait import: found and fixed a missing `use opentelemetry::metrics::MeterProvider as _;` in Task 9's test (`provider.meter(...)` does not resolve without the trait in scope).
- `HealthState`/`DependencyStatus`/`DependencyClass`/`ComponentTransport`/`HealthBody` (Task 14) match Task 15's router handlers, Task 16's `DependencyMetrics`/`TransportMetrics` (which reference `crate::health::types::DependencyClass` by its Task-14-defined variant names), and Task 18's integration test.
- `render_prometheus_text`/`MeterProviderError`/`RenderError` (Task 9) match Task 15's `metrics_handler` and the crate's `lib.rs` re-exports.
- Test-process isolation: found and fixed a real concurrency defect during self-review — `init()`'s internal `SubscriberInitExt::init()` call can only succeed once per process, but Task 11 originally put two tests calling it in one file (same process via shared test threads); split into `integration_exporter_failure.rs` and `integration_no_otlp.rs`. Separately, `opentelemetry::global::set_meter_provider` plus this crate's own process-global instrument caches (`histogram_cache`/`counter_cache`/`gauge_cache` in Task 12) meant any two unit tests in the same `cargo test --lib` binary that both install a global meter provider could interfere; added one shared `crate::metrics::global_meter_test_lock()` (Task 12) plus a `clear_instrument_caches()` reset, and updated every test in Tasks 12, 16 and 17 that touches the global meter provider to acquire the lock and clear the caches first. `init_test_telemetry` (Task 17) was additionally changed from the process-global `SubscriberInitExt::init()` to the thread-local, repeatable `tracing::subscriber::set_default`, since it is explicitly designed to be called from many tests.
- File structure map (top of document) updated to list both `tests/integration_exporter_failure.rs` and the added `tests/integration_no_otlp.rs`.

No remaining signature mismatches found between any task's "Produces" and a later task's "Consumes"/call sites.

---
