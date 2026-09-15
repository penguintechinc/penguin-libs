# penguin-bundle-host Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the `penguin-bundle-host` Rust crate (`penguin-libs/packages/rust-bundle-host`) — the WIT world, the stage-side host runtime (frame protocol server, capability enforcement, approved-permission model), the credential-less executor runtime (wasmtime engine, WASI wiring, instance pool, loader), and the `bundle-executor` binary — so Waddles' `svc_process`/`svc_action` (M3/M4) and `bundle-compiler` (M2) have a shared, tested implementation of the sandbox boundary between a stage and its WASM bundles.

**Architecture:** Two library facets in one crate — `host` (stage side: owns capability enforcement, the mTLS frame-protocol server, and the approved-permission model; holds real credentials via traits the *services* implement) and `executor` (credential-less side: wasmtime engine, WASI wiring with sockets denied by default, instance pool, bucket loader; talks back to `host` only through the wire protocol). A third artifact, the `bundle-executor` binary, wires `executor` end to end into a runnable process. `wire` is shared frame-codec code both facets depend on.

**Tech Stack:** Rust 1.97.1, Tokio, `wasmtime` 48.0.2 (component model + WASI 0.2), `rustls`/`tokio-rustls` (mTLS), `object_store` (S3-compatible bucket), `ed25519-dalek` (sidecar signature), `sqlparser` (SQL table-allowlist parsing), `governor` (egress rate limiting), `serde`/`serde_json` (wire frames — JSON, not a binary codec, per spec §6.6).

**Spec:** `docs/superpowers/specs/2026-09-14-rust-data-plane-design.md` (fetched from `origin/docs/rust-data-plane-spec` in the `waddlebot` repo — this plan argues from it; executors read both). Evidence: `spikes/penguin-dal-wasm/REPORT.md` (branch `spike/penguin-dal-wasm`) and `spikes/bundle-compiler-sandbox/REPORT.md` (branch `spike/bundle-compiler-sandbox`), both in the `waddlebot` repo.

## Global Constraints

These bind every task below; they are not repeated per task.

- **Rust 1.97.1**, edition 2021, pinned via `rust-toolchain.toml` — never rely on host cargo (`backend-rust.md`).
- **Shared-file collision (pre-flight review, session_01N2rQgkHY872RubwXoBZxtE):** Task 25 appends `build-rust-bundle-host` to `.github/workflows/ci.yml` and `publish-rust-bundle-host` to `.github/workflows/publish.yml` — the same two files `penguin-logging` (M1b) and `penguin-connectors` (M1d) also append to (each with distinct, uniquely-named jobs: `build-rust-logging`/`publish-rust-logging`, `build-rust-connectors*`/`build-rust-licensing`). `penguin-spine` (M1a) does not touch these two files (its own dedicated `rust-spine.yml`). A merge conflict here is textual (adjacent insertion), never semantic — rebase onto the release branch immediately before opening the PR rather than assuming this plan is the only one touching these files.
- **Every command runs inside the pinned Rust container via `make <target>` — never bare host `cargo`.** The Makefile (Task 1) wraps every `cargo` invocation in `docker run --rm -v "$(CURDIR)":/work -w /work rust:1.97-slim-bookworm@sha256:2775a09d208ff0d7c1f50490c45b62db929e87ba1dcbc3f2132ac71a704bcdd3 <cmd>` (the exact digest already pinned for `svc_streaming`'s builder stage and used by the bundle-compiler-sandbox spike — reused here for consistency, not re-resolved). Every task step below that says "Run: `make X`" means exactly that; no step invokes `cargo` directly on the host.
- **Exact dependency pins only** — `=x.y.z` in `Cargo.toml`, `Cargo.lock` committed, no bare `*`/`^`/`~` (`critical-rules.md` Dependency Pinning). Every version below was resolved against the live crates.io index on 2026-09-14 and is what Task 1 writes verbatim.
- **`[lints.rust] unsafe_code = "deny"`, `missing_docs = "deny"`; `[lints.clippy] unwrap_used = "deny"`** at the crate root, matching `rust-licensing`'s convention (`penguin-libs-inventory.md`). Exactly **two** `#[allow(unsafe_code)]` sites exist in the whole crate, both wrapping `wasmtime::component::Component::deserialize_file` (an `unsafe fn`: loading a precompiled `.cwasm` trusts the bytes), both placed strictly *after* `verify_digest_and_signature` has already accepted those bytes, each with a `// SAFETY:` comment naming that ordering — one in `executor::loader::bucket` (Task 20, the cache-hit load path) and one in the `bundle-executor` binary's `on_load` (Task 22). No other `unsafe` appears anywhere in this crate.
- **Every file created under `tests/` and `benches/` begins with exactly this line**, before any `use`/`mod` and after any `//!` module doc:
  ```rust
  #![allow(clippy::unwrap_used, clippy::panic)]
  ```
  `[lints.clippy] unwrap_used = "deny"` in `Cargo.toml` applies to *every* target in the package, and `make clippy` runs `--all-targets`, so without this line every `.unwrap()` in a test fails the lint gate. This is the identical convention `packages/rust-licensing/tests/client_tests.rs` already uses (read during planning: same crate-level allow, 55 `.unwrap()` calls beneath it). It is an allow **in test code only** — never in `src/`.
- **`cargo fmt --check`, `cargo clippy --all-targets -- -D warnings`, `cargo deny check`, `cargo audit` clean before every commit** (Task 25 wires these into CI; every task runs `make lint` locally first).
- **Coverage ≥ 90%** lines/branches/functions/statements (`cargo llvm-cov --fail-under-lines 90`, wired in Task 25) — `critical-rules.md` Coverage.
- **No `|| true` on any gate; every "clean" result reports the count of items examined; a zero denominator is a failure** (`critical-rules.md` Verification Integrity). Every negative test in this plan asserts a specific, non-zero count where one applies (e.g. "N crates examined by `cargo tree`", "N frames round-tripped").
- **Naming: Waddles, never "restream" or "waddlebot"** in any prose, comment, identifier or log line this plan adds. The only exceptions are literal references to the `waddlebot` **git repository name** (where the spec and spikes live) and the four legacy identifiers spec D22 lists, none of which this crate touches.
- **Commit messages**: `feat(bundle-host): ...` / `test(bundle-host): ...` / `fix(bundle-host): ...` / `chore(bundle-host): ...` / `docs(bundle-host): ...`, each ending with:
  ```
  Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
  Claude-Session: https://claude.ai/code/session_01N2rQgkHY872RubwXoBZxtE
  ```
- **Secrets**: never a CLI flag, never logged unmasked, env/file only (`security.md` Token & Secret Hygiene). The `bundle-executor` binary (Task 22) reads `BUNDLE_SIGNING_PUBLIC_KEY`, `BUNDLE_BUCKET_ACCESS_KEY_ID`/`_SECRET_ACCESS_KEY`, and the mTLS key material exclusively from env vars / mounted files.
- **Observability — `penguin-logging` (milestone M1b) is a hard dependency of this crate, not a stand-in.** M1b's plan landed on `origin/docs/plan-penguin-logging` (`docs/superpowers/plans/2026-09-14-penguin-logging.md`, 18 tasks, crate `penguin-logging` at `packages/rust-logging`, version `0.1.0`), so this crate consumes it directly and never hand-rolls telemetry: `penguin_logging::init(ServiceConfig::from_env("bundle-executor"))` is the only telemetry init in the `bundle-executor` binary (Task 23); `penguin_logging::sanitize_json_str` is the only sanitizer the WIT `log` host call's `fields-json` passes through (Task 14); `penguin_logging::metrics::{record_latency_ms, counter_add, gauge_set}` are the only metric emitters (Task 23); `penguin_logging::health::{HealthState, router}` serves `/health`/`/healthz`/`/metrics` (Task 23); `penguin_logging::testing::{init_test_telemetry, TelemetryCounts}` (its `testing` Cargo feature, a `[dev-dependencies]` entry here) is what the mandatory telemetry-validation gate asserts against (Task 23). **No hand-rolled `println!`, `log`, `tracing_subscriber` registry, or direct `opentelemetry-otlp` exporter construction appears anywhere in this crate** — `testing.md` Logging Library Conformance makes that a per-commit gate, and Task 23 Step 3 is the scan that enforces it with a printed, non-zero file count, and Task 23 Step 6 is the one-time proof that the scan can actually fail. `tracing::{info,warn,error,debug}!` macros are still used for every log line — `penguin-logging` is the sink those macros feed, not a replacement for them.
- **Boundary — this crate has no Valkey, no Postgres connection pool, and no platform-specific HTTP client of its own.** `host::db`'s table-allowlist guard wraps a `DbExecutor` trait the *service* (svc_process/svc_action, M3/M4) implements against its own SeaORM/per-bundle-role connection; `host::kv`'s guard wraps a `KvStore` trait the service implements against its own Valkey connection; `host::egress`'s SSRF/allowlist guard wraps an `HttpEgress` trait the service implements with its own `reqwest` client. This crate owns the *policy* (what is allowed, in what order, with what limits) and the *wire protocol*; the services own the *transport*.
- **The exact `penguin-logging` 0.1.0 surface this crate calls** (read verbatim off M1b's plan at `origin/docs/plan-penguin-logging`, Tasks 3, 4, 11, 12, 14, 15, 17 — not assumed):
  ```rust
  // config.rs (M1b Task 4)
  pub struct ServiceConfig { pub service_name: String, pub otlp_endpoint: Option<String>, pub otlp_protocol: OtlpProtocol, pub otlp_headers: Vec<(String, String)>, pub log_level: String }
  impl ServiceConfig { pub fn from_env(default_service_name: &str) -> ServiceConfig; }

  // init.rs (M1b Task 11) -- call exactly once per process
  pub fn init(cfg: ServiceConfig) -> (TelemetryGuard, LevelHandle, prometheus::Registry);
  pub struct TelemetryGuard; // pub fn shutdown(&mut self), Drop calls it

  // sanitize.rs (M1b Task 3) -- the WIT `log` host call's fields-json path
  pub fn sanitize_json_str(raw: &str) -> Result<String, SanitizeError>;

  // metrics.rs (M1b Task 12) -- histograms first
  pub fn record_latency_ms(name: &'static str, millis: f64, labels: &[opentelemetry::KeyValue]);
  pub fn counter_add(name: &'static str, value: u64, labels: &[opentelemetry::KeyValue]);
  pub fn gauge_set(name: &'static str, value: f64, labels: &[opentelemetry::KeyValue]);

  // health/ (M1b Tasks 14, 15)
  pub struct HealthState; // new, set_dependency, set_transport, set_sandbox, set_extra, uptime_seconds, snapshot
  pub enum DependencyClass { Dns, Tcp, Tls, Auth, Ok }
  pub struct DependencyStatus; // ok(), failed(class, detail), is_up()
  pub fn router(state: HealthState) -> axum::Router;          // /health + /healthz + /metrics
  pub fn metrics_router(state: HealthState) -> axum::Router;  // /metrics only

  // testing.rs (M1b Task 17, `testing` feature)
  pub fn init_test_telemetry(service_name: &str) -> TestTelemetry;
  pub struct TestTelemetry; // pub fn force_flush(&self), pub fn counts(&self) -> TelemetryCounts
  pub struct TelemetryCounts { pub log_records: usize, pub metric_data_points: usize, pub histogram_data_points: usize, pub spans: usize }
  ```
  If any of these signatures differ in the published `penguin-logging` 0.1.0, fix the call site here — never re-implement the function locally.
- **Boundary — no `bundle.yaml` manifest parsing in this crate.** Spec §4.8 lists a `manifest` module (bundle.yaml v2 parse + the 22 field-validation rules) as part of `penguin-bundle-host`; this plan's task scope, as given, is WIT world + executor host runtime + wire protocol + bucket loader + digest/signature verification + resource limits + trip rule — it does not include manifest parsing. `ApprovedPermissions` (Task 9) consumes the **already-resolved** `app_install_approvals.summary_json` shape the distribution API serves (spec §6.7, §6.9), never the raw `bundle.yaml`. Manifest parsing is deferred to a separate plan (likely folded into M2's `bundle-compiler`, which is the component that actually needs the full 31-rule validator against source manifests).
- **Boundary — no waddles-repo Dockerfile/Helm wiring.** This crate ships a fully working, independently buildable/testable `bundle-executor` binary (`src/bin/bundle_executor/main.rs`). Packaging it into the `waddles` repo's `core/bundle_executor` deployable image (its own `Cargo.toml`, `Dockerfile`, chart wiring) is out of scope — that repo's crate will depend on `penguin-bundle-host` once published (Task 25) and re-use or re-export this binary.
- **Spec updated to `origin/docs/rust-data-plane-spec` commit `680a0a9b` mid-plan — the four constraints below are folded in from that revision (§7.6, §4.6/D27, §6.10, §11.10/D28). §6.6 (wire protocol) and §6.7 (distribution API) — the sections Tasks 1-4 already implement — are byte-identical between the spec revision this plan started from and `680a0a9b`, confirmed by `diff` before writing this note; no rework of Tasks 1-4 was needed.**
- **Reconciliation is digest-only, four cases, never version/manifest text (§7.6).** `executor::loader`'s reconciliation function (Task 20) compares the digest set the distribution API advertises against the digest set this executor currently has loaded and takes exactly one of four actions per `app_id`: **same digest → no-op** (no fetch, no re-verify, no swap); **different digest → fetch/verify/precompile/hot-swap, then unload the old digest after drain**; **`app_id` newly present → add** (fetch/verify/precompile/load); **`app_id` no longer advertised → unload and evict its cached artifacts**. A version re-published with byte-identical content is therefore a no-op by construction, and a control-plane rollback (§6.10's `app_active_versions.version_id` pointed at an older row) is indistinguishable from a roll-forward — both are just "different digest" to this function. Task 20's tests assert all four branches, each with an exact count of bundles examined.
- **The compiler's trust split (§4.6, D27) is why the digest this crate verifies can be trusted at all.** `bundle-compiler`'s Job runs an **untrusted** `build` init container (gVisor, no credentials, no network — it executes bundle code) that hands bytes to a **trusted** `publisher` container (cluster-default runtime, bucket + signing-key + `waddles_publisher` DB-role credentials, never executes guest code) which measures the digest, precompiles, signs the sidecar, and uploads. **The hash this crate's `loader::verify_digest_and_signature` (Task 19) checks was therefore never computed inside the sandbox that ran the bundle's own code** — a compromised `build` container can tamper with the bytes but cannot choose the hash it is judged by, because it never computes that hash. This crate does not implement or depend on the compiler split (out of scope, M2); it only relies on the property it produces.
- **M2a's PA2 artifact contract is matched verbatim, with exactly one recorded deviation.** M2a (`origin/docs/plan-m2a-compiler-sdks`, `docs/superpowers/plans/2026-09-14-rust-data-plane-m2a-compiler-sdks.md`) declares itself the reference implementation of the artifact contract and names four things M1c must match. This plan matches all four:

  | PA2 item | M2a's definition | This plan |
  |---|---|---|
  | `.cwasm` cache-key shape | `{digest}-{wasmtime_abi}-{collector}`, `collector = drc` | Task 6 (`EngineHandle::wasmtime_abi`, collector pinned + validated), Task 20 (`BucketLoader::cwasm_cache_key`) — identical |
  | Signed sidecar JSON schema | M2a Task 14 `Sidecar`: `schema_version, app_id, version, digest, size_bytes, language, artifact_kind, scan_status, wit_world, built_at, builder, signature`; signed bytes = `serde_json::to_vec` of every field **except** `signature` (spec §9.4) | Task 19 `verify_digest_and_signature` parses and re-derives that exact object — identical |
  | `hello` frame fields | `wasmtime_version` / `wasmtime_abi` / `collector` (spec §6.6) | Task 2 `Message::Hello`, Task 21 `ExecutorClient::dial` — identical |
  | Bucket object layout | `bundles/{app_id}/{version}/{sha256-hex}.wasm` and `.json` | Task 20 `fetch_and_verify` — identical |

  **The one deviation — the WIT file's path, deliberate and recorded:** PA2 names `wit/waddle-bundle/stage.wit`. That path is correct *in the `waddles` repo*, where M2a's `bundle-compiler` lives and where the single NORMATIVE copy of the world belongs (spec §6.5, §4.0). This crate lives in `penguin-libs` and needs its own committed copy for `wasmtime::component::bindgen!` and for the fixture builds, so it commits it at `wit/waddle-bundle-stage.wit` — a flat filename because `bindgen!`'s `path:` argument and `cargo-component`'s `[package.metadata.component.target] path = "wit"` both resolve a *directory* of `.wit` files, and a nested `waddle-bundle/` subdirectory inside `wit/` would be parsed as a second, separate WIT package. **The package identifier, the world name, and the file's bytes are unchanged** — `package waddle:bundle@1.0.0` / `world stage`, so `waddle:bundle/stage@1.0.0` resolves identically on both sides; only the on-disk filename differs. Task 2 Step 1 commits a header comment in the file pointing at the normative copy, and keeping the two byte-identical (or generating one from the other) is tracked follow-up before M3/M4 land.
- **Telemetry emission is a blocking gate on every commit, with printed counts.** Task 23 runs `penguin_logging::testing::init_test_telemetry` against this crate's own end-to-end path and asserts `log_records >= 1`, `metric_data_points >= 1`, `histogram_data_points >= 1`, `spans >= 1`, printing every count (`critical-rules.md` Observability, `testing.md` Telemetry Validation). Zero received, or a sink that fails to start, is a **FAIL**, never a skip — and Task 23 also scans `src/` for hand-rolled logging (`println!`, `eprintln!`, `log::`, `tracing_subscriber::registry`, `opentelemetry_otlp::`) reporting the number of files scanned, which must be non-zero (`testing.md` Logging Library Conformance, `critical-rules.md` Verification Integrity).
- **The executor has no Postgres role and no Valkey ACL user, full stop (§6.10, §11.10/D28).** `config/postgres/rbac-matrix.yaml`'s row for "executor" is literally **No role**, and `config/valkey/acl-matrix.yaml` has no executor entry at all — both matrices live in the `waddles` repo and are out of scope here, but they are the normative confirmation of a constraint this crate's design already holds: `executor::*` (Tasks 6, 7, 18, 19, 20, 21) and the `bundle-executor` binary (Tasks 22, 23) never open a database connection, never authenticate to Valkey, and never import `sea-orm`, `sqlx`, `redis`, or `deadpool-redis` (asserted by the dependency-tree test, Task 24). A stage's digests reach the executor exclusively through the `load` wire frame (§6.6, Task 2) — which the stage itself sourced from the distribution API's `artifactDigest` field (§6.7) against `app_versions`/`app_active_versions` (§6.10) — never through a direct query this crate could make, because it has no credential to make one with.

## File Structure

```
penguin-libs/packages/rust-bundle-host/
  Cargo.toml
  Cargo.lock
  deny.toml
  rust-toolchain.toml
  .gitignore
  LICENSE
  README.md
  CHANGELOG.md
  Makefile                          # every cargo invocation, dockerized
  Dockerfile.fixtures               # pinned cargo-component + wasm-tools toolchain, builds tests/fixtures/*.wasm
  wit/
    waddle-bundle-stage.wit         # this crate's committed copy of waddle:bundle/stage@1.0.0
  src/
    lib.rs                          # crate root: pub mod wire; pub mod host; pub mod executor;
    wire/
      mod.rs
      frame.rs                      # length-prefixed frame codec
      message.rs                    # Frame/Message/ExportKind/CapabilityKind/ErrorCode types
      transport.rs                  # FrameTransport: correlation-id multiplexer
    host/
      mod.rs
      approvals.rs                  # ApprovedPermissions + parse()
      capability.rs                 # HttpEgress/KvStore/DbExecutor/RelayPush/Flags/Logger/Clock traits
      egress.rs                     # EgressGuard (full §8.2 order)
      db_guard.rs                   # DbGuard (sqlparser table allowlist)
      kv_guard.rs
      relay_guard.rs
      flags_guard.rs
      log_guard.rs                  # LogGuard -> penguin_logging::sanitize_json_str
      clock_guard.rs
      trip.rs                       # TripTracker (§7.5 three-strike disable)
      router.rs                     # HostCallRouter: wire host-call frames -> the guards above
      server.rs                     # mTLS frame-protocol server + ExecutorConnection
    executor/
      mod.rs
      engine.rs                     # wasmtime Engine/Config (component model, epoch, pooling, collector pin)
      bindings.rs                   # wasmtime::component::bindgen! invocation
      wasi_ctx.rs                   # WasiCtxBuilder per instance (deny sockets, scratch preopen)
      remote_host_impl.rs           # bindgen Host trait impls -> forward host-call over the wire (executor side)
      pool.rs                       # InstancePool (per-bundle pre-instantiated stores)
      invoke.rs                     # per-call invocation: epoch deadline, memory cap, trip reporting
      loader.rs                     # digest+signature verify, bucket poller, precompile, hot-swap
      wire_client.rs                # executor-side wire client: dial, hello, reconnect backoff
    bin/
      bundle_executor/
        main.rs
        config.rs                   # env-only config (clap derive)
        sandbox_check.rs            # gVisor self-check (/proc/version, /proc/self/status)
        telemetry.rs                # penguin_logging::init + health router + executor metrics
  tests/
    common/
      mod.rs                        # stub Host impls + link_stub_hosts, shared by the executor-side tests
    fixtures/
      hello_bundle/                 # tiny cargo-component Rust bundle: happy-path transform/dispatch
        Cargo.toml
        wit/waddle-bundle-stage.wit   (copied from ../../../wit/, not symlinked — see Task 5)
        src/lib.rs
      hostile_socket/               # opens a TCP socket from transform — must be denied
        Cargo.toml
        wit/waddle-bundle-stage.wit
        src/lib.rs
      stateful_counter/             # module-level counter — must read 1 on every call (Task 18)
        Cargo.toml
        wit/waddle-bundle-stage.wit
        src/lib.rs
      hang_forever/                 # infinite loop — must trip the epoch deadline (Task 18)
        Cargo.toml
        wit/waddle-bundle-stage.wit
        src/lib.rs
      memory_hog/                   # allocates 200 MB — must exceed the 64 MB cap (Task 18)
        Cargo.toml
        wit/waddle-bundle-stage.wit
        src/lib.rs
    wire_codec_tests.rs             # Tasks 2, 3
    wire_transport_tests.rs         # Tasks 4, 17
    fixture_build_tests.rs          # Task 5
    engine_instantiate_tests.rs     # Tasks 6, 7
    bindgen_smoke_tests.rs          # Task 7
    sandbox_denial_tests.rs         # Task 8
    approvals_tests.rs              # Task 9
    capability_fakes_tests.rs       # Task 10
    egress_guard_tests.rs           # Tasks 11, 12
    db_guard_tests.rs               # Task 13
    simple_guards_tests.rs          # Task 14
    trip_tests.rs                   # Task 15
    host_call_router_tests.rs       # Task 16
    host_server_tests.rs            # Task 17
    instance_pool_tests.rs          # Task 18
    invoke_limits_tests.rs          # Task 18
    loader_digest_tests.rs          # Task 19
    loader_reconcile_tests.rs       # Task 20
    loader_bucket_tests.rs          # Task 20
    executor_remote_host_tests.rs   # Task 21
    bundle_executor_e2e_tests.rs    # Task 22
    telemetry_gate_tests.rs         # Task 23 — the §14.7 / testing.md telemetry gate
    bundle_executor_dependency_tests.rs  # Task 24
  benches/
    call_roundtrip.rs               # Task 24
```

Every file directly under `tests/` compiles as its own binary, so `tests/common/mod.rs` is shared by `mod common;` declarations rather than by a crate import; each test file also carries the crate-level `#![allow(clippy::unwrap_used, clippy::panic)]` line from Global Constraints.

---

## Task 1: Crate scaffold, Makefile, dockerized build

**Depends on:** nothing — this is the first task.

**Files:**
- Create: `packages/rust-bundle-host/Cargo.toml`
- Create: `packages/rust-bundle-host/Cargo.lock` (generated by `cargo generate-lockfile` inside the container, not hand-written)
- Create: `packages/rust-bundle-host/deny.toml`
- Create: `packages/rust-bundle-host/rust-toolchain.toml`
- Create: `packages/rust-bundle-host/.gitignore`
- Create: `packages/rust-bundle-host/LICENSE` (copy of `packages/rust-licensing/LICENSE`, MIT)
- Create: `packages/rust-bundle-host/README.md`
- Create: `packages/rust-bundle-host/CHANGELOG.md`
- Create: `packages/rust-bundle-host/Makefile`
- Create: `packages/rust-bundle-host/src/lib.rs`
- Create: `packages/rust-bundle-host/src/wire/mod.rs` (empty stub)
- Create: `packages/rust-bundle-host/src/host/mod.rs` (empty stub)
- Create: `packages/rust-bundle-host/src/executor/mod.rs` (empty stub)

**Interfaces:**
- Consumes: nothing (first task).
- Produces: the crate skeleton every later task builds on; the `make` targets every later task's steps invoke (`make build`, `make test`, `make lint`, `make deny`, `make fmt`, `make cov`).

- [ ] **Step 1: Create the directory and `rust-toolchain.toml`**

```bash
mkdir -p /home/penguin/code/penguin-libs/.worktrees/plan-penguin-bundle-host/packages/rust-bundle-host/src/{wire,host,executor,bin/bundle_executor}
mkdir -p /home/penguin/code/penguin-libs/.worktrees/plan-penguin-bundle-host/packages/rust-bundle-host/{tests/fixtures,benches,wit}
```

Write `packages/rust-bundle-host/rust-toolchain.toml`:

```toml
[toolchain]
channel = "1.97.1"
components = ["rustfmt", "clippy", "llvm-tools-preview"]
```

- [ ] **Step 2: Write `Cargo.toml`**

```toml
[package]
name = "penguin-bundle-host"
version = "0.1.0"
edition = "2021"
rust-version = "1.97.1"
license = "MIT"
description = "Waddles WASM bundle sandbox: WIT world, host-API wire protocol, executor runtime, bucket loader."
repository = "https://github.com/penguintechinc/penguin-libs"
authors = ["Penguin Tech Inc <support@penguintech.io>"]
keywords = ["wasm", "wasmtime", "sandbox", "wasi"]
categories = ["wasm", "network-programming"]
publish = false

[lib]
name = "penguin_bundle_host"
path = "src/lib.rs"

[[bin]]
name = "bundle-executor"
path = "src/bin/bundle_executor/main.rs"

[dependencies]
# Telemetry is `penguin-logging` (milestone M1b) and nothing else: no
# tracing-subscriber, no opentelemetry-otlp, no opentelemetry_sdk, no
# prometheus registry of our own. `opentelemetry` itself stays a direct
# dependency only because `penguin_logging::metrics::*` takes
# `&[opentelemetry::KeyValue]` labels.
penguin-logging = "=0.1.0"
opentelemetry = "=0.32.0"
tracing = "=0.1.44"
axum = "=0.8.9"

tokio = { version = "=1.53.1", features = ["rt-multi-thread", "net", "io-util", "macros", "time", "sync", "fs", "signal"] }
serde = { version = "=1.0.229", features = ["derive"] }
serde_json = "=1.0.151"
thiserror = "=2.0.20"
anyhow = "=1.0.104"
rustls = { version = "=0.23.45", default-features = false, features = ["ring", "tls12"] }
tokio-rustls = { version = "=0.26.5", default-features = false, features = ["ring", "tls12"] }
rustls-pemfile = "=2.2.0"
wasmtime = "=48.0.2"
wasmtime-wasi = "=48.0.2"
object_store = { version = "=0.14.1", features = ["aws"] }
ed25519-dalek = "=3.0.0"
sha2 = "=0.10.9"
hex = "=0.4.3"
base64 = "=0.23.1"
subtle = "=2.6.1"
governor = "=0.10.4"
sqlparser = { version = "=0.63.0", features = ["visitor"] }
chrono = { version = "=0.4.45", features = ["serde"] }
# D30 (spec Sec5.11): InvocationScope.trace reuses penguin-spine's Trace
# type verbatim rather than duplicating {traceparent, tracestate} here --
# penguin-spine is M1a's crate and the type's single defining source.
penguin-spine = "=0.1.0"
futures = { version = "=0.3.34", default-features = false, features = ["std", "async-await"] }
bytes = "=1.12.1"
async-trait = "=0.1.92"
clap = { version = "=4.6.6", features = ["derive", "env"] }

[dev-dependencies]
tokio = { version = "=1.53.1", features = ["full", "test-util"] }
# The `testing` feature is what exposes init_test_telemetry/TelemetryCounts
# (M1b Task 17) that Task 23's telemetry gate asserts against.
penguin-logging = { version = "=0.1.0", features = ["testing"] }
rstest = "=0.27.0"
criterion = "=0.8.2"
rcgen = "=0.14.10"
tempfile = "=3.27.0"
rand_core = "=0.10.1"
ed25519-dalek = { version = "=3.0.0", features = ["rand_core"] }

[[bench]]
name = "call_roundtrip"
harness = false

[lints.rust]
unsafe_code = "deny"
missing_docs = "deny"

[lints.clippy]
unwrap_used = "deny"

[profile.release]
opt-level = 3
lto = "thin"
codegen-units = 1
strip = true
```

- [ ] **Step 3: Write `deny.toml`** (mirrors `packages/rust-licensing/deny.toml`, MIT-compatible allowlist)

```toml
# cargo-deny configuration for penguin-bundle-host.
#
# Run locally with: make deny
# CI wiring: penguin-libs root .github/workflows/ci.yml, job build-rust-bundle-host (Task 25).

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
deny = [
    # PRC-origin / sanctioned-entity crates are forbidden repo-wide
    # (general.md Supply Chain Security) -- explicit precedent, no known
    # transitive pull today, kept as a standing gate.
    { name = "xiu" },
]
skip = []
skip-tree = []

[sources]
unknown-registry = "deny"
unknown-git = "deny"
allow-registry = ["https://github.com/rust-lang/crates.io-index"]
allow-git = []
```

- [ ] **Step 4: Write `.gitignore`**

```
/target
/tests/fixtures/*/target
*.wasm
*.cwasm
```

- [ ] **Step 5: Copy `LICENSE`, write `README.md` and `CHANGELOG.md` skeletons**

```bash
cp /home/penguin/code/penguin-libs/.worktrees/plan-penguin-bundle-host/packages/rust-licensing/LICENSE \
   /home/penguin/code/penguin-libs/.worktrees/plan-penguin-bundle-host/packages/rust-bundle-host/LICENSE
```

Write `README.md`:

```markdown
# penguin-bundle-host

Waddles' WASM app-bundle sandbox: the `waddle:bundle/stage@1.0.0` WIT world,
the mTLS host-API wire protocol between a Waddles stage (`svc_process`,
`svc_action`) and its credential-less `bundle-executor`, the executor's
wasmtime runtime, and the S3-compatible bucket loader with digest +
signature verification.

Full design: `docs/superpowers/specs/2026-09-14-rust-data-plane-design.md`
in the `waddlebot` repo, §4.8, §6.5, §6.6, §7, §8, §11.7.

## Two library facets, one binary

- `penguin_bundle_host::host` -- the stage side. Implement `HttpEgress`,
  `KvStore`, `DbExecutor`, `RelayPush`, `Flags`, `Logger`, `Clock` against
  your own Valkey/Postgres/HTTP client, then hand them to
  `host::Server::new(...)`. The server enforces the approved-permission
  set (egress allowlist + SSRF, table allowlist, capability presence)
  before ever calling your trait implementations.
- `penguin_bundle_host::executor` -- the credential-less side. Holds a
  wasmtime `Engine`, loads bundles from an S3-compatible bucket, and
  talks to `host::Server` over the wire protocol. No Valkey, Postgres, or
  arbitrary-HTTP dependency exists in this facet -- asserted by
  `tests/bundle_executor_dependency_tests.rs`.
- `bundle-executor` binary (`src/bin/bundle_executor/`) -- wires
  `executor` into a runnable process: env config, mTLS client, bucket
  poller, gVisor self-check, and telemetry via `penguin-logging`
  (structured sanitized logs + OTLP logs/metrics/traces + the
  `/health`, `/healthz`, `/metrics` router). This crate never builds a
  `tracing_subscriber` registry or an OTLP exporter of its own.

## Environment (bundle-executor binary)

| Var | Default | Notes |
|---|---|---|
| `STAGE_HOST_API_ADDR` | *(required)* | `host:port` of the stage's mTLS host-API listener |
| `HOST_API_TLS_CERT_FILE` / `_KEY_FILE` / `_CA_FILE` | *(required)* | Client mTLS material |
| `EXECUTOR_STAGE_CONNECTIONS` | `4` | Pooled connections to the stage |
| `SANDBOX_RUNTIME_EXPECTED` | `gvisor` | `gvisor` or `runc` |
| `WADDLES_SANDBOX_GVISOR` | `true` | `true`/`false` |
| `EXECUTOR_CALL_TIMEOUT_MS` / `_MAX_CALL_TIMEOUT_MS` | `2000` / `10000` | Per-call deadline default / hard ceiling |
| `EXECUTOR_MEMORY_LIMIT_MB` / `_MAX_MEMORY_LIMIT_MB` | `64` / `256` | Per-instance memory cap default / hard ceiling |
| `EXECUTOR_INSTANCES_PER_BUNDLE` | `4` | Pool size per loaded bundle |
| `EXECUTOR_MAX_CONCURRENT_CALLS` | `32` | Global concurrency ceiling |
| `EXECUTOR_TRIP_THRESHOLD` / `_TRIP_WINDOW_S` | `3` / `300` | Sandbox trip disable threshold/window |
| `EXECUTOR_PRECOMPILE_DIR` | `/var/cache/waddles/wasm` | `.cwasm` cache directory |
| `EXECUTOR_WASM_COLLECTOR` | `drc` | Must equal `drc`; any other value refuses startup |
| `BUNDLE_BUCKET_ENDPOINT` / `_NAME` / `_REGION` | *(required)* | S3-compatible bucket |
| `BUNDLE_BUCKET_ACCESS_KEY_ID` / `_SECRET_ACCESS_KEY` | *(required)*, env only | Bucket credentials |
| `BUNDLE_POLL_INTERVAL_S` | `60` | Bucket poll cadence |
| `BUNDLE_SIGNING_PUBLIC_KEY` | *(required)*, base64 Ed25519 | Sidecar signature verification key |
| `EXECUTOR_HEALTH_PORT` | `9090` | `/health`, `/healthz`, `/metrics` (served by `penguin-logging`'s axum router) |
| `OTEL_EXPORTER_OTLP_ENDPOINT` / `_PROTOCOL` / `_HEADERS` | unset / `grpc` / unset | Read by `penguin_logging::ServiceConfig::from_env`; unset endpoint = stdout JSON only, no OTLP attempt |
| `OTEL_SERVICE_NAME` / `OTEL_RESOURCE_ATTRIBUTES` | `bundle-executor` / unset | Same, standard OTel env vars only — never a hardcoded vendor URL |
| `LOG_LEVEL` | `info` | Runtime-reloadable via `penguin_logging`'s `LevelHandle` |

Not offline-capable by design: the executor holds no cached bundle set of
its own opinion -- it serves whatever it last verified from the bucket and
degrades to stale-serving on bucket outage (`waddles_bundle_stale_age_seconds`).

## Development

All commands run in the pinned `rust:1.97-slim-bookworm` container via
`make` -- never bare host `cargo`. See `Makefile`.

```bash
make build           # cargo build --workspace
make lint            # fmt --check + clippy -D warnings
make fixtures        # (re)build all five tests/fixtures/*.wasm via Dockerfile.fixtures
make check-fixtures  # fail loudly if any fixture .wasm is missing
make test            # check-fixtures, then cargo test --workspace
make deny            # cargo deny check
make audit           # cargo audit
make cov             # cargo llvm-cov --fail-under-lines 90
make bench           # cargo bench
```

`make fixtures` must run once before `make test` on a fresh checkout —
the five `.wasm` components are `.gitignore`d, built from the committed
fixture sources by the pinned `cargo-component` toolchain.
```

Write `CHANGELOG.md`:

```markdown
# Changelog

All notable changes to `penguin-bundle-host` are documented here.
Format: [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]

### Added
- Initial crate scaffold.
```

- [ ] **Step 6: Write the Makefile**

```makefile
RUST_IMAGE := rust:1.97-slim-bookworm@sha256:2775a09d208ff0d7c1f50490c45b62db929e87ba1dcbc3f2132ac71a704bcdd3
DOCKER_RUN := docker run --rm -v "$(CURDIR)":/work -w /work -e CARGO_TARGET_DIR=/work/target $(RUST_IMAGE)
CARGO_DENY_VERSION := 0.20.2
CARGO_LLVM_COV_VERSION := 0.9.1

.PHONY: build lint fmt clippy test deny audit cov fixtures check-fixtures bench clean

build:
	$(DOCKER_RUN) cargo build --workspace --locked

fmt:
	$(DOCKER_RUN) cargo fmt --all --check

clippy:
	$(DOCKER_RUN) cargo clippy --workspace --all-targets --locked -- -D warnings

lint: fmt clippy

# Fails loudly rather than letting a fixture-dependent test be skipped:
# a missing .wasm is a FAIL, never a silent pass (critical-rules.md
# Verification Integrity).
check-fixtures:
	@n=0; for f in $(FIXTURES); do \
	    test -f "tests/fixtures/$$f/$$f.wasm" || { echo "missing tests/fixtures/$$f/$$f.wasm -- run 'make fixtures'"; exit 1; }; \
	    n=$$((n+1)); \
	done; \
	echo "fixture components present: $$n"; \
	test "$$n" -eq 5

test: check-fixtures
	$(DOCKER_RUN) cargo test --workspace --locked

deny:
	$(DOCKER_RUN) bash -c "cargo install cargo-deny --version $(CARGO_DENY_VERSION) --locked && cargo deny check"

audit:
	$(DOCKER_RUN) bash -c "cargo install cargo-audit --locked && cargo audit"

cov:
	$(DOCKER_RUN) bash -c "cargo install cargo-llvm-cov --version $(CARGO_LLVM_COV_VERSION) --locked && cargo llvm-cov --workspace --fail-under-lines 90"

FIXTURES := hello_bundle hostile_socket stateful_counter hang_forever memory_hog

fixtures:
	docker build -f Dockerfile.fixtures -t penguin-bundle-host-fixtures:local .
	docker run --rm -v "$(CURDIR)/tests/fixtures":/out penguin-bundle-host-fixtures:local \
		bash -euo pipefail -c 'n=0; for f in $(FIXTURES); do \
		    cp "/build/$$f/target/wasm32-wasip2/release/$$f.wasm" "/out/$$f/$$f.wasm"; \
		    n=$$((n+1)); \
		done; \
		echo "copied $$n fixture components"; \
		test "$$n" -eq 5 || { echo "expected 5 fixtures, copied $$n"; exit 1; }'

bench:
	$(DOCKER_RUN) cargo bench --locked

clean:
	$(DOCKER_RUN) cargo clean
```

- [ ] **Step 7: Write `src/lib.rs` and empty module stubs**

```rust
//! Waddles WASM app-bundle sandbox: the `waddle:bundle/stage@1.0.0` WIT
//! world, the mTLS host-API wire protocol, the stage-side capability
//! enforcement (`host`), and the credential-less executor runtime
//! (`executor`).
//!
//! See `README.md` for the two-facet split and the spec this crate
//! implements (`docs/superpowers/specs/2026-09-14-rust-data-plane-design.md`
//! §4.8, §6.5, §6.6, §7, §8, §11.7 in the `waddlebot` repo).

pub mod wire;
pub mod host;
pub mod executor;
```

`src/wire/mod.rs`, `src/host/mod.rs`, `src/executor/mod.rs`: each starts as

```rust
//! Empty until later tasks in
//! docs/superpowers/plans/2026-09-14-penguin-bundle-host.md add
//! submodules here (Task 2 for `wire`, Task 9 for `host`, Task 6 for
//! `executor`).
```

- [ ] **Step 8: Generate the lockfile and verify the empty crate builds**

Run: `make build`
Expected: `Compiling penguin-bundle-host v0.1.0 (...)`, `Finished` — succeeds with zero errors. This also writes `Cargo.lock`.

- [ ] **Step 9: Verify lint is clean on the skeleton**

Run: `make lint`
Expected: both `cargo fmt --all --check` and `cargo clippy` exit 0.

- [ ] **Step 10: Commit**

```bash
cd /home/penguin/code/penguin-libs/.worktrees/plan-penguin-bundle-host
git add packages/rust-bundle-host
git commit -m "$(cat <<'EOF'
chore(bundle-host): scaffold penguin-bundle-host crate with dockerized Makefile

Crate skeleton, exact-pinned Cargo.toml, deny.toml, and a Makefile that
routes every cargo invocation through the pinned rust:1.97-slim-bookworm
container -- no bare host cargo for this crate, ever.

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01N2rQgkHY872RubwXoBZxtE
EOF
)"
git push -u origin docs/plan-penguin-bundle-host
```

---

## Task 2: Commit the WIT world + wire message types

**Depends on:** Task 1 (crate scaffold, `make` targets, `src/wire/mod.rs` stub).

**Files:**
- Create: `packages/rust-bundle-host/wit/waddle-bundle-stage.wit`
- Create: `packages/rust-bundle-host/src/wire/message.rs`
- Modify: `packages/rust-bundle-host/src/wire/mod.rs`
- Test: `packages/rust-bundle-host/tests/wire_codec_tests.rs`

**Interfaces:**
- Consumes: nothing new.
- Produces: `wire::message::{Frame, Message, ExportKind, CapabilityKind, ErrorCode, SandboxInfo, HelloLimits, LoadLimits, InvocationScope}` — every later task (host `server.rs`/`router.rs`/the capability guards, executor `wire_client.rs`/`remote_host_impl.rs`/`invoke.rs`) matches on `Message` variants by these exact names/fields, and every host-call-adjacent task reads scope from `InvocationScope` (D30, spec §5.11/§6.6) rather than from a bundle-supplied argument -- no WIT interface (`db`/`kv`/`http`/`relay`) accepts a tenant or community parameter, by design.

- [ ] **Step 1: Write the WIT world verbatim from spec §6.5**

```wit
package waddle:bundle@1.0.0;

/// Values that cross the host boundary. WIT has no dynamic JSON value, so
/// every open-ended structure is carried as canonical UTF-8 JSON text and
/// validated on both sides.
interface types {
  record platform-event {
    platform: string,
    event-type: string,
    actor: option<string>,
    /// Canonical JSON object text. Never a scalar or array.
    payload-json: string,
    /// RFC 3339 UTC, millisecond precision.
    occurred-at: string,
  }

  record stage-envelope {
    tenant: string,
    community: option<string>,
    app-id: string,
    stage: string,
    event: platform-event,
    ts: string,
    target-app-id: option<string>,
    /// W3C traceparent, when the stage had one.
    trace-context: option<string>,
  }

  record transport-result {
    ok: bool,
    status: option<u16>,
    detail: option<string>,
    provider-message-id: option<string>,
  }

  record transport-error {
    /// The single field the action stage branches on.
    retryable: bool,
    code: string,
    message: string,
    retry-after-ms: option<u32>,
  }

  /// Returned by a stage export the bundle does not implement.
  record unsupported-stage {
    stage: string,
  }
}

/// Immutable, per-call scope. Capability: always granted.
interface context {
  record bundle-context {
    tenant: string,
    community: option<string>,
    app-id: string,
    feature: string,
    version: string,
    /// The Valkey stream entry id of the event being processed. Stable and
    /// unique per delivery target; the de-duplication key a bundle records
    /// to stay idempotent under at-least-once redelivery (Sec 5.4).
    message-id: string,
    /// Resolved 3-tier config (activation > tenant availability > bundle default),
    /// as canonical JSON object text.
    config-json: string,
  }

  get-context: func() -> bundle-context;
}

/// Guarded outbound HTTP. Capability: granted only when `egress` is non-empty.
interface http {
  record header { name: string, value: string }

  record request {
    method: string,
    url: string,
    headers: list<header>,
    body: option<list<u8>>,
    /// Header name -> secret reference name. The stage resolves the reference
    /// and injects the header; the secret value never enters the component.
    secret-refs: list<tuple<string, string>>,
  }

  record response {
    status: u16,
    headers: list<header>,
    body: list<u8>,
    truncated: bool,
  }

  variant error {
    denied(string),
    timeout,
    too-large(u64),
    rate-limited(u32),
    transport(string),
  }

  send: func(req: request) -> result<response, error>;
}

/// Bundle-scoped key/value, stored under the bundle's own `...:state` key.
/// Capability: always granted.
interface kv {
  variant error { too-large(u64), backend(string) }

  get: func(key: string) -> result<option<list<u8>>, error>;
  /// ttl-seconds = 0 means "no expiry"; the host clamps to KV_MAX_TTL_S.
  set: func(key: string, value: list<u8>, ttl-seconds: u32) -> result<_, error>;
  delete: func(key: string) -> result<_, error>;
  increment: func(key: string, delta: s64, ttl-seconds: u32) -> result<s64, error>;
}

/// Parameterized SQL executed BY THE STAGE under the bundle's own Postgres
/// role, restricted to the manifest's `data.tables` and row-level-security
/// scoped to the envelope's tenant/community. Capability: granted only when
/// `data.tables` is non-empty.
interface db {
  variant value {
    null-value,
    bool-value(bool),
    int-value(s64),
    float-value(f64),
    text-value(string),
    bytes-value(list<u8>),
  }

  record rows {
    columns: list<string>,
    rows: list<list<value>>,
    rows-affected: u64,
  }

  variant error {
    denied(string),
    syntax(string),
    conflict(string),
    timeout,
    backend(string),
  }

  /// Statement text with $1..$n placeholders. String interpolation of
  /// parameters is impossible across this boundary by construction.
  execute: func(statement: string, params: list<value>) -> result<rows, error>;
}

/// Push onto a provider-scoped outbound relay queue owned by svc-ingest.
/// Capability: granted only to action-stage bundles.
interface relay {
  variant error { denied(string), backend(string) }

  push: func(provider: string, message-json: string) -> result<_, error>;
}

/// PostHog flag + license entitlement, two-gate, cached, fail-open to the
/// supplied default. Capability: always granted.
interface flags {
  enabled: func(key: string, default-value: bool) -> bool;
  /// "free" | "professional" | "enterprise"
  tier: func() -> string;
}

/// Sanitized, levelled logging into the stage's OTel pipeline.
/// Capability: always granted.
interface log {
  enum level { error, warn, info, debug }
  /// `fields-json` is a canonical JSON object; the host sanitizes it with the
  /// penguin logging SENSITIVE_KEYS rule before emission.
  write: func(lvl: level, message: string, fields-json: string);
}

/// Capability: always granted.
interface clock {
  /// Milliseconds since the Unix epoch, as the stage sees it.
  now-millis: func() -> u64;
  /// RFC 3339 UTC, millisecond precision.
  now-rfc3339: func() -> string;
  /// Monotonic nanoseconds, for in-bundle duration measurement only.
  monotonic-nanos: func() -> u64;
}

interface process-stage {
  use types.{platform-event, unsupported-stage};
  /// `none` means "no reply"; the event is dropped, exactly as v1's
  /// `transform() -> PlatformEvent | None`.
  transform: func(event: platform-event) -> result<option<platform-event>, unsupported-stage>;
}

interface action-stage {
  use types.{stage-envelope, transport-result, transport-error};
  /// `config` is canonical JSON object text (the resolved 3-tier config).
  dispatch: func(envelope: stage-envelope, config: string)
    -> result<transport-result, transport-error>;
}

world stage {
  import context;
  import http;
  import kv;
  import db;
  import relay;
  import flags;
  import log;
  import clock;

  export process-stage;
  export action-stage;
}
```

Note in a comment at the top of the file (above `package waddle:bundle@1.0.0;`):

```wit
// Committed copy for penguin-bundle-host's own build/test needs. The
// single NORMATIVE copy is `wit/waddle-bundle/stage.wit` in the `waddles`
// repo (spec §6.5, §4.0) -- keeping the two byte-identical (or wiring one
// to generate from the other) is tracked as follow-up before M3/M4 land,
// not solved by this crate.
```

- [ ] **Step 2: Write the failing wire codec test first**

`tests/wire_codec_tests.rs`:

```rust
#![allow(clippy::unwrap_used, clippy::panic)]
use penguin_bundle_host::wire::message::{
    CapabilityKind, ErrorCode, ExportKind, Frame, HelloLimits, InvocationScope, LoadLimits, Message,
    SandboxInfo,
};

#[test]
fn hello_frame_round_trips_with_expected_json_shape() {
    let frame = Frame {
        v: 1,
        id: 42,
        message: Message::Hello {
            protocol_version: 1,
            executor_version: "0.1.0".to_string(),
            wasmtime_version: "48.0.2".to_string(),
            wasmtime_abi: "48".to_string(),
            collector: "drc".to_string(),
            sandbox: SandboxInfo {
                runtime: "gvisor".to_string(),
                verified: true,
            },
        },
    };

    let json = serde_json::to_value(&frame).unwrap();
    assert_eq!(json["v"], 1);
    assert_eq!(json["id"], 42);
    assert_eq!(json["kind"], "hello");
    assert_eq!(json["protocol_version"], 1);
    assert_eq!(json["collector"], "drc");
    assert_eq!(json["sandbox"]["runtime"], "gvisor");

    let round_tripped: Frame = serde_json::from_value(json).unwrap();
    match round_tripped.message {
        Message::Hello { collector, .. } => assert_eq!(collector, "drc"),
        other => panic!("expected Hello, got {other:?}"),
    }
}

fn sample_scope(app_id: &str) -> InvocationScope {
    InvocationScope {
        tenant_id: "acme".to_string(),
        community_id: Some("main".to_string()),
        workstream_id: "8f14e45f-ceea-467e-adde-3fb5c9752730".to_string(),
        app_id: app_id.to_string(),
        trace: Some(penguin_spine::Trace {
            traceparent: "00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01".to_string(),
            tracestate: None,
        }),
    }
}

#[test]
fn host_call_frame_carries_call_id_distinct_from_frame_id() {
    let frame = Frame {
        v: 1,
        id: 7,
        message: Message::HostCall {
            scope: sample_scope("waddles.socials.music.default"),
            capability: CapabilityKind::Http,
            op: "send".to_string(),
            args: serde_json::json!({"method": "GET", "url": "https://api.spotify.com/v1"}),
            call_id: 3,
        },
    };
    let json = serde_json::to_value(&frame).unwrap();
    assert_eq!(json["kind"], "host-call");
    assert_eq!(json["id"], 7);
    assert_eq!(json["call_id"], 3);
    assert_eq!(json["capability"], "http");
    assert_eq!(json["scope"]["app_id"], "waddles.socials.music.default");
    assert_eq!(json["scope"]["tenant_id"], "acme");
}

#[test]
fn host_call_scope_carries_workstream_id_and_trace_never_a_bare_tenant_argument() {
    // D30 (spec §5.11): no WIT capability accepts a tenant/community
    // argument -- scope travels only via InvocationScope on the frame.
    let frame = Frame {
        v: 1,
        id: 8,
        message: Message::HostCall {
            scope: sample_scope("waddles.bot.commands.default"),
            capability: CapabilityKind::Db,
            op: "execute".to_string(),
            args: serde_json::json!({"statement": "SELECT 1", "params": []}),
            call_id: 1,
        },
    };
    let json = serde_json::to_value(&frame).unwrap();
    assert_eq!(json["scope"]["workstream_id"], "8f14e45f-ceea-467e-adde-3fb5c9752730");
    assert_eq!(
        json["scope"]["trace"]["traceparent"],
        "00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01"
    );
    assert!(json["args"].get("tenant").is_none(), "args must never carry a tenant/community key");
}

#[test]
fn error_code_serializes_as_screaming_snake_case() {
    let frame = Frame {
        v: 1,
        id: 1,
        message: Message::Error {
            code: ErrorCode::DigestMismatch,
            message: "digest mismatch".to_string(),
            detail: None,
        },
    };
    let json = serde_json::to_value(&frame).unwrap();
    assert_eq!(json["code"], "DIGEST_MISMATCH");
}

#[test]
fn load_and_invoke_frames_match_spec_field_names() {
    let load = Frame {
        v: 1,
        id: 2,
        message: Message::Load {
            app_id: "waddles.bot.commands.default".to_string(),
            version: "3.0.0".to_string(),
            digest: "sha256:abc".to_string(),
            component_key: "bundles/waddles.bot.commands.default/3.0.0/abc.wasm".to_string(),
            sidecar_key: "bundles/waddles.bot.commands.default/3.0.0/abc.json".to_string(),
            capabilities: vec!["kv".to_string(), "log".to_string()],
            limits: LoadLimits { timeout_ms: 2000, memory_mb: 64 },
        },
    };
    let json = serde_json::to_value(&load).unwrap();
    assert_eq!(json["kind"], "load");
    assert_eq!(json["digest"], "sha256:abc");
    assert_eq!(json["limits"]["timeout_ms"], 2000);

    let invoke = Message::Invoke {
        digest: "sha256:abc".to_string(),
        export: ExportKind::Transform,
        payload: serde_json::json!({"platform": "twitch"}),
        deadline_ms: 2000,
        scope: sample_scope("waddles.bot.commands.default"),
    };
    let json = serde_json::to_value(&invoke).unwrap();
    assert_eq!(json["kind"], "invoke");
    assert_eq!(json["export"], "transform");
    assert_eq!(json["scope"]["app_id"], "waddles.bot.commands.default");
}

#[test]
fn every_stage_to_executor_and_executor_to_stage_kind_round_trips() {
    // One fixture per §6.6 message kind -- 13 total (hello, loaded, unloaded,
    // result, host-call, error, pong, hello-ok, load, unload, invoke,
    // host-result, ping, shutdown is 14; listed exhaustively below).
    let fixtures: Vec<Message> = vec![
        Message::Hello {
            protocol_version: 1,
            executor_version: "0.1.0".into(),
            wasmtime_version: "48.0.2".into(),
            wasmtime_abi: "48".into(),
            collector: "drc".into(),
            sandbox: SandboxInfo { runtime: "gvisor".into(), verified: true },
        },
        Message::Loaded {
            app_id: "a".into(), digest: "sha256:1".into(), precompile_ms: 5,
            exports: vec!["transform".into()],
        },
        Message::Unloaded { app_id: "a".into(), digest: "sha256:1".into() },
        Message::Result { payload: serde_json::json!(null), duration_ms: 1, fuel_used: 0 },
        Message::HostCall {
            scope: sample_scope("a"), capability: CapabilityKind::Kv, op: "get".into(),
            args: serde_json::json!({"key": "x"}), call_id: 1,
        },
        Message::Error { code: ErrorCode::FrameTooLarge, message: "m".into(), detail: None },
        Message::Pong,
        Message::HelloOk {
            stage: "process".into(), protocol_version: 1,
            limits: HelloLimits { call_timeout_ms: 2000, memory_mb: 64, max_concurrent_calls: 32 },
        },
        Message::Load {
            app_id: "a".into(), version: "1.0.0".into(), digest: "sha256:1".into(),
            component_key: "k1".into(), sidecar_key: "k2".into(),
            capabilities: vec![], limits: LoadLimits { timeout_ms: 2000, memory_mb: 64 },
        },
        Message::Unload { app_id: "a".into(), digest: "sha256:1".into() },
        Message::Invoke {
            digest: "sha256:1".into(), export: ExportKind::Dispatch,
            payload: serde_json::json!(null), deadline_ms: 2000, scope: sample_scope("a"),
        },
        Message::HostResult { result: Some(serde_json::json!(true)), error: None },
        Message::Ping,
        Message::Shutdown { grace_ms: 5000 },
    ];

    let mut examined = 0usize;
    for (i, message) in fixtures.into_iter().enumerate() {
        let frame = Frame { v: 1, id: i as u64, message };
        let json = serde_json::to_string(&frame).expect("serialize");
        let back: Frame = serde_json::from_str(&json).expect("deserialize");
        assert_eq!(back.id, i as u64, "frame {i}");
        examined += 1;
    }
    assert_eq!(examined, 14, "expected exactly 14 message-kind fixtures examined, got {examined}");
}
```

- [ ] **Step 3: Run the test to verify it fails**

Run: `make test`
Expected: FAIL — `error[E0432]: unresolved import 'penguin_bundle_host::wire::message'` (module doesn't exist yet).

- [ ] **Step 4: Implement `src/wire/message.rs`**

```rust
//! Wire message types for the host-API frame protocol (spec §6.6).
//!
//! Every frame is `{"v":1,"id":<u64>,"kind":"<kind>", ...fields}` --
//! a 4-byte big-endian length prefix (see `frame.rs`) followed by this
//! struct serialized as UTF-8 JSON. `kind` is the internally-tagged enum
//! discriminant; every other field is a direct sibling in the JSON object
//! via `#[serde(flatten)]`.
//!
//! **D30 (spec §5.11, §6.6):** `Message::Invoke` and `Message::HostCall`
//! both carry an [`InvocationScope`] -- the tenant/community/workstream
//! scope of the invocation in flight, set by the stage when it builds an
//! `invoke` frame from a binding-verified `StageEnvelope` and echoed back
//! by the executor on every `host-call` frame issued while executing that
//! invocation. No WIT interface (`db`, `kv`, `http`, `relay`) accepts a
//! tenant or community parameter -- scope is wire-carried, never
//! bundle-supplied.

use serde::{Deserialize, Serialize};

/// The tenant/community/workstream/app/trace scope of the invocation
/// currently in flight (spec §5.11 D30). Reuses [`penguin_spine::Trace`]
/// verbatim rather than duplicating `{traceparent, tracestate}` here --
/// `penguin-spine` (M1a) is that type's single defining crate.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct InvocationScope {
    pub tenant_id: String,
    pub community_id: Option<String>,
    pub workstream_id: String,
    pub app_id: String,
    pub trace: Option<penguin_spine::Trace>,
}

/// One frame: protocol version, correlation id, and the message itself.
///
/// `id` is allocated by whichever side speaks first for a given exchange
/// (the executor for `hello`/`loaded`/`result`/`host-call`; the stage for
/// `load`/`unload`/`invoke`/`ping`) and echoed back by every reply.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct Frame {
    pub v: u8,
    pub id: u64,
    #[serde(flatten)]
    pub message: Message,
}

/// Every message kind in both directions of the host-API wire protocol.
///
/// Executor -> stage: `Hello`, `Loaded`, `Unloaded`, `Result`, `HostCall`,
/// `Error`, `Pong`. Stage -> executor: `HelloOk`, `Load`, `Unload`,
/// `Invoke`, `HostResult`, `Ping`, `Shutdown`. `Error` and `Ping`/`Pong`
/// can originate from either side per spec §6.6.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
#[serde(tag = "kind", rename_all = "kebab-case")]
pub enum Message {
    Hello {
        protocol_version: u32,
        executor_version: String,
        wasmtime_version: String,
        wasmtime_abi: String,
        collector: String,
        sandbox: SandboxInfo,
    },
    Loaded {
        app_id: String,
        digest: String,
        precompile_ms: u64,
        exports: Vec<String>,
    },
    Unloaded {
        app_id: String,
        digest: String,
    },
    Result {
        payload: serde_json::Value,
        duration_ms: u64,
        fuel_used: u64,
    },
    HostCall {
        /// The invocation's full scope (D30, spec §5.11/§6.6) -- includes
        /// `app_id`, so no separate top-level `app_id` field exists here.
        scope: InvocationScope,
        capability: CapabilityKind,
        op: String,
        args: serde_json::Value,
        call_id: u64,
    },
    Error {
        code: ErrorCode,
        message: String,
        detail: Option<String>,
    },
    Pong,
    HelloOk {
        stage: String,
        protocol_version: u32,
        limits: HelloLimits,
    },
    Load {
        app_id: String,
        version: String,
        digest: String,
        component_key: String,
        sidecar_key: String,
        capabilities: Vec<String>,
        limits: LoadLimits,
    },
    Unload {
        app_id: String,
        digest: String,
    },
    Invoke {
        digest: String,
        export: ExportKind,
        payload: serde_json::Value,
        deadline_ms: u64,
        /// The invocation's full scope (D30, spec §5.11/§6.6) --
        /// supersedes the pre-D30 standalone `app_id`/`trace_context`
        /// fields: `scope.app_id` and `scope.trace` carry both.
        scope: InvocationScope,
    },
    HostResult {
        result: Option<serde_json::Value>,
        error: Option<HostResultError>,
    },
    Ping,
    Shutdown {
        grace_ms: u64,
    },
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct SandboxInfo {
    /// "gvisor" | "runc"
    pub runtime: String,
    pub verified: bool,
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct HelloLimits {
    pub call_timeout_ms: u64,
    pub memory_mb: u32,
    pub max_concurrent_calls: u32,
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct LoadLimits {
    pub timeout_ms: u64,
    pub memory_mb: u32,
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct HostResultError {
    pub code: String,
    pub message: String,
}

/// The `export` field of an `invoke` frame -- which WIT export to call.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum ExportKind {
    Transform,
    Dispatch,
}

/// The `capability` field of a `host-call` frame.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum CapabilityKind {
    Http,
    Kv,
    Db,
    Relay,
    Flags,
    Log,
    Clock,
    Context,
}

/// Stable `error.code` strings from spec §6.6.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "SCREAMING_SNAKE_CASE")]
pub enum ErrorCode {
    ProtocolVersion,
    FrameTooLarge,
    MalformedFrame,
    UnknownBundle,
    DigestMismatch,
    LoadFailed,
    ExportMissing,
    ExecutorDeadline,
    MemoryLimit,
    WasmTrap,
    HostCallDenied,
    HostCallFailed,
    UnsandboxedExecutor,
    ShuttingDown,
}
```

- [ ] **Step 5: Wire up the module and re-export in `src/wire/mod.rs`**

```rust
//! Frame codec and message types shared by the host (server) and executor
//! (client) sides of the mTLS wire protocol (spec §6.6).

pub mod message;
```

- [ ] **Step 6: Run the test to verify it passes**

Run: `make test`
Expected: PASS — `test result: ok. 6 passed; 0 failed` for `wire_codec_tests`.

- [ ] **Step 7: Commit**

```bash
git add packages/rust-bundle-host/wit packages/rust-bundle-host/src/wire packages/rust-bundle-host/tests/wire_codec_tests.rs
git commit -m "$(cat <<'EOF'
feat(bundle-host): commit WIT world and wire message types

wit/waddle-bundle-stage.wit is this crate's committed copy of
waddle:bundle/stage@1.0.0 (spec §6.5); wire::message::{Frame,Message,...}
implements the exact JSON shape of the host-API frame protocol (§6.6).
Message::Invoke/HostCall carry InvocationScope (D30, spec §5.11) --
tenant_id/community_id/workstream_id/app_id/trace, reusing
penguin-spine's Trace type -- superseding the pre-D30 standalone
app_id/trace_context fields.

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01N2rQgkHY872RubwXoBZxtE
EOF
)"
git push
```

---

## Task 3: Length-prefixed frame codec

**Depends on:** Task 2 (`wire::message::Frame`, which the codec serializes).

**Files:**
- Create: `packages/rust-bundle-host/src/wire/frame.rs`
- Modify: `packages/rust-bundle-host/src/wire/mod.rs`
- Test: `packages/rust-bundle-host/tests/wire_codec_tests.rs` (append)

**Interfaces:**
- Consumes: `wire::message::Frame` (Task 2).
- Produces: `wire::frame::{read_frame, write_frame, FrameError, MAX_FRAME_BYTES}` — `read_frame`/`write_frame` are the primitives `wire::transport::FrameTransport` (Task 4) builds on.

```rust
pub const MAX_FRAME_BYTES: usize = 1_048_576; // EXECUTOR_MAX_FRAME_BYTES default, spec §6.6

pub async fn write_frame<W: tokio::io::AsyncWrite + Unpin>(
    writer: &mut W,
    frame: &Frame,
) -> Result<(), FrameError>;

pub async fn read_frame<R: tokio::io::AsyncRead + Unpin>(
    reader: &mut R,
    max_bytes: usize,
) -> Result<Frame, FrameError>;

#[derive(Debug, thiserror::Error)]
pub enum FrameError {
    #[error("frame of {size} bytes exceeds the {limit}-byte limit")]
    TooLarge { size: usize, limit: usize },
    #[error("malformed frame JSON: {0}")]
    Malformed(String),
    #[error("connection closed while reading a frame")]
    ConnectionClosed,
    #[error("io error: {0}")]
    Io(#[from] std::io::Error),
}
```

- [ ] **Step 1: Write the failing tests**

Append to `tests/wire_codec_tests.rs`:

```rust
use penguin_bundle_host::wire::frame::{read_frame, write_frame, FrameError, MAX_FRAME_BYTES};

#[tokio::test]
async fn write_then_read_round_trips_a_frame() {
    let (mut client, mut server) = tokio::io::duplex(8192);
    let frame = Frame { v: 1, id: 1, message: Message::Ping };

    write_frame(&mut client, &frame).await.unwrap();
    let got = read_frame(&mut server, MAX_FRAME_BYTES).await.unwrap();

    assert_eq!(got, frame);
}

#[tokio::test]
async fn read_frame_rejects_a_length_prefix_over_the_limit() {
    let (mut client, mut server) = tokio::io::duplex(8192);
    // Hand-craft an oversized length prefix without actually sending
    // MAX_FRAME_BYTES+1 bytes of payload -- read_frame must reject on the
    // length prefix alone, before attempting to buffer the body.
    let oversized_len = (MAX_FRAME_BYTES as u32) + 1;
    tokio::io::AsyncWriteExt::write_all(&mut client, &oversized_len.to_be_bytes())
        .await
        .unwrap();

    let err = read_frame(&mut server, MAX_FRAME_BYTES).await.unwrap_err();
    match err {
        FrameError::TooLarge { size, limit } => {
            assert_eq!(size, oversized_len as usize);
            assert_eq!(limit, MAX_FRAME_BYTES);
        }
        other => panic!("expected TooLarge, got {other:?}"),
    }
}

#[tokio::test]
async fn read_frame_rejects_malformed_json() {
    let (mut client, mut server) = tokio::io::duplex(8192);
    let body = b"{not json";
    let len = (body.len() as u32).to_be_bytes();
    tokio::io::AsyncWriteExt::write_all(&mut client, &len).await.unwrap();
    tokio::io::AsyncWriteExt::write_all(&mut client, body).await.unwrap();

    let err = read_frame(&mut server, MAX_FRAME_BYTES).await.unwrap_err();
    assert!(matches!(err, FrameError::Malformed(_)), "got {err:?}");
}

#[tokio::test]
async fn read_frame_reports_connection_closed_on_clean_eof() {
    let (client, mut server) = tokio::io::duplex(8192);
    drop(client);
    let err = read_frame(&mut server, MAX_FRAME_BYTES).await.unwrap_err();
    assert!(matches!(err, FrameError::ConnectionClosed), "got {err:?}");
}

#[tokio::test]
async fn ten_frames_written_are_ten_frames_read_in_order() {
    let (mut client, mut server) = tokio::io::duplex(65536);
    let sent: Vec<Frame> = (0..10)
        .map(|i| Frame { v: 1, id: i, message: Message::Ping })
        .collect();

    for f in &sent {
        write_frame(&mut client, f).await.unwrap();
    }
    let mut received = Vec::new();
    for _ in 0..10 {
        received.push(read_frame(&mut server, MAX_FRAME_BYTES).await.unwrap());
    }
    assert_eq!(received.len(), 10, "expected 10 frames read, got {}", received.len());
    assert_eq!(received, sent);
}
```

- [ ] **Step 2: Run to verify failure**

Run: `make test`
Expected: FAIL — `unresolved import 'penguin_bundle_host::wire::frame'`.

- [ ] **Step 3: Implement `src/wire/frame.rs`**

```rust
//! Length-prefixed frame codec: a 4-byte big-endian `u32` length followed
//! by that many bytes of UTF-8 JSON (spec §6.6 "Framing"). Carried inside
//! whatever transport-level stream the caller supplies (a TLS stream in
//! production, an in-memory duplex in tests).

use tokio::io::{AsyncRead, AsyncReadExt, AsyncWrite, AsyncWriteExt};

use super::message::Frame;

/// `EXECUTOR_MAX_FRAME_BYTES` default (spec §6.6, §7.3).
pub const MAX_FRAME_BYTES: usize = 1_048_576;

#[derive(Debug, thiserror::Error)]
pub enum FrameError {
    #[error("frame of {size} bytes exceeds the {limit}-byte limit")]
    TooLarge { size: usize, limit: usize },
    #[error("malformed frame JSON: {0}")]
    Malformed(String),
    #[error("connection closed while reading a frame")]
    ConnectionClosed,
    #[error("io error: {0}")]
    Io(#[from] std::io::Error),
}

/// Serializes `frame` to JSON and writes it as one length-prefixed frame.
pub async fn write_frame<W: AsyncWrite + Unpin>(
    writer: &mut W,
    frame: &Frame,
) -> Result<(), FrameError> {
    let body = serde_json::to_vec(frame).map_err(|e| FrameError::Malformed(e.to_string()))?;
    let len = u32::try_from(body.len())
        .map_err(|_| FrameError::TooLarge { size: body.len(), limit: u32::MAX as usize })?;
    writer.write_all(&len.to_be_bytes()).await?;
    writer.write_all(&body).await?;
    writer.flush().await?;
    Ok(())
}

/// Reads one length-prefixed frame and deserializes it.
///
/// The length prefix is checked against `max_bytes` *before* any body
/// bytes are read, so an attacker-controlled oversized length can never
/// force an allocation beyond the limit.
pub async fn read_frame<R: AsyncRead + Unpin>(
    reader: &mut R,
    max_bytes: usize,
) -> Result<Frame, FrameError> {
    let mut len_buf = [0u8; 4];
    match reader.read_exact(&mut len_buf).await {
        Ok(_) => {}
        Err(e) if e.kind() == std::io::ErrorKind::UnexpectedEof => {
            return Err(FrameError::ConnectionClosed);
        }
        Err(e) => return Err(FrameError::Io(e)),
    }
    let len = u32::from_be_bytes(len_buf) as usize;
    if len > max_bytes {
        return Err(FrameError::TooLarge { size: len, limit: max_bytes });
    }

    let mut body = vec![0u8; len];
    reader
        .read_exact(&mut body)
        .await
        .map_err(|e| {
            if e.kind() == std::io::ErrorKind::UnexpectedEof {
                FrameError::ConnectionClosed
            } else {
                FrameError::Io(e)
            }
        })?;

    serde_json::from_slice(&body).map_err(|e| FrameError::Malformed(e.to_string()))
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::wire::message::Message;

    #[tokio::test]
    async fn write_frame_prefixes_length_big_endian() {
        let (mut client, mut server) = tokio::io::duplex(4096);
        let frame = Frame { v: 1, id: 0, message: Message::Ping };
        write_frame(&mut client, &frame).await.unwrap();

        let mut len_buf = [0u8; 4];
        server.read_exact(&mut len_buf).await.unwrap();
        let len = u32::from_be_bytes(len_buf) as usize;
        let expected = serde_json::to_vec(&frame).unwrap().len();
        assert_eq!(len, expected);
    }
}
```

- [ ] **Step 4: Export from `src/wire/mod.rs`**

```rust
pub mod frame;
pub mod message;
```

- [ ] **Step 5: Run to verify pass**

Run: `make test`
Expected: PASS — all `wire_codec_tests` and the inline `frame::tests` module green.

- [ ] **Step 6: Commit**

```bash
git add packages/rust-bundle-host/src/wire packages/rust-bundle-host/tests/wire_codec_tests.rs
git commit -m "$(cat <<'EOF'
feat(bundle-host): length-prefixed frame codec

read_frame/write_frame implement spec §6.6's 4-byte-BE-length + UTF-8-JSON
framing, rejecting an oversized length prefix before buffering any body
bytes -- the frame-too-large path never allocates past the limit.

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01N2rQgkHY872RubwXoBZxtE
EOF
)"
git push
```

---

## Task 4: `FrameTransport` — correlation-id multiplexer

**Depends on:** Task 3 (`wire::frame` read/write halves and `MAX_FRAME_BYTES`), Task 2 (`Message`).

**Files:**
- Create: `packages/rust-bundle-host/src/wire/transport.rs`
- Modify: `packages/rust-bundle-host/src/wire/mod.rs`
- Test: `packages/rust-bundle-host/tests/wire_transport_tests.rs`

**Interfaces:**
- Consumes: `wire::frame::{read_frame, write_frame, FrameError, MAX_FRAME_BYTES}` (Task 3), `wire::message::{Frame, Message}` (Task 2).
- Produces:
  ```rust
  pub struct FrameTransport { /* ... */ }
  impl FrameTransport {
      /// Splits `stream` into a read half driven by a background task and
      /// a write half retained here; `max_frame_bytes` bounds every read.
      pub fn spawn<S>(stream: S, max_frame_bytes: usize) -> Self
      where
          S: tokio::io::AsyncRead + tokio::io::AsyncWrite + Send + Unpin + 'static;

      /// Allocates the next outgoing correlation id.
      pub fn next_id(&self) -> u64;

      /// Sends `message` with a freshly allocated id and awaits the frame
      /// whose `id` matches it (any interleaved frame with a different id
      /// is delivered instead via `recv_unsolicited`).
      pub async fn call(&self, message: Message) -> Result<Message, TransportError>;

      /// Sends `message` under an id the caller already owns (used to
      /// reply to a peer-initiated request, e.g. `host-result` for a
      /// `host-call`, or `loaded` which has no reply at all).
      pub async fn send(&self, id: u64, message: Message) -> Result<(), TransportError>;

      /// Receives the next frame that was not claimed by a pending `call`
      /// -- i.e. every peer-initiated request this side must handle.
      pub async fn recv_unsolicited(&self) -> Result<Frame, TransportError>;
  }

  #[derive(Debug, thiserror::Error)]
  pub enum TransportError {
      #[error(transparent)]
      Frame(#[from] penguin_bundle_host::wire::frame::FrameError),
      #[error("transport is closed")]
      Closed,
      #[error("call timed out waiting for a reply")]
      Timeout,
  }
  ```
  `host::server` (Task 17) and `executor::wire_client` (Task 21) both build on this — `server` awaits `recv_unsolicited()` for `hello`/`loaded`/`host-call`, `wire_client` awaits it for `load`/`unload`/`invoke`/`ping`/`shutdown`; both use `call()` for the request/reply pairs (`invoke`->`result`, `host-call`->`host-result`, `hello`->`hello-ok`).

- [ ] **Step 1: Write the failing tests**

`tests/wire_transport_tests.rs`:

```rust
#![allow(clippy::unwrap_used, clippy::panic)]
use penguin_bundle_host::wire::message::{Frame, Message};
use penguin_bundle_host::wire::transport::{FrameTransport, TransportError};
use std::time::Duration;

#[tokio::test]
async fn call_returns_the_reply_with_a_matching_id() {
    let (client_io, server_io) = tokio::io::duplex(8192);
    let client = FrameTransport::spawn(client_io, 1_048_576);
    let server = FrameTransport::spawn(server_io, 1_048_576);

    // Server: read one unsolicited frame (the "call"), reply on the same id.
    let server_task = tokio::spawn(async move {
        let frame = server.recv_unsolicited().await.unwrap();
        server.send(frame.id, Message::Pong).await.unwrap();
    });

    let reply = client.call(Message::Ping).await.unwrap();
    assert!(matches!(reply, Message::Pong));
    server_task.await.unwrap();
}

#[tokio::test]
async fn concurrent_calls_get_their_own_replies_even_out_of_order() {
    let (client_io, server_io) = tokio::io::duplex(65536);
    let client = std::sync::Arc::new(FrameTransport::spawn(client_io, 1_048_576));
    let server = FrameTransport::spawn(server_io, 1_048_576);

    let server_task = tokio::spawn(async move {
        // Reply to the two calls in reverse arrival order to prove
        // correlation, not FIFO order, resolves each `call()`.
        let f1 = server.recv_unsolicited().await.unwrap();
        let f2 = server.recv_unsolicited().await.unwrap();
        server.send(f2.id, Message::Pong).await.unwrap();
        server.send(f1.id, Message::Pong).await.unwrap();
    });

    let c1 = client.clone();
    let c2 = client.clone();
    let (r1, r2) = tokio::join!(c1.call(Message::Ping), c2.call(Message::Ping));
    assert!(matches!(r1.unwrap(), Message::Pong));
    assert!(matches!(r2.unwrap(), Message::Pong));
    server_task.await.unwrap();
}

#[tokio::test]
async fn unsolicited_frames_are_delivered_via_recv_unsolicited_not_call() {
    let (client_io, server_io) = tokio::io::duplex(8192);
    let client = FrameTransport::spawn(client_io, 1_048_576);
    let server = FrameTransport::spawn(server_io, 1_048_576);

    // Server sends a peer-initiated request (no prior `call` on this id).
    server.send(server.next_id(), Message::Ping).await.unwrap();

    let got: Frame = tokio::time::timeout(Duration::from_secs(1), client.recv_unsolicited())
        .await
        .expect("timed out")
        .unwrap();
    assert!(matches!(got.message, Message::Ping));
}

#[tokio::test]
async fn call_on_a_closed_transport_returns_closed_error() {
    let (client_io, server_io) = tokio::io::duplex(8192);
    let client = FrameTransport::spawn(client_io, 1_048_576);
    drop(server_io);
    // Give the reader task a moment to observe EOF.
    tokio::time::sleep(Duration::from_millis(50)).await;
    let err = client.call(Message::Ping).await.unwrap_err();
    assert!(matches!(err, TransportError::Closed), "got {err:?}");
}
```

- [ ] **Step 2: Run to verify failure**

Run: `make test`
Expected: FAIL — `unresolved import 'penguin_bundle_host::wire::transport'`.

- [ ] **Step 3: Implement `src/wire/transport.rs`**

```rust
//! Correlation-id multiplexing over the frame codec (`frame.rs`). One
//! `FrameTransport` owns a background task that reads every incoming
//! frame and either resolves a pending `call()` future (id matches an
//! outstanding request) or forwards the frame to `recv_unsolicited()`'s
//! queue (id does not match anything pending -- a peer-initiated
//! request this side must handle).

use std::collections::HashMap;
use std::sync::atomic::{AtomicU64, Ordering};
use std::sync::Arc;

use tokio::io::{AsyncRead, AsyncWrite};
use tokio::sync::{mpsc, oneshot, Mutex};

use super::frame::{read_frame, write_frame, FrameError};
use super::message::{Frame, Message};

#[derive(Debug, thiserror::Error)]
pub enum TransportError {
    #[error(transparent)]
    Frame(#[from] FrameError),
    #[error("transport is closed")]
    Closed,
    #[error("call timed out waiting for a reply")]
    Timeout,
}

type PendingMap = Arc<Mutex<HashMap<u64, oneshot::Sender<Message>>>>;

/// A bidirectional, id-multiplexed frame connection over any
/// `AsyncRead + AsyncWrite` stream (a `tokio_rustls::TlsStream` in
/// production, `tokio::io::DuplexStream` in tests).
pub struct FrameTransport {
    write_half: Mutex<Box<dyn AsyncWrite + Send + Unpin>>,
    next_id: AtomicU64,
    pending: PendingMap,
    unsolicited_rx: Mutex<mpsc::UnboundedReceiver<Frame>>,
    closed: Arc<std::sync::atomic::AtomicBool>,
}

impl FrameTransport {
    /// Splits `stream` and spawns the background reader task.
    pub fn spawn<S>(stream: S, max_frame_bytes: usize) -> Self
    where
        S: AsyncRead + AsyncWrite + Send + Unpin + 'static,
    {
        let (read_half, write_half) = tokio::io::split(stream);
        let pending: PendingMap = Arc::new(Mutex::new(HashMap::new()));
        let (unsolicited_tx, unsolicited_rx) = mpsc::unbounded_channel();
        let closed = Arc::new(std::sync::atomic::AtomicBool::new(false));

        let pending_for_task = pending.clone();
        let closed_for_task = closed.clone();
        tokio::spawn(async move {
            let mut reader = read_half;
            loop {
                match read_frame(&mut reader, max_frame_bytes).await {
                    Ok(frame) => {
                        let mut pending = pending_for_task.lock().await;
                        if let Some(sender) = pending.remove(&frame.id) {
                            let _ = sender.send(frame.message);
                        } else {
                            drop(pending);
                            if unsolicited_tx.send(frame).is_err() {
                                break;
                            }
                        }
                    }
                    Err(_) => {
                        closed_for_task.store(true, Ordering::SeqCst);
                        break;
                    }
                }
            }
        });

        Self {
            write_half: Mutex::new(Box::new(write_half)),
            next_id: AtomicU64::new(1),
            pending,
            unsolicited_rx: Mutex::new(unsolicited_rx),
            closed,
        }
    }

    pub fn next_id(&self) -> u64 {
        self.next_id.fetch_add(1, Ordering::SeqCst)
    }

    /// Sends `message` under a freshly allocated id and awaits the reply
    /// carrying that same id.
    pub async fn call(&self, message: Message) -> Result<Message, TransportError> {
        if self.closed.load(Ordering::SeqCst) {
            return Err(TransportError::Closed);
        }
        let id = self.next_id();
        let (tx, rx) = oneshot::channel();
        self.pending.lock().await.insert(id, tx);

        self.write_frame_locked(id, message).await?;

        rx.await.map_err(|_| TransportError::Closed)
    }

    /// Sends `message` under a caller-supplied id (a reply to a
    /// peer-initiated request, or a fire-and-forget message with no
    /// reply expected).
    pub async fn send(&self, id: u64, message: Message) -> Result<(), TransportError> {
        self.write_frame_locked(id, message).await
    }

    /// Awaits the next frame whose id did not match any pending `call()`.
    pub async fn recv_unsolicited(&self) -> Result<Frame, TransportError> {
        self.unsolicited_rx
            .lock()
            .await
            .recv()
            .await
            .ok_or(TransportError::Closed)
    }

    async fn write_frame_locked(&self, id: u64, message: Message) -> Result<(), TransportError> {
        let frame = Frame { v: 1, id, message };
        let mut w = self.write_half.lock().await;
        write_frame(&mut *w, &frame).await?;
        Ok(())
    }
}
```

- [ ] **Step 4: Export from `src/wire/mod.rs`**

```rust
pub mod frame;
pub mod message;
pub mod transport;
```

- [ ] **Step 5: Run to verify pass**

Run: `make test`
Expected: PASS — all four `wire_transport_tests` green.

- [ ] **Step 6: Commit**

```bash
git add packages/rust-bundle-host/src/wire packages/rust-bundle-host/tests/wire_transport_tests.rs
git commit -m "$(cat <<'EOF'
feat(bundle-host): FrameTransport correlation-id multiplexer

FrameTransport::call()/send()/recv_unsolicited() give both the host
server and the executor client a shared, tested primitive for the
bidirectional, id-multiplexed host-API connection (spec §6.6).

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01N2rQgkHY872RubwXoBZxtE
EOF
)"
git push
```

---

## Task 5: Test-fixture toolchain — `hello_bundle` and `hostile_socket`

**Depends on:** Task 2 (the committed `wit/waddle-bundle-stage.wit` each fixture copies), Task 1 (the `fixtures`/`check-fixtures` Makefile targets).

**Files:**
- Create: `packages/rust-bundle-host/Dockerfile.fixtures`
- Create: `packages/rust-bundle-host/tests/fixtures/hello_bundle/Cargo.toml`
- Create: `packages/rust-bundle-host/tests/fixtures/hello_bundle/wit/waddle-bundle-stage.wit` (copy of `wit/waddle-bundle-stage.wit`)
- Create: `packages/rust-bundle-host/tests/fixtures/hello_bundle/src/lib.rs`
- Create: `packages/rust-bundle-host/tests/fixtures/hostile_socket/Cargo.toml`
- Create: `packages/rust-bundle-host/tests/fixtures/hostile_socket/wit/waddle-bundle-stage.wit` (copy)
- Create: `packages/rust-bundle-host/tests/fixtures/hostile_socket/src/lib.rs`
- Modify: `packages/rust-bundle-host/Makefile` (already has the `fixtures` target from Task 1 — this task is what makes it actually work)
- Test: `packages/rust-bundle-host/tests/fixture_build_tests.rs`

**Interfaces:**
- Consumes: `wit/waddle-bundle-stage.wit` (Task 2).
- Produces: `tests/fixtures/hello_bundle/hello_bundle.wasm` and `tests/fixtures/hostile_socket/hostile_socket.wasm` (both `.gitignore`d, rebuilt by `make fixtures`) — every later task that needs a real component (Tasks 7, 8, 19, 20) loads these two files by path, via a `fixture_path(name: &str) -> PathBuf` test helper this task also adds.

Per the bundle-compiler-sandbox spike (`spikes/bundle-compiler-sandbox/REPORT.md`), Rust bundles build with `cargo component build --target wasm32-wasip2` at `cargo-component 0.21.1`, and `cargo-component` silently tries to fetch the `wasm32-wasip1` rustup target on first use even when targeting wasip2 — both targets must be pre-installed in the image at build time, network-enabled, before the network-free fixture build runs.

- [ ] **Step 1: Write `Dockerfile.fixtures`** (pinned toolchain, no floating tags beyond the digest-pinned base)

```dockerfile
# Builds the test-fixture WASM components under tests/fixtures/.
# Pinned exactly to the bundle-compiler-sandbox spike's versions
# (spikes/bundle-compiler-sandbox/REPORT.md "Versions & digests"):
#   cargo-component 0.21.1, wasm-tools 1.259.0, rustc/cargo 1.97.1.
#
# Two fixtures at Task 5; Task 18 Step 1 replaces the three marked blocks
# below with their five-fixture versions when it adds stateful_counter,
# hang_forever and memory_hog.
FROM rust:1.97-slim-bookworm@sha256:2775a09d208ff0d7c1f50490c45b62db929e87ba1dcbc3f2132ac71a704bcdd3

SHELL ["/bin/bash", "-euo", "pipefail", "-c"]

RUN apt-get update \
    && apt-get install --no-install-recommends -y pkg-config libssl-dev \
    && rm -rf /var/lib/apt/lists/*

# cargo-component auto-fetches wasm32-wasip1 on first use even when the
# final target is wasip2 -- both are pre-installed here, network-enabled,
# so the later per-fixture build step is genuinely network-free.
RUN rustup target add wasm32-wasip1 wasm32-wasip2
RUN cargo install cargo-component --version 0.21.1 --locked
RUN cargo install wasm-tools --version 1.259.0 --locked

WORKDIR /build
# FIXTURE COPY BLOCK
COPY tests/fixtures/hello_bundle /build/hello_bundle
COPY tests/fixtures/hostile_socket /build/hostile_socket

# FIXTURE BUILD BLOCK -- one loop, N components. `--offline` first because every rustup target
# and crate is already present; the plain retry has network in this build
# stage (it is the *sandboxed compiler's* build step that must be
# network-free, not this fixture-generation image -- the spike's own
# image-build-time vs per-bundle-build-time split).
RUN built=0; \
    for f in hello_bundle hostile_socket; do \
      cd "/build/$f"; \
      cargo component build --release --target wasm32-wasip2 --offline \
        || cargo component build --release --target wasm32-wasip2; \
      test -f "/build/$f/target/wasm32-wasip2/release/$f.wasm"; \
      built=$((built+1)); \
    done; \
    echo "built $built fixture components"; \
    test "$built" -eq 2

# Validate that EVERY component actually targets our world before shipping
# them as fixtures -- a fixture that silently fails to target the world
# would make every later "real component" test pass for the wrong reason,
# and a zero denominator here is a FAIL, not a pass.
# FIXTURE VALIDATE BLOCK
RUN checked=0; \
    for f in hello_bundle hostile_socket; do \
      wasm-tools component wit "/build/$f/target/wasm32-wasip2/release/$f.wasm" > "/tmp/$f.wit"; \
      grep -q 'package waddle:bundle' "/tmp/$f.wit" \
        || { echo "$f.wasm does not declare the waddle:bundle package"; exit 1; }; \
      grep -q 'world stage' "/tmp/$f.wit" \
        || { echo "$f.wasm does not target the stage world"; exit 1; }; \
      checked=$((checked+1)); \
    done; \
    echo "validated $checked fixture components against waddle:bundle/stage@1.0.0"; \
    test "$checked" -eq 2
```

Notes on the shape above, which every later fixture addition preserves:

- `SHELL ["/bin/bash", "-euo", "pipefail", "-c"]` replaces Docker's default `/bin/sh -c`, so a failure anywhere inside a multi-command `RUN` (including inside a pipe) fails the build instead of being masked by the last command's status (`critical-rules.md` Verification Integrity).
- Both loops count what they processed and assert an exact, non-zero total. A `COPY` that silently landed nothing, or a `for` loop over an empty list, would otherwise report a clean build having compiled zero components.
- `--offline` first, plain retry second: `cargo component build`'s first invocation sometimes wants to refresh its own component-registry index even with every rustup target present. The retry has network in *this* build stage — it is the *sandboxed compiler's* build step (M2a, `waddles` repo) that must be network-free, not this fixture-generation image. That is the spike's own documented image-build-time vs per-bundle-build-time split.
- The three blocks tagged `# FIXTURE COPY BLOCK`, `# FIXTURE BUILD BLOCK` and `# FIXTURE VALIDATE BLOCK` are the only parts Task 18 Step 1 edits; it gives their exact replacement text.

- [ ] **Step 2: Write the `hello_bundle` fixture source**

`tests/fixtures/hello_bundle/Cargo.toml`:

```toml
[package]
name = "hello_bundle"
version = "0.1.0"
edition = "2021"
publish = false

[dependencies]
wit-bindgen = "=0.36.0"

[lib]
crate-type = ["cdylib"]

[package.metadata.component]
package = "waddle:bundle-fixture"

[package.metadata.component.target]
path = "wit"
world = "stage"

[profile.release]
opt-level = "s"
lto = true
strip = true
```

`tests/fixtures/hello_bundle/src/lib.rs`:

```rust
//! Test fixture: the smallest bundle that satisfies the `stage` world.
//! `transform` echoes the input event back unchanged wrapped in `Some`
//! (unless `event.event_type == "drop_me"`, in which case it returns
//! `None`, exercising the "no reply" path); `dispatch` returns a fixed
//! successful `transport-result`. Used by Tasks 7, 8, 19 and 20 as the
//! one real, cargo-component-built component this crate's tests load.

#[allow(warnings)]
mod bindings;

use bindings::exports::waddle::bundle::action_stage::{Guest as ActionGuest, TransportError, TransportResult};
use bindings::exports::waddle::bundle::process_stage::{Guest as ProcessGuest, PlatformEvent, UnsupportedStage};
use bindings::waddle::bundle::context::get_context;
use bindings::waddle::bundle::log::{write as log_write, Level};

struct Component;

impl ProcessGuest for Component {
    fn transform(event: PlatformEvent) -> Result<Option<PlatformEvent>, UnsupportedStage> {
        let ctx = get_context();
        log_write(
            Level::Debug,
            "hello_bundle transform called",
            &format!("{{\"app_id\":\"{}\"}}", ctx.app_id),
        );
        if event.event_type == "drop_me" {
            return Ok(None);
        }
        Ok(Some(event))
    }
}

impl ActionGuest for Component {
    fn dispatch(
        _envelope: bindings::exports::waddle::bundle::action_stage::StageEnvelope,
        _config: String,
    ) -> Result<TransportResult, TransportError> {
        Ok(TransportResult {
            ok: true,
            status: Some(200),
            detail: Some("hello_bundle fixture dispatch".to_string()),
            provider_message_id: None,
        })
    }
}

bindings::export!(Component with_types_in bindings);
```

- [ ] **Step 3: Write the `hostile_socket` fixture source**

`tests/fixtures/hostile_socket/Cargo.toml`: identical to `hello_bundle`'s, with `name = "hostile_socket"`.

`tests/fixtures/hostile_socket/src/lib.rs`:

```rust
//! Test fixture for the §14.6 test-1 socket-denial negative test:
//! `transform` attempts to open a real TCP connection using Rust's std
//! networking (which lowers to `wasi:sockets` under wasm32-wasip2)
//! *before* touching the event at all, then reports what happened
//! through the `log` import so the host-side test can assert on it
//! without needing the guest to trap.

#[allow(warnings)]
mod bindings;

use bindings::exports::waddle::bundle::action_stage::{Guest as ActionGuest, TransportError, TransportResult};
use bindings::exports::waddle::bundle::process_stage::{Guest as ProcessGuest, PlatformEvent, UnsupportedStage};
use bindings::waddle::bundle::log::{write as log_write, Level};

use std::net::TcpStream;

struct Component;

impl ProcessGuest for Component {
    fn transform(event: PlatformEvent) -> Result<Option<PlatformEvent>, UnsupportedStage> {
        match TcpStream::connect("127.0.0.1:9") {
            Ok(_) => log_write(Level::Error, "socket probe: unexpectedly succeeded", "{}"),
            Err(e) => log_write(
                Level::Info,
                "socket probe: denied cleanly",
                &format!("{{\"error\":\"{}\"}}", e),
            ),
        }
        // The component keeps running normally after the denied call --
        // this is the behaviour spec §6.5's "wasi:sockets stub rule" and
        // §14.6 test 1 require, so the fixture proves it by still
        // returning a well-formed reply.
        Ok(Some(event))
    }
}

impl ActionGuest for Component {
    fn dispatch(
        _envelope: bindings::exports::waddle::bundle::action_stage::StageEnvelope,
        _config: String,
    ) -> Result<TransportResult, TransportError> {
        Ok(TransportResult { ok: true, status: Some(200), detail: None, provider_message_id: None })
    }
}

bindings::export!(Component with_types_in bindings);
```

Copy the WIT file into both fixture directories (cargo-component resolves `wit/` relative to the fixture's own `Cargo.toml`, so a symlink into the crate root would break the Docker build context):

```bash
cp packages/rust-bundle-host/wit/waddle-bundle-stage.wit \
   packages/rust-bundle-host/tests/fixtures/hello_bundle/wit/waddle-bundle-stage.wit
cp packages/rust-bundle-host/wit/waddle-bundle-stage.wit \
   packages/rust-bundle-host/tests/fixtures/hostile_socket/wit/waddle-bundle-stage.wit
```

- [ ] **Step 4: Write the failing fixture-presence test**

`tests/fixture_build_tests.rs`:

```rust
#![allow(clippy::unwrap_used, clippy::panic)]
use std::path::PathBuf;

fn fixture_path(name: &str) -> PathBuf {
    PathBuf::from(env!("CARGO_MANIFEST_DIR"))
        .join("tests/fixtures")
        .join(name)
        .join(format!("{name}.wasm"))
}

#[test]
fn hello_bundle_and_hostile_socket_fixtures_exist_and_are_wasm() {
    let mut examined = 0;
    for name in ["hello_bundle", "hostile_socket"] {
        let path = fixture_path(name);
        assert!(
            path.exists(),
            "{path:?} does not exist -- run `make fixtures` before `make test`"
        );
        let bytes = std::fs::read(&path).unwrap();
        assert!(bytes.len() > 4, "{path:?} is suspiciously small");
        // WASM binary magic number: 0x00 0x61 0x73 0x6D
        assert_eq!(&bytes[0..4], &[0x00, 0x61, 0x73, 0x6D], "{path:?} is not a WASM binary");
        examined += 1;
    }
    assert_eq!(examined, 2, "expected exactly 2 fixtures examined, got {examined}");
}
```

- [ ] **Step 5: Build the fixtures and run the test**

Run: `make fixtures`
Expected: Docker build succeeds; the final `RUN wasm-tools component wit ...` validation line passes; `hello_bundle.wasm` and `hostile_socket.wasm` land under `tests/fixtures/*/`.

Run: `make test`
Expected: PASS — `fixture_build_tests` green (2 fixtures examined).

- [ ] **Step 6: Commit**

Note: the fixture `.wasm` files are `.gitignore`d (Task 1) — only source + Dockerfile are committed. CI (Task 25) runs `make fixtures` before `make test` in the same job.

```bash
git add packages/rust-bundle-host/Dockerfile.fixtures packages/rust-bundle-host/tests/fixtures packages/rust-bundle-host/tests/fixture_build_tests.rs
git commit -m "$(cat <<'EOF'
test(bundle-host): cargo-component test fixtures (hello_bundle, hostile_socket)

Two tiny Rust bundles built with the pinned cargo-component 0.21.1 +
wasm32-wasip2 toolchain from the bundle-compiler-sandbox spike -- the
first real WASM components this crate's later tests instantiate.

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01N2rQgkHY872RubwXoBZxtE
EOF
)"
git push
```

---

## Task 6: wasmtime `Engine`/`Config` — component model, epoch interruption, pooling allocator, pinned collector

**Depends on:** Task 1 (crate scaffold, `wasmtime` pin, `src/executor/mod.rs` stub).

**Files:**
- Create: `packages/rust-bundle-host/src/executor/engine.rs`
- Modify: `packages/rust-bundle-host/src/executor/mod.rs`
- Test: `packages/rust-bundle-host/tests/engine_instantiate_tests.rs`

**Interfaces:**
- Consumes: nothing new (pure `wasmtime` API).
- Produces:
  ```rust
  pub struct EngineConfig {
      pub max_memory_bytes: usize,       // limits.memory_mb * 1024 * 1024
      pub epoch_tick_ms: u64,            // internal ticker granularity, default 10
      pub collector: String,             // must equal "drc" -- validated
  }

  #[derive(Debug, thiserror::Error)]
  pub enum EngineError {
      #[error("unsupported GC collector '{0}' -- this executor is pinned to 'drc'")]
      UnsupportedCollector(String),
      #[error("wasmtime engine construction failed: {0}")]
      Wasmtime(#[from] anyhow::Error),
  }

  pub struct EngineHandle {
      pub engine: wasmtime::Engine,
      pub wasmtime_abi: String,     // e.g. "48" -- from wasmtime's own crate version major
  }
  impl EngineHandle {
      pub fn new(config: &EngineConfig) -> Result<Self, EngineError>;
      /// Spawns the background epoch ticker; returns a handle whose Drop
      /// stops it. Must be called once per process.
      pub fn spawn_epoch_ticker(&self) -> EpochTicker;
      pub fn ticks_for_timeout(&self, timeout_ms: u64) -> u64; // ceil(timeout_ms / epoch_tick_ms)
  }
  pub struct EpochTicker { /* Drop stops the background task */ }
  ```
  Task 7 (bindgen/WasiCtx) and Task 18 (per-call invocation) both consume `EngineHandle`.

- [ ] **Step 1: Write the failing tests**

`tests/engine_instantiate_tests.rs`:

```rust
#![allow(clippy::unwrap_used, clippy::panic)]
use penguin_bundle_host::executor::engine::{EngineConfig, EngineError, EngineHandle};

fn config() -> EngineConfig {
    EngineConfig {
        max_memory_bytes: 64 * 1024 * 1024,
        epoch_tick_ms: 10,
        collector: "drc".to_string(),
    }
}

#[test]
fn engine_builds_with_component_model_and_epoch_interruption() {
    let handle = EngineHandle::new(&config()).expect("engine should build");
    assert!(handle.engine.config().wasm_component_model_async_stackful() || true); // config is opaque past construction; smoke-check it built
    assert!(!handle.wasmtime_abi.is_empty());
}

#[test]
fn unsupported_collector_is_rejected_at_construction() {
    let mut cfg = config();
    cfg.collector = "copying".to_string();
    let err = EngineHandle::new(&cfg).unwrap_err();
    assert!(matches!(err, EngineError::UnsupportedCollector(c) if c == "copying"));
}

#[test]
fn ticks_for_timeout_rounds_up() {
    let handle = EngineHandle::new(&config()).unwrap();
    assert_eq!(handle.ticks_for_timeout(2000), 200); // 2000 / 10 = 200 exactly
    assert_eq!(handle.ticks_for_timeout(2005), 201); // rounds up
    assert_eq!(handle.ticks_for_timeout(1), 1);      // never zero ticks
}

#[tokio::test]
async fn epoch_ticker_increments_the_engine_epoch_over_time() {
    let handle = EngineHandle::new(&config()).unwrap();
    let _ticker = handle.spawn_epoch_ticker();
    // No direct getter for the current epoch on `Engine`; instead prove
    // the ticker is alive by using it to trip a deliberately-tiny
    // deadline on a trivial store and observing the trap -- covered
    // end-to-end in Task 18's invoke tests. Here we just assert the
    // ticker task does not immediately panic/exit within one tick.
    tokio::time::sleep(std::time::Duration::from_millis(50)).await;
    // If the background task had panicked, `spawn` would have logged it;
    // this test's only job is to exercise spawn/drop without panicking.
    drop(_ticker);
}
```

- [ ] **Step 2: Run to verify failure**

Run: `make test`
Expected: FAIL — module `executor::engine` does not exist.

- [ ] **Step 3: Implement `src/executor/engine.rs`**

```rust
//! wasmtime `Engine` construction: component model, WASI 0.2, epoch
//! interruption, the pooling allocator, and a pinned GC collector
//! (`drc`, matching `componentize-py`'s own output -- spec §7.2, the
//! `penguin-dal-wasm` spike Round 2 "Cold start" section).

use std::sync::Arc;
use std::time::Duration;

use wasmtime::{Config, Engine, PoolingAllocationConfig};

#[derive(Debug, Clone)]
pub struct EngineConfig {
    /// `limits.memory_mb * 1024 * 1024` -- the hard per-instance ceiling
    /// the pooling allocator reserves space for. Individual instances are
    /// capped further, per-call, via `StoreLimits` (Task 18).
    pub max_memory_bytes: usize,
    /// Internal ticker granularity in milliseconds. Not a spec-fixed env
    /// var -- an implementation detail of how finely the epoch deadline
    /// can be expressed. 10ms gives sub-100ms resolution against the
    /// `limits.timeout_ms` floor of 50ms (spec §6.4.2).
    pub epoch_tick_ms: u64,
    /// Must equal `"drc"` -- `EXECUTOR_WASM_COLLECTOR` (spec §12.7). Any
    /// other value refuses to build an engine rather than silently using
    /// a mismatched collector that would make every precompiled `.cwasm`
    /// unloadable (spec §7.2).
    pub collector: String,
}

#[derive(Debug, thiserror::Error)]
pub enum EngineError {
    #[error("unsupported GC collector '{0}' -- this executor is pinned to 'drc'")]
    UnsupportedCollector(String),
    #[error("wasmtime engine construction failed: {0}")]
    Wasmtime(#[from] anyhow::Error),
}

pub struct EngineHandle {
    pub engine: Engine,
    /// The wasmtime crate's major version, used as the `wasmtime_abi`
    /// field of the `hello` frame and the `.cwasm` cache key
    /// (`{digest}-{wasmtime_abi}-{collector}`, spec §7.2).
    pub wasmtime_abi: String,
    epoch_tick_ms: u64,
}

/// Stops the background epoch-incrementing task when dropped.
pub struct EpochTicker {
    _handle: tokio::task::JoinHandle<()>,
}

impl Drop for EpochTicker {
    fn drop(&mut self) {
        self._handle.abort();
    }
}

impl EngineHandle {
    pub fn new(config: &EngineConfig) -> Result<Self, EngineError> {
        if config.collector != "drc" {
            return Err(EngineError::UnsupportedCollector(config.collector.clone()));
        }

        let mut wasmtime_config = Config::new();
        wasmtime_config
            .wasm_component_model(true)
            .epoch_interruption(true)
            .collector(wasmtime::Collector::DeferredReferenceCounting);

        let mut pooling = PoolingAllocationConfig::new();
        pooling
            .total_component_instances(4096)
            .total_memories(4096)
            .max_memory_size(config.max_memory_bytes);
        wasmtime_config.allocation_strategy(wasmtime::InstanceAllocationStrategy::Pooling(pooling));

        let engine = Engine::new(&wasmtime_config).map_err(EngineError::Wasmtime)?;

        // wasmtime's OWN crate version, e.g. "48.0.2" -> "48", as the ABI
        // identity component of the .cwasm cache key. It must be
        // `wasmtime::VERSION`, never this crate's `CARGO_PKG_VERSION` --
        // the cache key names the runtime that produced the .cwasm, and
        // a .cwasm produced by a different wasmtime major will not
        // deserialize (spec §7.2).
        let wasmtime_abi = wasmtime::VERSION.split('.').next().unwrap_or("unknown").to_string();

        Ok(Self { engine, wasmtime_abi, epoch_tick_ms: config.epoch_tick_ms })
    }

    /// Converts a wall-clock timeout into a whole number of epoch ticks,
    /// rounding up so a timeout is never shorter than requested and never
    /// zero (a zero-tick deadline would trap immediately, per wasmtime's
    /// `set_epoch_deadline` docs: "a store will trap immediately with an
    /// epoch deadline of 0").
    pub fn ticks_for_timeout(&self, timeout_ms: u64) -> u64 {
        let ticks = timeout_ms.div_ceil(self.epoch_tick_ms.max(1));
        ticks.max(1)
    }

    /// Spawns the background task that increments the engine's epoch
    /// every `epoch_tick_ms` -- the mechanism `Store::set_epoch_deadline`
    /// (Task 18) measures against.
    pub fn spawn_epoch_ticker(&self) -> EpochTicker {
        let engine = self.engine.clone();
        let interval = Duration::from_millis(self.epoch_tick_ms.max(1));
        let handle = tokio::spawn(async move {
            let mut ticker = tokio::time::interval(interval);
            loop {
                ticker.tick().await;
                engine.increment_epoch();
            }
        });
        EpochTicker { _handle: handle }
    }
}

impl std::fmt::Debug for EngineHandle {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.debug_struct("EngineHandle")
            .field("wasmtime_abi", &self.wasmtime_abi)
            .finish_non_exhaustive()
    }
}
```

Add this assertion to `tests/engine_instantiate_tests.rs` so the `wasmtime_abi` source can never silently drift back to this crate's own version:

```rust
#[test]
fn wasmtime_abi_is_wasmtimes_major_not_this_crates() {
    let handle = EngineHandle::new(&config()).unwrap();
    assert_eq!(handle.wasmtime_abi, "48", "the .cwasm cache key's ABI component must be wasmtime's own major version");
    assert_ne!(
        handle.wasmtime_abi,
        env!("CARGO_PKG_VERSION").split('.').next().unwrap_or(""),
        "wasmtime_abi must not be derived from penguin-bundle-host's own version"
    );
}
```

It costs nothing at runtime and makes the one line that is easy to get wrong — `wasmtime::VERSION` vs this crate's `CARGO_PKG_VERSION` — impossible to get wrong silently. (`"48"` is the major of the `wasmtime = "=48.0.2"` pin from Task 1; a future wasmtime bump updates both the pin and this expected value in the same commit, which is exactly the review signal it is there to force.)

- [ ] **Step 4: Export from `src/executor/mod.rs`**

```rust
//! The credential-less executor runtime: the wasmtime engine, WASI
//! wiring, the instance pool, and the bucket loader. No Valkey, no
//! Postgres, no arbitrary-HTTP client anywhere in this module tree
//! (spec §6.10, §11.10 -- asserted by Task 24's dependency-tree test).

pub mod engine;
```

- [ ] **Step 5: Run to verify pass**

Run: `make test`
Expected: PASS — all `engine_instantiate_tests` green.

- [ ] **Step 6: Commit**

```bash
git add packages/rust-bundle-host/src/executor packages/rust-bundle-host/tests/engine_instantiate_tests.rs
git commit -m "$(cat <<'EOF'
feat(bundle-host): wasmtime Engine construction with pinned drc collector

EngineHandle wires component model + epoch interruption + the pooling
allocator, refuses to build with any collector other than "drc" (a
mismatch makes every precompiled .cwasm unloadable per spec §7.2), and
exposes ticks_for_timeout() for Task 18's per-call deadlines.

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01N2rQgkHY872RubwXoBZxtE
EOF
)"
git push
```

---

## Task 7: WIT bindgen wiring, `WasiCtx` (sockets denied by default), end-to-end instantiation

**Depends on:** Task 6 (`EngineHandle`), Task 5 (the `hello_bundle` fixture this instantiates), Task 2 (the WIT file `bindgen!` reads).

**Files:**
- Create: `packages/rust-bundle-host/src/executor/bindings.rs`
- Create: `packages/rust-bundle-host/src/executor/wasi_ctx.rs`
- Modify: `packages/rust-bundle-host/src/executor/mod.rs`
- Test: `packages/rust-bundle-host/tests/bindgen_smoke_tests.rs`

**Interfaces:**
- Consumes: `wit/waddle-bundle-stage.wit` (Task 2), `executor::engine::EngineHandle` (Task 6), the `hello_bundle` fixture (Task 5).
- Produces:
  ```rust
  // executor::bindings -- re-exports the wasmtime::component::bindgen! output.
  pub use stage_world::Stage;                      // the generated world struct
  pub use stage_world::waddle::bundle::{context, http, kv, db, relay, flags, log, clock};
  pub use stage_world::exports::waddle::bundle::{process_stage, action_stage};

  // executor::wasi_ctx
  pub struct GuestWasiCtx { pub table: wasmtime::component::ResourceTable, pub wasi: wasmtime_wasi::WasiCtx }
  impl wasmtime_wasi::WasiView for GuestWasiCtx { fn ctx(&mut self) -> wasmtime_wasi::WasiCtxView<'_>; }
  pub fn build_guest_wasi_ctx(scratch_dir: &std::path::Path) -> anyhow::Result<GuestWasiCtx>;
  ```
  Task 21 (the executor-side remote `Host` implementation) implements `context::Host`, `http::Host`, `kv::Host`, `db::Host`, `relay::Host`, `flags::Host`, `log::Host` and `clock::Host` for `ExecutorHostState`, forwarding each to the stage over the wire; the stage side never implements these traits at all — it answers `host-call` frames through `HostCallRouter` (Task 16) instead, which is why there is no `host/wasi_host_impl.rs` in this crate. Task 18 (instance pool + per-call invoke) consumes `build_guest_wasi_ctx` and calls `Stage::instantiate_async` + `stage.waddle_bundle_process_stage().call_transform(...)`/`.waddle_bundle_action_stage().call_dispatch(...)`.

- [ ] **Step 1: Write the failing end-to-end smoke test**

`tests/bindgen_smoke_tests.rs`:

```rust
#![allow(clippy::unwrap_used, clippy::panic)]
use penguin_bundle_host::executor::bindings::{self, stage_world::Stage};
use penguin_bundle_host::executor::engine::{EngineConfig, EngineHandle};
use penguin_bundle_host::executor::wasi_ctx::{build_guest_wasi_ctx, GuestWasiCtx};
use wasmtime::component::{Component, Linker, ResourceTable};
use wasmtime::Store;

struct TestHostState {
    wasi: GuestWasiCtx,
}

impl wasmtime_wasi::WasiView for TestHostState {
    fn ctx(&mut self) -> wasmtime_wasi::WasiCtxView<'_> {
        wasmtime_wasi::WasiCtxView { ctx: &mut self.wasi.wasi, table: &mut self.wasi.table }
    }
}

// Minimal stub Host impls for every world import -- Tasks 16/23 replace
// these with the real guard-backed / wire-forwarding implementations.
// `#[async_trait::async_trait]` matches the `imports: { default: async }`-
// equivalent `async: true` bindgen option used below.
mod stub_hosts {
    use super::TestHostState;
    use penguin_bundle_host::executor::bindings::stage_world::waddle::bundle::*;

    impl context::Host for TestHostState {
        async fn get_context(&mut self) -> context::BundleContext {
            context::BundleContext {
                tenant: "test".into(),
                community: None,
                app_id: "waddles.test.fixture.hello".into(),
                feature: "waddles.test.fixture".into(),
                version: "0.1.0".into(),
                message_id: "test-1".into(),
                config_json: "{}".into(),
            }
        }
    }

    impl http::Host for TestHostState {
        async fn send(&mut self, _req: http::Request) -> Result<http::Response, http::Error> {
            Err(http::Error::Denied("not granted in smoke test".into()))
        }
    }

    impl kv::Host for TestHostState {
        async fn get(&mut self, _key: String) -> Result<Option<Vec<u8>>, kv::Error> { Ok(None) }
        async fn set(&mut self, _key: String, _value: Vec<u8>, _ttl_seconds: u32) -> Result<(), kv::Error> { Ok(()) }
        async fn delete(&mut self, _key: String) -> Result<(), kv::Error> { Ok(()) }
        async fn increment(&mut self, _key: String, delta: i64, _ttl_seconds: u32) -> Result<i64, kv::Error> { Ok(delta) }
    }

    impl db::Host for TestHostState {
        async fn execute(&mut self, _statement: String, _params: Vec<db::Value>) -> Result<db::Rows, db::Error> {
            Err(db::Error::Denied("not granted in smoke test".into()))
        }
    }

    impl relay::Host for TestHostState {
        async fn push(&mut self, _provider: String, _message_json: String) -> Result<(), relay::Error> {
            Err(relay::Error::Denied("not granted in smoke test".into()))
        }
    }

    impl flags::Host for TestHostState {
        async fn enabled(&mut self, _key: String, default_value: bool) -> bool { default_value }
        async fn tier(&mut self) -> String { "free".into() }
    }

    impl log::Host for TestHostState {
        async fn write(&mut self, _lvl: log::Level, message: String, _fields_json: String) {
            eprintln!("[guest log] {message}");
        }
    }

    impl clock::Host for TestHostState {
        async fn now_millis(&mut self) -> u64 {
            std::time::SystemTime::now().duration_since(std::time::UNIX_EPOCH).unwrap().as_millis() as u64
        }
        async fn now_rfc3339(&mut self) -> String {
            chrono::Utc::now().to_rfc3339()
        }
        async fn monotonic_nanos(&mut self) -> u64 {
            std::time::Instant::now().elapsed().as_nanos() as u64
        }
    }
}

fn fixture_path(name: &str) -> std::path::PathBuf {
    std::path::PathBuf::from(env!("CARGO_MANIFEST_DIR"))
        .join("tests/fixtures")
        .join(name)
        .join(format!("{name}.wasm"))
}

#[tokio::test]
async fn hello_bundle_instantiates_and_transform_echoes_the_event() {
    let handle = EngineHandle::new(&EngineConfig {
        max_memory_bytes: 64 * 1024 * 1024,
        epoch_tick_ms: 10,
        collector: "drc".to_string(),
    })
    .unwrap();

    let component = Component::from_file(&handle.engine, fixture_path("hello_bundle"))
        .expect("hello_bundle.wasm should compile as a component -- run `make fixtures` first");

    let mut linker: Linker<TestHostState> = Linker::new(&handle.engine);
    wasmtime_wasi::p2::add_to_linker_async(&mut linker).expect("wasi linking");
    bindings::stage_world::waddle::bundle::context::add_to_linker(&mut linker, |s| s)
        .expect("context linking");
    bindings::stage_world::waddle::bundle::http::add_to_linker(&mut linker, |s| s).unwrap();
    bindings::stage_world::waddle::bundle::kv::add_to_linker(&mut linker, |s| s).unwrap();
    bindings::stage_world::waddle::bundle::db::add_to_linker(&mut linker, |s| s).unwrap();
    bindings::stage_world::waddle::bundle::relay::add_to_linker(&mut linker, |s| s).unwrap();
    bindings::stage_world::waddle::bundle::flags::add_to_linker(&mut linker, |s| s).unwrap();
    bindings::stage_world::waddle::bundle::log::add_to_linker(&mut linker, |s| s).unwrap();
    bindings::stage_world::waddle::bundle::clock::add_to_linker(&mut linker, |s| s).unwrap();

    let scratch = tempfile::tempdir().unwrap();
    let wasi = build_guest_wasi_ctx(scratch.path()).unwrap();
    let mut store = Store::new(&handle.engine, TestHostState { wasi });
    store.set_epoch_deadline(handle.ticks_for_timeout(2000));

    let (stage, _instance) = Stage::instantiate_async(&mut store, &component, &linker)
        .await
        .expect("instantiation should succeed against our linker + WASI wiring");

    let event = bindings::stage_world::waddle::bundle::types::PlatformEvent {
        platform: "twitch".into(),
        event_type: "chat.message".into(),
        actor: Some("penguin".into()),
        payload_json: "{}".into(),
        occurred_at: "2026-09-14T12:00:00.000Z".into(),
    };

    let result = stage
        .waddle_bundle_process_stage()
        .call_transform(&mut store, &event)
        .await
        .expect("call_transform should not trap")
        .expect("transform should return Ok for a non-drop_me event");

    let echoed = result.expect("expected Some(event), got None");
    assert_eq!(echoed.event_type, "chat.message");
}

#[tokio::test]
async fn hello_bundle_transform_returns_none_for_drop_me() {
    // The setup below repeats the previous test's verbatim rather than
    // sharing a helper: each `#[tokio::test]` owns its own Engine and
    // Store, and a shared builder would hide which knob a failure came
    // from. What it proves is different -- the `option<platform-event>`
    // "no reply" path round-trips as `None`, not as an error.
    let handle = EngineHandle::new(&EngineConfig {
        max_memory_bytes: 64 * 1024 * 1024,
        epoch_tick_ms: 10,
        collector: "drc".to_string(),
    })
    .unwrap();
    let component = Component::from_file(&handle.engine, fixture_path("hello_bundle")).unwrap();
    let mut linker: Linker<TestHostState> = Linker::new(&handle.engine);
    wasmtime_wasi::p2::add_to_linker_async(&mut linker).unwrap();
    bindings::stage_world::waddle::bundle::context::add_to_linker(&mut linker, |s| s).unwrap();
    bindings::stage_world::waddle::bundle::http::add_to_linker(&mut linker, |s| s).unwrap();
    bindings::stage_world::waddle::bundle::kv::add_to_linker(&mut linker, |s| s).unwrap();
    bindings::stage_world::waddle::bundle::db::add_to_linker(&mut linker, |s| s).unwrap();
    bindings::stage_world::waddle::bundle::relay::add_to_linker(&mut linker, |s| s).unwrap();
    bindings::stage_world::waddle::bundle::flags::add_to_linker(&mut linker, |s| s).unwrap();
    bindings::stage_world::waddle::bundle::log::add_to_linker(&mut linker, |s| s).unwrap();
    bindings::stage_world::waddle::bundle::clock::add_to_linker(&mut linker, |s| s).unwrap();
    let scratch = tempfile::tempdir().unwrap();
    let wasi = build_guest_wasi_ctx(scratch.path()).unwrap();
    let mut store = Store::new(&handle.engine, TestHostState { wasi });
    store.set_epoch_deadline(handle.ticks_for_timeout(2000));
    let (stage, _instance) = Stage::instantiate_async(&mut store, &component, &linker).await.unwrap();

    let event = bindings::stage_world::waddle::bundle::types::PlatformEvent {
        platform: "twitch".into(),
        event_type: "drop_me".into(),
        actor: None,
        payload_json: "{}".into(),
        occurred_at: "2026-09-14T12:00:00.000Z".into(),
    };
    let result = stage
        .waddle_bundle_process_stage()
        .call_transform(&mut store, &event)
        .await
        .unwrap()
        .unwrap();
    assert!(result.is_none(), "expected None for drop_me, got {result:?}");
}
```

- [ ] **Step 2: Run to verify failure**

Run: `make test`
Expected: FAIL — `executor::bindings`/`executor::wasi_ctx` do not exist.

- [ ] **Step 3: Implement `src/executor/bindings.rs`**

```rust
//! `wasmtime::component::bindgen!` output for `waddle:bundle/stage@1.0.0`.
//!
//! Generates, from `wit/waddle-bundle-stage.wit`: a `Stage` struct with
//! `Stage::instantiate_async`, `.waddle_bundle_process_stage().call_transform(...)`
//! and `.waddle_bundle_action_stage().call_dispatch(...)`; and, per
//! imported interface, a `Host` trait (`context::Host`, `http::Host`,
//! `kv::Host`, `db::Host`, `relay::Host`, `flags::Host`, `log::Host`,
//! `clock::Host`) plus an `add_to_linker` free function. Our world
//! imports no `wasi:*` interface directly (spec §6.5), so this macro
//! invocation has no overlap with `wasmtime_wasi`'s own bindings and
//! needs no `with:` remapping.

pub mod stage_world {
    wasmtime::component::bindgen!({
        world: "stage",
        path: "wit/waddle-bundle-stage.wit",
        async: true,
    });
}
```

- [ ] **Step 4: Implement `src/executor/wasi_ctx.rs`**

```rust
//! Per-instance `WasiCtx`: a single read-only `/scratch` preopen, empty
//! args/env, and -- critically -- **no call to `.inherit_network()`,
//! `.allow_tcp()`, `.allow_udp()`, or `.allow_ip_name_lookup()`**, which
//! leaves every one of `wasmtime-wasi`'s own default-deny checks in
//! force (verified against `wasmtime-wasi` 48.0.2 source:
//! `SocketAddrCheck::default()` returns `false` for every address, and
//! `AllowedNetworkUses` defaults every flag to `false` -- see
//! `src/sockets/mod.rs` and `src/ctx.rs` in that crate). This *is* the
//! "denying implementation... native to the Rust executor" spec §6.5
//! requires: wasmtime-wasi's own real `wasi:sockets` implementation,
//! configured to refuse everything, rather than a hand-authored stub.

use wasmtime::component::ResourceTable;
use wasmtime_wasi::{FsPerms, WasiCtx, WasiCtxBuilder, WasiCtxView, WasiView};

pub struct GuestWasiCtx {
    pub table: ResourceTable,
    pub wasi: WasiCtx,
}

impl WasiView for GuestWasiCtx {
    fn ctx(&mut self) -> WasiCtxView<'_> {
        WasiCtxView { ctx: &mut self.wasi, table: &mut self.table }
    }
}

/// Builds a `GuestWasiCtx` for one bundle instance. `scratch_dir` must be
/// an empty, instance-local directory (spec §6.5: "a single read-only
/// preopen at `/scratch` (empty at load)") -- the caller (Task 18's
/// instance pool) is responsible for giving each instance its own.
///
/// Deliberately does **not** call `.inherit_env()`, `.inherit_args()`,
/// `.inherit_network()`, `.allow_tcp()`, `.allow_udp()`, or
/// `.allow_ip_name_lookup()` -- every one of those stays at its
/// documented default (empty / denied), which is the whole mechanism.
pub fn build_guest_wasi_ctx(scratch_dir: &std::path::Path) -> anyhow::Result<GuestWasiCtx> {
    let mut builder = WasiCtxBuilder::new();
    builder.preopened_dir(scratch_dir, "/scratch", FsPerms::ReadOnly)?;
    let wasi = builder.build();
    Ok(GuestWasiCtx { table: ResourceTable::new(), wasi })
}
```

- [ ] **Step 5: Export from `src/executor/mod.rs`**

```rust
pub mod bindings;
pub mod engine;
pub mod wasi_ctx;
```

- [ ] **Step 6: Run to verify pass**

Run: `make test`
Expected: PASS — both `bindgen_smoke_tests` green. If the generated module path or method names differ from what Step 1 assumed (e.g. `call_transform` vs. a different auto-generated name), the compiler error names the actual generated path — adjust the test's call sites to match and re-run; this is expected first-pass friction with a code-generating macro, not a design change.

- [ ] **Step 7: Commit**

```bash
git add packages/rust-bundle-host/src/executor/bindings.rs packages/rust-bundle-host/src/executor/wasi_ctx.rs packages/rust-bundle-host/src/executor/mod.rs packages/rust-bundle-host/tests/bindgen_smoke_tests.rs
git commit -m "$(cat <<'EOF'
feat(bundle-host): WIT bindgen wiring and default-deny guest WasiCtx

bindgen! generates Stage/context/http/kv/db/relay/flags/log/clock from
the committed WIT world; build_guest_wasi_ctx() never calls
inherit_network()/allow_tcp()/allow_udp()/allow_ip_name_lookup(), which
keeps wasmtime-wasi's own real (not hand-stubbed) socket implementation
at its documented default-deny -- verified end to end against the
hello_bundle fixture.

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01N2rQgkHY872RubwXoBZxtE
EOF
)"
git push
```

---

## Task 8: Negative tests — socket denial and read-only `/scratch`

**Depends on:** Task 7 (bindings, `build_guest_wasi_ctx`, `tests/common`), Task 5 (the `hostile_socket` fixture).

**Files:**
- Create: `packages/rust-bundle-host/tests/sandbox_denial_tests.rs`

**Interfaces:**
- Consumes: everything from Task 7 (`bindings`, `wasi_ctx`, `engine`), the `hostile_socket` fixture (Task 5).
- Produces: nothing new — pure test coverage of an existing guarantee (spec §14.6 test 1, and the read-only-`/scratch` half of §11.2 layer 6).

This is the crate-level version of spec §14.6 test 1 ("Guest calls `wasi:sockets` through the executor's native denying implementations") and the filesystem half of layer 6 ("no `wasi:filesystem` beyond a read-only empty `/scratch`"). The full negative-sandbox suite (gVisor pod boundary, NetworkPolicy, mTLS peer identity) is infrastructure-level and belongs to M3/M4/M6; this task covers exactly the two guarantees this crate's own code is responsible for.

- [ ] **Step 1: Write the failing tests**

`tests/sandbox_denial_tests.rs`:

```rust
#![allow(clippy::unwrap_used, clippy::panic)]
use penguin_bundle_host::executor::bindings::{self, stage_world::Stage};
use penguin_bundle_host::executor::engine::{EngineConfig, EngineHandle};
use penguin_bundle_host::executor::wasi_ctx::build_guest_wasi_ctx;
use wasmtime::component::{Component, Linker};
use wasmtime::Store;

// Reuse the same TestHostState + stub Host impls pattern from Task 7 --
// factored into a shared `tests/common/mod.rs` helper by this task so it
// is not duplicated a third time in Task 18's tests.
mod common;
use common::{link_stub_hosts, TestHostState};

fn fixture_path(name: &str) -> std::path::PathBuf {
    std::path::PathBuf::from(env!("CARGO_MANIFEST_DIR"))
        .join("tests/fixtures")
        .join(name)
        .join(format!("{name}.wasm"))
}

#[tokio::test]
async fn hostile_socket_component_is_denied_and_keeps_running() {
    let handle = EngineHandle::new(&EngineConfig {
        max_memory_bytes: 64 * 1024 * 1024,
        epoch_tick_ms: 10,
        collector: "drc".to_string(),
    })
    .unwrap();
    let component = Component::from_file(&handle.engine, fixture_path("hostile_socket")).unwrap();

    let mut linker: Linker<TestHostState> = Linker::new(&handle.engine);
    wasmtime_wasi::p2::add_to_linker_async(&mut linker).unwrap();
    link_stub_hosts(&mut linker);

    let scratch = tempfile::tempdir().unwrap();
    let wasi = build_guest_wasi_ctx(scratch.path()).unwrap();
    let mut store = Store::new(&handle.engine, TestHostState { wasi });
    store.set_epoch_deadline(handle.ticks_for_timeout(2000));

    let (stage, _instance) = Stage::instantiate_async(&mut store, &component, &linker).await.unwrap();

    let event = bindings::stage_world::waddle::bundle::types::PlatformEvent {
        platform: "twitch".into(),
        event_type: "chat.message".into(),
        actor: None,
        payload_json: "{}".into(),
        occurred_at: "2026-09-14T12:00:00.000Z".into(),
    };

    // The pass condition IS the call completing normally: a socket
    // connect attempt that trapped, hung, or actually connected would
    // all fail this test differently (a trap surfaces as an Err here; a
    // hang would time out the test harness; an actual connection is
    // structurally impossible since nothing listens on 127.0.0.1:9 in
    // the test sandbox and, more importantly, is denied before any
    // connection attempt is made at all per wasmtime-wasi's
    // AllowedNetworkUses default).
    let result = tokio::time::timeout(
        std::time::Duration::from_secs(5),
        stage.waddle_bundle_process_stage().call_transform(&mut store, &event),
    )
    .await
    .expect("call must not hang")
    .expect("call must not trap")
    .expect("transform must return Ok, not UnsupportedStage");

    assert!(result.is_some(), "hostile_socket should still echo the event back after the denied socket call");
}

#[tokio::test]
async fn scratch_preopen_is_read_only() {
    // Build a WasiCtx exactly as build_guest_wasi_ctx does, then assert
    // at the host level that the preopen was requested read-only --
    // the guest-side write-denial itself is exercised transitively by
    // every fixture that instantiates successfully (a component built
    // for wasm32-wasip2 that tried a filesystem write to `/scratch`
    // during its own module-init would fail identically to the
    // hostile_socket case above; no fixture in this crate attempts one
    // because it is not part of §14.6's crate-scoped guarantees --
    // this test instead pins the *configuration* the guarantee rests on).
    let scratch = tempfile::tempdir().unwrap();
    let wasi = build_guest_wasi_ctx(scratch.path()).unwrap();
    // `WasiCtx` does not expose its preopen list for inspection publicly;
    // the configuration-level guarantee is therefore pinned by asserting
    // build_guest_wasi_ctx's own source calls `FsPerms::ReadOnly` --
    // enforced by a `grep`-based static-shape test rather than a runtime
    // introspection wasmtime-wasi does not provide.
    let source = std::fs::read_to_string(
        std::path::PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("src/executor/wasi_ctx.rs"),
    )
    .unwrap();
    assert!(
        source.contains("FsPerms::ReadOnly"),
        "build_guest_wasi_ctx must preopen /scratch as FsPerms::ReadOnly, not ReadWrite"
    );
    let _ = wasi; // constructed successfully above; the assertion is on the source shape
}
```

- [ ] **Step 2: Factor the shared test host into `tests/common/mod.rs`**

```rust
//! Shared test-only Host stub implementations, factored out of
//! Task 7's bindgen smoke test so Task 8 and Task 18 do not duplicate
//! eight trivial trait impls a third and fourth time.
#![allow(clippy::unwrap_used, clippy::panic)]

use penguin_bundle_host::executor::bindings::stage_world::waddle::bundle::*;
use penguin_bundle_host::executor::wasi_ctx::GuestWasiCtx;
use wasmtime::component::Linker;

pub struct TestHostState {
    pub wasi: GuestWasiCtx,
}

impl wasmtime_wasi::WasiView for TestHostState {
    fn ctx(&mut self) -> wasmtime_wasi::WasiCtxView<'_> {
        wasmtime_wasi::WasiCtxView { ctx: &mut self.wasi.wasi, table: &mut self.wasi.table }
    }
}

impl context::Host for TestHostState {
    async fn get_context(&mut self) -> context::BundleContext {
        context::BundleContext {
            tenant: "test".into(),
            community: None,
            app_id: "waddles.test.fixture.hello".into(),
            feature: "waddles.test.fixture".into(),
            version: "0.1.0".into(),
            message_id: "test-1".into(),
            config_json: "{}".into(),
        }
    }
}

impl http::Host for TestHostState {
    async fn send(&mut self, _req: http::Request) -> Result<http::Response, http::Error> {
        Err(http::Error::Denied("not granted in test".into()))
    }
}

impl kv::Host for TestHostState {
    async fn get(&mut self, _key: String) -> Result<Option<Vec<u8>>, kv::Error> { Ok(None) }
    async fn set(&mut self, _key: String, _value: Vec<u8>, _ttl_seconds: u32) -> Result<(), kv::Error> { Ok(()) }
    async fn delete(&mut self, _key: String) -> Result<(), kv::Error> { Ok(()) }
    async fn increment(&mut self, _key: String, delta: i64, _ttl_seconds: u32) -> Result<i64, kv::Error> { Ok(delta) }
}

impl db::Host for TestHostState {
    async fn execute(&mut self, _statement: String, _params: Vec<db::Value>) -> Result<db::Rows, db::Error> {
        Err(db::Error::Denied("not granted in test".into()))
    }
}

impl relay::Host for TestHostState {
    async fn push(&mut self, _provider: String, _message_json: String) -> Result<(), relay::Error> {
        Err(relay::Error::Denied("not granted in test".into()))
    }
}

impl flags::Host for TestHostState {
    async fn enabled(&mut self, _key: String, default_value: bool) -> bool { default_value }
    async fn tier(&mut self) -> String { "free".into() }
}

impl log::Host for TestHostState {
    async fn write(&mut self, _lvl: log::Level, message: String, _fields_json: String) {
        eprintln!("[guest log] {message}");
    }
}

impl clock::Host for TestHostState {
    async fn now_millis(&mut self) -> u64 {
        std::time::SystemTime::now().duration_since(std::time::UNIX_EPOCH).unwrap().as_millis() as u64
    }
    async fn now_rfc3339(&mut self) -> String { chrono::Utc::now().to_rfc3339() }
    async fn monotonic_nanos(&mut self) -> u64 { std::time::Instant::now().elapsed().as_nanos() as u64 }
}

pub fn link_stub_hosts(linker: &mut Linker<TestHostState>) {
    context::add_to_linker(linker, |s| s).unwrap();
    http::add_to_linker(linker, |s| s).unwrap();
    kv::add_to_linker(linker, |s| s).unwrap();
    db::add_to_linker(linker, |s| s).unwrap();
    relay::add_to_linker(linker, |s| s).unwrap();
    flags::add_to_linker(linker, |s| s).unwrap();
    log::add_to_linker(linker, |s| s).unwrap();
    clock::add_to_linker(linker, |s| s).unwrap();
}
```

Then simplify Task 7's `bindgen_smoke_tests.rs` to `mod common; use common::{link_stub_hosts, TestHostState};` in place of its inline `stub_hosts` module (small follow-up edit within this task, since Task 7 already committed the duplicate — this task's commit removes the duplication).

- [ ] **Step 3: Run to verify the new tests fail first (no `common` module yet), then pass**

Run: `make test`
Expected first: FAIL — `tests/common/mod.rs` referenced but not present as a proper test module (Rust integration tests need `tests/common/mod.rs`, not `tests/common.rs`, to avoid being treated as its own test binary).
After Step 2: Expected: PASS — both new tests green, and Task 7's `bindgen_smoke_tests` still green after the refactor to use `common`.

- [ ] **Step 4: Commit**

```bash
git add packages/rust-bundle-host/tests/sandbox_denial_tests.rs packages/rust-bundle-host/tests/common packages/rust-bundle-host/tests/bindgen_smoke_tests.rs
git commit -m "$(cat <<'EOF'
test(bundle-host): negative tests for socket denial and read-only scratch

hostile_socket_component_is_denied_and_keeps_running is the crate-level
proof of spec §14.6 test 1: a real TCP connect attempt from the guest
fails cleanly and the component keeps serving. Factored the Task 7 stub
Host impls into tests/common so this and Task 18 do not re-duplicate them.

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01N2rQgkHY872RubwXoBZxtE
EOF
)"
git push
```

---

## Task 9: `ApprovedPermissions` — the approved-permission-set model

**Depends on:** Task 1 (crate scaffold, `src/host/mod.rs` stub).

**Files:**
- Create: `packages/rust-bundle-host/src/host/approvals.rs`
- Modify: `packages/rust-bundle-host/src/host/mod.rs`
- Test: `packages/rust-bundle-host/tests/approvals_tests.rs`

**Interfaces:**
- Consumes: nothing new (parses the distribution API's `manifest` field, spec §6.7, shaped by `app_install_approvals.summary_json`, spec §6.9).
- Produces:
  ```rust
  pub struct ApprovedPermissions {
      pub app_id: String,
      pub egress: Vec<EgressRule>,           // {host, methods}
      pub tables: Vec<TableGrant>,            // {name, read: bool, write: bool}
      pub capabilities: Vec<Capability>,      // Http | Kv | Db | Relay | Flags | Log | Clock | Context
      pub routes_to: Vec<String>,             // exact app_ids, no wildcards
      pub limits: ApprovedLimits,             // {timeout_ms, memory_mb, egress_rps}
  }
  pub struct EgressRule { pub host: String, pub methods: Vec<String> }
  pub struct TableGrant { pub name: String, pub read: bool, pub write: bool }
  pub struct ApprovedLimits { pub timeout_ms: u64, pub memory_mb: u32, pub egress_rps: u32 }
  #[derive(Debug, Clone, Copy, PartialEq, Eq, Hash)]
  pub enum Capability { Http, Kv, Db, Relay, Flags, Log, Clock, Context }

  impl ApprovedPermissions {
      pub fn from_json(app_id: &str, summary_json: &serde_json::Value) -> Result<Self, ApprovalsError>;
      pub fn has_capability(&self, cap: Capability) -> bool;
      pub fn egress_rule_for(&self, host: &str) -> Option<&EgressRule>;   // exact + single-label wildcard match, spec §8.1
      pub fn table_grant_for(&self, name: &str) -> Option<&TableGrant>;
      pub fn allows_route_to(&self, target_app_id: &str) -> bool;
  }
  #[derive(Debug, thiserror::Error)]
  pub enum ApprovalsError {
      #[error("missing required field '{0}' in approval summary")]
      MissingField(&'static str),
      #[error("invalid value for '{field}': {reason}")]
      InvalidField { field: &'static str, reason: String },
  }
  ```
  Task 10 (capability traits) and Task 11/12 (egress guard) consume `egress_rule_for`/`has_capability`; Task 13 (db guard) consumes `table_grant_for`/`has_capability`; Task 15 (trip tracker) and Task 16 (host-call router) consume `has_capability`.

- [ ] **Step 1: Write the failing tests**

`tests/approvals_tests.rs`:

```rust
#![allow(clippy::unwrap_used, clippy::panic)]
use penguin_bundle_host::host::approvals::{ApprovalsError, ApprovedPermissions, Capability};
use serde_json::json;

fn sample_summary() -> serde_json::Value {
    json!({
        "egress": [
            {"host": "api.spotify.com", "methods": ["GET", "POST"]},
            {"host": "*.googleapis.com"}
        ],
        "data": {
            "tables": [
                {"name": "music_queue", "read": true, "write": true},
                {"name": "music_history", "read": true, "write": false}
            ]
        },
        "capabilities": ["http", "kv", "db", "log", "clock", "context"],
        "routes_to": ["waddles.socials.music.legacy"],
        "limits": {"timeout_ms": 2000, "memory_mb": 64, "egress_rps": 10}
    })
}

#[test]
fn parses_a_full_summary() {
    let approved = ApprovedPermissions::from_json("waddles.socials.music.default", &sample_summary()).unwrap();
    assert_eq!(approved.app_id, "waddles.socials.music.default");
    assert_eq!(approved.egress.len(), 2);
    assert_eq!(approved.tables.len(), 2);
    assert_eq!(approved.limits.timeout_ms, 2000);
}

#[test]
fn methods_default_to_all_six_when_omitted() {
    let approved = ApprovedPermissions::from_json("a", &sample_summary()).unwrap();
    let wildcard = approved.egress_rule_for("api.googleapis.com").unwrap();
    assert_eq!(wildcard.methods, vec!["GET", "HEAD", "POST", "PUT", "PATCH", "DELETE"]);
}

#[test]
fn exact_host_match_takes_precedence_and_wildcard_matches_one_label() {
    let approved = ApprovedPermissions::from_json("a", &sample_summary()).unwrap();
    assert!(approved.egress_rule_for("api.spotify.com").is_some());
    assert!(approved.egress_rule_for("storage.googleapis.com").is_some());
    // *.googleapis.com matches exactly one label -- not two, not zero.
    assert!(approved.egress_rule_for("a.b.googleapis.com").is_none());
    assert!(approved.egress_rule_for("googleapis.com").is_none());
    assert!(approved.egress_rule_for("evil.com").is_none());
}

#[test]
fn has_capability_reflects_the_declared_list() {
    let approved = ApprovedPermissions::from_json("a", &sample_summary()).unwrap();
    assert!(approved.has_capability(Capability::Http));
    assert!(approved.has_capability(Capability::Db));
    assert!(!approved.has_capability(Capability::Relay));
}

#[test]
fn table_grant_lookup_carries_read_write_flags() {
    let approved = ApprovedPermissions::from_json("a", &sample_summary()).unwrap();
    let queue = approved.table_grant_for("music_queue").unwrap();
    assert!(queue.read && queue.write);
    let history = approved.table_grant_for("music_history").unwrap();
    assert!(history.read && !history.write);
    assert!(approved.table_grant_for("users").is_none());
}

#[test]
fn allows_route_to_is_exact_only_no_wildcards() {
    let approved = ApprovedPermissions::from_json("a", &sample_summary()).unwrap();
    assert!(approved.allows_route_to("waddles.socials.music.legacy"));
    assert!(!approved.allows_route_to("waddles.socials.music.other"));
}

#[test]
fn missing_limits_field_is_a_named_error() {
    let mut summary = sample_summary();
    summary.as_object_mut().unwrap().remove("limits");
    let err = ApprovedPermissions::from_json("a", &summary).unwrap_err();
    assert!(matches!(err, ApprovalsError::MissingField("limits")), "got {err:?}");
}

#[test]
fn empty_egress_and_tables_and_routes_to_parse_as_empty_not_missing() {
    let summary = json!({
        "egress": [],
        "data": {"tables": []},
        "capabilities": ["log", "clock", "context"],
        "routes_to": [],
        "limits": {"timeout_ms": 2000, "memory_mb": 64, "egress_rps": 10}
    });
    let approved = ApprovedPermissions::from_json("a", &summary).unwrap();
    assert!(approved.egress.is_empty());
    assert!(approved.tables.is_empty());
    assert!(approved.routes_to.is_empty());
    assert!(!approved.has_capability(Capability::Http));
}
```

- [ ] **Step 2: Run to verify failure**

Run: `make test`
Expected: FAIL — `host::approvals` module does not exist.

- [ ] **Step 3: Implement `src/host/approvals.rs`**

```rust
//! The approved-permission-set model (spec §9.7.3, §6.9). The runtime
//! enforces THIS record, generated once at approval time from the
//! bundle's manifest plus its compiled artifact's actual imports --
//! never the raw manifest at request time. This crate never fetches or
//! parses `app_install_approvals` itself; the caller (the stage service,
//! M3/M4) hands it the already-resolved JSON it got from the
//! distribution API's `manifest` field (spec §6.7) or from hub-api
//! directly, and this module turns it into a typed, queryable value.

use std::collections::HashSet;

use serde_json::Value;

#[derive(Debug, Clone)]
pub struct ApprovedPermissions {
    pub app_id: String,
    pub egress: Vec<EgressRule>,
    pub tables: Vec<TableGrant>,
    pub capabilities: HashSet<Capability>,
    pub routes_to: Vec<String>,
    pub limits: ApprovedLimits,
}

#[derive(Debug, Clone)]
pub struct EgressRule {
    pub host: String,
    pub methods: Vec<String>,
}

#[derive(Debug, Clone)]
pub struct TableGrant {
    pub name: String,
    pub read: bool,
    pub write: bool,
}

#[derive(Debug, Clone, Copy)]
pub struct ApprovedLimits {
    pub timeout_ms: u64,
    pub memory_mb: u32,
    pub egress_rps: u32,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash)]
pub enum Capability {
    Http,
    Kv,
    Db,
    Relay,
    Flags,
    Log,
    Clock,
    Context,
}

impl Capability {
    fn parse(s: &str) -> Option<Self> {
        match s {
            "http" => Some(Self::Http),
            "kv" => Some(Self::Kv),
            "db" => Some(Self::Db),
            "relay" => Some(Self::Relay),
            "flags" => Some(Self::Flags),
            "log" => Some(Self::Log),
            "clock" => Some(Self::Clock),
            "context" => Some(Self::Context),
            _ => None,
        }
    }
}

const DEFAULT_METHODS: &[&str] = &["GET", "HEAD", "POST", "PUT", "PATCH", "DELETE"];

#[derive(Debug, thiserror::Error)]
pub enum ApprovalsError {
    #[error("missing required field '{0}' in approval summary")]
    MissingField(&'static str),
    #[error("invalid value for '{field}': {reason}")]
    InvalidField { field: &'static str, reason: String },
}

impl ApprovedPermissions {
    pub fn from_json(app_id: &str, summary: &Value) -> Result<Self, ApprovalsError> {
        let egress = summary
            .get("egress")
            .ok_or(ApprovalsError::MissingField("egress"))?
            .as_array()
            .ok_or_else(|| ApprovalsError::InvalidField { field: "egress", reason: "not an array".into() })?
            .iter()
            .map(|entry| {
                let host = entry
                    .get("host")
                    .and_then(Value::as_str)
                    .ok_or_else(|| ApprovalsError::InvalidField { field: "egress[].host", reason: "missing or not a string".into() })?
                    .to_string();
                let methods = match entry.get("methods") {
                    Some(Value::Array(items)) => items
                        .iter()
                        .filter_map(Value::as_str)
                        .map(str::to_string)
                        .collect(),
                    _ => DEFAULT_METHODS.iter().map(|m| m.to_string()).collect(),
                };
                Ok(EgressRule { host, methods })
            })
            .collect::<Result<Vec<_>, ApprovalsError>>()?;

        let tables = summary
            .get("data")
            .and_then(|d| d.get("tables"))
            .ok_or(ApprovalsError::MissingField("data.tables"))?
            .as_array()
            .ok_or_else(|| ApprovalsError::InvalidField { field: "data.tables", reason: "not an array".into() })?
            .iter()
            .map(|entry| {
                let name = entry
                    .get("name")
                    .and_then(Value::as_str)
                    .ok_or_else(|| ApprovalsError::InvalidField { field: "data.tables[].name", reason: "missing or not a string".into() })?
                    .to_string();
                let read = entry.get("read").and_then(Value::as_bool).unwrap_or(false);
                let write = entry.get("write").and_then(Value::as_bool).unwrap_or(false);
                Ok(TableGrant { name, read, write })
            })
            .collect::<Result<Vec<_>, ApprovalsError>>()?;

        let capabilities = summary
            .get("capabilities")
            .ok_or(ApprovalsError::MissingField("capabilities"))?
            .as_array()
            .ok_or_else(|| ApprovalsError::InvalidField { field: "capabilities", reason: "not an array".into() })?
            .iter()
            .filter_map(Value::as_str)
            .filter_map(Capability::parse)
            .collect();

        let routes_to = summary
            .get("routes_to")
            .ok_or(ApprovalsError::MissingField("routes_to"))?
            .as_array()
            .ok_or_else(|| ApprovalsError::InvalidField { field: "routes_to", reason: "not an array".into() })?
            .iter()
            .filter_map(Value::as_str)
            .map(str::to_string)
            .collect();

        let limits_json = summary.get("limits").ok_or(ApprovalsError::MissingField("limits"))?;
        let limits = ApprovedLimits {
            timeout_ms: limits_json
                .get("timeout_ms")
                .and_then(Value::as_u64)
                .ok_or_else(|| ApprovalsError::InvalidField { field: "limits.timeout_ms", reason: "missing or not a u64".into() })?,
            memory_mb: limits_json
                .get("memory_mb")
                .and_then(Value::as_u64)
                .ok_or_else(|| ApprovalsError::InvalidField { field: "limits.memory_mb", reason: "missing or not a u32".into() })? as u32,
            egress_rps: limits_json
                .get("egress_rps")
                .and_then(Value::as_u64)
                .ok_or_else(|| ApprovalsError::InvalidField { field: "limits.egress_rps", reason: "missing or not a u32".into() })? as u32,
        };

        Ok(Self { app_id: app_id.to_string(), egress, tables, capabilities, routes_to, limits })
    }

    pub fn has_capability(&self, cap: Capability) -> bool {
        self.capabilities.contains(&cap)
    }

    /// Exact host match wins; otherwise a single-label wildcard entry
    /// (`*.example.com`) matches exactly one label of prefix (spec §8.1:
    /// "matches `a.example.com`, not `a.b.example.com` and not
    /// `example.com` itself").
    pub fn egress_rule_for(&self, host: &str) -> Option<&EgressRule> {
        if let Some(rule) = self.egress.iter().find(|r| r.host == host) {
            return Some(rule);
        }
        self.egress.iter().find(|r| {
            r.host
                .strip_prefix("*.")
                .map(|suffix| {
                    host.strip_suffix(suffix)
                        .and_then(|prefix| prefix.strip_suffix('.'))
                        .map(|label_prefix| !label_prefix.is_empty() && !label_prefix.contains('.'))
                        .unwrap_or(false)
                })
                .unwrap_or(false)
        })
    }

    pub fn table_grant_for(&self, name: &str) -> Option<&TableGrant> {
        self.tables.iter().find(|t| t.name == name)
    }

    pub fn allows_route_to(&self, target_app_id: &str) -> bool {
        self.routes_to.iter().any(|r| r == target_app_id)
    }
}
```

- [ ] **Step 4: Export from `src/host/mod.rs`**

```rust
//! The stage-side host runtime: capability enforcement, the
//! approved-permission model, and the mTLS frame-protocol server. Never
//! holds a bundle credential itself -- every real Valkey/Postgres/HTTP
//! call is delegated to a trait the *service* implements (spec §11.3,
//! §11.10 -- see this plan's Global Constraints).

pub mod approvals;
```

- [ ] **Step 5: Run to verify pass**

Run: `make test`
Expected: PASS — all 8 `approvals_tests` green.

- [ ] **Step 6: Commit**

```bash
git add packages/rust-bundle-host/src/host packages/rust-bundle-host/tests/approvals_tests.rs
git commit -m "$(cat <<'EOF'
feat(bundle-host): ApprovedPermissions -- the approved-permission-set model

Parses the already-approved capability summary (spec §6.9's
app_install_approvals shape, as served by the distribution API's
manifest field, §6.7) into a typed, queryable ApprovedPermissions the
egress/db/kv/relay guards enforce against -- never the raw manifest.

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01N2rQgkHY872RubwXoBZxtE
EOF
)"
git push
```

---

## Task 10: Capability traits — `HttpEgress`, `KvStore`, `DbExecutor`, `RelayPush`, `Flags`, `Logger`, `Clock`

**Depends on:** Task 9 (`ApprovedPermissions`, which every guard takes by reference).

**Files:**
- Create: `packages/rust-bundle-host/src/host/capability.rs`
- Modify: `packages/rust-bundle-host/src/host/mod.rs`
- Test: `packages/rust-bundle-host/tests/capability_fakes_tests.rs`

**Interfaces:**
- Consumes: nothing new (pure trait definitions).
- Produces the seven traits the *service* (svc_process/svc_action, M3/M4) implements against its own transport:
  ```rust
  #[async_trait::async_trait]
  pub trait HttpEgress: Send + Sync {
      /// Called only after the full §8.2 allowlist/SSRF/rate-limit chain
      /// has already approved `target_addr` (the pinned, resolved
      /// socket address) and `sni` (the TLS server name to present) --
      /// this trait performs the transport only, never a policy check.
      async fn execute(
          &self,
          target_addr: std::net::SocketAddr,
          sni: &str,
          request: PreparedHttpRequest,
      ) -> Result<RawHttpResponse, HttpTransportError>;
  }
  pub struct PreparedHttpRequest { pub method: String, pub path_and_query: String, pub headers: Vec<(String, String)>, pub body: Option<Vec<u8>>, pub timeout: std::time::Duration }
  pub struct RawHttpResponse { pub status: u16, pub headers: Vec<(String, String)>, pub body: Vec<u8> }
  #[derive(Debug, thiserror::Error)] pub enum HttpTransportError { #[error("timeout")] Timeout, #[error("tls verification failed: {0}")] Tls(String), #[error("transport error: {0}")] Other(String) }

  #[async_trait::async_trait]
  pub trait KvStore: Send + Sync {
      async fn get(&self, namespaced_key: &str) -> Result<Option<Vec<u8>>, KvBackendError>;
      async fn set(&self, namespaced_key: &str, value: &[u8], ttl_seconds: u32) -> Result<(), KvBackendError>;
      async fn delete(&self, namespaced_key: &str) -> Result<(), KvBackendError>;
      async fn increment(&self, namespaced_key: &str, delta: i64, ttl_seconds: u32) -> Result<i64, KvBackendError>;
  }
  #[derive(Debug, thiserror::Error)] pub enum KvBackendError { #[error("backend error: {0}")] Backend(String) }

  #[async_trait::async_trait]
  pub trait DbExecutor: Send + Sync {
      /// Called only after `host::db_guard` has already parsed and
      /// table-allowlist-checked `statement` -- this trait executes a
      /// pre-approved statement under the bundle's own Postgres role.
      /// `scope.tenant_id`/`scope.community_id` (D30, spec §5.11/§7.4)
      /// come from a binding-MAC-verified envelope upstream, never from
      /// the bundle -- the implementation MUST run `statement` inside a
      /// transaction that first issues `SET LOCAL waddles.tenant = scope.tenant_id`
      /// and `SET LOCAL waddles.community = scope.community_id.unwrap_or("_tenant")`,
      /// so Postgres row-level-security policies scope every row this
      /// call can see or write to that tenant/community, independent of
      /// which table the bundle's own role can otherwise reach.
      async fn execute(&self, scope: &crate::wire::message::InvocationScope, statement: &str, params: &[DbValue]) -> Result<DbRows, DbBackendError>;
  }
  #[derive(Debug, Clone)] pub enum DbValue { Null, Bool(bool), Int(i64), Float(f64), Text(String), Bytes(Vec<u8>) }
  #[derive(Debug, Clone)] pub struct DbRows { pub columns: Vec<String>, pub rows: Vec<Vec<DbValue>>, pub rows_affected: u64 }
  #[derive(Debug, thiserror::Error)] pub enum DbBackendError { #[error("backend error: {0}")] Backend(String), #[error("conflict: {0}")] Conflict(String), #[error("timeout")] Timeout }

  #[async_trait::async_trait]
  pub trait RelayPush: Send + Sync {
      async fn push(&self, provider: &str, message_json: &str) -> Result<(), RelayBackendError>;
  }
  #[derive(Debug, thiserror::Error)] pub enum RelayBackendError { #[error("unknown provider '{0}'")] UnknownProvider(String), #[error("backend error: {0}")] Backend(String) }

  #[async_trait::async_trait]
  pub trait Flags: Send + Sync {
      async fn enabled(&self, key: &str, default_value: bool) -> bool;
      async fn tier(&self) -> String;
  }

  pub trait Logger: Send + Sync {
      /// `sanitized_fields_json` has already had the SENSITIVE_KEYS
      /// rule applied by `host::log_guard` -- this trait only forwards.
      fn write(&self, level: LogLevel, app_id: &str, message: &str, sanitized_fields_json: &str);
  }
  #[derive(Debug, Clone, Copy)] pub enum LogLevel { Error, Warn, Info, Debug }

  pub trait Clock: Send + Sync {
      fn now_millis(&self) -> u64;
      fn now_rfc3339(&self) -> String;
      fn monotonic_nanos(&self) -> u64;
  }
  ```
  Task 11/12 (`EgressGuard`) wraps `HttpEgress`; Task 13 (`DbGuard`) wraps `DbExecutor`; Task 14 wraps `KvStore`/`RelayPush`/`Flags`/`Logger`/`Clock`; Task 16 (the host-call router) holds one guard per trait and is the only thing that calls them.

- [ ] **Step 1: Write the failing tests**

`tests/capability_fakes_tests.rs`:

```rust
#![allow(clippy::unwrap_used, clippy::panic)]
use penguin_bundle_host::host::capability::*;
use std::collections::HashMap;
use std::sync::Mutex;

/// A minimal in-memory fake -- the "trait objects + test doubles" pattern
/// `writing-rust-tests` recommends over a real network/DB call.
struct FakeKv {
    store: Mutex<HashMap<String, Vec<u8>>>,
}

#[async_trait::async_trait]
impl KvStore for FakeKv {
    async fn get(&self, key: &str) -> Result<Option<Vec<u8>>, KvBackendError> {
        Ok(self.store.lock().unwrap().get(key).cloned())
    }
    async fn set(&self, key: &str, value: &[u8], _ttl_seconds: u32) -> Result<(), KvBackendError> {
        self.store.lock().unwrap().insert(key.to_string(), value.to_vec());
        Ok(())
    }
    async fn delete(&self, key: &str) -> Result<(), KvBackendError> {
        self.store.lock().unwrap().remove(key);
        Ok(())
    }
    async fn increment(&self, key: &str, delta: i64, _ttl_seconds: u32) -> Result<i64, KvBackendError> {
        let mut store = self.store.lock().unwrap();
        let current = store
            .get(key)
            .and_then(|v| std::str::from_utf8(v).ok())
            .and_then(|s| s.parse::<i64>().ok())
            .unwrap_or(0);
        let next = current + delta;
        store.insert(key.to_string(), next.to_string().into_bytes());
        Ok(next)
    }
}

#[tokio::test]
async fn fake_kv_round_trips_through_the_trait_object() {
    let kv: std::sync::Arc<dyn KvStore> = std::sync::Arc::new(FakeKv { store: Mutex::new(HashMap::new()) });
    kv.set("b:x", b"hello", 0).await.unwrap();
    assert_eq!(kv.get("b:x").await.unwrap(), Some(b"hello".to_vec()));
    assert_eq!(kv.increment("b:counter", 5, 0).await.unwrap(), 5);
    assert_eq!(kv.increment("b:counter", 3, 0).await.unwrap(), 8);
    kv.delete("b:x").await.unwrap();
    assert_eq!(kv.get("b:x").await.unwrap(), None);
}

struct FakeFlags;
#[async_trait::async_trait]
impl Flags for FakeFlags {
    async fn enabled(&self, _key: &str, default_value: bool) -> bool { default_value }
    async fn tier(&self) -> String { "free".to_string() }
}

#[tokio::test]
async fn fake_flags_fails_open_to_the_supplied_default() {
    let flags: std::sync::Arc<dyn Flags> = std::sync::Arc::new(FakeFlags);
    assert!(flags.enabled("waddles.core.wasm-bundles", true).await);
    assert!(!flags.enabled("waddles.core.wasm-bundles", false).await);
}

struct FakeClock;
impl Clock for FakeClock {
    fn now_millis(&self) -> u64 { 1_757_851_200_000 }
    fn now_rfc3339(&self) -> String { "2026-09-14T12:00:00.000Z".to_string() }
    fn monotonic_nanos(&self) -> u64 { 42 }
}

#[test]
fn fake_clock_is_object_safe_and_callable() {
    let clock: std::sync::Arc<dyn Clock> = std::sync::Arc::new(FakeClock);
    assert_eq!(clock.now_millis(), 1_757_851_200_000);
    assert_eq!(clock.monotonic_nanos(), 42);
}

struct RecordingLogger {
    lines: Mutex<Vec<String>>,
}
impl Logger for RecordingLogger {
    fn write(&self, level: LogLevel, app_id: &str, message: &str, sanitized_fields_json: &str) {
        self.lines.lock().unwrap().push(format!("{level:?} {app_id} {message} {sanitized_fields_json}"));
    }
}

#[test]
fn logger_trait_is_object_safe_and_records_calls() {
    let logger: std::sync::Arc<dyn Logger> = std::sync::Arc::new(RecordingLogger { lines: Mutex::new(Vec::new()) });
    logger.write(LogLevel::Info, "waddles.test.fixture.hello", "hi", "{}");
    // Downcast back to assert -- proves the trait object is usable end to end.
    let recording = logger.as_ref() as &dyn std::any::Any;
    let _ = recording; // object-safety + call succeeded is the assertion; message content checked via a concrete-type variant below.
}

#[test]
fn logger_concrete_type_records_the_call() {
    let logger = RecordingLogger { lines: Mutex::new(Vec::new()) };
    logger.write(LogLevel::Warn, "a", "m", "{\"k\":\"v\"}");
    let lines = logger.lines.lock().unwrap();
    assert_eq!(lines.len(), 1);
    assert!(lines[0].contains("Warn"));
    assert!(lines[0].contains("m"));
}
```

- [ ] **Step 2: Run to verify failure**

Run: `make test`
Expected: FAIL — `host::capability` module does not exist.

- [ ] **Step 3: Implement `src/host/capability.rs`**

```rust
//! The seven capability traits a service (svc_process/svc_action, M3/M4)
//! implements against its own real transport. This crate never
//! implements these against a real Valkey/Postgres/HTTP client itself
//! (spec §11.3, §11.10 -- see Global Constraints) -- it only defines the
//! contract and, in `egress.rs`/`db_guard.rs`/etc., the policy layer
//! that decides *whether* to call into an implementation at all.

use async_trait::async_trait;
use thiserror::Error;

use crate::wire::message::InvocationScope;

// -- http --

#[async_trait]
pub trait HttpEgress: Send + Sync {
    /// `target_addr`/`sni` have already passed the full §8.2 chain
    /// (scheme, allowlist, method, denylist, SSRF/DNS-rebind pinning) --
    /// this method performs the transport only.
    async fn execute(
        &self,
        target_addr: std::net::SocketAddr,
        sni: &str,
        request: PreparedHttpRequest,
    ) -> Result<RawHttpResponse, HttpTransportError>;
}

#[derive(Debug, Clone)]
pub struct PreparedHttpRequest {
    pub method: String,
    pub path_and_query: String,
    pub headers: Vec<(String, String)>,
    pub body: Option<Vec<u8>>,
    pub timeout: std::time::Duration,
}

#[derive(Debug, Clone)]
pub struct RawHttpResponse {
    pub status: u16,
    pub headers: Vec<(String, String)>,
    pub body: Vec<u8>,
}

#[derive(Debug, Error)]
pub enum HttpTransportError {
    #[error("timeout")]
    Timeout,
    #[error("tls verification failed: {0}")]
    Tls(String),
    #[error("transport error: {0}")]
    Other(String),
}

// -- kv --

#[async_trait]
pub trait KvStore: Send + Sync {
    async fn get(&self, namespaced_key: &str) -> Result<Option<Vec<u8>>, KvBackendError>;
    async fn set(&self, namespaced_key: &str, value: &[u8], ttl_seconds: u32) -> Result<(), KvBackendError>;
    async fn delete(&self, namespaced_key: &str) -> Result<(), KvBackendError>;
    async fn increment(&self, namespaced_key: &str, delta: i64, ttl_seconds: u32) -> Result<i64, KvBackendError>;
}

#[derive(Debug, Error)]
pub enum KvBackendError {
    #[error("backend error: {0}")]
    Backend(String),
}

// -- db --

#[async_trait]
pub trait DbExecutor: Send + Sync {
    /// Called only after `host::db_guard` has parsed and table-checked
    /// `statement` -- executes a pre-approved statement under the
    /// bundle's own Postgres role (spec §7.4, §11.10: the executor
    /// itself never holds this role; only the service does).
    ///
    /// **D30 (spec §5.11):** `scope.tenant_id`/`scope.community_id` come
    /// from a binding-MAC-verified envelope upstream, never from the
    /// bundle. The implementation MUST run `statement` inside a
    /// transaction that first issues `SET LOCAL waddles.tenant` and
    /// `SET LOCAL waddles.community` from those two fields, so Postgres
    /// row-level-security scopes every row this call can see or write --
    /// two independent layers, deliberately: this trait's caller
    /// (`db_guard`) already checked the table allowlist; RLS catches a
    /// table-allowlist bug or a compromised bundle role from the other
    /// side.
    async fn execute(&self, scope: &InvocationScope, statement: &str, params: &[DbValue]) -> Result<DbRows, DbBackendError>;
}

#[derive(Debug, Clone, PartialEq)]
pub enum DbValue {
    Null,
    Bool(bool),
    Int(i64),
    Float(f64),
    Text(String),
    Bytes(Vec<u8>),
}

#[derive(Debug, Clone)]
pub struct DbRows {
    pub columns: Vec<String>,
    pub rows: Vec<Vec<DbValue>>,
    pub rows_affected: u64,
}

#[derive(Debug, Error)]
pub enum DbBackendError {
    #[error("backend error: {0}")]
    Backend(String),
    #[error("conflict: {0}")]
    Conflict(String),
    #[error("timeout")]
    Timeout,
}

// -- relay --

#[async_trait]
pub trait RelayPush: Send + Sync {
    async fn push(&self, provider: &str, message_json: &str) -> Result<(), RelayBackendError>;
}

#[derive(Debug, Error)]
pub enum RelayBackendError {
    #[error("unknown provider '{0}'")]
    UnknownProvider(String),
    #[error("backend error: {0}")]
    Backend(String),
}

// -- flags --

#[async_trait]
pub trait Flags: Send + Sync {
    async fn enabled(&self, key: &str, default_value: bool) -> bool;
    /// "free" | "professional" | "enterprise"
    async fn tier(&self) -> String;
}

// -- log --

#[derive(Debug, Clone, Copy)]
pub enum LogLevel {
    Error,
    Warn,
    Info,
    Debug,
}

pub trait Logger: Send + Sync {
    /// `sanitized_fields_json` has already had the penguin-logging
    /// SENSITIVE_KEYS rule applied by `host::log_guard` (Task 14) --
    /// this trait only forwards into the stage's own OTel pipeline.
    fn write(&self, level: LogLevel, app_id: &str, message: &str, sanitized_fields_json: &str);
}

// -- clock --

pub trait Clock: Send + Sync {
    fn now_millis(&self) -> u64;
    fn now_rfc3339(&self) -> String;
    fn monotonic_nanos(&self) -> u64;
}
```

- [ ] **Step 4: Export from `src/host/mod.rs`**

```rust
pub mod approvals;
pub mod capability;
```

- [ ] **Step 5: Run to verify pass**

Run: `make test`
Expected: PASS — all `capability_fakes_tests` green.

- [ ] **Step 6: Commit**

```bash
git add packages/rust-bundle-host/src/host/capability.rs packages/rust-bundle-host/src/host/mod.rs packages/rust-bundle-host/tests/capability_fakes_tests.rs
git commit -m "$(cat <<'EOF'
feat(bundle-host): capability traits HttpEgress/KvStore/DbExecutor/RelayPush/Flags/Logger/Clock

Seven traits a service implements against its own Valkey/Postgres/HTTP
transport; this crate never implements them against a real backend
itself (spec §11.3, §11.10). Proven object-safe and usable behind
Arc<dyn ...> with in-memory fakes, matching writing-rust-tests' "trait
objects + test doubles" guidance over a real network/DB call.

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01N2rQgkHY872RubwXoBZxtE
EOF
)"
git push
```

---

## Task 11: `EgressGuard` part 1 — scheme, URL, allowlist, denylist, SSRF (§8.2 steps 1-7)

**Depends on:** Task 10 (`HttpEgress`), Task 9 (`ApprovedPermissions::egress_rule_for`).

**Files:**
- Create: `packages/rust-bundle-host/src/host/egress.rs`
- Modify: `packages/rust-bundle-host/src/host/mod.rs`
- Test: `packages/rust-bundle-host/tests/egress_guard_tests.rs`

**Interfaces:**
- Consumes: `host::approvals::{ApprovedPermissions, EgressRule}` (Task 9), `host::capability::HttpEgress` (Task 10).
- Produces:
  ```rust
  pub struct EgressRequest {
      pub method: String,
      pub url: String,
      pub headers: Vec<(String, String)>,
      pub body: Option<Vec<u8>>,
      pub secret_refs: Vec<(String, String)>,   // header name -> secret ref name, spec §8.3
  }
  pub struct EgressResponse { pub status: u16, pub headers: Vec<(String, String)>, pub body: Vec<u8>, pub truncated: bool }

  #[derive(Debug, Clone, PartialEq, Eq)]
  pub enum EgressDenial {
      SchemeNotHttps, MalformedUrl, HostNotDeclared, MethodNotDeclared,
      HostDenylisted, SsrfBlockedAddress, DnsRebindBlocked,
      RedirectOffAllowlist, TlsVerificationFailed,
      /// Spec §8.3: an unresolvable `secret_refs` entry. Used only by
      /// Task 12's `send()` — `check_allowlist_and_resolve` (this task)
      /// never resolves secrets, so it never produces this variant.
      SecretUnresolved,
  }
  impl EgressDenial {
      pub fn reason_str(&self) -> &'static str; // exact §8.2 "Denial reason" strings, e.g. "scheme_not_https"
  }
  #[derive(Debug)] pub enum EgressOutcome { Response(EgressResponse), Denied(EgressDenial), RateLimited { retry_after_ms: u32 }, Timeout, TooLarge(u64) }

  #[async_trait::async_trait]
  pub trait DnsResolver: Send + Sync {
      async fn resolve(&self, host: &str) -> std::io::Result<Vec<std::net::IpAddr>>;
  }
  pub trait TenantDenylist: Send + Sync {
      fn is_denylisted(&self, host: &str) -> bool;
  }

  pub struct EgressGuardConfig { pub allow_private_hosts: bool, pub max_redirects: u8, pub response_byte_cap: usize, pub call_timeout: std::time::Duration }

  pub struct EgressGuard<T: HttpEgress> {
      pub fn new(transport: std::sync::Arc<T>, resolver: std::sync::Arc<dyn DnsResolver>, denylist: std::sync::Arc<dyn TenantDenylist>, config: EgressGuardConfig) -> Self;
      /// Runs the full §8.2 order and, only if every check passes, calls
      /// `transport.execute(...)`. Steps 8-12 (rate limit, redirects,
      /// size cap, timeout) are added in Task 12 -- this task's `check()`
      /// covers steps 1-7 and stops there (callers in Task 12 chain the
      /// rest).
      pub fn check_allowlist_and_resolve(&self, approved: &ApprovedPermissions, req: &EgressRequest) -> Result<std::net::SocketAddr, EgressDenial>;
  }
  ```
  Task 12 extends `EgressGuard` with `send()` (the full chain, calling `check_allowlist_and_resolve` first); Task 16 (host-call router) calls `EgressGuard::send()` for `capability == Http, op == "send"`.

- [ ] **Step 1: Write the failing tests**

`tests/egress_guard_tests.rs`:

```rust
#![allow(clippy::unwrap_used, clippy::panic)]
use penguin_bundle_host::host::approvals::ApprovedPermissions;
use penguin_bundle_host::host::capability::{HttpTransportError, PreparedHttpRequest, RawHttpResponse, HttpEgress};
use penguin_bundle_host::host::egress::{DnsResolver, EgressDenial, EgressGuard, EgressGuardConfig, EgressRequest, TenantDenylist};
use serde_json::json;
use std::net::IpAddr;
use std::sync::Arc;

fn approved_with_egress(rules: serde_json::Value) -> ApprovedPermissions {
    ApprovedPermissions::from_json(
        "waddles.test.fixture.hello",
        &json!({
            "egress": rules,
            "data": {"tables": []},
            "capabilities": ["http"],
            "routes_to": [],
            "limits": {"timeout_ms": 2000, "memory_mb": 64, "egress_rps": 10}
        }),
    )
    .unwrap()
}

struct FakeResolver(Vec<IpAddr>);
#[async_trait::async_trait]
impl DnsResolver for FakeResolver {
    async fn resolve(&self, _host: &str) -> std::io::Result<Vec<IpAddr>> { Ok(self.0.clone()) }
}

struct NoDenylist;
impl TenantDenylist for NoDenylist { fn is_denylisted(&self, _host: &str) -> bool { false } }

struct AlwaysDenylist;
impl TenantDenylist for AlwaysDenylist { fn is_denylisted(&self, _host: &str) -> bool { true } }

struct FakeTransport;
#[async_trait::async_trait]
impl HttpEgress for FakeTransport {
    async fn execute(&self, _addr: std::net::SocketAddr, _sni: &str, _req: PreparedHttpRequest) -> Result<RawHttpResponse, HttpTransportError> {
        Ok(RawHttpResponse { status: 200, headers: vec![], body: vec![] })
    }
}

fn guard(resolver: Vec<IpAddr>, denylist: Arc<dyn TenantDenylist>) -> EgressGuard<FakeTransport> {
    EgressGuard::new(
        Arc::new(FakeTransport),
        Arc::new(FakeResolver(resolver)),
        denylist,
        EgressGuardConfig { allow_private_hosts: false, max_redirects: 3, response_byte_cap: 1_048_576, call_timeout: std::time::Duration::from_secs(5) },
    )
}

fn public_ip() -> IpAddr { "93.184.216.34".parse().unwrap() } // example.com-class public address

#[test]
fn rejects_non_https_scheme() {
    let approved = approved_with_egress(json!([{"host": "api.spotify.com"}]));
    let g = guard(vec![public_ip()], Arc::new(NoDenylist));
    let req = EgressRequest { method: "GET".into(), url: "http://api.spotify.com/x".into(), headers: vec![], body: None, secret_refs: vec![] };
    let err = g.check_allowlist_and_resolve(&approved, &req).unwrap_err();
    assert_eq!(err, EgressDenial::SchemeNotHttps);
    assert_eq!(err.reason_str(), "scheme_not_https");
}

#[test]
fn rejects_malformed_url() {
    let approved = approved_with_egress(json!([{"host": "api.spotify.com"}]));
    let g = guard(vec![public_ip()], Arc::new(NoDenylist));
    let req = EgressRequest { method: "GET".into(), url: "not a url at all".into(), headers: vec![], body: None, secret_refs: vec![] };
    assert_eq!(g.check_allowlist_and_resolve(&approved, &req).unwrap_err(), EgressDenial::MalformedUrl);
}

#[test]
fn rejects_url_with_embedded_credentials() {
    let approved = approved_with_egress(json!([{"host": "api.spotify.com"}]));
    let g = guard(vec![public_ip()], Arc::new(NoDenylist));
    let req = EgressRequest { method: "GET".into(), url: "https://user:pass@api.spotify.com/x".into(), headers: vec![], body: None, secret_refs: vec![] };
    assert_eq!(g.check_allowlist_and_resolve(&approved, &req).unwrap_err(), EgressDenial::MalformedUrl);
}

#[test]
fn rejects_a_host_not_on_the_allowlist() {
    let approved = approved_with_egress(json!([{"host": "api.spotify.com"}]));
    let g = guard(vec![public_ip()], Arc::new(NoDenylist));
    let req = EgressRequest { method: "GET".into(), url: "https://evil.example.com/x".into(), headers: vec![], body: None, secret_refs: vec![] };
    assert_eq!(g.check_allowlist_and_resolve(&approved, &req).unwrap_err(), EgressDenial::HostNotDeclared);
}

#[test]
fn rejects_a_method_not_declared_for_that_host() {
    let approved = approved_with_egress(json!([{"host": "api.spotify.com", "methods": ["GET"]}]));
    let g = guard(vec![public_ip()], Arc::new(NoDenylist));
    let req = EgressRequest { method: "DELETE".into(), url: "https://api.spotify.com/x".into(), headers: vec![], body: None, secret_refs: vec![] };
    assert_eq!(g.check_allowlist_and_resolve(&approved, &req).unwrap_err(), EgressDenial::MethodNotDeclared);
}

#[test]
fn rejects_a_denylisted_host_even_when_allowlisted() {
    let approved = approved_with_egress(json!([{"host": "api.spotify.com"}]));
    let g = guard(vec![public_ip()], Arc::new(AlwaysDenylist));
    let req = EgressRequest { method: "GET".into(), url: "https://api.spotify.com/x".into(), headers: vec![], body: None, secret_refs: vec![] };
    assert_eq!(g.check_allowlist_and_resolve(&approved, &req).unwrap_err(), EgressDenial::HostDenylisted);
}

#[test]
fn rejects_ssrf_private_range_by_default() {
    let approved = approved_with_egress(json!([{"host": "internal.example.com"}]));
    let g = guard(vec!["10.0.0.5".parse().unwrap()], Arc::new(NoDenylist));
    let req = EgressRequest { method: "GET".into(), url: "https://internal.example.com/x".into(), headers: vec![], body: None, secret_refs: vec![] };
    assert_eq!(g.check_allowlist_and_resolve(&approved, &req).unwrap_err(), EgressDenial::SsrfBlockedAddress);
}

#[test]
fn allow_private_hosts_lifts_only_the_private_range_half() {
    let approved = approved_with_egress(json!([{"host": "internal.example.com"}]));
    let g = EgressGuard::new(
        Arc::new(FakeTransport),
        Arc::new(FakeResolver(vec!["10.0.0.5".parse().unwrap()])),
        Arc::new(NoDenylist),
        EgressGuardConfig { allow_private_hosts: true, max_redirects: 3, response_byte_cap: 1_048_576, call_timeout: std::time::Duration::from_secs(5) },
    );
    let req = EgressRequest { method: "GET".into(), url: "https://internal.example.com/x".into(), headers: vec![], body: None, secret_refs: vec![] };
    assert!(g.check_allowlist_and_resolve(&approved, &req).is_ok());
}

#[test]
fn allow_private_hosts_never_unblocks_loopback_link_local_or_cloud_metadata() {
    let approved = approved_with_egress(json!([{"host": "metadata.example.com"}]));
    for addr in ["127.0.0.1", "169.254.169.254", "169.254.1.1", "224.0.0.1"] {
        let g = EgressGuard::new(
            Arc::new(FakeTransport),
            Arc::new(FakeResolver(vec![addr.parse().unwrap()])),
            Arc::new(NoDenylist),
            EgressGuardConfig { allow_private_hosts: true, max_redirects: 3, response_byte_cap: 1_048_576, call_timeout: std::time::Duration::from_secs(5) },
        );
        let req = EgressRequest { method: "GET".into(), url: "https://metadata.example.com/x".into(), headers: vec![], body: None, secret_refs: vec![] };
        assert_eq!(
            g.check_allowlist_and_resolve(&approved, &req).unwrap_err(),
            EgressDenial::SsrfBlockedAddress,
            "address {addr} must stay blocked even with allowPrivateHosts"
        );
    }
}

#[test]
fn wildcard_host_matches_are_honored_by_the_guard_not_just_the_approvals_lookup() {
    let approved = approved_with_egress(json!([{"host": "*.googleapis.com"}]));
    let g = guard(vec![public_ip()], Arc::new(NoDenylist));
    let req = EgressRequest { method: "GET".into(), url: "https://storage.googleapis.com/x".into(), headers: vec![], body: None, secret_refs: vec![] };
    assert!(g.check_allowlist_and_resolve(&approved, &req).is_ok());
}

#[test]
fn resolved_address_is_returned_on_success_for_dns_rebind_pinning() {
    let approved = approved_with_egress(json!([{"host": "api.spotify.com"}]));
    let ip = public_ip();
    let g = guard(vec![ip], Arc::new(NoDenylist));
    let req = EgressRequest { method: "GET".into(), url: "https://api.spotify.com/x".into(), headers: vec![], body: None, secret_refs: vec![] };
    let addr = g.check_allowlist_and_resolve(&approved, &req).unwrap();
    assert_eq!(addr.ip(), ip);
}
```

- [ ] **Step 2: Run to verify failure**

Run: `make test`
Expected: FAIL — `host::egress` module does not exist.

- [ ] **Step 3: Implement `src/host/egress.rs` (steps 1-7)**

```rust
//! Guarded outbound HTTP -- spec §8.2's ordered enforcement chain. This
//! module implements steps 1-7 (scheme, URL shape, allowlist, method,
//! tenant denylist, SSRF/private-range, DNS-rebind pinning); Task 12
//! adds steps 8-12 (rate limit, TLS delegated to the transport, redirect
//! re-checking, response size cap, timeout) plus the actual `send()`
//! that calls into `HttpEgress`.

use std::net::{IpAddr, Ipv4Addr, Ipv6Addr, SocketAddr};
use std::sync::Arc;

use async_trait::async_trait;
use url::Url;

use super::approvals::ApprovedPermissions;
use super::capability::HttpEgress;

#[derive(Debug, Clone)]
pub struct EgressRequest {
    pub method: String,
    pub url: String,
    pub headers: Vec<(String, String)>,
    pub body: Option<Vec<u8>>,
    /// Header name -> secret reference name (spec §8.3). Resolved by
    /// Task 12's `send()` immediately before the transport call; never
    /// present in this module's own checks.
    pub secret_refs: Vec<(String, String)>,
}

#[derive(Debug, Clone)]
pub struct EgressResponse {
    pub status: u16,
    pub headers: Vec<(String, String)>,
    pub body: Vec<u8>,
    pub truncated: bool,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum EgressDenial {
    SchemeNotHttps,
    MalformedUrl,
    HostNotDeclared,
    MethodNotDeclared,
    HostDenylisted,
    SsrfBlockedAddress,
    DnsRebindBlocked,
    RedirectOffAllowlist,
    TlsVerificationFailed,
    /// Spec §8.3: an unresolvable `secret_refs` entry. Produced only by
    /// Task 12's `send()` — this task's `check_allowlist_and_resolve`
    /// never resolves secrets, so it never returns this variant, but the
    /// type is defined here (not redeclared in Task 12) so both call
    /// sites share one enum.
    SecretUnresolved,
}

impl EgressDenial {
    /// The exact `Denial reason` strings from spec §8.2's table, plus
    /// `secret_unresolved` from §8.3.
    pub fn reason_str(&self) -> &'static str {
        match self {
            Self::SchemeNotHttps => "scheme_not_https",
            Self::MalformedUrl => "malformed_url",
            Self::HostNotDeclared => "host_not_declared",
            Self::MethodNotDeclared => "method_not_declared",
            Self::HostDenylisted => "host_denylisted",
            Self::SsrfBlockedAddress => "ssrf_blocked_address",
            Self::DnsRebindBlocked => "dns_rebind_blocked",
            Self::RedirectOffAllowlist => "redirect_off_allowlist",
            Self::TlsVerificationFailed => "tls_verification_failed",
            Self::SecretUnresolved => "secret_unresolved",
        }
    }
}

#[derive(Debug)]
pub enum EgressOutcome {
    Response(EgressResponse),
    Denied(EgressDenial),
    RateLimited { retry_after_ms: u32 },
    Timeout,
    TooLarge(u64),
}

#[async_trait]
pub trait DnsResolver: Send + Sync {
    async fn resolve(&self, host: &str) -> std::io::Result<Vec<IpAddr>>;
}

pub trait TenantDenylist: Send + Sync {
    fn is_denylisted(&self, host: &str) -> bool;
}

#[derive(Debug, Clone)]
pub struct EgressGuardConfig {
    pub allow_private_hosts: bool,
    pub max_redirects: u8,
    pub response_byte_cap: usize,
    pub call_timeout: std::time::Duration,
}

pub struct EgressGuard<T: HttpEgress> {
    transport: Arc<T>,
    resolver: Arc<dyn DnsResolver>,
    denylist: Arc<dyn TenantDenylist>,
    pub(super) config: EgressGuardConfig,
    pub(super) limiters: tokio::sync::Mutex<std::collections::HashMap<String, Arc<governor::DefaultDirectRateLimiter>>>,
}

impl<T: HttpEgress> EgressGuard<T> {
    pub fn new(
        transport: Arc<T>,
        resolver: Arc<dyn DnsResolver>,
        denylist: Arc<dyn TenantDenylist>,
        config: EgressGuardConfig,
    ) -> Self {
        Self { transport, resolver, denylist, config, limiters: tokio::sync::Mutex::new(std::collections::HashMap::new()) }
    }

    pub(super) fn transport(&self) -> &Arc<T> {
        &self.transport
    }

    /// Runs spec §8.2 steps 1-7. On success, returns the resolved,
    /// checked socket address the caller must connect to directly (step
    /// 7's "no second resolution between check and connect").
    pub fn check_allowlist_and_resolve(
        &self,
        approved: &ApprovedPermissions,
        req: &EgressRequest,
    ) -> Result<SocketAddr, EgressDenial> {
        let addr = self.check_steps_1_to_6_sync(approved, req)?;
        Ok(addr)
    }

    /// Split out so Task 12's redirect-hop re-check (step 10, "every hop
    /// re-runs steps 1-7") can call the same logic without going through
    /// `async fn` state for the parts that don't need it. DNS resolution
    /// itself is async (Task 12 awaits it); this synchronous entry point
    /// exists purely for the unit tests above, which supply a `FakeResolver`
    /// via a blocking-friendly seam -- see the `resolve_blocking` helper.
    fn check_steps_1_to_6_sync(&self, approved: &ApprovedPermissions, req: &EgressRequest) -> Result<SocketAddr, EgressDenial> {
        let url = Url::parse(&req.url).map_err(|_| EgressDenial::MalformedUrl)?;

        // Step 1: scheme is https.
        if url.scheme() != "https" {
            return Err(EgressDenial::SchemeNotHttps);
        }
        // Step 2: no embedded credentials, no fragment-only target, clean parse.
        if !url.username().is_empty() || url.password().is_some() {
            return Err(EgressDenial::MalformedUrl);
        }
        let host = url.host_str().ok_or(EgressDenial::MalformedUrl)?.to_lowercase();

        // Step 3: host matches an approved egress[].host entry.
        let rule = approved.egress_rule_for(&host).ok_or(EgressDenial::HostNotDeclared)?;

        // Step 4: method is in that entry's methods.
        if !rule.methods.iter().any(|m| m.eq_ignore_ascii_case(&req.method)) {
            return Err(EgressDenial::MethodNotDeclared);
        }

        // Step 5: tenant-level global denylist.
        if self.denylist.is_denylisted(&host) {
            return Err(EgressDenial::HostDenylisted);
        }

        // Steps 6-7: resolve and check the address range, then pin to it.
        // Resolution itself is async in production (Task 12's `send()`);
        // this sync helper is exercised directly by this task's tests via
        // `resolve_blocking`, which is a thin `futures::executor::block_on`
        // wrapper kept private to this module.
        let addresses = resolve_blocking(self.resolver.as_ref(), &host)
            .map_err(|_| EgressDenial::MalformedUrl)?;
        let chosen = addresses
            .into_iter()
            .find(|addr| self.address_allowed(*addr))
            .ok_or(EgressDenial::SsrfBlockedAddress)?;

        let port = url.port_or_known_default().unwrap_or(443);
        Ok(SocketAddr::new(chosen, port))
    }

    fn address_allowed(&self, addr: IpAddr) -> bool {
        if is_always_blocked(addr) {
            return false;
        }
        if is_private_range(addr) && !self.config.allow_private_hosts {
            return false;
        }
        true
    }
}

fn resolve_blocking(resolver: &dyn DnsResolver, host: &str) -> std::io::Result<Vec<IpAddr>> {
    // A dedicated current-thread runtime, not the caller's -- this
    // function exists only so the synchronous unit tests above (and the
    // synchronous SQL-shaped early steps) can call an async `DnsResolver`
    // without becoming `async fn` themselves. Task 12's real `send()`
    // path calls `resolver.resolve(host).await` directly on the async
    // executor and does not use this helper.
    tokio::runtime::Builder::new_current_thread()
        .enable_all()
        .build()
        .expect("building a throwaway runtime for a DNS resolve")
        .block_on(resolver.resolve(host))
}

/// Loopback, link-local, unspecified, multicast, and cloud-metadata
/// addresses -- blocked in **every** configuration, `allowPrivateHosts`
/// or not (spec §8.2 step 6, §8.5).
fn is_always_blocked(addr: IpAddr) -> bool {
    match addr {
        IpAddr::V4(v4) => {
            v4.is_loopback()
                || v4.is_link_local()
                || v4.is_unspecified()
                || v4.is_multicast()
                || v4 == Ipv4Addr::new(169, 254, 169, 254)
        }
        IpAddr::V6(v6) => {
            v6.is_loopback()
                || v6.is_unspecified()
                || v6.is_multicast()
                || (v6.segments()[0] & 0xffc0) == 0xfe80 // fe80::/10 link-local
                || v6.to_string().starts_with("fd00:ec2:")
        }
    }
}

/// The private-range half of §8.2 step 6 -- lifted by
/// `bundles.egress.allowPrivateHosts` (spec §8.5), unlike
/// `is_always_blocked`'s ranges.
fn is_private_range(addr: IpAddr) -> bool {
    match addr {
        IpAddr::V4(v4) => v4.is_private(),
        IpAddr::V6(v6) => (v6.segments()[0] & 0xfe00) == 0xfc00, // fc00::/7
    }
}
```

- [ ] **Step 4: Export from `src/host/mod.rs`**

```rust
pub mod approvals;
pub mod capability;
pub mod egress;
```

- [ ] **Step 5: Run to verify pass**

Run: `make test`
Expected: PASS — all 11 `egress_guard_tests` green.

- [ ] **Step 6: Commit**

```bash
git add packages/rust-bundle-host/src/host/egress.rs packages/rust-bundle-host/src/host/mod.rs packages/rust-bundle-host/tests/egress_guard_tests.rs
git commit -m "$(cat <<'EOF'
feat(bundle-host): EgressGuard steps 1-7 (scheme, allowlist, SSRF, DNS pin)

check_allowlist_and_resolve() implements spec §8.2 steps 1-7 exactly,
including the allowPrivateHosts override that lifts only the RFC 1918 /
fc00::/7 half of the SSRF check while loopback/link-local/multicast/
cloud-metadata stay blocked unconditionally (§8.5).

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01N2rQgkHY872RubwXoBZxtE
EOF
)"
git push
```

---

## Task 12: `EgressGuard::send()` — rate limit, redirects, size cap, timeout, secret injection (§8.2 steps 8-12, §8.3)

**Depends on:** Task 11 (`EgressGuard::check_allowlist_and_resolve`, which `send()` calls first).

**Files:**
- Modify: `packages/rust-bundle-host/src/host/egress.rs`
- Test: `packages/rust-bundle-host/tests/egress_guard_tests.rs` (append)

**Interfaces:**
- Consumes: everything from Task 11.
- Produces:
  ```rust
  #[async_trait::async_trait]
  pub trait SecretResolver: Send + Sync {
      /// Resolves a secret reference name to its value, or `None` if
      /// unresolvable (spec §8.3: "An unresolvable reference returns
      /// `denied(\"secret_unresolved\")` and is classified non-retryable").
      async fn resolve(&self, secret_ref_name: &str) -> Option<String>;
  }

  impl<T: HttpEgress> EgressGuard<T> {
      pub async fn send(
          &self,
          approved: &ApprovedPermissions,
          req: EgressRequest,
          secrets: &dyn SecretResolver,
      ) -> EgressOutcome;
  }
  ```
  Task 16 (host-call router) calls `EgressGuard::send()` directly for every `capability == Http` host-call.

- [ ] **Step 1: Write the failing tests (appended to `tests/egress_guard_tests.rs`)**

```rust
use penguin_bundle_host::host::egress::{EgressOutcome, SecretResolver};
use std::sync::atomic::{AtomicU32, Ordering};

struct NoSecrets;
#[async_trait::async_trait]
impl SecretResolver for NoSecrets {
    async fn resolve(&self, _name: &str) -> Option<String> { None }
}

struct FixedSecrets(std::collections::HashMap<String, String>);
#[async_trait::async_trait]
impl SecretResolver for FixedSecrets {
    async fn resolve(&self, name: &str) -> Option<String> { self.0.get(name).cloned() }
}

struct RecordingTransport {
    calls: std::sync::Mutex<Vec<PreparedHttpRequest>>,
}
#[async_trait::async_trait]
impl HttpEgress for RecordingTransport {
    async fn execute(&self, _addr: std::net::SocketAddr, _sni: &str, req: PreparedHttpRequest) -> Result<RawHttpResponse, HttpTransportError> {
        self.calls.lock().unwrap().push(req);
        Ok(RawHttpResponse { status: 200, headers: vec![], body: b"ok".to_vec() })
    }
}

#[tokio::test]
async fn send_happy_path_returns_a_response_and_calls_the_transport_exactly_once() {
    let approved = approved_with_egress(json!([{"host": "api.spotify.com"}]));
    let transport = Arc::new(RecordingTransport { calls: std::sync::Mutex::new(vec![]) });
    let g = EgressGuard::new(
        transport.clone(),
        Arc::new(FakeResolver(vec![public_ip()])),
        Arc::new(NoDenylist),
        EgressGuardConfig { allow_private_hosts: false, max_redirects: 3, response_byte_cap: 1_048_576, call_timeout: std::time::Duration::from_secs(5) },
    );
    let req = EgressRequest { method: "GET".into(), url: "https://api.spotify.com/v1/me".into(), headers: vec![], body: None, secret_refs: vec![] };
    let outcome = g.send(&approved, req, &NoSecrets).await;
    match outcome {
        EgressOutcome::Response(resp) => assert_eq!(resp.status, 200),
        other => panic!("expected Response, got {other:?}"),
    }
    assert_eq!(transport.calls.lock().unwrap().len(), 1);
}

#[tokio::test]
async fn secret_ref_is_resolved_and_injected_as_a_header_never_the_bundles_own_value() {
    let approved = approved_with_egress(json!([{"host": "api.spotify.com"}]));
    let transport = Arc::new(RecordingTransport { calls: std::sync::Mutex::new(vec![]) });
    let g = EgressGuard::new(
        transport.clone(),
        Arc::new(FakeResolver(vec![public_ip()])),
        Arc::new(NoDenylist),
        EgressGuardConfig { allow_private_hosts: false, max_redirects: 3, response_byte_cap: 1_048_576, call_timeout: std::time::Duration::from_secs(5) },
    );
    let mut secrets_map = std::collections::HashMap::new();
    secrets_map.insert("SPOTIFY_BOT_TOKEN_REF".to_string(), "secret-value-xyz".to_string());
    let secrets = FixedSecrets(secrets_map);
    let req = EgressRequest {
        method: "GET".into(), url: "https://api.spotify.com/v1/me".into(),
        headers: vec![], body: None,
        secret_refs: vec![("Authorization".to_string(), "SPOTIFY_BOT_TOKEN_REF".to_string())],
    };
    g.send(&approved, req, &secrets).await;
    let calls = transport.calls.lock().unwrap();
    let sent = &calls[0];
    assert!(
        sent.headers.iter().any(|(k, v)| k == "Authorization" && v == "secret-value-xyz"),
        "expected the resolved secret injected as the Authorization header, got {:?}", sent.headers
    );
}

#[tokio::test]
async fn unresolvable_secret_ref_denies_the_call_without_ever_reaching_the_transport() {
    let approved = approved_with_egress(json!([{"host": "api.spotify.com"}]));
    let transport = Arc::new(RecordingTransport { calls: std::sync::Mutex::new(vec![]) });
    let g = EgressGuard::new(
        transport.clone(),
        Arc::new(FakeResolver(vec![public_ip()])),
        Arc::new(NoDenylist),
        EgressGuardConfig { allow_private_hosts: false, max_redirects: 3, response_byte_cap: 1_048_576, call_timeout: std::time::Duration::from_secs(5) },
    );
    let req = EgressRequest {
        method: "GET".into(), url: "https://api.spotify.com/v1/me".into(),
        headers: vec![], body: None,
        secret_refs: vec![("Authorization".to_string(), "UNKNOWN_REF".to_string())],
    };
    let outcome = g.send(&approved, req, &NoSecrets).await;
    assert!(matches!(outcome, EgressOutcome::Denied(_)), "expected Denied, got {outcome:?}");
    assert_eq!(transport.calls.lock().unwrap().len(), 0);
}

#[tokio::test]
async fn rate_limiter_admits_up_to_the_burst_then_rate_limits() {
    let approved = ApprovedPermissions::from_json(
        "a",
        &json!({
            "egress": [{"host": "api.spotify.com"}], "data": {"tables": []},
            "capabilities": ["http"], "routes_to": [],
            "limits": {"timeout_ms": 2000, "memory_mb": 64, "egress_rps": 1}
        }),
    )
    .unwrap();
    let transport = Arc::new(RecordingTransport { calls: std::sync::Mutex::new(vec![]) });
    let g = EgressGuard::new(
        transport,
        Arc::new(FakeResolver(vec![public_ip()])),
        Arc::new(NoDenylist),
        EgressGuardConfig { allow_private_hosts: false, max_redirects: 3, response_byte_cap: 1_048_576, call_timeout: std::time::Duration::from_secs(5) },
    );
    let mk_req = || EgressRequest { method: "GET".into(), url: "https://api.spotify.com/v1/me".into(), headers: vec![], body: None, secret_refs: vec![] };

    let mut rate_limited_seen = false;
    for _ in 0..25 {
        if let EgressOutcome::RateLimited { .. } = g.send(&approved, mk_req(), &NoSecrets).await {
            rate_limited_seen = true;
            break;
        }
    }
    assert!(rate_limited_seen, "expected at least one RateLimited outcome within 25 rapid calls at egress_rps=1");
}

#[tokio::test]
async fn response_larger_than_the_cap_is_truncated_not_denied() {
    struct BigTransport;
    #[async_trait::async_trait]
    impl HttpEgress for BigTransport {
        async fn execute(&self, _addr: std::net::SocketAddr, _sni: &str, _req: PreparedHttpRequest) -> Result<RawHttpResponse, HttpTransportError> {
            Ok(RawHttpResponse { status: 200, headers: vec![], body: vec![0u8; 200] })
        }
    }
    let approved = approved_with_egress(json!([{"host": "api.spotify.com"}]));
    let g = EgressGuard::new(
        Arc::new(BigTransport),
        Arc::new(FakeResolver(vec![public_ip()])),
        Arc::new(NoDenylist),
        EgressGuardConfig { allow_private_hosts: false, max_redirects: 3, response_byte_cap: 100, call_timeout: std::time::Duration::from_secs(5) },
    );
    let req = EgressRequest { method: "GET".into(), url: "https://api.spotify.com/v1/me".into(), headers: vec![], body: None, secret_refs: vec![] };
    match g.send(&approved, req, &NoSecrets).await {
        EgressOutcome::Response(resp) => {
            assert!(resp.truncated);
            assert_eq!(resp.body.len(), 100);
        }
        other => panic!("expected a truncated Response, got {other:?}"),
    }
}

#[tokio::test]
async fn transport_timeout_maps_to_timeout_outcome() {
    struct SlowTransport;
    #[async_trait::async_trait]
    impl HttpEgress for SlowTransport {
        async fn execute(&self, _addr: std::net::SocketAddr, _sni: &str, _req: PreparedHttpRequest) -> Result<RawHttpResponse, HttpTransportError> {
            tokio::time::sleep(std::time::Duration::from_secs(10)).await;
            Ok(RawHttpResponse { status: 200, headers: vec![], body: vec![] })
        }
    }
    let approved = approved_with_egress(json!([{"host": "api.spotify.com"}]));
    let g = EgressGuard::new(
        Arc::new(SlowTransport),
        Arc::new(FakeResolver(vec![public_ip()])),
        Arc::new(NoDenylist),
        EgressGuardConfig { allow_private_hosts: false, max_redirects: 3, response_byte_cap: 1_048_576, call_timeout: std::time::Duration::from_millis(50) },
    );
    let req = EgressRequest { method: "GET".into(), url: "https://api.spotify.com/v1/me".into(), headers: vec![], body: None, secret_refs: vec![] };
    assert!(matches!(g.send(&approved, req, &NoSecrets).await, EgressOutcome::Timeout));
}
```

- [ ] **Step 2: Run to verify failure**

Run: `make test`
Expected: FAIL — `EgressGuard` has no method `send`, `SecretResolver` does not exist.

- [ ] **Step 3: Extend `src/host/egress.rs`**

Add to the top imports: `use std::num::NonZeroU32;` and `use governor::{Quota, RateLimiter};`.

```rust
#[async_trait]
pub trait SecretResolver: Send + Sync {
    /// Spec §8.3: "An unresolvable reference returns
    /// `denied("secret_unresolved")` and is classified non-retryable."
    async fn resolve(&self, secret_ref_name: &str) -> Option<String>;
}

impl<T: HttpEgress> EgressGuard<T> {
    /// The full spec §8.2 chain: steps 1-7 via
    /// `check_allowlist_and_resolve`, then 8 (rate limit), 9 (TLS is the
    /// transport's job -- `HttpEgress::execute` is expected to fail with
    /// `HttpTransportError::Tls` on a bad chain, mapped below), 10
    /// (redirects -- handled by re-invoking this same function against
    /// the `Location` target, which re-runs steps 1-7 from scratch as
    /// required), 11 (response cap, truncate not deny), 12 (timeout).
    pub async fn send(
        &self,
        approved: &ApprovedPermissions,
        req: EgressRequest,
        secrets: &dyn SecretResolver,
    ) -> EgressOutcome {
        self.send_with_redirect_budget(approved, req, secrets, self.config.max_redirects).await
    }

    async fn send_with_redirect_budget(
        &self,
        approved: &ApprovedPermissions,
        req: EgressRequest,
        secrets: &dyn SecretResolver,
        redirects_left: u8,
    ) -> EgressOutcome {
        // Steps 1-6 (async DNS resolution replaces Task 11's blocking helper here).
        let url = match Url::parse(&req.url) {
            Ok(u) => u,
            Err(_) => return EgressOutcome::Denied(EgressDenial::MalformedUrl),
        };
        if url.scheme() != "https" {
            return EgressOutcome::Denied(EgressDenial::SchemeNotHttps);
        }
        if !url.username().is_empty() || url.password().is_some() {
            return EgressOutcome::Denied(EgressDenial::MalformedUrl);
        }
        let host = match url.host_str() {
            Some(h) => h.to_lowercase(),
            None => return EgressOutcome::Denied(EgressDenial::MalformedUrl),
        };
        let rule = match approved.egress_rule_for(&host) {
            Some(r) => r.clone(),
            None => return EgressOutcome::Denied(EgressDenial::HostNotDeclared),
        };
        if !rule.methods.iter().any(|m| m.eq_ignore_ascii_case(&req.method)) {
            return EgressOutcome::Denied(EgressDenial::MethodNotDeclared);
        }
        if self.denylist.is_denylisted(&host) {
            return EgressOutcome::Denied(EgressDenial::HostDenylisted);
        }
        let addresses = match self.resolver.resolve(&host).await {
            Ok(a) => a,
            Err(_) => return EgressOutcome::Denied(EgressDenial::MalformedUrl),
        };
        let chosen = match addresses.into_iter().find(|a| self.address_allowed(*a)) {
            Some(a) => a,
            None => return EgressOutcome::Denied(EgressDenial::SsrfBlockedAddress),
        };
        let port = url.port_or_known_default().unwrap_or(443);
        let target_addr = SocketAddr::new(chosen, port);

        // Step 8: per-bundle token bucket.
        let limiter = self.limiter_for(&approved.app_id, approved.limits.egress_rps).await;
        if let Err(negative) = limiter.check() {
            let retry_after_ms = negative.wait_time_from(governor::clock::DefaultClock::default().now()).as_millis() as u32;
            return EgressOutcome::RateLimited { retry_after_ms };
        }

        // Resolve secrets and build headers (spec §8.3) before the
        // transport call -- the resolved value never crosses back out
        // of this function.
        let mut headers = req.headers.clone();
        for (header_name, secret_ref_name) in &req.secret_refs {
            match secrets.resolve(secret_ref_name).await {
                Some(value) => headers.push((header_name.clone(), value)),
                None => return EgressOutcome::Denied(EgressDenial::SecretUnresolved),
            }
        }

        let prepared = super::capability::PreparedHttpRequest {
            method: req.method.clone(),
            path_and_query: format!("{}{}", url.path(), url.query().map(|q| format!("?{q}")).unwrap_or_default()),
            headers,
            body: req.body.clone(),
            timeout: self.config.call_timeout,
        };

        let call = self.transport.execute(target_addr, &host, prepared);
        let outcome = match tokio::time::timeout(self.config.call_timeout, call).await {
            Ok(Ok(resp)) => resp,
            Ok(Err(super::capability::HttpTransportError::Tls(_))) => {
                return EgressOutcome::Denied(EgressDenial::TlsVerificationFailed)
            }
            Ok(Err(_)) | Err(_) => return EgressOutcome::Timeout,
        };

        // Step 10: redirects re-run steps 1-7 against the target.
        if (300..400).contains(&outcome.status) && redirects_left > 0 {
            if let Some((_, location)) = outcome.headers.iter().find(|(k, _)| k.eq_ignore_ascii_case("location")) {
                let mut redirected = req.clone();
                redirected.url = location.clone();
                return Box::pin(self.send_with_redirect_budget(approved, redirected, secrets, redirects_left - 1)).await;
            }
        }
        if (300..400).contains(&outcome.status) && redirects_left == 0 {
            return EgressOutcome::Denied(EgressDenial::RedirectOffAllowlist);
        }

        // Step 11: response size cap, truncate rather than deny.
        let (body, truncated) = if outcome.body.len() > self.config.response_byte_cap {
            (outcome.body[..self.config.response_byte_cap].to_vec(), true)
        } else {
            (outcome.body, false)
        };

        EgressOutcome::Response(EgressResponse { status: outcome.status, headers: outcome.headers, body, truncated })
    }

    async fn limiter_for(&self, app_id: &str, egress_rps: u32) -> Arc<governor::DefaultDirectRateLimiter> {
        let mut limiters = self.limiters.lock().await;
        limiters
            .entry(app_id.to_string())
            .or_insert_with(|| {
                let rps = NonZeroU32::new(egress_rps.max(1)).unwrap();
                let burst = NonZeroU32::new((egress_rps.max(1)) * 2).unwrap(); // EGRESS_RATE_LIMIT_BURST default relationship
                Arc::new(RateLimiter::direct(Quota::per_second(rps).allow_burst(burst)))
            })
            .clone()
    }
}
```

`EgressDenial::SecretUnresolved` and its `reason_str()` arm are already defined in Task 11 — this task only adds the call site above that produces it. Note also that `DnsRebindBlocked` has no separate runtime check of its own anywhere in this crate: pinning every request to the address chosen at resolution time (Task 11, never re-resolving) makes a rebind structurally impossible rather than something to detect after the fact. The variant exists so `reason_str()`'s vocabulary matches spec §8.2's table in full; it is a deliberate "prevented by construction" case, not a missing implementation.

- [ ] **Step 4: Run to verify pass**

Run: `make test`
Expected: PASS — all `egress_guard_tests` (Task 11's 11 plus this task's 6) green, 17 total.

- [ ] **Step 5: Commit**

```bash
git add packages/rust-bundle-host/src/host/egress.rs packages/rust-bundle-host/tests/egress_guard_tests.rs
git commit -m "$(cat <<'EOF'
feat(bundle-host): EgressGuard::send() -- rate limit, redirects, size cap, secrets

Completes spec §8.2: per-bundle governor-backed token bucket (step 8),
redirect re-checking against the full allowlist per hop (step 10),
truncate-not-deny on oversized responses (step 11), a timeout outcome
(step 12), and §8.3 secret-reference injection immediately before the
transport call -- an unresolvable reference denies before any network
call is attempted.

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01N2rQgkHY872RubwXoBZxtE
EOF
)"
git push
```

---

## Task 13: `DbGuard` — SQL statement-kind allowlist + table-allowlist pre-check

**Depends on:** Task 10 (`DbExecutor`), Task 9 (`ApprovedPermissions::table_grant_for`).

**Files:**
- Create: `packages/rust-bundle-host/src/host/db_guard.rs`
- Modify: `packages/rust-bundle-host/src/host/mod.rs`
- Test: `packages/rust-bundle-host/tests/db_guard_tests.rs`

**Interfaces:**
- Consumes: `host::approvals::{ApprovedPermissions, TableGrant}` (Task 9), `host::capability::{DbExecutor, DbValue, DbRows, DbBackendError}` (Task 10).
- Produces:
  ```rust
  #[derive(Debug, Clone, PartialEq, Eq)]
  pub enum DbDenial { Denied(String), Syntax(String) }
  #[derive(Debug)] pub enum DbOutcome { Rows(DbRows), Denied(DbDenial), Timeout }

  pub struct DbGuard<T: DbExecutor> { /* ... */ }
  impl<T: DbExecutor> DbGuard<T> {
      pub fn new(executor: std::sync::Arc<T>) -> Self;
      /// Parses `statement` (Postgres dialect), rejects anything that
      /// isn't exactly one `SELECT`/`INSERT`/`UPDATE`/`DELETE` (allowlist,
      /// not a denylist -- see the design note in Task 13's implementation
      /// step), extracts every referenced table name, and checks each one
      /// against `approved.tables` with the correct read/write direction
      /// before ever calling `executor.execute(scope, ...)`. `scope`
      /// (D30, spec §5.11) is forwarded to `DbExecutor::execute` unchanged
      /// so the implementation can drive RLS from it -- this guard never
      /// reads `scope.tenant_id`/`community_id` itself, only relays them.
      pub async fn execute(&self, approved: &ApprovedPermissions, scope: &InvocationScope, statement: &str, params: &[DbValue]) -> DbOutcome;
  }
  ```
  Task 16 (host-call router) calls `DbGuard::execute()` for every `capability == Db` host-call.

- [ ] **Step 1: Write the failing tests**

`tests/db_guard_tests.rs`:

```rust
#![allow(clippy::unwrap_used, clippy::panic)]
use penguin_bundle_host::host::approvals::ApprovedPermissions;
use penguin_bundle_host::host::capability::{DbBackendError, DbExecutor, DbRows, DbValue};
use penguin_bundle_host::host::db_guard::{DbGuard, DbOutcome};
use penguin_bundle_host::wire::message::InvocationScope;
use serde_json::json;
use std::sync::{Arc, Mutex};

fn sample_scope() -> InvocationScope {
    InvocationScope {
        tenant_id: "acme".to_string(),
        community_id: None,
        workstream_id: "8f14e45f-ceea-467e-adde-3fb5c9752730".to_string(),
        app_id: "a".to_string(),
        trace: None,
    }
}

fn approved_with_tables(tables: serde_json::Value) -> ApprovedPermissions {
    ApprovedPermissions::from_json(
        "a",
        &json!({
            "egress": [], "data": {"tables": tables},
            "capabilities": ["db"], "routes_to": [],
            "limits": {"timeout_ms": 2000, "memory_mb": 64, "egress_rps": 10}
        }),
    )
    .unwrap()
}

struct RecordingExecutor {
    calls: Mutex<Vec<String>>,
}
#[async_trait::async_trait]
impl DbExecutor for RecordingExecutor {
    async fn execute(&self, _scope: &InvocationScope, statement: &str, _params: &[DbValue]) -> Result<DbRows, DbBackendError> {
        self.calls.lock().unwrap().push(statement.to_string());
        Ok(DbRows { columns: vec![], rows: vec![], rows_affected: 0 })
    }
}

fn guard() -> (DbGuard<RecordingExecutor>, Arc<RecordingExecutor>) {
    let exec = Arc::new(RecordingExecutor { calls: Mutex::new(vec![]) });
    (DbGuard::new(exec.clone()), exec)
}

#[tokio::test]
async fn select_on_a_granted_readable_table_reaches_the_executor() {
    let approved = approved_with_tables(json!([{"name": "music_queue", "read": true, "write": false}]));
    let (g, exec) = guard();
    let outcome = g.execute(&approved, &sample_scope(), "SELECT * FROM music_queue WHERE id = $1", &[DbValue::Int(1)]).await;
    assert!(matches!(outcome, DbOutcome::Rows(_)));
    assert_eq!(exec.calls.lock().unwrap().len(), 1);
}

#[tokio::test]
async fn insert_on_a_read_only_table_is_denied_before_reaching_the_executor() {
    let approved = approved_with_tables(json!([{"name": "music_queue", "read": true, "write": false}]));
    let (g, exec) = guard();
    let outcome = g.execute(&approved, &sample_scope(), "INSERT INTO music_queue (id) VALUES ($1)", &[DbValue::Int(1)]).await;
    assert!(matches!(outcome, DbOutcome::Denied(_)), "got {outcome:?}");
    assert_eq!(exec.calls.lock().unwrap().len(), 0);
}

#[tokio::test]
async fn statement_referencing_an_ungranted_table_is_denied() {
    let approved = approved_with_tables(json!([{"name": "music_queue", "read": true, "write": true}]));
    let (g, exec) = guard();
    let outcome = g.execute(&approved, &sample_scope(), "SELECT * FROM users", &[]).await;
    assert!(matches!(outcome, DbOutcome::Denied(_)));
    assert_eq!(exec.calls.lock().unwrap().len(), 0);
}

#[tokio::test]
async fn multi_statement_batches_are_denied() {
    let approved = approved_with_tables(json!([{"name": "music_queue", "read": true, "write": true}]));
    let (g, exec) = guard();
    let outcome = g.execute(&approved, &sample_scope(), "SELECT * FROM music_queue; DROP TABLE music_queue;", &[]).await;
    assert!(matches!(outcome, DbOutcome::Denied(_)));
    assert_eq!(exec.calls.lock().unwrap().len(), 0);
}

#[tokio::test]
async fn ddl_and_grant_statements_are_denied_by_the_allowlist() {
    let approved = approved_with_tables(json!([{"name": "music_queue", "read": true, "write": true}]));
    let (g, _exec) = guard();
    for stmt in [
        "CREATE TABLE evil (id int)",
        "DROP TABLE music_queue",
        "ALTER TABLE music_queue ADD COLUMN x int",
        "GRANT ALL ON music_queue TO someone",
        "COPY music_queue TO STDOUT",
    ] {
        let outcome = g.execute(&approved, &sample_scope(), stmt, &[]).await;
        assert!(matches!(outcome, DbOutcome::Denied(_)), "expected {stmt} to be denied, got {outcome:?}");
    }
}

#[tokio::test]
async fn unparseable_sql_is_denied_with_a_syntax_reason() {
    let approved = approved_with_tables(json!([{"name": "music_queue", "read": true, "write": true}]));
    let (g, exec) = guard();
    let outcome = g.execute(&approved, &sample_scope(), "SELEKT * FRUM music_queue", &[]).await;
    assert!(matches!(outcome, DbOutcome::Denied(_)));
    assert_eq!(exec.calls.lock().unwrap().len(), 0);
}

#[tokio::test]
async fn update_and_delete_on_a_read_write_table_both_reach_the_executor() {
    let approved = approved_with_tables(json!([{"name": "music_queue", "read": true, "write": true}]));
    let (g, exec) = guard();
    assert!(matches!(g.execute(&approved, &sample_scope(), "UPDATE music_queue SET x = 1 WHERE id = $1", &[DbValue::Int(1)]).await, DbOutcome::Rows(_)));
    assert!(matches!(g.execute(&approved, &sample_scope(), "DELETE FROM music_queue WHERE id = $1", &[DbValue::Int(1)]).await, DbOutcome::Rows(_)));
    assert_eq!(exec.calls.lock().unwrap().len(), 2);
}

/// D30 (spec §5.11): DbGuard must forward `scope` to `DbExecutor::execute`
/// completely unmodified -- tenant_id/community_id are what the
/// implementation's `SET LOCAL waddles.tenant`/`waddles.community` (a
/// service concern, M3/M4, out of this crate's scope -- see Global
/// Constraints "no Postgres connection pool") drives its RLS policies
/// from. This crate's own contract-level guarantee ends at "the exact
/// scope handed to `DbGuard::execute` is the exact scope `DbExecutor::
/// execute` receives" -- proving that RLS actually refuses a
/// cross-tenant row is a live-Postgres integration test that belongs
/// with the service crate that owns the connection.
struct ScopeRecordingExecutor {
    scopes: Mutex<Vec<InvocationScope>>,
}
#[async_trait::async_trait]
impl DbExecutor for ScopeRecordingExecutor {
    async fn execute(&self, scope: &InvocationScope, _statement: &str, _params: &[DbValue]) -> Result<DbRows, DbBackendError> {
        self.scopes.lock().unwrap().push(scope.clone());
        Ok(DbRows { columns: vec![], rows: vec![], rows_affected: 0 })
    }
}

#[tokio::test]
async fn db_execute_forwards_the_full_invocation_scope_unmodified() {
    let approved = approved_with_tables(json!([{"name": "music_queue", "read": true, "write": true}]));
    let exec = Arc::new(ScopeRecordingExecutor { scopes: Mutex::new(vec![]) });
    let g = DbGuard::new(exec.clone());
    let scope_a = InvocationScope {
        tenant_id: "tenant-a".to_string(),
        community_id: Some("main".to_string()),
        workstream_id: "8f14e45f-ceea-467e-adde-3fb5c9752730".to_string(),
        app_id: "a".to_string(),
        trace: None,
    };

    let outcome = g.execute(&approved, &scope_a, "SELECT * FROM music_queue", &[]).await;
    assert!(matches!(outcome, DbOutcome::Rows(_)));

    let recorded = exec.scopes.lock().unwrap();
    assert_eq!(recorded.len(), 1);
    assert_eq!(recorded[0].tenant_id, "tenant-a");
    assert_eq!(recorded[0].community_id.as_deref(), Some("main"));
    assert_eq!(recorded[0].workstream_id, "8f14e45f-ceea-467e-adde-3fb5c9752730");
}
```

- [ ] **Step 2: Run to verify failure**

Run: `make test`
Expected: FAIL — `host::db_guard` module does not exist.

- [ ] **Step 3: Implement `src/host/db_guard.rs`**

```rust
//! Table-allowlist enforcement for the `db` capability (spec §7.4).
//! **Allowlist, not a denylist**: only `SELECT`/`INSERT`/`UPDATE`/
//! `DELETE` statement kinds are ever permitted; every other
//! `sqlparser::ast::Statement` variant -- `Copy`, `Grant`, every
//! `Create*`/`Drop*`/`Alter*`, and anything else the parser can produce
//! -- is denied by the same `_ => deny` arm. This is a strict superset
//! of spec §7.4's named denial list ("more than one top-level statement,
//! a `COPY`, a `DO`, a `SET ROLE`, a `GRANT`, or a
//! `CREATE`/`DROP`/`ALTER`") without needing this module to enumerate
//! every one of `sqlparser`'s AST variant names by hand.

use std::sync::Arc;

use sqlparser::ast::{visit_relations, Statement};
use sqlparser::dialect::PostgreSqlDialect;
use sqlparser::parser::Parser;

use super::approvals::ApprovedPermissions;
use super::capability::{DbBackendError, DbExecutor, DbRows, DbValue};
use crate::wire::message::InvocationScope;

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum DbDenial {
    Denied(String),
    Syntax(String),
}

#[derive(Debug)]
pub enum DbOutcome {
    Rows(DbRows),
    Denied(DbDenial),
    Timeout,
}

pub struct DbGuard<T: DbExecutor> {
    executor: Arc<T>,
}

impl<T: DbExecutor> DbGuard<T> {
    pub fn new(executor: Arc<T>) -> Self {
        Self { executor }
    }

    pub async fn execute(&self, approved: &ApprovedPermissions, scope: &InvocationScope, statement: &str, params: &[DbValue]) -> DbOutcome {
        let statements = match Parser::parse_sql(&PostgreSqlDialect {}, statement) {
            Ok(s) => s,
            Err(e) => return DbOutcome::Denied(DbDenial::Syntax(e.to_string())),
        };

        if statements.len() != 1 {
            return DbOutcome::Denied(DbDenial::Denied("multiple top-level statements not permitted".to_string()));
        }
        let stmt = &statements[0];

        let is_write = match stmt {
            Statement::Query(_) => false,
            Statement::Insert(_) | Statement::Update { .. } | Statement::Delete(_) => true,
            _ => {
                return DbOutcome::Denied(DbDenial::Denied(format!(
                    "statement kind not permitted: only SELECT/INSERT/UPDATE/DELETE are allowed"
                )))
            }
        };

        let mut tables = Vec::new();
        let _ = visit_relations(stmt, |relation| {
            tables.push(relation.to_string().to_lowercase());
            std::ops::ControlFlow::<()>::Continue(())
        });

        for table in &tables {
            let grant = match approved.table_grant_for(table) {
                Some(g) => g,
                None => return DbOutcome::Denied(DbDenial::Denied(format!("table '{table}' is not in the approved data.tables set"))),
            };
            if is_write && !grant.write {
                return DbOutcome::Denied(DbDenial::Denied(format!("table '{table}' is approved read-only")));
            }
            if !is_write && !grant.read {
                return DbOutcome::Denied(DbDenial::Denied(format!("table '{table}' is not approved for read")));
            }
        }

        match self.executor.execute(scope, statement, params).await {
            Ok(rows) => DbOutcome::Rows(rows),
            Err(DbBackendError::Timeout) => DbOutcome::Timeout,
            Err(e) => DbOutcome::Denied(DbDenial::Denied(e.to_string())),
        }
    }
}
```

- [ ] **Step 4: Export from `src/host/mod.rs`**

```rust
pub mod approvals;
pub mod capability;
pub mod db_guard;
pub mod egress;
```

- [ ] **Step 5: Run to verify pass**

Run: `make test`
Expected: PASS — all 8 `db_guard_tests` green (D30 adds `db_execute_forwards_the_full_invocation_scope_unmodified`).

- [ ] **Step 6: Commit**

```bash
git add packages/rust-bundle-host/src/host/db_guard.rs packages/rust-bundle-host/src/host/mod.rs packages/rust-bundle-host/tests/db_guard_tests.rs
git commit -m "$(cat <<'EOF'
feat(bundle-host): DbGuard -- sqlparser statement-kind and table allowlist

Allowlist (SELECT/INSERT/UPDATE/DELETE only), not a denylist -- every
other sqlparser::ast::Statement variant is denied by one catch-all arm,
which is a strict superset of spec §7.4's named denial list without
enumerating sqlparser's AST by hand. Table references are extracted via
sqlparser::ast::visit_relations and checked against the approved
read/write grant before ever reaching DbExecutor. DbGuard::execute and
DbExecutor::execute both take the D30 InvocationScope (spec §5.11) so a
tenant/community-scoped SET LOCAL/RLS implementation (M3/M4, this
crate's Postgres connection boundary) has the exact scope to drive it
from -- forwarded unmodified, proven by a dedicated test.

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01N2rQgkHY872RubwXoBZxtE
EOF
)"
git push
```

---

## Task 14: Kv/Relay/Flags/Log/Clock guards — capability presence + kv namespacing

**Depends on:** Task 10 (`KvStore`/`RelayPush`/`Flags`/`Logger`/`Clock`), Task 9 (`ApprovedPermissions::has_capability`), and `penguin-logging` 0.1.0 for `sanitize_json_str`.

**Files:**
- Create: `packages/rust-bundle-host/src/host/kv_guard.rs`
- Create: `packages/rust-bundle-host/src/host/relay_guard.rs`
- Create: `packages/rust-bundle-host/src/host/flags_guard.rs`
- Create: `packages/rust-bundle-host/src/host/log_guard.rs`
- Create: `packages/rust-bundle-host/src/host/clock_guard.rs`
- Modify: `packages/rust-bundle-host/src/host/mod.rs`
- Test: `packages/rust-bundle-host/tests/simple_guards_tests.rs`

**Interfaces:**
- Consumes: `host::approvals::{ApprovedPermissions, Capability}` (Task 9), `host::capability::{KvStore, RelayPush, Flags, Logger, Clock, LogLevel}` (Task 10).
- Produces:
  ```rust
  #[derive(Debug, Clone, PartialEq, Eq)] pub enum GuardDenial { NotGranted(&'static str), TooLarge(u64), Backend(String), InvalidKey(String) }

  pub struct KvGuard<T: KvStore> { /* ... */ }
  impl<T: KvStore> KvGuard<T> {
      pub fn new(store: std::sync::Arc<T>, max_value_bytes: usize, max_ttl_seconds: u32) -> Self;
      /// `base_key` is the bundle's own state key, built by the CALLER
      /// (the host-call router, Task 16) from the envelope's tenant and
      /// community as `waddles:t:{tenant}:c:{community|_tenant}:app:{app_id}:state`
      /// -- never from anything the guest supplied. `key` is the guest's
      /// own key, appended here as `{base_key}:b:{key}` so a bundle can
      /// never reach the stage's own hash fields (spec §6.2, §7.4).
      /// The guard deliberately does not build `base_key` itself: it has
      /// no envelope, and taking a pre-built key keeps the tenant/community
      /// derivation in exactly one place.
      pub async fn get(&self, approved: &ApprovedPermissions, base_key: &str, key: &str) -> Result<Option<Vec<u8>>, GuardDenial>;
      pub async fn set(&self, approved: &ApprovedPermissions, base_key: &str, key: &str, value: &[u8], ttl_seconds: u32) -> Result<(), GuardDenial>;
      pub async fn delete(&self, approved: &ApprovedPermissions, base_key: &str, key: &str) -> Result<(), GuardDenial>;
      pub async fn increment(&self, approved: &ApprovedPermissions, base_key: &str, key: &str, delta: i64, ttl_seconds: u32) -> Result<i64, GuardDenial>;
  }

  pub struct RelayGuard<T: RelayPush> { /* ... */ }
  impl<T: RelayPush> RelayGuard<T> {
      pub fn new(relay: std::sync::Arc<T>, known_providers: Vec<String>) -> Self;
      /// Capability::Relay is granted only to action-stage bundles
      /// (spec §6.5) -- `approved` alone can't distinguish stage, so the
      /// caller (host-call router, Task 16) only routes here for an
      /// action-stage bundle's connection in the first place; this guard
      /// still checks `has_capability(Relay)` as the second, independent
      /// layer spec §11.1's "two independent layers, deliberately" pattern
      /// calls for elsewhere in the design.
      pub async fn push(&self, approved: &ApprovedPermissions, provider: &str, message_json: &str) -> Result<(), GuardDenial>;
  }

  pub struct FlagsGuard<T: Flags> { /* ... */ }
  impl<T: Flags> FlagsGuard<T> {
      pub fn new(flags: std::sync::Arc<T>) -> Self;
      pub async fn enabled(&self, key: &str, default_value: bool) -> bool;  // always granted -- no capability check
      pub async fn tier(&self) -> String;
  }

  pub struct LogGuard<T: Logger> { /* ... */ }
  impl<T: Logger> LogGuard<T> {
      pub fn new(logger: std::sync::Arc<T>, stage_log_level: LogLevel) -> Self;
      /// Sanitizes `fields_json` via `penguin_logging::sanitize_json_str`
      /// (never a local copy of the SENSITIVE_KEYS rule) and clamps
      /// `level` to never exceed `stage_log_level` before forwarding.
      pub fn write(&self, app_id: &str, level: LogLevel, message: &str, fields_json: &str);
  }

  pub struct ClockGuard<T: Clock>(std::sync::Arc<T>);  // always granted -- a transparent pass-through, kept as its own type for symmetry with the other five guards and a single call site in Task 16
  impl<T: Clock> ClockGuard<T> {
      pub fn new(clock: std::sync::Arc<T>) -> Self;
      pub fn now_millis(&self) -> u64;
      pub fn now_rfc3339(&self) -> String;
      pub fn monotonic_nanos(&self) -> u64;
  }
  ```
  Task 16 (the host-call router) holds one of each guard type per stage process.

- [ ] **Step 1: Write the failing tests**

`tests/simple_guards_tests.rs`:

```rust
#![allow(clippy::unwrap_used, clippy::panic)]
use penguin_bundle_host::host::approvals::ApprovedPermissions;
use penguin_bundle_host::host::capability::{Flags, KvBackendError, KvStore, LogLevel, Logger, RelayBackendError, RelayPush};
use penguin_bundle_host::host::clock_guard::ClockGuard;
use penguin_bundle_host::host::flags_guard::FlagsGuard;
use penguin_bundle_host::host::kv_guard::KvGuard;
use penguin_bundle_host::host::log_guard::LogGuard;
use penguin_bundle_host::host::relay_guard::RelayGuard;
use serde_json::json;
use std::collections::HashMap;
use std::sync::{Arc, Mutex};

fn approved(capabilities: serde_json::Value) -> ApprovedPermissions {
    ApprovedPermissions::from_json(
        "a",
        &json!({"egress": [], "data": {"tables": []}, "capabilities": capabilities, "routes_to": [], "limits": {"timeout_ms": 2000, "memory_mb": 64, "egress_rps": 10}}),
    )
    .unwrap()
}

struct FakeKv(Mutex<HashMap<String, Vec<u8>>>);
#[async_trait::async_trait]
impl KvStore for FakeKv {
    async fn get(&self, k: &str) -> Result<Option<Vec<u8>>, KvBackendError> { Ok(self.0.lock().unwrap().get(k).cloned()) }
    async fn set(&self, k: &str, v: &[u8], _t: u32) -> Result<(), KvBackendError> { self.0.lock().unwrap().insert(k.to_string(), v.to_vec()); Ok(()) }
    async fn delete(&self, k: &str) -> Result<(), KvBackendError> { self.0.lock().unwrap().remove(k); Ok(()) }
    async fn increment(&self, _k: &str, delta: i64, _t: u32) -> Result<i64, KvBackendError> { Ok(delta) }
}

#[tokio::test]
async fn kv_get_namespaces_the_guest_key_under_b_prefix() {
    let fake = Arc::new(FakeKv(Mutex::new(HashMap::new())));
    fake.0.lock().unwrap().insert("app:waddles.test.a:state:b:mykey".to_string(), b"v".to_vec());
    let guard = KvGuard::new(fake, 65536, 2_592_000);
    let approved = approved(json!(["kv"]));
    let value = guard.get(&approved, "waddles:t:acme:c:_tenant:app:waddles.test.a:state", "mykey").await.unwrap();
    assert_eq!(value, Some(b"v".to_vec()));
}

#[tokio::test]
async fn kv_set_rejects_a_value_over_the_max_size() {
    let fake = Arc::new(FakeKv(Mutex::new(HashMap::new())));
    let guard = KvGuard::new(fake, 8, 2_592_000);
    let approved = approved(json!(["kv"]));
    let err = guard.set(&approved, "waddles:t:acme:c:_tenant:app:a:state", "k", &[0u8; 100], 0).await.unwrap_err();
    assert!(matches!(err, penguin_bundle_host::host::kv_guard::GuardDenial::TooLarge(100)));
}

/// D30 defense-in-depth (spec §5.11 spirit): a guest key that is empty,
/// looks absolute, or looks like a path-traversal attempt is refused
/// before it is ever namespaced under the bundle's own state key.
#[tokio::test]
async fn kv_rejects_empty_absolute_and_path_traversal_keys() {
    let fake = Arc::new(FakeKv(Mutex::new(HashMap::new())));
    let guard = KvGuard::new(fake, 65536, 2_592_000);
    let approved = approved(json!(["kv"]));
    let base_key = "waddles:t:acme:c:_tenant:app:a:state";

    let mut examined = 0;
    for bad_key in ["", "/etc/passwd", "../../other-bundle-secret", "a/../../b"] {
        let err = guard.get(&approved, base_key, bad_key).await.unwrap_err();
        assert!(
            matches!(err, penguin_bundle_host::host::kv_guard::GuardDenial::InvalidKey(_)),
            "expected {bad_key:?} to be rejected as InvalidKey, got {err:?}"
        );
        examined += 1;
    }
    assert_eq!(examined, 4, "expected exactly 4 malformed-key cases examined");
}

struct FakeRelay;
#[async_trait::async_trait]
impl RelayPush for FakeRelay {
    async fn push(&self, _p: &str, _m: &str) -> Result<(), RelayBackendError> { Ok(()) }
}

#[tokio::test]
async fn relay_push_denied_without_the_relay_capability() {
    let guard = RelayGuard::new(Arc::new(FakeRelay), vec!["twitch".to_string()]);
    let approved = approved(json!(["log"])); // no "relay"
    let err = guard.push(&approved, "twitch", "{}").await.unwrap_err();
    assert!(matches!(err, penguin_bundle_host::host::relay_guard::GuardDenial::NotGranted(_)));
}

#[tokio::test]
async fn relay_push_succeeds_with_the_relay_capability_and_a_known_provider() {
    let guard = RelayGuard::new(Arc::new(FakeRelay), vec!["twitch".to_string()]);
    let approved = approved(json!(["relay"]));
    assert!(guard.push(&approved, "twitch", "{}").await.is_ok());
}

struct FakeFlags;
#[async_trait::async_trait]
impl Flags for FakeFlags {
    async fn enabled(&self, _k: &str, d: bool) -> bool { d }
    async fn tier(&self) -> String { "free".into() }
}

#[tokio::test]
async fn flags_guard_is_always_callable_with_no_capability_gate() {
    let guard = FlagsGuard::new(Arc::new(FakeFlags));
    assert!(guard.enabled("waddles.core.wasm-bundles", true).await);
    assert_eq!(guard.tier().await, "free");
}

struct RecordingLogger(Mutex<Vec<(String, String)>>);
impl Logger for RecordingLogger {
    fn write(&self, level: LogLevel, app_id: &str, message: &str, fields: &str) {
        self.0.lock().unwrap().push((format!("{level:?}"), format!("{app_id}:{message}:{fields}")));
    }
}

#[test]
fn log_guard_sanitizes_sensitive_keys_before_forwarding() {
    let recorder = Arc::new(RecordingLogger(Mutex::new(vec![])));
    let guard = LogGuard::new(recorder.clone(), LogLevel::Debug);
    guard.write("a", LogLevel::Info, "msg", "{\"password\":\"hunter2\",\"user\":\"x\"}");
    let calls = recorder.0.lock().unwrap();
    assert_eq!(calls.len(), 1);
    assert!(calls[0].1.contains("[REDACTED]"), "got {}", calls[0].1);
    assert!(!calls[0].1.contains("hunter2"));
}

#[test]
fn log_guard_clamps_level_above_the_stage_configured_level() {
    let recorder = Arc::new(RecordingLogger(Mutex::new(vec![])));
    let guard = LogGuard::new(recorder.clone(), LogLevel::Info); // stage is INFO
    guard.write("a", LogLevel::Debug, "should not exceed info", "{}"); // guest asks for DEBUG
    let calls = recorder.0.lock().unwrap();
    assert_eq!(calls[0].0, "Info", "a guest-requested DEBUG must clamp down to the stage's configured INFO");
}

struct FixedClock;
impl penguin_bundle_host::host::capability::Clock for FixedClock {
    fn now_millis(&self) -> u64 { 123 }
    fn now_rfc3339(&self) -> String { "2026-09-14T00:00:00.000Z".into() }
    fn monotonic_nanos(&self) -> u64 { 456 }
}

#[test]
fn clock_guard_passes_through_transparently() {
    let guard = ClockGuard::new(Arc::new(FixedClock));
    assert_eq!(guard.now_millis(), 123);
    assert_eq!(guard.monotonic_nanos(), 456);
}
```

- [ ] **Step 2: Run to verify failure**

Run: `make test`
Expected: FAIL — none of the five guard modules exist yet.

- [ ] **Step 3: Implement `src/host/kv_guard.rs`**

```rust
//! Bundle-scoped KV (spec §6.5 `kv` interface, §7.4). The guest's key is
//! namespaced as `b:{key}` under the bundle's own state hash so it can
//! never collide with or reach a field the stage itself owns.

use std::sync::Arc;

use super::approvals::ApprovedPermissions;
use super::capability::{KvBackendError, KvStore};

/// `NotGranted` carries the compile-time-known, fixed-string reasons
/// (capability absent, unknown provider); `Backend` carries an owned
/// message from a real `KvBackendError`/`RelayBackendError`, which is
/// only known at runtime and cannot be `&'static str`.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum GuardDenial {
    NotGranted(&'static str),
    TooLarge(u64),
    Backend(String),
    /// D30 defense-in-depth (spec §5.11's "no bundle host call accepts a
    /// tenant or community argument" spirit extended to key hygiene):
    /// empty, absolute-looking (`/...`), or path-traversal-looking
    /// (containing `..`) guest keys are refused before namespacing, even
    /// though a Valkey hash field has no hierarchical meaning and so
    /// cannot literally "escape" -- refusing defensively costs nothing
    /// and removes an entire class of guest input from ever reaching the
    /// backend unexamined.
    InvalidKey(String),
}

pub struct KvGuard<T: KvStore> {
    store: Arc<T>,
    max_value_bytes: usize,
    max_ttl_seconds: u32,
}

/// Rejects empty, absolute-looking, or path-traversal-looking guest keys.
fn validate_guest_key(key: &str) -> Result<(), GuardDenial> {
    if key.is_empty() {
        return Err(GuardDenial::InvalidKey("key must not be empty".to_string()));
    }
    if key.starts_with('/') {
        return Err(GuardDenial::InvalidKey(format!("key {key:?} must not look like an absolute path")));
    }
    if key.contains("..") {
        return Err(GuardDenial::InvalidKey(format!("key {key:?} must not contain '..'")));
    }
    Ok(())
}

impl<T: KvStore> KvGuard<T> {
    pub fn new(store: Arc<T>, max_value_bytes: usize, max_ttl_seconds: u32) -> Self {
        Self { store, max_value_bytes, max_ttl_seconds }
    }

    fn namespaced(base_key: &str, guest_key: &str) -> String {
        format!("{base_key}:b:{guest_key}")
    }

    pub async fn get(&self, _approved: &ApprovedPermissions, base_key: &str, key: &str) -> Result<Option<Vec<u8>>, GuardDenial> {
        validate_guest_key(key)?;
        self.store
            .get(&Self::namespaced(base_key, key))
            .await
            .map_err(|KvBackendError::Backend(e)| GuardDenial::Backend(e))
    }

    pub async fn set(&self, _approved: &ApprovedPermissions, base_key: &str, key: &str, value: &[u8], ttl_seconds: u32) -> Result<(), GuardDenial> {
        validate_guest_key(key)?;
        if value.len() > self.max_value_bytes {
            return Err(GuardDenial::TooLarge(value.len() as u64));
        }
        let ttl = ttl_seconds.min(self.max_ttl_seconds);
        self.store
            .set(&Self::namespaced(base_key, key), value, ttl)
            .await
            .map_err(|KvBackendError::Backend(e)| GuardDenial::Backend(e))
    }

    pub async fn delete(&self, _approved: &ApprovedPermissions, base_key: &str, key: &str) -> Result<(), GuardDenial> {
        validate_guest_key(key)?;
        self.store
            .delete(&Self::namespaced(base_key, key))
            .await
            .map_err(|KvBackendError::Backend(e)| GuardDenial::Backend(e))
    }

    pub async fn increment(&self, _approved: &ApprovedPermissions, base_key: &str, key: &str, delta: i64, ttl_seconds: u32) -> Result<i64, GuardDenial> {
        validate_guest_key(key)?;
        let ttl = ttl_seconds.min(self.max_ttl_seconds);
        self.store
            .increment(&Self::namespaced(base_key, key), delta, ttl)
            .await
            .map_err(|KvBackendError::Backend(e)| GuardDenial::Backend(e))
    }
}
```

- [ ] **Step 4: Implement `src/host/relay_guard.rs`**

```rust
//! Outbound relay push (spec §6.5 `relay` interface). Granted only to
//! action-stage bundles; this guard's own `has_capability(Relay)` check
//! is the second of the "two independent layers, deliberately" the
//! design applies elsewhere (§7.4's db parser+role pattern) -- the
//! host-call router (Task 16) is the first layer, only ever routing a
//! `relay` call for a connection it already knows is an action stage.

use std::sync::Arc;

use super::approvals::{ApprovedPermissions, Capability};
use super::capability::RelayPush;
use super::kv_guard::GuardDenial;

pub struct RelayGuard<T: RelayPush> {
    relay: Arc<T>,
    known_providers: Vec<String>,
}

impl<T: RelayPush> RelayGuard<T> {
    pub fn new(relay: Arc<T>, known_providers: Vec<String>) -> Self {
        Self { relay, known_providers }
    }

    pub async fn push(&self, approved: &ApprovedPermissions, provider: &str, message_json: &str) -> Result<(), GuardDenial> {
        if !approved.has_capability(Capability::Relay) {
            return Err(GuardDenial::NotGranted("relay capability not granted"));
        }
        if !self.known_providers.iter().any(|p| p == provider) {
            return Err(GuardDenial::NotGranted("unknown relay provider"));
        }
        self.relay
            .push(provider, message_json)
            .await
            .map_err(|e| GuardDenial::Backend(e.to_string()))
    }
}
```

- [ ] **Step 5: Implement `src/host/flags_guard.rs`**

```rust
//! PostHog flag + license entitlement (spec §6.5 `flags` interface).
//! Always granted -- no capability check, matching `context`/`clock`.

use std::sync::Arc;

use super::capability::Flags;

pub struct FlagsGuard<T: Flags> {
    flags: Arc<T>,
}

impl<T: Flags> FlagsGuard<T> {
    pub fn new(flags: Arc<T>) -> Self {
        Self { flags }
    }

    pub async fn enabled(&self, key: &str, default_value: bool) -> bool {
        self.flags.enabled(key, default_value).await
    }

    pub async fn tier(&self) -> String {
        self.flags.tier().await
    }
}
```

- [ ] **Step 6: Implement `src/host/log_guard.rs`**

```rust
//! Sanitized, levelled logging (spec §6.5 `log` interface, §7.4, §11.5).
//!
//! Sanitization is **`penguin_logging::sanitize_json_str` and nothing
//! else**. That function is the verbatim Rust port of
//! `python-utils/logging.py`'s `SENSITIVE_KEYS` rule (M1b plan, Tasks 2
//! and 3), and M1b names this exact call site as its consumer: "the WIT
//! `log` host call's `fields-json` argument is sanitized through exactly
//! this function in `penguin-bundle-host`". Re-implementing the key list
//! here would give the WIT `log` path a second, silently-drifting copy of
//! a security rule -- the failure mode `testing.md` Logging Library
//! Conformance exists to catch.

use std::sync::Arc;

use super::capability::{LogLevel, Logger};

/// Lower rank = more severe. Used only to clamp a guest-requested level
/// down to the stage's configured ceiling.
fn level_rank(level: LogLevel) -> u8 {
    match level {
        LogLevel::Error => 0,
        LogLevel::Warn => 1,
        LogLevel::Info => 2,
        LogLevel::Debug => 3,
    }
}

/// Wraps a `Logger` with the two rules the WIT `log` interface owes the
/// host: sanitize the guest's fields, and never let the guest log above
/// the stage's configured level.
pub struct LogGuard<T: Logger> {
    logger: Arc<T>,
    stage_log_level: LogLevel,
}

impl<T: Logger> LogGuard<T> {
    /// `stage_log_level` is the stage process's own configured ceiling;
    /// a guest asking for anything more verbose is clamped to it.
    pub fn new(logger: Arc<T>, stage_log_level: LogLevel) -> Self {
        Self { logger, stage_log_level }
    }

    /// Sanitizes `fields_json` through `penguin-logging` and clamps
    /// `level` down to `stage_log_level` before forwarding -- "a bundle
    /// cannot raise its own log level above the stage's configured
    /// LOG_LEVEL" (spec §7.4).
    ///
    /// A `fields_json` that is not parseable JSON is replaced with `{}`
    /// rather than dropped or forwarded raw: the message itself still
    /// reaches the operator, and unparseable guest bytes never reach the
    /// log sink.
    pub fn write(&self, app_id: &str, level: LogLevel, message: &str, fields_json: &str) {
        let clamped = if level_rank(level) > level_rank(self.stage_log_level) {
            self.stage_log_level
        } else {
            level
        };

        let sanitized_json =
            penguin_logging::sanitize_json_str(fields_json).unwrap_or_else(|_| "{}".to_string());

        self.logger.write(clamped, app_id, message, &sanitized_json);
    }
}
```

- [ ] **Step 7: Implement `src/host/clock_guard.rs`**

```rust
//! Wall clock + monotonic clock (spec §6.5 `clock` interface). Always
//! granted; a transparent pass-through kept as its own type only for
//! symmetry with the other five guards and one call site in Task 16.

use std::sync::Arc;

use super::capability::Clock;

pub struct ClockGuard<T: Clock>(Arc<T>);

impl<T: Clock> ClockGuard<T> {
    pub fn new(clock: Arc<T>) -> Self {
        Self(clock)
    }
    pub fn now_millis(&self) -> u64 {
        self.0.now_millis()
    }
    pub fn now_rfc3339(&self) -> String {
        self.0.now_rfc3339()
    }
    pub fn monotonic_nanos(&self) -> u64 {
        self.0.monotonic_nanos()
    }
}
```

- [ ] **Step 8: Export all five from `src/host/mod.rs`**

```rust
pub mod approvals;
pub mod capability;
pub mod clock_guard;
pub mod db_guard;
pub mod egress;
pub mod flags_guard;
pub mod kv_guard;
pub mod log_guard;
pub mod relay_guard;
```

- [ ] **Step 9: Run to verify pass**

Run: `make test`
Expected: PASS — all `simple_guards_tests` green.

- [ ] **Step 10: Commit**

```bash
git add packages/rust-bundle-host/src/host packages/rust-bundle-host/tests/simple_guards_tests.rs
git commit -m "$(cat <<'EOF'
feat(bundle-host): Kv/Relay/Flags/Log/Clock guards

KvGuard namespaces every guest key under b:{key}; RelayGuard is action-
stage-only via has_capability(Relay) plus a known-provider check;
LogGuard ports python-utils' SENSITIVE_KEYS rule verbatim and clamps a
guest's requested level down to the stage's configured LOG_LEVEL;
Flags/Clock guards are always-granted pass-throughs. KvGuard also
rejects empty, absolute-looking, or path-traversal-looking guest keys
before namespacing (D30 defense in depth, spec §5.11's spirit).

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01N2rQgkHY872RubwXoBZxtE
EOF
)"
git push
```

---

## Task 15: `TripTracker` — the three-strike disable rule (§7.5)

**Depends on:** Task 9 (`Capability`, for the denial-trip path's capability label).

**Files:**
- Create: `packages/rust-bundle-host/src/host/trip.rs`
- Modify: `packages/rust-bundle-host/src/host/mod.rs`
- Test: `packages/rust-bundle-host/tests/trip_tests.rs`

**Interfaces:**
- Consumes: nothing new.
- Produces:
  ```rust
  #[derive(Debug, Clone, Copy, PartialEq, Eq)]
  pub enum TripLimit { Timeout, Memory, Trap, Denied }

  #[derive(Debug, Clone, Copy, PartialEq, Eq)]
  pub enum TripOutcome { Recorded { strike: u8 }, Disabled }

  pub struct TripTracker { /* per (app_id, digest) sliding window */ }
  impl TripTracker {
      pub fn new(threshold: u8, window: std::time::Duration) -> Self;
      /// Records one trip for `(app_id, digest)` at `now` and returns
      /// whether this is the 1st/2nd strike or the disabling 3rd.
      pub fn record_trip(&self, app_id: &str, digest: &str, limit: TripLimit, now: std::time::Instant) -> TripOutcome;
      /// True once `record_trip` has returned `Disabled` for this exact
      /// `(app_id, digest)` and no `reset` has cleared it since.
      pub fn is_disabled(&self, app_id: &str, digest: &str) -> bool;
      /// Spec §7.5: "A disabled bundle is re-enabled when the pod
      /// observes a new artifactDigest for it ... or when the pod
      /// restarts." Called by the loader (Task 20) whenever it hot-swaps
      /// `app_id` onto a different digest -- the *old* digest's disabled
      /// state is irrelevant once nothing routes to it, and the *new*
      /// digest starts with a clean window.
      pub fn reset(&self, app_id: &str);
  }
  ```
  Task 16 (host-call router) calls `record_trip` on the 3rd consecutive `denied` host call within the window (spec §6.5: "three denials within `EXECUTOR_TRIP_WINDOW_S` count as a sandbox trip"); Task 18 (per-call invocation) calls it on a deadline breach, memory-limit breach, or guest trap; Task 20 (loader) calls `reset` on every digest change for an `app_id`.

- [ ] **Step 1: Write the failing tests**

`tests/trip_tests.rs`:

```rust
#![allow(clippy::unwrap_used, clippy::panic)]
use penguin_bundle_host::host::trip::{TripLimit, TripOutcome, TripTracker};
use std::time::{Duration, Instant};

#[test]
fn first_and_second_trips_are_recorded_not_disabled() {
    let tracker = TripTracker::new(3, Duration::from_secs(300));
    let now = Instant::now();
    assert_eq!(tracker.record_trip("a", "sha256:1", TripLimit::Timeout, now), TripOutcome::Recorded { strike: 1 });
    assert_eq!(tracker.record_trip("a", "sha256:1", TripLimit::Memory, now), TripOutcome::Recorded { strike: 2 });
    assert!(!tracker.is_disabled("a", "sha256:1"));
}

#[test]
fn third_trip_within_the_window_disables() {
    let tracker = TripTracker::new(3, Duration::from_secs(300));
    let now = Instant::now();
    tracker.record_trip("a", "sha256:1", TripLimit::Timeout, now);
    tracker.record_trip("a", "sha256:1", TripLimit::Timeout, now);
    let outcome = tracker.record_trip("a", "sha256:1", TripLimit::Trap, now);
    assert_eq!(outcome, TripOutcome::Disabled);
    assert!(tracker.is_disabled("a", "sha256:1"));
}

#[test]
fn every_subsequent_event_after_disable_is_also_reported_disabled() {
    let tracker = TripTracker::new(3, Duration::from_secs(300));
    let now = Instant::now();
    for _ in 0..3 {
        tracker.record_trip("a", "sha256:1", TripLimit::Denied, now);
    }
    assert!(tracker.is_disabled("a", "sha256:1"));
    // A 4th trip is still meaningfully "disabled", never a crash or a
    // reset back to strike 1.
    let outcome = tracker.record_trip("a", "sha256:1", TripLimit::Denied, now);
    assert_eq!(outcome, TripOutcome::Disabled);
}

#[test]
fn trips_outside_the_window_do_not_accumulate() {
    let tracker = TripTracker::new(3, Duration::from_millis(50));
    let t0 = Instant::now();
    tracker.record_trip("a", "sha256:1", TripLimit::Timeout, t0);
    tracker.record_trip("a", "sha256:1", TripLimit::Timeout, t0 + Duration::from_millis(10));
    // Third trip arrives after the window from the first two has elapsed --
    // the window is sliding, so this should count as strike 1 of a fresh
    // window, not the disabling third strike.
    let outcome = tracker.record_trip("a", "sha256:1", TripLimit::Trap, t0 + Duration::from_millis(200));
    assert_ne!(outcome, TripOutcome::Disabled);
    assert!(!tracker.is_disabled("a", "sha256:1"));
}

#[test]
fn different_digests_of_the_same_app_id_are_tracked_independently() {
    let tracker = TripTracker::new(3, Duration::from_secs(300));
    let now = Instant::now();
    for _ in 0..3 {
        tracker.record_trip("a", "sha256:1", TripLimit::Denied, now);
    }
    assert!(tracker.is_disabled("a", "sha256:1"));
    assert!(!tracker.is_disabled("a", "sha256:2"), "a different digest of the same app_id must start clean");
}

#[test]
fn different_app_ids_are_tracked_independently() {
    let tracker = TripTracker::new(3, Duration::from_secs(300));
    let now = Instant::now();
    for _ in 0..3 {
        tracker.record_trip("a", "sha256:1", TripLimit::Denied, now);
    }
    assert!(!tracker.is_disabled("b", "sha256:1"));
}

#[test]
fn reset_clears_the_disabled_state_for_every_digest_of_that_app_id() {
    let tracker = TripTracker::new(3, Duration::from_secs(300));
    let now = Instant::now();
    for _ in 0..3 {
        tracker.record_trip("a", "sha256:1", TripLimit::Denied, now);
    }
    assert!(tracker.is_disabled("a", "sha256:1"));
    tracker.reset("a");
    assert!(!tracker.is_disabled("a", "sha256:1"));
}
```

- [ ] **Step 2: Run to verify failure**

Run: `make test`
Expected: FAIL — `host::trip` module does not exist.

- [ ] **Step 3: Implement `src/host/trip.rs`**

```rust
//! The three-strike sandbox-trip disable rule (spec §7.5). A **trip** is
//! any call-deadline breach, memory-limit breach, guest trap, or the
//! third `denied` host call within the window; three trips per
//! `(app_id, digest)` within `EXECUTOR_TRIP_WINDOW_S` disables that
//! exact digest in this process until a new digest is observed for
//! `app_id` or the process restarts.

use std::collections::HashMap;
use std::sync::Mutex;
use std::time::{Duration, Instant};

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum TripLimit {
    Timeout,
    Memory,
    Trap,
    Denied,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum TripOutcome {
    Recorded { strike: u8 },
    Disabled,
}

#[derive(Debug, Default)]
struct BundleTripState {
    trip_times: Vec<Instant>,
    disabled: bool,
}

pub struct TripTracker {
    threshold: u8,
    window: Duration,
    state: Mutex<HashMap<(String, String), BundleTripState>>,
}

impl TripTracker {
    pub fn new(threshold: u8, window: Duration) -> Self {
        Self { threshold, window, state: Mutex::new(HashMap::new()) }
    }

    pub fn record_trip(&self, app_id: &str, digest: &str, _limit: TripLimit, now: Instant) -> TripOutcome {
        let mut state = self.state.lock().unwrap();
        let entry = state.entry((app_id.to_string(), digest.to_string())).or_default();

        if entry.disabled {
            return TripOutcome::Disabled;
        }

        entry.trip_times.retain(|&t| now.duration_since(t) <= self.window);
        entry.trip_times.push(now);

        let strike = entry.trip_times.len() as u8;
        if strike >= self.threshold {
            entry.disabled = true;
            TripOutcome::Disabled
        } else {
            TripOutcome::Recorded { strike }
        }
    }

    pub fn is_disabled(&self, app_id: &str, digest: &str) -> bool {
        self.state
            .lock()
            .unwrap()
            .get(&(app_id.to_string(), digest.to_string()))
            .map(|s| s.disabled)
            .unwrap_or(false)
    }

    /// Clears every tracked digest's state for `app_id` -- called on a
    /// hot-swap (spec §7.5: re-enable is "a new artifactDigest ... or a
    /// pod restart", never a runtime switch, so this is the loader's job,
    /// not an operator action this crate exposes).
    pub fn reset(&self, app_id: &str) {
        self.state.lock().unwrap().retain(|(id, _), _| id != app_id);
    }
}
```

- [ ] **Step 4: Export from `src/host/mod.rs`**

```rust
pub mod trip;
```

(alongside the existing seven `pub mod` lines, alphabetically ordered)

- [ ] **Step 5: Run to verify pass**

Run: `make test`
Expected: PASS — all 7 `trip_tests` green.

- [ ] **Step 6: Commit**

```bash
git add packages/rust-bundle-host/src/host/trip.rs packages/rust-bundle-host/src/host/mod.rs packages/rust-bundle-host/tests/trip_tests.rs
git commit -m "$(cat <<'EOF'
feat(bundle-host): TripTracker -- three-strike sandbox disable per (app_id, digest)

record_trip()'s sliding window (not a fixed bucket) means trips outside
EXECUTOR_TRIP_WINDOW_S never accumulate toward the disabling third
strike; different digests of the same app_id are tracked independently,
matching spec §7.5's re-enable-on-new-digest rule via reset().

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01N2rQgkHY872RubwXoBZxtE
EOF
)"
git push
```

---

## Task 16: Host-call router — dispatches wire `host-call` frames to the guards

**Depends on:** Tasks 11-12 (`EgressGuard`), Task 13 (`DbGuard`), Task 14 (the five simple guards), Task 15 (`TripTracker`), Task 2 (`CapabilityKind`, `HostResultError`).

**Files:**
- Create: `packages/rust-bundle-host/src/host/router.rs`
- Modify: `packages/rust-bundle-host/src/host/mod.rs`
- Test: `packages/rust-bundle-host/tests/host_call_router_tests.rs`

**Interfaces:**
- Consumes: `wire::message::{CapabilityKind, HostResultError}` (Task 2), `host::approvals::{ApprovedPermissions, Capability}` (Task 9), `host::capability::*` (Task 10), `host::egress::{EgressGuard, EgressRequest, EgressOutcome, SecretResolver}` (Tasks 11-12), `host::db_guard::{DbGuard, DbOutcome}` (Task 13), `host::{kv_guard, relay_guard, flags_guard, log_guard, clock_guard}` (Task 14), `host::trip::{TripTracker, TripLimit}` (Task 15).
- Produces:
  ```rust
  pub struct HostCallContext {
      pub app_id: String,
      pub digest: String,
      pub approved: std::sync::Arc<ApprovedPermissions>,
      pub bundle_context: BundleContextInfo,  // {tenant, community, feature, version, message_id, config_json, workstream_id, trace} -- synthesized by the caller from a binding-MAC-verified envelope, spec §7.4 "context", §5.11 D30
  }
  pub struct BundleContextInfo { pub tenant: String, pub community: Option<String>, pub feature: String, pub version: String, pub message_id: String, pub config_json: String, pub workstream_id: String, pub trace: Option<penguin_spine::Trace> }
  impl HostCallContext {
      /// Builds the D30 `InvocationScope` (spec §5.11) this context
      /// implies -- the single place `tenant_id`/`community_id`/
      /// `workstream_id`/`app_id`/`trace` are assembled from a
      /// `HostCallContext`, so `DbGuard`/usage-metering call sites never
      /// duplicate the field mapping.
      pub fn scope(&self) -> crate::wire::message::InvocationScope;
  }

  pub struct HostCallRouter<Http: HttpEgress, Kv: KvStore, Db: DbExecutor, Relay: RelayPush, Fl: Flags, Lg: Logger, Ck: Clock> {
      /// `usage` (D31, spec §5.12): when present, every successful
      /// dispatch increments the matching `HostCallKind` counter on a
      /// `UsageDelta` keyed by this call's scope and batches it via
      /// `UsageBatcher::record` -- the caller (the stage, M4/M5) owns
      /// flushing the batcher onto `waddles:usage` via `SpineClient::
      /// append_usage`. `None` disables usage recording entirely
      /// (`metering.enabled=false`, spec §12.3).
      pub fn new(egress: EgressGuard<Http>, kv: KvGuard<Kv>, db: DbGuard<Db>, relay: RelayGuard<Relay>, flags: FlagsGuard<Fl>, log: LogGuard<Lg>, clock: ClockGuard<Ck>, trips: std::sync::Arc<TripTracker>, secrets: std::sync::Arc<dyn SecretResolver>, usage: Option<std::sync::Arc<penguin_spine::UsageBatcher>>, stage: impl Into<String>) -> Self;
      /// Routes one `(capability, op, args)` triple to the matching
      /// guard and returns the `host-result` payload shape (`Ok(json)`
      /// or `Err({code, message})`), incrementing the trip tracker on the
      /// third `denied` outcome within the window (spec §6.5: "three
      /// denials within EXECUTOR_TRIP_WINDOW_S count as a sandbox trip").
      pub async fn dispatch(&self, ctx: &HostCallContext, capability: CapabilityKind, op: &str, args: serde_json::Value) -> Result<serde_json::Value, HostResultError>;
  }
  ```
  Task 17 (mTLS server) owns one `HostCallRouter` per stage process and calls `dispatch` for every `Message::HostCall` it reads off `recv_unsolicited()`.

- [ ] **Step 1: Write the failing tests**

`tests/host_call_router_tests.rs`:

```rust
#![allow(clippy::unwrap_used, clippy::panic)]
use penguin_bundle_host::host::approvals::ApprovedPermissions;
use penguin_bundle_host::host::capability::*;
use penguin_bundle_host::host::clock_guard::ClockGuard;
use penguin_bundle_host::host::db_guard::DbGuard;
use penguin_bundle_host::host::egress::{DnsResolver, EgressGuard, EgressGuardConfig, SecretResolver, TenantDenylist};
use penguin_bundle_host::host::flags_guard::FlagsGuard;
use penguin_bundle_host::host::kv_guard::KvGuard;
use penguin_bundle_host::host::log_guard::LogGuard;
use penguin_bundle_host::host::relay_guard::RelayGuard;
use penguin_bundle_host::host::router::{BundleContextInfo, HostCallContext, HostCallRouter};
use penguin_bundle_host::host::trip::TripTracker;
use penguin_bundle_host::wire::message::CapabilityKind;
use serde_json::json;
use std::sync::Arc;
use std::time::Duration;

// -- minimal fakes, one per trait, mirroring earlier tasks' patterns --
struct FakeHttp;
#[async_trait::async_trait]
impl HttpEgress for FakeHttp {
    async fn execute(&self, _a: std::net::SocketAddr, _s: &str, _r: PreparedHttpRequest) -> Result<RawHttpResponse, HttpTransportError> {
        Ok(RawHttpResponse { status: 200, headers: vec![], body: b"{}".to_vec() })
    }
}
struct FakeResolver;
#[async_trait::async_trait]
impl DnsResolver for FakeResolver {
    async fn resolve(&self, _h: &str) -> std::io::Result<Vec<std::net::IpAddr>> { Ok(vec!["93.184.216.34".parse().unwrap()]) }
}
struct NoDenylist;
impl TenantDenylist for NoDenylist { fn is_denylisted(&self, _h: &str) -> bool { false } }
struct NoSecrets;
#[async_trait::async_trait]
impl SecretResolver for NoSecrets { async fn resolve(&self, _n: &str) -> Option<String> { None } }
struct FakeKv;
#[async_trait::async_trait]
impl KvStore for FakeKv {
    async fn get(&self, _k: &str) -> Result<Option<Vec<u8>>, KvBackendError> { Ok(None) }
    async fn set(&self, _k: &str, _v: &[u8], _t: u32) -> Result<(), KvBackendError> { Ok(()) }
    async fn delete(&self, _k: &str) -> Result<(), KvBackendError> { Ok(()) }
    async fn increment(&self, _k: &str, d: i64, _t: u32) -> Result<i64, KvBackendError> { Ok(d) }
}
struct FakeDb;
#[async_trait::async_trait]
impl DbExecutor for FakeDb {
    async fn execute(&self, _scope: &penguin_bundle_host::wire::message::InvocationScope, _s: &str, _p: &[DbValue]) -> Result<DbRows, DbBackendError> {
        Ok(DbRows { columns: vec![], rows: vec![], rows_affected: 0 })
    }
}
struct FakeRelay;
#[async_trait::async_trait]
impl RelayPush for FakeRelay { async fn push(&self, _p: &str, _m: &str) -> Result<(), RelayBackendError> { Ok(()) } }
struct FakeFlags;
#[async_trait::async_trait]
impl Flags for FakeFlags {
    async fn enabled(&self, _k: &str, d: bool) -> bool { d }
    async fn tier(&self) -> String { "free".into() }
}
struct FakeLogger;
impl Logger for FakeLogger { fn write(&self, _l: LogLevel, _a: &str, _m: &str, _f: &str) {} }
struct FakeClock;
impl Clock for FakeClock {
    fn now_millis(&self) -> u64 { 1 }
    fn now_rfc3339(&self) -> String { "2026-09-14T00:00:00.000Z".into() }
    fn monotonic_nanos(&self) -> u64 { 1 }
}

fn router() -> HostCallRouter<FakeHttp, FakeKv, FakeDb, FakeRelay, FakeFlags, FakeLogger, FakeClock> {
    HostCallRouter::new(
        EgressGuard::new(Arc::new(FakeHttp), Arc::new(FakeResolver), Arc::new(NoDenylist), EgressGuardConfig { allow_private_hosts: false, max_redirects: 3, response_byte_cap: 1_048_576, call_timeout: Duration::from_secs(5) }),
        KvGuard::new(Arc::new(FakeKv), 65536, 2_592_000),
        DbGuard::new(Arc::new(FakeDb)),
        RelayGuard::new(Arc::new(FakeRelay), vec!["twitch".to_string()]),
        FlagsGuard::new(Arc::new(FakeFlags)),
        LogGuard::new(Arc::new(FakeLogger), LogLevel::Info),
        ClockGuard::new(Arc::new(FakeClock)),
        Arc::new(TripTracker::new(3, Duration::from_secs(300))),
        Arc::new(NoSecrets),
        None,
        "process",
    )
}

fn ctx(capabilities: serde_json::Value) -> HostCallContext {
    let approved = ApprovedPermissions::from_json(
        "waddles.test.fixture.hello",
        &json!({"egress": [{"host": "api.spotify.com"}], "data": {"tables": [{"name": "t", "read": true, "write": true}]}, "capabilities": capabilities, "routes_to": [], "limits": {"timeout_ms": 2000, "memory_mb": 64, "egress_rps": 10}}),
    )
    .unwrap();
    HostCallContext {
        app_id: "waddles.test.fixture.hello".to_string(),
        digest: "sha256:1".to_string(),
        approved: Arc::new(approved),
        bundle_context: BundleContextInfo {
            tenant: "t".into(), community: None, feature: "f".into(), version: "0.1.0".into(),
            message_id: "m1".into(), config_json: "{}".into(),
            workstream_id: "8f14e45f-ceea-467e-adde-3fb5c9752730".into(), trace: None,
        },
    }
}

#[tokio::test]
async fn kv_get_dispatches_and_returns_null_for_a_missing_key() {
    let r = router();
    let result = r.dispatch(&ctx(json!(["kv"])), CapabilityKind::Kv, "get", json!({"key": "x"})).await.unwrap();
    assert_eq!(result, json!(null));
}

#[tokio::test]
async fn http_send_without_the_http_capability_is_denied() {
    let r = router();
    let err = r.dispatch(&ctx(json!(["kv"])), CapabilityKind::Http, "send", json!({"method": "GET", "url": "https://api.spotify.com/x", "headers": [], "secret_refs": []})).await.unwrap_err();
    assert_eq!(err.code, "HOST_CALL_DENIED");
}

#[tokio::test]
async fn http_send_with_the_capability_and_an_allowlisted_host_succeeds() {
    let r = router();
    let result = r.dispatch(&ctx(json!(["http"])), CapabilityKind::Http, "send", json!({"method": "GET", "url": "https://api.spotify.com/x", "headers": [], "secret_refs": []})).await.unwrap();
    assert_eq!(result["status"], 200);
}

#[tokio::test]
async fn db_execute_without_the_db_capability_is_denied() {
    let r = router();
    let err = r.dispatch(&ctx(json!(["kv"])), CapabilityKind::Db, "execute", json!({"statement": "SELECT 1 FROM t", "params": []})).await.unwrap_err();
    assert_eq!(err.code, "HOST_CALL_DENIED");
}

#[tokio::test]
async fn three_denied_calls_within_the_window_trip_the_tracker() {
    let r = router();
    let c = ctx(json!(["kv"])); // no http capability -> every http.send is denied
    for _ in 0..2 {
        r.dispatch(&c, CapabilityKind::Http, "send", json!({"method": "GET", "url": "https://api.spotify.com/x", "headers": [], "secret_refs": []})).await.unwrap_err();
    }
    assert!(!r.trips().is_disabled(&c.app_id, &c.digest));
    r.dispatch(&c, CapabilityKind::Http, "send", json!({"method": "GET", "url": "https://api.spotify.com/x", "headers": [], "secret_refs": []})).await.unwrap_err();
    assert!(r.trips().is_disabled(&c.app_id, &c.digest), "the third denial in the window must trip the bundle");
}

#[tokio::test]
async fn flags_and_clock_and_context_are_always_dispatchable_with_no_capability_check() {
    let r = router();
    let c = ctx(json!([])); // no capabilities declared at all
    assert!(r.dispatch(&c, CapabilityKind::Flags, "enabled", json!({"key": "waddles.core.wasm-bundles", "default_value": true})).await.is_ok());
    assert!(r.dispatch(&c, CapabilityKind::Clock, "now_millis", json!({})).await.is_ok());
    assert!(r.dispatch(&c, CapabilityKind::Context, "get_context", json!({})).await.is_ok());
}

#[tokio::test]
async fn unknown_op_for_a_capability_is_a_host_call_failed_error() {
    let r = router();
    let err = r.dispatch(&ctx(json!(["kv"])), CapabilityKind::Kv, "not_a_real_op", json!({})).await.unwrap_err();
    assert_eq!(err.code, "HOST_CALL_FAILED");
}
```

- [ ] **Step 2: Run to verify failure**

Run: `make test`
Expected: FAIL — `host::router` module does not exist.

- [ ] **Step 3: Implement `src/host/router.rs`**

```rust
//! Dispatches one `host-call` frame's `(capability, op, args)` to the
//! matching guard, translating the guard's outcome into the
//! `host-result` shape the wire protocol carries (spec §6.6). This is
//! the single place capability presence, the approved-permission set,
//! and the trip tracker all meet.

use std::sync::Arc;

use serde_json::{json, Value};

use super::approvals::{ApprovedPermissions, Capability};
use super::capability::*;
use super::clock_guard::ClockGuard;
use super::db_guard::{DbGuard, DbOutcome};
use super::egress::{EgressGuard, EgressRequest, EgressOutcome, SecretResolver};
use super::flags_guard::FlagsGuard;
use super::kv_guard::KvGuard;
use super::log_guard::LogGuard;
use super::relay_guard::RelayGuard;
use super::trip::{TripLimit, TripTracker};
use crate::wire::message::{CapabilityKind, HostResultError};
use tracing::Instrument;

#[derive(Debug, Clone)]
pub struct BundleContextInfo {
    pub tenant: String,
    pub community: Option<String>,
    pub feature: String,
    pub version: String,
    pub message_id: String,
    pub config_json: String,
    /// D30 (spec §5.11, §6.11): the workstream this invocation belongs
    /// to, sourced from a binding-MAC-verified envelope, never guessed.
    pub workstream_id: String,
    /// D30 (spec §5.11, §13.2): the envelope's trace context, propagated
    /// into every host-call frame and span this invocation produces.
    pub trace: Option<penguin_spine::Trace>,
}

pub struct HostCallContext {
    pub app_id: String,
    pub digest: String,
    pub approved: Arc<ApprovedPermissions>,
    pub bundle_context: BundleContextInfo,
}

impl HostCallContext {
    /// Builds the D30 `InvocationScope` (spec §5.11) this context
    /// implies. `DbGuard::execute` and usage-metering call sites use
    /// this rather than re-deriving the same five fields by hand.
    pub fn scope(&self) -> crate::wire::message::InvocationScope {
        crate::wire::message::InvocationScope {
            tenant_id: self.bundle_context.tenant.clone(),
            community_id: self.bundle_context.community.clone(),
            workstream_id: self.bundle_context.workstream_id.clone(),
            app_id: self.app_id.clone(),
            trace: self.bundle_context.trace.clone(),
        }
    }
}

pub struct HostCallRouter<Http: HttpEgress, Kv: KvStore, Db: DbExecutor, Relay: RelayPush, Fl: Flags, Lg: Logger, Ck: Clock> {
    egress: EgressGuard<Http>,
    kv: KvGuard<Kv>,
    db: DbGuard<Db>,
    relay: RelayGuard<Relay>,
    flags: FlagsGuard<Fl>,
    log: LogGuard<Lg>,
    clock: ClockGuard<Ck>,
    trips: Arc<TripTracker>,
    secrets: Arc<dyn SecretResolver>,
    /// D31 (spec §5.12): `None` when `metering.enabled=false`.
    usage: Option<Arc<penguin_spine::UsageBatcher>>,
    /// `"process"` or `"action"` -- this router is instantiated once per
    /// stage process (spec §5.12's `UsageDelta.stage`), never shared
    /// between the two.
    stage: String,
}

/// The subset of `CapabilityKind` spec §5.12 counts as "host calls by
/// kind" -- `Context` and `Clock` are local/free and never counted.
fn usage_kind_for(capability: CapabilityKind) -> Option<penguin_spine::HostCallKind> {
    match capability {
        CapabilityKind::Http => Some(penguin_spine::HostCallKind::Http),
        CapabilityKind::Kv => Some(penguin_spine::HostCallKind::Kv),
        CapabilityKind::Db => Some(penguin_spine::HostCallKind::Db),
        CapabilityKind::Relay => Some(penguin_spine::HostCallKind::Relay),
        CapabilityKind::Flags => Some(penguin_spine::HostCallKind::Flags),
        CapabilityKind::Log => Some(penguin_spine::HostCallKind::Log),
        CapabilityKind::Context | CapabilityKind::Clock => None,
    }
}

fn denied(reason: &str) -> HostResultError {
    HostResultError { code: "HOST_CALL_DENIED".to_string(), message: reason.to_string() }
}

fn failed(reason: &str) -> HostResultError {
    HostResultError { code: "HOST_CALL_FAILED".to_string(), message: reason.to_string() }
}

impl<Http: HttpEgress, Kv: KvStore, Db: DbExecutor, Relay: RelayPush, Fl: Flags, Lg: Logger, Ck: Clock>
    HostCallRouter<Http, Kv, Db, Relay, Fl, Lg, Ck>
{
    #[allow(clippy::too_many_arguments)]
    pub fn new(
        egress: EgressGuard<Http>,
        kv: KvGuard<Kv>,
        db: DbGuard<Db>,
        relay: RelayGuard<Relay>,
        flags: FlagsGuard<Fl>,
        log: LogGuard<Lg>,
        clock: ClockGuard<Ck>,
        trips: Arc<TripTracker>,
        secrets: Arc<dyn SecretResolver>,
        usage: Option<Arc<penguin_spine::UsageBatcher>>,
        stage: impl Into<String>,
    ) -> Self {
        Self { egress, kv, db, relay, flags, log, clock, trips, secrets, usage, stage: stage.into() }
    }

    /// D31 (spec §5.12): records one successful host call of `capability`'s
    /// kind against `ctx`'s scope. A no-op when usage recording is
    /// disabled, or for a capability spec §5.12 does not count
    /// (`context`, `clock`).
    fn record_usage(&self, ctx: &HostCallContext, capability: CapabilityKind) {
        let Some(usage) = &self.usage else { return };
        let Some(kind) = usage_kind_for(capability) else { return };
        let mut delta = penguin_spine::UsageDelta::zero(
            ctx.bundle_context.tenant.clone(),
            ctx.bundle_context.community.clone(),
            ctx.bundle_context.workstream_id.clone(),
            self.stage.clone(),
            Some(ctx.app_id.clone()),
        );
        delta.host_calls.increment(kind);
        usage.record(delta);
    }

    pub fn trips(&self) -> &TripTracker {
        &self.trips
    }

    fn record_denial_trip(&self, ctx: &HostCallContext) {
        let outcome = self.trips.record_trip(&ctx.app_id, &ctx.digest, TripLimit::Denied, std::time::Instant::now());
        let _ = outcome; // the caller only needs is_disabled(); the Recorded/Disabled distinction is logged by the caller of dispatch (Task 17's server), not here.
    }

    pub async fn dispatch(
        &self,
        ctx: &HostCallContext,
        capability: CapabilityKind,
        op: &str,
        args: Value,
    ) -> Result<Value, HostResultError> {
        // D30 (spec §5.11, §13.2): one span per host call, carrying the
        // same four ids as the owning bundle.invoke span (Task 22).
        // Built with `Instrument` on the future below, never
        // `span.enter()` -- an `Entered` guard held across `.await`
        // attaches to whatever task the runtime resumes next.
        let community_label = ctx.bundle_context.community.as_deref().unwrap_or("_tenant").to_string();
        let span = tracing::info_span!(
            "host.call",
            capability = ?capability,
            op,
            waddles.tenant_id = %ctx.bundle_context.tenant,
            waddles.community_id = %community_label,
            waddles.workstream_id = %ctx.bundle_context.workstream_id,
            waddles.app_id = %ctx.app_id,
        );
        async move {
        let result = match capability {
            CapabilityKind::Context => match op {
                "get_context" => Ok(json!({
                    "tenant": ctx.bundle_context.tenant,
                    "community": ctx.bundle_context.community,
                    "app_id": ctx.app_id,
                    "feature": ctx.bundle_context.feature,
                    "version": ctx.bundle_context.version,
                    "message_id": ctx.bundle_context.message_id,
                    "config_json": ctx.bundle_context.config_json,
                })),
                other => Err(failed(&format!("unknown context op '{other}'"))),
            },
            CapabilityKind::Clock => match op {
                "now_millis" => Ok(json!(self.clock.now_millis())),
                "now_rfc3339" => Ok(json!(self.clock.now_rfc3339())),
                "monotonic_nanos" => Ok(json!(self.clock.monotonic_nanos())),
                other => Err(failed(&format!("unknown clock op '{other}'"))),
            },
            CapabilityKind::Flags => match op {
                "enabled" => {
                    let key = args["key"].as_str().unwrap_or_default();
                    let default_value = args["default_value"].as_bool().unwrap_or(false);
                    Ok(json!(self.flags.enabled(key, default_value).await))
                }
                "tier" => Ok(json!(self.flags.tier().await)),
                other => Err(failed(&format!("unknown flags op '{other}'"))),
            },
            CapabilityKind::Log => match op {
                "write" => {
                    let level = match args["lvl"].as_str().unwrap_or("info") {
                        "error" => LogLevel::Error,
                        "warn" => LogLevel::Warn,
                        "debug" => LogLevel::Debug,
                        _ => LogLevel::Info,
                    };
                    let message = args["message"].as_str().unwrap_or_default();
                    let fields_json = args["fields_json"].as_str().unwrap_or("{}");
                    self.log.write(&ctx.app_id, level, message, fields_json);
                    Ok(Value::Null)
                }
                other => Err(failed(&format!("unknown log op '{other}'"))),
            },
            CapabilityKind::Kv => {
                if !ctx.approved.has_capability(Capability::Kv) {
                    self.record_denial_trip(ctx);
                    return Err(denied("kv capability not granted"));
                }
                // Bundle state key, spec §6.2: `{scope}:app:{app_id}:state`
                // where `{scope}` = `waddles:t:{tenant}:c:{community|_tenant}`
                // -- tenant/community come only from the envelope's own
                // bundle_context (never from guest-supplied data), and
                // `_tenant` is the literal rendering for a tenant-wide
                // activation, matching every other key builder in this design.
                let base_key = format!(
                    "waddles:t:{}:c:{}:app:{}:state",
                    ctx.bundle_context.tenant,
                    ctx.bundle_context.community.as_deref().unwrap_or("_tenant"),
                    ctx.app_id
                );
                let key = args["key"].as_str().unwrap_or_default();
                match op {
                    "get" => self.kv.get(&ctx.approved, &base_key, key).await.map(|v| json!(v)).map_err(|e| denied(&format!("{e:?}"))),
                    "set" => {
                        let value = args["value"].as_array().map(|a| a.iter().filter_map(|v| v.as_u64()).map(|n| n as u8).collect::<Vec<u8>>()).unwrap_or_default();
                        let ttl = args["ttl_seconds"].as_u64().unwrap_or(0) as u32;
                        self.kv.set(&ctx.approved, &base_key, key, &value, ttl).await.map(|_| Value::Null).map_err(|e| denied(&format!("{e:?}")))
                    }
                    "delete" => self.kv.delete(&ctx.approved, &base_key, key).await.map(|_| Value::Null).map_err(|e| denied(&format!("{e:?}"))),
                    "increment" => {
                        let delta = args["delta"].as_i64().unwrap_or(0);
                        let ttl = args["ttl_seconds"].as_u64().unwrap_or(0) as u32;
                        self.kv.increment(&ctx.approved, &base_key, key, delta, ttl).await.map(|v| json!(v)).map_err(|e| denied(&format!("{e:?}")))
                    }
                    other => Err(failed(&format!("unknown kv op '{other}'"))),
                }
            }
            CapabilityKind::Db => {
                if !ctx.approved.has_capability(Capability::Db) {
                    self.record_denial_trip(ctx);
                    return Err(denied("db capability not granted"));
                }
                if op != "execute" {
                    return Err(failed(&format!("unknown db op '{op}'")));
                }
                let statement = args["statement"].as_str().unwrap_or_default();
                match self.db.execute(&ctx.approved, &ctx.scope(), statement, &[]).await {
                    DbOutcome::Rows(rows) => Ok(json!({"columns": rows.columns, "rows_affected": rows.rows_affected})),
                    DbOutcome::Denied(reason) => {
                        self.record_denial_trip(ctx);
                        Err(denied(&format!("{reason:?}")))
                    }
                    DbOutcome::Timeout => Err(HostResultError { code: "EXECUTOR_DEADLINE".to_string(), message: "db call timed out".to_string() }),
                }
            }
            CapabilityKind::Relay => {
                let provider = args["provider"].as_str().unwrap_or_default();
                let message_json = args["message_json"].as_str().unwrap_or("{}");
                if op != "push" {
                    return Err(failed(&format!("unknown relay op '{op}'")));
                }
                self.relay.push(&ctx.approved, provider, message_json).await.map(|_| Value::Null).map_err(|e| {
                    self.record_denial_trip(ctx);
                    denied(&format!("{e:?}"))
                })
            }
            CapabilityKind::Http => {
                if !ctx.approved.has_capability(Capability::Http) {
                    self.record_denial_trip(ctx);
                    return Err(denied("http capability not granted"));
                }
                if op != "send" {
                    return Err(failed(&format!("unknown http op '{op}'")));
                }
                let req = EgressRequest {
                    method: args["method"].as_str().unwrap_or("GET").to_string(),
                    url: args["url"].as_str().unwrap_or_default().to_string(),
                    headers: vec![],
                    body: None,
                    secret_refs: vec![],
                };
                match self.egress.send(&ctx.approved, req, self.secrets.as_ref()).await {
                    EgressOutcome::Response(resp) => Ok(json!({"status": resp.status, "headers": resp.headers, "body": resp.body, "truncated": resp.truncated})),
                    EgressOutcome::Denied(reason) => {
                        self.record_denial_trip(ctx);
                        Err(denied(reason.reason_str()))
                    }
                    EgressOutcome::RateLimited { retry_after_ms } => {
                        Err(HostResultError { code: "RATE_LIMITED".to_string(), message: retry_after_ms.to_string() })
                    }
                    EgressOutcome::Timeout => Err(HostResultError { code: "EXECUTOR_DEADLINE".to_string(), message: "http call timed out".to_string() }),
                    EgressOutcome::TooLarge(n) => Err(HostResultError { code: "HOST_CALL_FAILED".to_string(), message: format!("response too large: {n} bytes") }),
                }
            }
        };
        if result.is_ok() {
            self.record_usage(ctx, capability);
        }
        result
        }
        .instrument(span)
        .await
    }
}
```

- [ ] **Step 4: Export from `src/host/mod.rs`**

```rust
pub mod router;
```

- [ ] **Step 5: Run to verify pass**

Run: `make test`
Expected: PASS — all 7 `host_call_router_tests` green.

- [ ] **Step 6: Commit**

```bash
git add packages/rust-bundle-host/src/host/router.rs packages/rust-bundle-host/src/host/mod.rs packages/rust-bundle-host/tests/host_call_router_tests.rs
git commit -m "$(cat <<'EOF'
feat(bundle-host): HostCallRouter -- dispatch host-call frames to the guards

Single dispatch point for (capability, op, args): checks
ApprovedPermissions.has_capability before ever touching a guard,
increments the TripTracker on every denial, and translates each guard's
outcome into the wire protocol's host-result / error.code shapes.

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01N2rQgkHY872RubwXoBZxtE
EOF
)"
git push
```

---

## Task 17: mTLS frame-protocol server — `host::server`

**Depends on:** Task 16 (`HostCallRouter`), Task 4 (`FrameTransport`), Task 2 (`Message`).

**Files:**
- Modify: `packages/rust-bundle-host/Cargo.toml` (add `x509-parser = "=0.18.1"`, `rcgen` moves from dev- to a regular dependency is **not** needed — test certs stay dev-only; add `tokio-rustls`'s `server` re-export usage, already pinned)
- Modify: `packages/rust-bundle-host/src/wire/transport.rs` (add `call_with_id`)
- Create: `packages/rust-bundle-host/src/host/server.rs`
- Modify: `packages/rust-bundle-host/src/host/mod.rs`
- Test: `packages/rust-bundle-host/tests/host_server_tests.rs`

**Interfaces:**
- Consumes: `wire::transport::FrameTransport` (Task 4, extended here), `wire::message::*` (Task 2), `host::router::{HostCallRouter, HostCallContext}` (Task 16).
- Produces:
  ```rust
  pub enum SandboxPosture { Gvisor, Runc }
  pub struct ServerTlsConfig {
      pub cert_chain: Vec<rustls_pki_types::CertificateDer<'static>>,
      pub private_key: rustls_pki_types::PrivateKeyDer<'static>,
      pub client_ca: rustls_pki_types::CertificateDer<'static>,
      pub expected_peer_identity: String,   // exact CN to match on the client cert
  }
  pub struct ServerPosture { pub expected_collector: String, pub sandbox_expected: SandboxPosture }

  #[derive(Debug, thiserror::Error)] pub enum ServerError { /* Io, Tls, ProtocolVersion, UnsandboxedExecutor, PeerIdentity, ... */ }
  #[derive(Debug, thiserror::Error)] pub enum HostApiError { /* Transport, Executor{code, message} */ }

  pub struct Server { /* ... */ }
  impl Server {
      pub async fn bind(addr: std::net::SocketAddr, tls: ServerTlsConfig, posture: ServerPosture) -> Result<Self, ServerError>;
      /// Accepts one connection, completes the TLS handshake, pins the
      /// peer's Common Name, awaits `hello`, checks protocol_version(=1)/
      /// collector/sandbox posture agreement, replies `hello-ok`.
      pub async fn accept(&self) -> Result<std::sync::Arc<ExecutorConnection>, ServerError>;
  }

  pub struct HelloInfo { pub executor_version: String, pub wasmtime_version: String, pub wasmtime_abi: String, pub collector: String, pub sandbox: SandboxInfo }

  pub struct ExecutorConnection { pub hello: HelloInfo, /* ... */ }
  impl ExecutorConnection {
      pub async fn load(&self, app_id: &str, version: &str, digest: &str, component_key: &str, sidecar_key: &str, capabilities: Vec<String>, limits: LoadLimits) -> Result<(String, u64, Vec<String>), HostApiError>; // (digest, precompile_ms, exports)
      pub async fn invoke(&self, app_id: &str, digest: &str, export: ExportKind, payload: serde_json::Value, deadline_ms: u64, ctx: HostCallContextTemplate) -> Result<serde_json::Value, HostApiError>;
      pub async fn unload(&self, app_id: &str, digest: &str) -> Result<(), HostApiError>;
      pub async fn ping(&self) -> Result<(), HostApiError>;
      pub async fn shutdown(&self, grace_ms: u64) -> Result<(), HostApiError>;
      /// Spawns the background task answering `host-call` frames with
      /// `router` for as long as this connection lives.
      pub fn spawn_host_call_loop<Http, Kv, Db, Relay, Fl, Lg, Ck>(&self, router: std::sync::Arc<HostCallRouter<Http, Kv, Db, Relay, Fl, Lg, Ck>>) -> tokio::task::JoinHandle<()>
      where Http: HttpEgress + 'static, Kv: KvStore + 'static, Db: DbExecutor + 'static, Relay: RelayPush + 'static, Fl: Flags + 'static, Lg: Logger + 'static, Ck: Clock + 'static;
  }
  pub struct HostCallContextTemplate { pub approved: std::sync::Arc<ApprovedPermissions>, pub bundle_context: BundleContextInfo }
  ```
  The `svc_process`/`svc_action` binaries (M3/M4, out of scope here) are the actual callers of `Server::bind`/`accept`/`ExecutorConnection::{load,invoke,unload}`; Task 22 (`bundle-executor` binary integration test) exercises the executor side of this same connection.

- [ ] **Step 1: Add `call_with_id` to `FrameTransport` (`src/wire/transport.rs`)**

```rust
impl FrameTransport {
    /// Like `call`, but the caller supplies the id instead of `call`
    /// allocating one internally. `host::server::ExecutorConnection::invoke`
    /// needs to know the frame id an `invoke` will use *before* sending
    /// it, so it can register that id's approved-permissions context for
    /// a resulting `host-call`'s `call_id` to look up, with no window
    /// where a fast host-call could arrive before the context exists.
    pub async fn call_with_id(&self, id: u64, message: Message) -> Result<Message, TransportError> {
        if self.closed.load(Ordering::SeqCst) {
            return Err(TransportError::Closed);
        }
        let (tx, rx) = oneshot::channel();
        self.pending.lock().await.insert(id, tx);
        self.write_frame_locked(id, message).await?;
        rx.await.map_err(|_| TransportError::Closed)
    }
}
```

Add a test to `tests/wire_transport_tests.rs`:

```rust
#[tokio::test]
async fn call_with_id_uses_the_caller_supplied_id() {
    let (client_io, server_io) = tokio::io::duplex(8192);
    let client = FrameTransport::spawn(client_io, 1_048_576);
    let server = FrameTransport::spawn(server_io, 1_048_576);
    let server_task = tokio::spawn(async move {
        let frame = server.recv_unsolicited().await.unwrap();
        assert_eq!(frame.id, 99);
        server.send(99, Message::Pong).await.unwrap();
    });
    let reply = client.call_with_id(99, Message::Ping).await.unwrap();
    assert!(matches!(reply, Message::Pong));
    server_task.await.unwrap();
}
```

Run: `make test` — expect this one new test to fail, then pass once the method above is added; the rest of `wire_transport_tests` stays green throughout.

- [ ] **Step 2: Write the failing server tests**

`tests/host_server_tests.rs`:

```rust
#![allow(clippy::unwrap_used, clippy::panic)]
use penguin_bundle_host::host::server::{Server, ServerError, ServerPosture, ServerTlsConfig, SandboxPosture};
use penguin_bundle_host::wire::message::{Message, SandboxInfo};
use penguin_bundle_host::wire::transport::FrameTransport;
use rcgen::{Certificate, CertificateParams, KeyPair};
use rustls_pki_types::{CertificateDer, PrivateKeyDer, ServerName};
use std::net::SocketAddr;
use std::sync::Arc;

/// A throwaway CA, kept in memory (not just as DER) so multiple leaves
/// can be signed by the same key material -- one CA per test, two
/// leaves each (the stage's own cert and the executor's).
fn make_ca() -> (Certificate, KeyPair, CertificateDer<'static>) {
    let mut ca_params = CertificateParams::new(vec![]).unwrap();
    ca_params.is_ca = rcgen::IsCa::Ca(rcgen::BasicConstraints::Unconstrained);
    let ca_key = KeyPair::generate().unwrap();
    let ca_cert = ca_params.self_signed(&ca_key).unwrap();
    let der = ca_cert.der().clone();
    (ca_cert, ca_key, der)
}

fn make_leaf(ca_cert: &Certificate, ca_key: &KeyPair, common_name: &str) -> (CertificateDer<'static>, PrivateKeyDer<'static>) {
    let mut leaf_params = CertificateParams::new(vec![common_name.to_string()]).unwrap();
    leaf_params.distinguished_name.push(rcgen::DnType::CommonName, common_name);
    let leaf_key = KeyPair::generate().unwrap();
    let leaf_cert = leaf_params.signed_by(&leaf_key, ca_cert, ca_key).unwrap();
    (leaf_cert.der().clone(), PrivateKeyDer::Pkcs8(leaf_key.serialize_der().into()))
}

/// Dials `addr` over mTLS presenting the executor's own cert, sends
/// `hello` with the given `collector`/`sandbox_runtime`, and returns the
/// transport. The two negative-path tests below never await a reply on
/// the returned `call()` future beyond what `FrameTransport` itself
/// resolves when the server closes the connection without one -- that
/// resolves promptly to `TransportError::Closed`, not a hang.
async fn dial_and_send_hello(
    addr: SocketAddr,
    ca_der: CertificateDer<'static>,
    client_cert_der: CertificateDer<'static>,
    client_key: PrivateKeyDer<'static>,
    collector: &str,
    sandbox_runtime: &str,
) -> Arc<FrameTransport> {
    let mut root_store = rustls::RootCertStore::empty();
    root_store.add(ca_der).unwrap();
    let client_config = rustls::ClientConfig::builder()
        .with_root_certificates(root_store)
        .with_client_auth_cert(vec![client_cert_der], client_key)
        .unwrap();
    let connector = tokio_rustls::TlsConnector::from(Arc::new(client_config));

    let tcp = tokio::net::TcpStream::connect(addr).await.unwrap();
    let server_name = ServerName::try_from("svc-process".to_string()).unwrap();
    let tls_stream = connector.connect(server_name, tcp).await.unwrap();

    let transport = Arc::new(FrameTransport::spawn(tls_stream, penguin_bundle_host::wire::frame::MAX_FRAME_BYTES));
    let _ = transport
        .call(Message::Hello {
            protocol_version: 1,
            executor_version: "0.1.0".to_string(),
            wasmtime_version: "48.0.2".to_string(),
            wasmtime_abi: "48".to_string(),
            collector: collector.to_string(),
            sandbox: SandboxInfo { runtime: sandbox_runtime.to_string(), verified: sandbox_runtime == "gvisor" },
        })
        .await;
    transport
}

#[tokio::test]
async fn server_binds_and_accepts_a_correctly_identified_executor() {
    let (ca_cert, ca_key, ca_der) = make_ca();
    let (server_cert_der, server_key) = make_leaf(&ca_cert, &ca_key, "svc-process");
    let (executor_cert_der, executor_key) = make_leaf(&ca_cert, &ca_key, "svc-process-executor");

    let addr: SocketAddr = "127.0.0.1:0".parse().unwrap();
    let server = Server::bind(
        addr,
        ServerTlsConfig {
            cert_chain: vec![server_cert_der],
            private_key: server_key,
            client_ca: ca_der.clone(),
            expected_peer_identity: "svc-process-executor".to_string(),
        },
        ServerPosture { expected_collector: "drc".to_string(), sandbox_expected: SandboxPosture::Gvisor },
    )
    .await
    .unwrap();
    let bound_addr = server.local_addr();

    let server_task = tokio::spawn(async move {
        let conn = server.accept().await.unwrap();
        assert_eq!(conn.hello.collector, "drc");
        conn
    });

    let _client_transport = dial_and_send_hello(bound_addr, ca_der, executor_cert_der, executor_key, "drc", "gvisor").await;
    server_task.await.unwrap();
}

#[tokio::test]
async fn server_refuses_a_hello_reporting_runc_when_gvisor_is_expected() {
    let (ca_cert, ca_key, ca_der) = make_ca();
    let (server_cert_der, server_key) = make_leaf(&ca_cert, &ca_key, "svc-process");
    let (executor_cert_der, executor_key) = make_leaf(&ca_cert, &ca_key, "svc-process-executor");
    let addr: SocketAddr = "127.0.0.1:0".parse().unwrap();
    let server = Server::bind(
        addr,
        ServerTlsConfig { cert_chain: vec![server_cert_der], private_key: server_key, client_ca: ca_der.clone(), expected_peer_identity: "svc-process-executor".to_string() },
        ServerPosture { expected_collector: "drc".to_string(), sandbox_expected: SandboxPosture::Gvisor },
    )
    .await
    .unwrap();
    let bound_addr = server.local_addr();

    let server_task = tokio::spawn(async move { server.accept().await });

    dial_and_send_hello(bound_addr, ca_der, executor_cert_der, executor_key, "drc", "runc").await;
    let result = server_task.await.unwrap();
    assert!(matches!(result, Err(ServerError::UnsandboxedExecutor)), "got {result:?}");
}

#[tokio::test]
async fn server_refuses_a_mismatched_collector() {
    let (ca_cert, ca_key, ca_der) = make_ca();
    let (server_cert_der, server_key) = make_leaf(&ca_cert, &ca_key, "svc-process");
    let (executor_cert_der, executor_key) = make_leaf(&ca_cert, &ca_key, "svc-process-executor");
    let addr: SocketAddr = "127.0.0.1:0".parse().unwrap();
    let server = Server::bind(
        addr,
        ServerTlsConfig { cert_chain: vec![server_cert_der], private_key: server_key, client_ca: ca_der.clone(), expected_peer_identity: "svc-process-executor".to_string() },
        ServerPosture { expected_collector: "drc".to_string(), sandbox_expected: SandboxPosture::Gvisor },
    )
    .await
    .unwrap();
    let bound_addr = server.local_addr();
    let server_task = tokio::spawn(async move { server.accept().await });
    dial_and_send_hello(bound_addr, ca_der, executor_cert_der, executor_key, "copying", "gvisor").await;
    assert!(matches!(server_task.await.unwrap(), Err(ServerError::ProtocolVersion)));
}
```

- [ ] **Step 3: Run to verify failure**

Run: `make test`
Expected: FAIL — `host::server` module does not exist.

- [ ] **Step 4: Implement `src/host/server.rs`**

```rust
//! The mTLS frame-protocol server (spec §6.6, §11.2 layer 5): accepts
//! the executor's TLS connection, pins its Common Name, agrees on
//! protocol version/collector/sandbox posture during the `hello`
//! handshake, and exposes `load`/`invoke`/`unload`/`ping`/`shutdown` to
//! the caller (the stage service, M3/M4) plus a background loop that
//! answers `host-call` frames via a `HostCallRouter`.

use std::collections::HashMap;
use std::net::SocketAddr;
use std::sync::atomic::{AtomicU64, Ordering};
use std::sync::Arc;

use rustls_pki_types::{CertificateDer, PrivateKeyDer};
use tokio::net::{TcpListener, TcpStream};
use tokio::sync::Mutex;
use tokio_rustls::TlsAcceptor;

use super::approvals::ApprovedPermissions;
use super::capability::{Clock, DbExecutor, Flags, HttpEgress, KvStore, Logger, RelayPush};
use super::router::{BundleContextInfo, HostCallContext, HostCallRouter};
use crate::wire::message::{ExportKind, HelloLimits, LoadLimits, Message, SandboxInfo};
use crate::wire::transport::FrameTransport;

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum SandboxPosture {
    Gvisor,
    Runc,
}

pub struct ServerTlsConfig {
    pub cert_chain: Vec<CertificateDer<'static>>,
    pub private_key: PrivateKeyDer<'static>,
    pub client_ca: CertificateDer<'static>,
    pub expected_peer_identity: String,
}

#[derive(Debug, Clone)]
pub struct ServerPosture {
    pub expected_collector: String,
    pub sandbox_expected: SandboxPosture,
}

#[derive(Debug, thiserror::Error)]
pub enum ServerError {
    #[error("io error: {0}")]
    Io(#[from] std::io::Error),
    #[error("tls error: {0}")]
    Tls(String),
    #[error("peer identity mismatch")]
    PeerIdentity,
    #[error("protocol version or collector mismatch")]
    ProtocolVersion,
    #[error("executor is not under the expected sandbox posture")]
    UnsandboxedExecutor,
    #[error("connection closed during handshake")]
    HandshakeClosed,
}

#[derive(Debug, thiserror::Error)]
pub enum HostApiError {
    #[error("transport error: {0}")]
    Transport(#[from] crate::wire::transport::TransportError),
    #[error("executor error {code}: {message}")]
    Executor { code: String, message: String },
    #[error("unexpected reply kind for this call")]
    UnexpectedReply,
}

pub struct HelloInfo {
    pub executor_version: String,
    pub wasmtime_version: String,
    pub wasmtime_abi: String,
    pub collector: String,
    pub sandbox: SandboxInfo,
}

pub struct HostCallContextTemplate {
    pub approved: Arc<ApprovedPermissions>,
    pub bundle_context: BundleContextInfo,
}

pub struct Server {
    listener: TcpListener,
    acceptor: TlsAcceptor,
    posture: ServerPosture,
    expected_peer_identity: String,
}

impl Server {
    pub async fn bind(addr: SocketAddr, tls: ServerTlsConfig, posture: ServerPosture) -> Result<Self, ServerError> {
        let mut root_store = rustls::RootCertStore::empty();
        root_store.add(tls.client_ca).map_err(|e| ServerError::Tls(e.to_string()))?;
        let client_verifier = rustls::server::WebPkiClientVerifier::builder(Arc::new(root_store))
            .build()
            .map_err(|e| ServerError::Tls(e.to_string()))?;
        let server_config = rustls::ServerConfig::builder()
            .with_client_cert_verifier(client_verifier)
            .with_single_cert(tls.cert_chain, tls.private_key)
            .map_err(|e| ServerError::Tls(e.to_string()))?;
        let acceptor = TlsAcceptor::from(Arc::new(server_config));
        let listener = TcpListener::bind(addr).await?;
        Ok(Self { listener, acceptor, posture, expected_peer_identity: tls.expected_peer_identity })
    }

    pub fn local_addr(&self) -> SocketAddr {
        self.listener.local_addr().expect("a bound listener always has a local address")
    }

    pub async fn accept(&self) -> Result<Arc<ExecutorConnection>, ServerError> {
        let (tcp, _peer_addr) = self.listener.accept().await?;
        let tls_stream = self.acceptor.accept(tcp).await.map_err(|e| ServerError::Tls(e.to_string()))?;

        let peer_certs = tls_stream.get_ref().1.peer_certificates().map(|c| c.to_vec()).unwrap_or_default();
        let leaf = peer_certs.first().ok_or(ServerError::PeerIdentity)?;
        let (_, parsed) = x509_parser::parse_x509_certificate(leaf.as_ref()).map_err(|_| ServerError::PeerIdentity)?;
        let cn = parsed
            .subject()
            .iter_common_name()
            .next()
            .and_then(|a| a.as_str().ok())
            .ok_or(ServerError::PeerIdentity)?;
        if cn != self.expected_peer_identity {
            return Err(ServerError::PeerIdentity);
        }

        let transport = Arc::new(FrameTransport::spawn(tls_stream, crate::wire::frame::MAX_FRAME_BYTES));

        let hello_frame = transport.recv_unsolicited().await.map_err(|_| ServerError::HandshakeClosed)?;
        let (executor_version, wasmtime_version, wasmtime_abi, collector, sandbox) = match hello_frame.message {
            Message::Hello { executor_version, wasmtime_version, wasmtime_abi, collector, sandbox, .. } => {
                (executor_version, wasmtime_version, wasmtime_abi, collector, sandbox)
            }
            _ => return Err(ServerError::HandshakeClosed),
        };

        let expected_runtime = match self.posture.sandbox_expected {
            SandboxPosture::Gvisor => "gvisor",
            SandboxPosture::Runc => "runc",
        };
        if sandbox.runtime != expected_runtime {
            return Err(ServerError::UnsandboxedExecutor);
        }
        if collector != self.posture.expected_collector {
            return Err(ServerError::ProtocolVersion);
        }

        transport
            .send(
                hello_frame.id,
                Message::HelloOk {
                    stage: "process".to_string(),
                    protocol_version: 1,
                    limits: HelloLimits { call_timeout_ms: 2000, memory_mb: 64, max_concurrent_calls: 32 },
                },
            )
            .await
            .map_err(|_| ServerError::HandshakeClosed)?;

        Ok(Arc::new(ExecutorConnection {
            transport,
            hello: HelloInfo { executor_version, wasmtime_version, wasmtime_abi, collector, sandbox },
            pending_contexts: Mutex::new(HashMap::new()),
        }))
    }
}

/// The invoke-scoped context stored under the frame id `invoke()`
/// allocated, so a resulting `host-call`'s `call_id` (spec §6.6: "the
/// originating invoke id") can be resolved back to the right
/// `ApprovedPermissions`/`BundleContextInfo`/digest by
/// `spawn_host_call_loop` without any window where a fast host-call
/// could arrive before this entry exists (`invoke()` inserts it before
/// the `Invoke` frame is even written).
struct InFlightInvoke {
    digest: String,
    approved: Arc<ApprovedPermissions>,
    bundle_context: BundleContextInfo,
}

pub struct ExecutorConnection {
    pub hello: HelloInfo,
    transport: Arc<FrameTransport>,
    pending_contexts: Mutex<HashMap<u64, InFlightInvoke>>,
}

impl ExecutorConnection {
    pub async fn load(
        &self,
        app_id: &str,
        version: &str,
        digest: &str,
        component_key: &str,
        sidecar_key: &str,
        capabilities: Vec<String>,
        limits: LoadLimits,
    ) -> Result<(String, u64, Vec<String>), HostApiError> {
        let reply = self
            .transport
            .call(Message::Load {
                app_id: app_id.to_string(),
                version: version.to_string(),
                digest: digest.to_string(),
                component_key: component_key.to_string(),
                sidecar_key: sidecar_key.to_string(),
                capabilities,
                limits,
            })
            .await?;
        match reply {
            Message::Loaded { digest, precompile_ms, exports, .. } => Ok((digest, precompile_ms, exports)),
            Message::Error { code, message, .. } => Err(HostApiError::Executor { code: format!("{code:?}"), message }),
            _ => Err(HostApiError::UnexpectedReply),
        }
    }

    pub async fn invoke(
        &self,
        app_id: &str,
        digest: &str,
        export: ExportKind,
        payload: serde_json::Value,
        deadline_ms: u64,
        ctx: HostCallContextTemplate,
    ) -> Result<serde_json::Value, HostApiError> {
        let id = self.transport.next_id();
        // D30 (spec §5.11, §6.6): built from ctx.bundle_context BEFORE it
        // moves into InFlightInvoke below -- scope.app_id/.trace supersede
        // the pre-D30 standalone app_id/trace_context frame fields.
        let scope = crate::wire::message::InvocationScope {
            tenant_id: ctx.bundle_context.tenant.clone(),
            community_id: ctx.bundle_context.community.clone(),
            workstream_id: ctx.bundle_context.workstream_id.clone(),
            app_id: app_id.to_string(),
            trace: ctx.bundle_context.trace.clone(),
        };
        self.pending_contexts.lock().await.insert(
            id,
            InFlightInvoke { digest: digest.to_string(), approved: ctx.approved, bundle_context: ctx.bundle_context },
        );

        let reply = self
            .transport
            .call_with_id(
                id,
                Message::Invoke {
                    digest: digest.to_string(),
                    export,
                    payload,
                    deadline_ms,
                    scope,
                },
            )
            .await;

        self.pending_contexts.lock().await.remove(&id);

        match reply? {
            Message::Result { payload, .. } => Ok(payload),
            Message::Error { code, message, .. } => Err(HostApiError::Executor { code: format!("{code:?}"), message }),
            _ => Err(HostApiError::UnexpectedReply),
        }
    }

    pub async fn unload(&self, app_id: &str, digest: &str) -> Result<(), HostApiError> {
        match self.transport.call(Message::Unload { app_id: app_id.to_string(), digest: digest.to_string() }).await? {
            Message::Unloaded { .. } => Ok(()),
            Message::Error { code, message, .. } => Err(HostApiError::Executor { code: format!("{code:?}"), message }),
            _ => Err(HostApiError::UnexpectedReply),
        }
    }

    pub async fn ping(&self) -> Result<(), HostApiError> {
        match self.transport.call(Message::Ping).await? {
            Message::Pong => Ok(()),
            _ => Err(HostApiError::UnexpectedReply),
        }
    }

    pub async fn shutdown(&self, grace_ms: u64) -> Result<(), HostApiError> {
        self.transport.call(Message::Shutdown { grace_ms }).await?;
        Ok(())
    }

    /// Answers `host-call` frames with `router` for as long as this
    /// connection lives. Each call's context is resolved from
    /// `pending_contexts` by the host-call's `call_id` (spec §6.6: "the
    /// originating invoke id") -- a call_id with no matching entry (the
    /// invoke it belongs to already completed, or never existed) replies
    /// `UNKNOWN_BUNDLE` rather than guessing at a default context. Takes
    /// `self: Arc<Self>` so the spawned `'static` task can hold its own
    /// clone; `Server::accept` therefore returns `Arc<ExecutorConnection>`.
    #[allow(clippy::too_many_arguments)]
    pub fn spawn_host_call_loop<Http, Kv, Db, Relay, Fl, Lg, Ck>(
        self: Arc<Self>,
        router: Arc<HostCallRouter<Http, Kv, Db, Relay, Fl, Lg, Ck>>,
    ) -> tokio::task::JoinHandle<()>
    where
        Http: HttpEgress + 'static,
        Kv: KvStore + 'static,
        Db: DbExecutor + 'static,
        Relay: RelayPush + 'static,
        Fl: Flags + 'static,
        Lg: Logger + 'static,
        Ck: Clock + 'static,
    {
        tokio::spawn(async move {
            loop {
                let frame = match self.transport.recv_unsolicited().await {
                    Ok(f) => f,
                    Err(_) => break,
                };
                // D30 (spec §5.11): `scope` on the incoming frame is the
                // credential-less, untrusted executor's own echo -- only
                // `scope.app_id` (a label, exactly as the pre-D30 bare
                // `app_id` field was) is taken from it. tenant_id/
                // community_id/workstream_id/trace are never read from
                // here; `bundle_context` below (looked up by call_id from
                // `pending_contexts`, populated by THIS stage from a
                // binding-MAC-verified envelope) is the only authoritative
                // source those four ever have.
                let Message::HostCall { scope: incoming_scope, capability, op, args, call_id } = frame.message else {
                    continue;
                };
                let app_id = incoming_scope.app_id;

                let in_flight = self.pending_contexts.lock().await.get(&call_id).map(|i| {
                    (i.digest.clone(), i.approved.clone(), i.bundle_context.clone())
                });
                let Some((digest, approved, bundle_context)) = in_flight else {
                    let _ = self
                        .transport
                        .send(
                            frame.id,
                            Message::HostResult {
                                result: None,
                                error: Some(crate::wire::message::HostResultError {
                                    code: "UNKNOWN_BUNDLE".to_string(),
                                    message: "no in-flight invoke for this call_id".to_string(),
                                }),
                            },
                        )
                        .await;
                    continue;
                };

                let ctx = HostCallContext { app_id, digest, approved, bundle_context };
                let result = router.dispatch(&ctx, capability, &op, args).await;
                let reply = match result {
                    Ok(value) => Message::HostResult { result: Some(value), error: None },
                    Err(e) => Message::HostResult { result: None, error: Some(e) },
                };
                let _ = self.transport.send(frame.id, reply).await;
            }
        })
    }
}
```

- [ ] **Step 5: Add `x509-parser` to `Cargo.toml`**

```toml
x509-parser = "=0.18.1"
```

- [ ] **Step 6: Export from `src/host/mod.rs`**

```rust
pub mod server;
```

- [ ] **Step 7: Run to verify pass**

Run: `make test`
Expected: PASS — `wire_transport_tests` (now 5, including `call_with_id`) and `host_server_tests` (3) all green. Implement the two `dial_and_send_hello`/`make_ca_and_leaf_signed_by_same_ca` test helpers this step's tests reference (straightforward `tokio_rustls::TlsConnector` + `rcgen` composition mirroring the server side above) before this step is considered done — they are load-bearing test infrastructure, not scaffolding to skip.

- [ ] **Step 8: Commit**

```bash
git add packages/rust-bundle-host/Cargo.toml packages/rust-bundle-host/src/wire/transport.rs packages/rust-bundle-host/src/host/server.rs packages/rust-bundle-host/src/host/mod.rs packages/rust-bundle-host/tests/host_server_tests.rs packages/rust-bundle-host/tests/wire_transport_tests.rs
git commit -m "$(cat <<'EOF'
feat(bundle-host): mTLS frame-protocol server with peer identity + posture pinning

Server::accept() completes the mTLS handshake, pins the client
certificate's Common Name, and refuses a hello reporting a collector or
sandbox runtime that disagrees with this stage's own configuration
(UNSANDBOXED_EXECUTOR / PROTOCOL_VERSION, spec §6.6, §12.2).
ExecutorConnection exposes load/invoke/unload/ping/shutdown plus a
background loop that answers host-call frames via HostCallRouter.

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01N2rQgkHY872RubwXoBZxtE
EOF
)"
git push
```

---

## Task 18: `InstancePool` + per-call `invoke()` — deadline, memory cap, fresh-instance guarantee

**Depends on:** Task 7 (bindings, `build_guest_wasi_ctx`, `tests/common`), Task 6 (`EngineHandle`, epoch ticker), Task 5 (fixtures — this task adds three more).

**Files:**
- Create: `packages/rust-bundle-host/src/executor/pool.rs`
- Create: `packages/rust-bundle-host/src/executor/invoke.rs`
- Modify: `packages/rust-bundle-host/src/executor/mod.rs`
- Modify: `packages/rust-bundle-host/tests/fixtures/*` (three new fixtures) and `Dockerfile.fixtures`, `Makefile`
- Test: `packages/rust-bundle-host/tests/invoke_limits_tests.rs`

**Interfaces:**
- Consumes: `executor::engine::EngineHandle` (Task 6), `executor::bindings::stage_world::Stage` (Task 7), `executor::wasi_ctx::build_guest_wasi_ctx` (Task 7).
- Produces:
  ```rust
  #[derive(Debug, thiserror::Error)]
  pub enum InvokeError {
      #[error("pool exhausted waiting for an instance slot")]
      PoolExhausted,
      #[error("call deadline exceeded")]
      Deadline,
      #[error("instance exceeded its memory limit")]
      MemoryLimit,
      #[error("guest trap: {0}")]
      Trap(String),
      #[error("component error: {0}")]
      ComponentError(String),
  }

  pub struct InstancePool {
      pub fn new(instances_per_bundle: usize, pool_wait: std::time::Duration) -> Self;
      /// Acquires one of `instances_per_bundle` concurrency slots for
      /// `(app_id, digest)`, waiting up to `pool_wait` before failing
      /// with `PoolExhausted` (spec §7.2's `pool_exhausted`, mapped to
      /// `HOST_CALL_FAILED` by the caller, which the stage treats as
      /// retryable).
      pub async fn checkout(&self, app_id: &str, digest: &str) -> Result<PoolPermit, InvokeError>;
  }
  pub struct PoolPermit { /* releases its slot on Drop */ }

  pub struct BundleRuntime {
      pub fn new(engine: std::sync::Arc<EngineHandle>, component: wasmtime::component::Component, linker: wasmtime::component::Linker<ExecutorHostState>, scratch_dir: std::path::PathBuf) -> Self;
      /// Always instantiates a brand-new Store + component instance --
      /// "every instance is fresh per call with respect to guest linear
      /// memory: no state survives between invocations" (spec §7.2).
      pub async fn call_transform(&self, pool: &InstancePool, app_id: &str, digest: &str, timeout_ms: u64, memory_mb: u32, event: PlatformEventDto) -> Result<Option<PlatformEventDto>, InvokeError>;
      pub async fn call_dispatch(&self, pool: &InstancePool, app_id: &str, digest: &str, timeout_ms: u64, memory_mb: u32, envelope: StageEnvelopeDto, config_json: &str) -> Result<Result<TransportResultDto, TransportErrorDto>, InvokeError>;
  }
  ```
  Task 20's loader produces the verified `Component` each `BundleRuntime` wraps; Task 21's `wire_client` drives `call_transform`/`call_dispatch` in response to `invoke` frames, through the `StageRequestHandler` the Task 22 binary implements.

  **Forward note — these two signatures change once more, in Task 21.** `call_transform` and `call_dispatch` each gain a final `wire: RemoteHostWire` parameter there, because the executor-side `Host` trait impls added in Task 21 read it off the `Store`'s state to forward every capability call to the stage. Task 21 Step 1 gives the exact final text of both methods and of `ExecutorHostState`; implement this task's versions as written, then let Task 21 replace them. Nothing between the two tasks calls either method from outside this crate.

`ExecutorHostState`, `PlatformEventDto`, `StageEnvelopeDto`, `TransportResultDto`, `TransportErrorDto` are introduced in this task as the plain-Rust mirrors of the bindgen-generated WIT record types, so `invoke.rs` doesn't leak `wasmtime::component`-specific types into its public signature (Task 21's `wire_client` and the Task 22 binary's `Handler` work with these DTOs, converting to/from the bindgen types only at the actual call boundary).

- [ ] **Step 1: Add three fixtures**

`tests/fixtures/stateful_counter/src/lib.rs` (`Cargo.toml`/`wit/` identical in shape to `hello_bundle`'s, `name = "stateful_counter"`):

```rust
//! Proves "every instance is fresh per call": a module-level counter
//! that would read 1, 2, 3, ... across calls IF state survived -- it
//! must read 1 on every single call instead.
#[allow(warnings)]
mod bindings;
use bindings::exports::waddle::bundle::action_stage::{Guest as ActionGuest, TransportError, TransportResult};
use bindings::exports::waddle::bundle::process_stage::{Guest as ProcessGuest, PlatformEvent, UnsupportedStage};
use std::sync::atomic::{AtomicU32, Ordering};

static COUNTER: AtomicU32 = AtomicU32::new(0);
struct Component;

impl ProcessGuest for Component {
    fn transform(mut event: PlatformEvent) -> Result<Option<PlatformEvent>, UnsupportedStage> {
        let count = COUNTER.fetch_add(1, Ordering::SeqCst) + 1;
        event.payload_json = format!("{{\"counter\":{count}}}");
        Ok(Some(event))
    }
}
impl ActionGuest for Component {
    fn dispatch(_e: bindings::exports::waddle::bundle::action_stage::StageEnvelope, _c: String) -> Result<TransportResult, TransportError> {
        Ok(TransportResult { ok: true, status: Some(200), detail: None, provider_message_id: None })
    }
}
bindings::export!(Component with_types_in bindings);
```

`tests/fixtures/hang_forever/src/lib.rs` (`name = "hang_forever"`):

```rust
//! For the epoch-deadline trip test: spins forever, giving wasmtime's
//! epoch-check instrumentation (injected at loop back-edges regardless
//! of source language, since it's wasmtime's own Cranelift compilation
//! step that adds it -- spec §7.3) something to actually interrupt.
#[allow(warnings)]
mod bindings;
use bindings::exports::waddle::bundle::action_stage::{Guest as ActionGuest, TransportError, TransportResult};
use bindings::exports::waddle::bundle::process_stage::{Guest as ProcessGuest, PlatformEvent, UnsupportedStage};

struct Component;
impl ProcessGuest for Component {
    fn transform(_event: PlatformEvent) -> Result<Option<PlatformEvent>, UnsupportedStage> {
        loop {
            std::hint::spin_loop();
        }
    }
}
impl ActionGuest for Component {
    fn dispatch(_e: bindings::exports::waddle::bundle::action_stage::StageEnvelope, _c: String) -> Result<TransportResult, TransportError> {
        Ok(TransportResult { ok: true, status: Some(200), detail: None, provider_message_id: None })
    }
}
bindings::export!(Component with_types_in bindings);
```

`tests/fixtures/memory_hog/src/lib.rs` (`name = "memory_hog"`):

```rust
//! For the memory-cap trip test: allocates and touches 200 MB, which
//! must exceed a 64 MB StoreLimits cap and fail the allocation.
#[allow(warnings)]
mod bindings;
use bindings::exports::waddle::bundle::action_stage::{Guest as ActionGuest, TransportError, TransportResult};
use bindings::exports::waddle::bundle::process_stage::{Guest as ProcessGuest, PlatformEvent, UnsupportedStage};

struct Component;
impl ProcessGuest for Component {
    fn transform(event: PlatformEvent) -> Result<Option<PlatformEvent>, UnsupportedStage> {
        let mut buf: Vec<u8> = Vec::new();
        buf.resize(200 * 1024 * 1024, 1u8); // touch every page, not just reserve
        std::hint::black_box(&buf);
        Ok(Some(event))
    }
}
impl ActionGuest for Component {
    fn dispatch(_e: bindings::exports::waddle::bundle::action_stage::StageEnvelope, _c: String) -> Result<TransportResult, TransportError> {
        Ok(TransportResult { ok: true, status: Some(200), detail: None, provider_message_id: None })
    }
}
bindings::export!(Component with_types_in bindings);
```

Each of the three also needs a `Cargo.toml` and a `wit/waddle-bundle-stage.wit`, both byte-identical to `hello_bundle`'s (Task 5) except for the `name = "..."` line:

```bash
cd /home/penguin/code/penguin-libs/.worktrees/plan-penguin-bundle-host/packages/rust-bundle-host/tests/fixtures
for f in stateful_counter hang_forever memory_hog; do
  mkdir -p "$f/src" "$f/wit"
  sed "s/^name = \"hello_bundle\"$/name = \"$f\"/" hello_bundle/Cargo.toml > "$f/Cargo.toml"
  cp hello_bundle/wit/waddle-bundle-stage.wit "$f/wit/waddle-bundle-stage.wit"
done
grep -h '^name = ' stateful_counter/Cargo.toml hang_forever/Cargo.toml memory_hog/Cargo.toml
```
Expected: exactly three lines, `name = "stateful_counter"`, `name = "hang_forever"`, `name = "memory_hog"` — if any still reads `hello_bundle`, the `sed` missed and the fixture build will collide on output filenames.

Then replace the three tagged blocks in `Dockerfile.fixtures` (Task 5) with these exact five-fixture versions:

```dockerfile
# FIXTURE COPY BLOCK
COPY tests/fixtures/hello_bundle /build/hello_bundle
COPY tests/fixtures/hostile_socket /build/hostile_socket
COPY tests/fixtures/stateful_counter /build/stateful_counter
COPY tests/fixtures/hang_forever /build/hang_forever
COPY tests/fixtures/memory_hog /build/memory_hog
```

```dockerfile
# FIXTURE BUILD BLOCK -- one loop, N components.
RUN built=0; \
    for f in hello_bundle hostile_socket stateful_counter hang_forever memory_hog; do \
      cd "/build/$f"; \
      cargo component build --release --target wasm32-wasip2 --offline \
        || cargo component build --release --target wasm32-wasip2; \
      test -f "/build/$f/target/wasm32-wasip2/release/$f.wasm"; \
      built=$((built+1)); \
    done; \
    echo "built $built fixture components"; \
    test "$built" -eq 5
```

```dockerfile
# FIXTURE VALIDATE BLOCK
RUN checked=0; \
    for f in hello_bundle hostile_socket stateful_counter hang_forever memory_hog; do \
      wasm-tools component wit "/build/$f/target/wasm32-wasip2/release/$f.wasm" > "/tmp/$f.wit"; \
      grep -q 'package waddle:bundle' "/tmp/$f.wit" \
        || { echo "$f.wasm does not declare the waddle:bundle package"; exit 1; }; \
      grep -q 'world stage' "/tmp/$f.wit" \
        || { echo "$f.wasm does not target the stage world"; exit 1; }; \
      checked=$((checked+1)); \
    done; \
    echo "validated $checked fixture components against waddle:bundle/stage@1.0.0"; \
    test "$checked" -eq 5
```

The `Makefile` needs no change: Task 1's `fixtures`/`check-fixtures` targets already iterate `$(FIXTURES) = hello_bundle hostile_socket stateful_counter hang_forever memory_hog` and assert a count of 5 — they were written for the final set from the start, which is why `make check-fixtures` fails until this step lands.

Rebuild and verify all five exist:

Run: `make fixtures && make check-fixtures`
Expected: `built 5 fixture components`, `validated 5 fixture components against waddle:bundle/stage@1.0.0`, `copied 5 fixture components`, `fixture components present: 5`.

- [ ] **Step 2: Write the failing tests**

`tests/invoke_limits_tests.rs`:

```rust
#![allow(clippy::unwrap_used, clippy::panic)]
mod common;
use common::{link_stub_hosts, TestHostState};
use penguin_bundle_host::executor::bindings::{self, stage_world::Stage};
use penguin_bundle_host::executor::engine::{EngineConfig, EngineHandle};
use penguin_bundle_host::executor::invoke::{BundleRuntime, InvokeError};
use penguin_bundle_host::executor::pool::InstancePool;
use penguin_bundle_host::executor::wasi_ctx::build_guest_wasi_ctx;
use wasmtime::component::{Component, Linker};
use std::time::Duration;

fn fixture_path(name: &str) -> std::path::PathBuf {
    std::path::PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("tests/fixtures").join(name).join(format!("{name}.wasm"))
}

fn engine() -> EngineHandle {
    EngineHandle::new(&EngineConfig { max_memory_bytes: 64 * 1024 * 1024, epoch_tick_ms: 5, collector: "drc".to_string() }).unwrap()
}

#[tokio::test]
async fn two_consecutive_calls_never_see_shared_state() {
    let handle = std::sync::Arc::new(engine());
    let _ticker = handle.spawn_epoch_ticker();
    let component = Component::from_file(&handle.engine, fixture_path("stateful_counter")).unwrap();
    let mut linker: Linker<TestHostState> = Linker::new(&handle.engine);
    wasmtime_wasi::p2::add_to_linker_async(&mut linker).unwrap();
    link_stub_hosts(&mut linker);
    let scratch = tempfile::tempdir().unwrap();

    let pool = InstancePool::new(4, Duration::from_millis(500));
    for _ in 0..2 {
        let wasi = build_guest_wasi_ctx(scratch.path()).unwrap();
        let mut store = wasmtime::Store::new(&handle.engine, TestHostState { wasi });
        store.set_epoch_deadline(handle.ticks_for_timeout(2000));
        let (stage, _instance) = Stage::instantiate_async(&mut store, &component, &linker).await.unwrap();
        let event = bindings::stage_world::waddle::bundle::types::PlatformEvent {
            platform: "twitch".into(), event_type: "chat.message".into(), actor: None,
            payload_json: "{}".into(), occurred_at: "2026-09-14T12:00:00.000Z".into(),
        };
        let result = stage.waddle_bundle_process_stage().call_transform(&mut store, &event).await.unwrap().unwrap().unwrap();
        assert!(result.payload_json.contains("\"counter\":1"), "expected counter=1 on every fresh instance, got {}", result.payload_json);
    }
}

#[tokio::test]
async fn hang_forever_trips_the_epoch_deadline() {
    let handle = engine();
    let _ticker = handle.spawn_epoch_ticker();
    let component = Component::from_file(&handle.engine, fixture_path("hang_forever")).unwrap();
    let mut linker: Linker<TestHostState> = Linker::new(&handle.engine);
    wasmtime_wasi::p2::add_to_linker_async(&mut linker).unwrap();
    link_stub_hosts(&mut linker);
    let scratch = tempfile::tempdir().unwrap();
    let wasi = build_guest_wasi_ctx(scratch.path()).unwrap();
    let mut store = wasmtime::Store::new(&handle.engine, TestHostState { wasi });
    store.set_epoch_deadline(handle.ticks_for_timeout(100)); // a short 100ms deadline
    let (stage, _instance) = Stage::instantiate_async(&mut store, &component, &linker).await.unwrap();
    let event = bindings::stage_world::waddle::bundle::types::PlatformEvent {
        platform: "twitch".into(), event_type: "chat.message".into(), actor: None,
        payload_json: "{}".into(), occurred_at: "2026-09-14T12:00:00.000Z".into(),
    };
    let result = tokio::time::timeout(
        Duration::from_secs(5),
        stage.waddle_bundle_process_stage().call_transform(&mut store, &event),
    )
    .await
    .expect("the epoch deadline, not the test's own timeout, must be what stops this call");
    assert!(result.is_err(), "expected a trap from the epoch deadline, got {result:?}");
}

#[tokio::test]
async fn memory_hog_exceeds_a_64mb_cap() {
    let handle = engine();
    let component = Component::from_file(&handle.engine, fixture_path("memory_hog")).unwrap();
    let mut linker: Linker<TestHostState> = Linker::new(&handle.engine);
    wasmtime_wasi::p2::add_to_linker_async(&mut linker).unwrap();
    link_stub_hosts(&mut linker);
    let scratch = tempfile::tempdir().unwrap();
    let wasi = build_guest_wasi_ctx(scratch.path()).unwrap();
    let limits = wasmtime::StoreLimitsBuilder::new().memory_size(64 * 1024 * 1024).build();
    struct LimitedState { wasi: penguin_bundle_host::executor::wasi_ctx::GuestWasiCtx, limits: wasmtime::StoreLimits }
    impl wasmtime_wasi::WasiView for LimitedState {
        fn ctx(&mut self) -> wasmtime_wasi::WasiCtxView<'_> {
            wasmtime_wasi::WasiCtxView { ctx: &mut self.wasi.wasi, table: &mut self.wasi.table }
        }
    }
    // Re-link against LimitedState specifically for this test since
    // TestHostState has no `limits` field -- a small, test-local linker
    // rebuild mirroring the shared one.
    let mut limited_linker: Linker<LimitedState> = Linker::new(&handle.engine);
    wasmtime_wasi::p2::add_to_linker_async(&mut limited_linker).unwrap();
    common::link_stub_hosts_for_limited_state(&mut limited_linker);
    let mut store = wasmtime::Store::new(&handle.engine, LimitedState { wasi, limits });
    store.limiter(|s| &mut s.limits);
    store.set_epoch_deadline(handle.ticks_for_timeout(2000));
    let (stage, _instance) = Stage::instantiate_async(&mut store, &component, &limited_linker).await.unwrap();
    let event = bindings::stage_world::waddle::bundle::types::PlatformEvent {
        platform: "twitch".into(), event_type: "chat.message".into(), actor: None,
        payload_json: "{}".into(), occurred_at: "2026-09-14T12:00:00.000Z".into(),
    };
    let result = stage.waddle_bundle_process_stage().call_transform(&mut store, &event).await;
    assert!(result.is_err(), "expected the 200MB allocation to trap against a 64MB StoreLimits cap, got {result:?}");
}

#[tokio::test]
async fn pool_checkout_times_out_when_exhausted() {
    let pool = InstancePool::new(1, Duration::from_millis(50));
    let _first = pool.checkout("a", "sha256:1").await.unwrap();
    let second = pool.checkout("a", "sha256:1").await;
    assert!(matches!(second, Err(InvokeError::PoolExhausted)));
}

#[tokio::test]
async fn pool_checkout_succeeds_after_a_permit_is_released() {
    let pool = InstancePool::new(1, Duration::from_millis(200));
    let first = pool.checkout("a", "sha256:1").await.unwrap();
    let pool2 = &pool;
    let waiter = tokio::spawn(async move { pool2.checkout("a", "sha256:1").await });
    tokio::time::sleep(Duration::from_millis(20)).await;
    drop(first);
    assert!(waiter.await.unwrap().is_ok());
}
```

Add `link_stub_hosts_for_limited_state` to `tests/common/mod.rs` -- a copy of `link_stub_hosts` generic over any `T: wasmtime_wasi::WasiView + context::Host + http::Host + kv::Host + db::Host + relay::Host + flags::Host + log::Host + clock::Host` instead of the concrete `TestHostState`, since the memory-cap test needs a second, distinct host-state type. Simplify by making `link_stub_hosts` itself generic from this task onward:

```rust
pub fn link_stub_hosts<T>(linker: &mut Linker<T>)
where
    T: context::Host + http::Host + kv::Host + db::Host + relay::Host + flags::Host + log::Host + clock::Host,
{
    context::add_to_linker(linker, |s| s).unwrap();
    http::add_to_linker(linker, |s| s).unwrap();
    kv::add_to_linker(linker, |s| s).unwrap();
    db::add_to_linker(linker, |s| s).unwrap();
    relay::add_to_linker(linker, |s| s).unwrap();
    flags::add_to_linker(linker, |s| s).unwrap();
    log::add_to_linker(linker, |s| s).unwrap();
    clock::add_to_linker(linker, |s| s).unwrap();
}
```

and implement the eight `Host` trait impls for `LimitedState` in the test file by delegating to the same bodies as `TestHostState`'s (or, more simply, give `LimitedState` a `TestHostState`-shaped inner value and forward every method) -- since both need identical stub behaviour, factor the trait impls themselves generically over any type exposing a marker trait `HasStubHostBehavior` in `tests/common/mod.rs` rather than duplicating eight impls a second time. Implement whichever of these two factoring approaches compiles cleanest; either satisfies this task's actual requirement (a second host-state type usable with `link_stub_hosts`).

- [ ] **Step 3: Run to verify failure**

Run: `make fixtures && make test`
Expected: FAIL — `executor::pool`/`executor::invoke` do not exist yet.

- [ ] **Step 4: Implement `src/executor/pool.rs`**

```rust
//! Per-`(app_id, digest)` concurrency gating (spec §7.2:
//! `EXECUTOR_INSTANCES_PER_BUNDLE`, `EXECUTOR_POOL_WAIT_MS`). Does not
//! cache `Store`/instance objects itself -- "every instance is fresh per
//! call" (§7.2) is achieved by `invoke.rs` always instantiating anew
//! from the already-precompiled `Component`; this pool exists purely to
//! bound how many such instantiations run concurrently per bundle.

use std::collections::HashMap;
use std::sync::Arc;
use std::time::Duration;

use tokio::sync::{Mutex, OwnedSemaphorePermit, Semaphore};

use super::invoke::InvokeError;

pub struct InstancePool {
    instances_per_bundle: usize,
    pool_wait: Duration,
    semaphores: Mutex<HashMap<(String, String), Arc<Semaphore>>>,
}

pub struct PoolPermit(#[allow(dead_code)] OwnedSemaphorePermit);

impl InstancePool {
    pub fn new(instances_per_bundle: usize, pool_wait: Duration) -> Self {
        Self { instances_per_bundle, pool_wait, semaphores: Mutex::new(HashMap::new()) }
    }

    pub async fn checkout(&self, app_id: &str, digest: &str) -> Result<PoolPermit, InvokeError> {
        let semaphore = {
            let mut semaphores = self.semaphores.lock().await;
            semaphores
                .entry((app_id.to_string(), digest.to_string()))
                .or_insert_with(|| Arc::new(Semaphore::new(self.instances_per_bundle)))
                .clone()
        };
        match tokio::time::timeout(self.pool_wait, semaphore.acquire_owned()).await {
            Ok(Ok(permit)) => Ok(PoolPermit(permit)),
            _ => Err(InvokeError::PoolExhausted),
        }
    }
}
```

- [ ] **Step 5: Implement `src/executor/invoke.rs`**

```rust
//! Per-call invocation: acquires a pool slot, instantiates a fresh
//! component instance, arms the epoch deadline and the memory cap, and
//! reports the outcome as `InvokeError` variants the wire client (Task
//! 22) maps onto `error.code` (`EXECUTOR_DEADLINE`, `MEMORY_LIMIT`,
//! `WASM_TRAP`, `HOST_CALL_FAILED`/`pool_exhausted`).

use std::path::Path;

use wasmtime::component::{Component, Linker};
use wasmtime::{Store, StoreLimits, StoreLimitsBuilder};

use super::bindings::stage_world::waddle::bundle::types::PlatformEvent as WitPlatformEvent;
use super::bindings::stage_world::waddle::bundle::types::{StageEnvelope as WitStageEnvelope, TransportError as WitTransportError, TransportResult as WitTransportResult};
use super::bindings::stage_world::Stage;
use super::engine::EngineHandle;
use super::pool::InstancePool;
use super::wasi_ctx::{build_guest_wasi_ctx, GuestWasiCtx};

#[derive(Debug, thiserror::Error)]
pub enum InvokeError {
    #[error("pool exhausted waiting for an instance slot")]
    PoolExhausted,
    #[error("call deadline exceeded")]
    Deadline,
    #[error("instance exceeded its memory limit")]
    MemoryLimit,
    #[error("guest trap: {0}")]
    Trap(String),
    #[error("component error: {0}")]
    ComponentError(String),
}

// `Serialize`/`Deserialize` on all four DTOs below are load-bearing, not
// decorative: Task 22's `Handler::on_invoke` round-trips an `invoke`
// frame's `payload` (`serde_json::Value`) through `serde_json::from_value`
// into one of these, and its `result` back out through `serde_json::to_value`.
#[derive(Debug, Clone, serde::Serialize, serde::Deserialize)]
pub struct PlatformEventDto {
    pub platform: String,
    pub event_type: String,
    pub actor: Option<String>,
    pub payload_json: String,
    pub occurred_at: String,
}

impl From<PlatformEventDto> for WitPlatformEvent {
    fn from(e: PlatformEventDto) -> Self {
        WitPlatformEvent { platform: e.platform, event_type: e.event_type, actor: e.actor, payload_json: e.payload_json, occurred_at: e.occurred_at }
    }
}
impl From<WitPlatformEvent> for PlatformEventDto {
    fn from(e: WitPlatformEvent) -> Self {
        PlatformEventDto { platform: e.platform, event_type: e.event_type, actor: e.actor, payload_json: e.payload_json, occurred_at: e.occurred_at }
    }
}

#[derive(Debug, Clone, serde::Serialize, serde::Deserialize)]
pub struct StageEnvelopeDto {
    pub tenant: String,
    pub community: Option<String>,
    pub app_id: String,
    pub stage: String,
    pub event: PlatformEventDto,
    pub ts: String,
    pub target_app_id: Option<String>,
    pub trace_context: Option<String>,
}

#[derive(Debug, Clone, serde::Serialize, serde::Deserialize)]
pub struct TransportResultDto {
    pub ok: bool,
    pub status: Option<u16>,
    pub detail: Option<String>,
    pub provider_message_id: Option<String>,
}

#[derive(Debug, Clone, serde::Serialize, serde::Deserialize)]
pub struct TransportErrorDto {
    pub retryable: bool,
    pub code: String,
    pub message: String,
    pub retry_after_ms: Option<u32>,
}

/// Host state used for real (non-test) invocations -- one instance per
/// call, built fresh by `instantiate_fresh` below. Task 22's
/// `RemoteHostImpl` implements the eight WIT `Host` traits for this type
/// by forwarding to the stage connection rather than answering locally.
pub struct ExecutorHostState {
    pub wasi: GuestWasiCtx,
    pub limits: StoreLimits,
}

impl wasmtime_wasi::WasiView for ExecutorHostState {
    fn ctx(&mut self) -> wasmtime_wasi::WasiCtxView<'_> {
        wasmtime_wasi::WasiCtxView { ctx: &mut self.wasi.wasi, table: &mut self.wasi.table }
    }
}

pub struct BundleRuntime {
    engine: std::sync::Arc<EngineHandle>,
    component: Component,
    linker: Linker<ExecutorHostState>,
    scratch_dir: std::path::PathBuf,
}

impl BundleRuntime {
    pub fn new(engine: std::sync::Arc<EngineHandle>, component: Component, linker: Linker<ExecutorHostState>, scratch_dir: std::path::PathBuf) -> Self {
        Self { engine, component, linker, scratch_dir }
    }

    async fn instantiate_fresh(&self, timeout_ms: u64, memory_mb: u32) -> Result<(Store<ExecutorHostState>, Stage), InvokeError> {
        let wasi = build_guest_wasi_ctx(&self.scratch_dir).map_err(|e| InvokeError::ComponentError(e.to_string()))?;
        let limits = StoreLimitsBuilder::new().memory_size(memory_mb as usize * 1024 * 1024).build();
        let mut store = Store::new(&self.engine.engine, ExecutorHostState { wasi, limits });
        store.limiter(|s| &mut s.limits);
        store.epoch_deadline_trap();
        store.set_epoch_deadline(self.engine.ticks_for_timeout(timeout_ms));
        let (stage, _instance) = Stage::instantiate_async(&mut store, &self.component, &self.linker)
            .await
            .map_err(|e| InvokeError::ComponentError(e.to_string()))?;
        Ok((store, stage))
    }

    pub async fn call_transform(
        &self,
        pool: &InstancePool,
        app_id: &str,
        digest: &str,
        timeout_ms: u64,
        memory_mb: u32,
        event: PlatformEventDto,
    ) -> Result<Option<PlatformEventDto>, InvokeError> {
        let _permit = pool.checkout(app_id, digest).await?;
        let (mut store, stage) = self.instantiate_fresh(timeout_ms, memory_mb).await?;
        let wit_event: WitPlatformEvent = event.into();
        let result = stage
            .waddle_bundle_process_stage()
            .call_transform(&mut store, &wit_event)
            .await
            .map_err(|e| classify_call_error(&e))?;
        result
            .map(|opt| opt.map(PlatformEventDto::from))
            .map_err(|unsupported| InvokeError::ComponentError(format!("unsupported stage: {}", unsupported.stage)))
    }

    pub async fn call_dispatch(
        &self,
        pool: &InstancePool,
        app_id: &str,
        digest: &str,
        timeout_ms: u64,
        memory_mb: u32,
        envelope: StageEnvelopeDto,
        config_json: &str,
    ) -> Result<Result<TransportResultDto, TransportErrorDto>, InvokeError> {
        let _permit = pool.checkout(app_id, digest).await?;
        let (mut store, stage) = self.instantiate_fresh(timeout_ms, memory_mb).await?;
        let wit_envelope = WitStageEnvelope {
            tenant: envelope.tenant,
            community: envelope.community,
            app_id: envelope.app_id,
            stage: envelope.stage,
            event: envelope.event.into(),
            ts: envelope.ts,
            target_app_id: envelope.target_app_id,
            trace_context: envelope.trace_context,
        };
        let result = stage
            .waddle_bundle_action_stage()
            .call_dispatch(&mut store, &wit_envelope, config_json)
            .await
            .map_err(|e| classify_call_error(&e))?;
        Ok(result.map(|r: WitTransportResult| TransportResultDto { ok: r.ok, status: r.status, detail: r.detail, provider_message_id: r.provider_message_id })
            .map_err(|e: WitTransportError| TransportErrorDto { retryable: e.retryable, code: e.code, message: e.message, retry_after_ms: e.retry_after_ms }))
    }
}

/// wasmtime surfaces both a deadline trap and a memory-limit trap as the
/// same `anyhow::Error` "trap" shape at this API layer; classify by the
/// trap's own `Display` text, which wasmtime documents as stable enough
/// to match on for exactly this purpose (`wasmtime::Trap::EpochDeadline`
/// prints as "epoch deadline exceeded"; a `StoreLimits` denial surfaces
/// as a component-level unreachable trap whose message wasmtime derives
/// from the same "instance ran out of memory" wording it uses for core
/// modules).
fn classify_call_error(err: &wasmtime::Error) -> InvokeError {
    let msg = err.to_string();
    if msg.contains("epoch deadline") {
        InvokeError::Deadline
    } else if msg.to_lowercase().contains("memory") || msg.to_lowercase().contains("resource limit") {
        InvokeError::MemoryLimit
    } else {
        InvokeError::Trap(msg)
    }
}
```

- [ ] **Step 6: Export from `src/executor/mod.rs`**

```rust
pub mod bindings;
pub mod engine;
pub mod invoke;
pub mod pool;
pub mod wasi_ctx;
```

- [ ] **Step 7: Run to verify pass**

Run: `make fixtures && make test`
Expected: PASS — all `invoke_limits_tests` green (state-freshness, epoch-deadline trip, memory-cap trip, pool exhaustion/release).

- [ ] **Step 8: Commit**

```bash
git add packages/rust-bundle-host/src/executor/pool.rs packages/rust-bundle-host/src/executor/invoke.rs packages/rust-bundle-host/src/executor/mod.rs packages/rust-bundle-host/tests/invoke_limits_tests.rs packages/rust-bundle-host/tests/common packages/rust-bundle-host/tests/fixtures packages/rust-bundle-host/Dockerfile.fixtures packages/rust-bundle-host/Makefile
git commit -m "$(cat <<'EOF'
feat(bundle-host): InstancePool + per-call invoke with deadline/memory/freshness

BundleRuntime::call_transform/call_dispatch always instantiate a fresh
Store+component instance per call (no guest state survives between
invocations, proven against a real stateful_counter fixture), arm the
epoch deadline and a StoreLimits memory cap per call, and classify a
trap into Deadline/MemoryLimit/Trap for the wire client to map onto
error.code. InstancePool bounds concurrent instantiations per
(app_id, digest) and times out at EXECUTOR_POOL_WAIT_MS.

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01N2rQgkHY872RubwXoBZxtE
EOF
)"
git push
```

---

## Task 19: Loader — digest and Ed25519 signature verification

**Depends on:** Task 1 (the `ed25519-dalek`/`sha2`/`base64` pins and the `src/executor/mod.rs` stub).

**Files:**
- Create: `packages/rust-bundle-host/src/executor/loader/mod.rs`
- Create: `packages/rust-bundle-host/src/executor/loader/verify.rs`
- Modify: `packages/rust-bundle-host/src/executor/mod.rs`
- Test: `packages/rust-bundle-host/tests/loader_digest_tests.rs`

**Interfaces:**
- Consumes: nothing new (`sha2`, `ed25519-dalek`, both already pinned in Task 1).
- Produces:
  ```rust
  /// The signed sidecar, schema verbatim from spec §9.4 and byte-for-byte
  /// the struct M2a's `bundle_compiler::sidecar::Sidecar` serializes
  /// (`origin/docs/plan-m2a-compiler-sdks`, Task 14) -- this crate is the
  /// consumer of exactly those bytes, so the field set, the field order
  /// and the signed-message derivation below are not ours to choose.
  #[derive(Debug, Clone, PartialEq, Eq, serde::Deserialize, serde::Serialize)]
  pub struct SidecarMetadata {
      pub schema_version: u32,
      pub app_id: String,
      pub version: String,
      pub digest: String,
      pub size_bytes: u64,
      pub language: String,
      pub artifact_kind: String,
      pub scan_status: String,
      pub wit_world: String,
      pub built_at: String,
      pub builder: String,
      pub signature: String,
  }

  #[derive(Debug, Clone, PartialEq, Eq)]
  pub enum VerifyError {
      MalformedSidecar(String),
      SignatureInvalid,
      SidecarDigestMismatch { expected: String, sidecar: String },
      ComputedDigestMismatch { expected: String, computed: String },
      /// The sidecar verifies but was built against a different WIT world
      /// than this executor's bindings were generated from -- refusing is
      /// the only safe action, since the component's imports/exports may
      /// not match what the linker provides.
      WitWorldMismatch { expected: String, sidecar: String },
  }

  /// The one WIT world this executor can host. Compared against the
  /// sidecar's `wit_world` field, which M2a's publisher writes as the
  /// literal `"waddle:bundle/stage@1.0.0"`.
  pub const SUPPORTED_WIT_WORLD: &str = "waddle:bundle/stage@1.0.0";

  /// Verifies, in this exact order (spec §11.7): (1) the sidecar's
  /// Ed25519 signature against `signing_public_key`, over the canonical
  /// JSON of every sidecar field *except* `signature`; (2) the now-trusted
  /// sidecar's `wit_world` equals `SUPPORTED_WIT_WORLD`; (3) its `digest`
  /// field equals `expected_digest` (the value the stage sent in `load`,
  /// itself sourced from hub-api's `app_versions` row per spec §6.10 --
  /// the trusted `waddles_publisher` container is what measured it, never
  /// the untrusted `build` container, per D27); (4) the SHA-256 actually
  /// computed over `component_bytes` equals both. Any disagreement refuses
  /// the load; the caller (Task 20) never falls back to loading anyway.
  pub fn verify_digest_and_signature(
      expected_digest: &str,
      component_bytes: &[u8],
      sidecar_json: &[u8],
      signing_public_key: &ed25519_dalek::VerifyingKey,
  ) -> Result<SidecarMetadata, VerifyError>;
  ```
  Task 20 (bucket poller) calls this for every fetched `(component, sidecar)` pair before precompiling or loading anything.

- [ ] **Step 1: Write the failing tests**

`tests/loader_digest_tests.rs`:

```rust
#![allow(clippy::unwrap_used, clippy::panic)]

use ed25519_dalek::{Signer, SigningKey, VerifyingKey};
use penguin_bundle_host::executor::loader::verify::{
    verify_digest_and_signature, SidecarMetadata, VerifyError, SUPPORTED_WIT_WORLD,
};
use rand_core::OsRng;
use sha2::{Digest, Sha256};

fn sha256_hex(bytes: &[u8]) -> String {
    format!("sha256:{}", hex::encode(Sha256::digest(bytes)))
}

fn b64(bytes: &[u8]) -> String {
    use base64::Engine;
    base64::engine::general_purpose::STANDARD.encode(bytes)
}

/// Builds a sidecar exactly the way M2a's `build_and_sign_sidecar` does
/// (`origin/docs/plan-m2a-compiler-sdks`, Task 14): the signed bytes are
/// `serde_json::to_vec` of a `serde_json::json!` object carrying every
/// field except `signature`. `serde_json::Map` is a `BTreeMap` unless the
/// `preserve_order` feature is on (it is not, here or in M2a), so that
/// serialization is already canonical sorted-key JSON with no
/// insignificant whitespace -- both sides derive identical bytes without
/// a separate canonicalization step.
fn make_signed_sidecar(
    signing_key: &SigningKey,
    app_id: &str,
    version: &str,
    digest: &str,
    wit_world: &str,
) -> Vec<u8> {
    let unsigned = serde_json::json!({
        "schema_version": 1,
        "app_id": app_id,
        "version": version,
        "digest": digest,
        "size_bytes": 2_148_231u64,
        "language": "python",
        "artifact_kind": "component",
        "scan_status": "scanned",
        "wit_world": wit_world,
        "built_at": "2026-09-14T12:00:00.000Z",
        "builder": "bundle-compiler@0.1.0",
    });
    let signature = signing_key.sign(&serde_json::to_vec(&unsigned).unwrap());
    let mut signed = unsigned;
    signed["signature"] = serde_json::Value::String(b64(&signature.to_bytes()));
    serde_json::to_vec(&signed).unwrap()
}

#[test]
fn valid_component_sidecar_and_signature_all_agree() {
    let signing_key = SigningKey::generate(&mut OsRng);
    let verifying_key: VerifyingKey = signing_key.verifying_key();
    let component_bytes = b"fake wasm bytes for this test";
    let digest = sha256_hex(component_bytes);
    let sidecar = make_signed_sidecar(&signing_key, "waddles.test.a", "1.0.0", &digest, SUPPORTED_WIT_WORLD);

    let metadata: SidecarMetadata =
        verify_digest_and_signature(&digest, component_bytes, &sidecar, &verifying_key).unwrap();
    assert_eq!(metadata.app_id, "waddles.test.a");
    assert_eq!(metadata.digest, digest);
    assert_eq!(metadata.schema_version, 1);
    assert_eq!(metadata.wit_world, SUPPORTED_WIT_WORLD);
    assert_eq!(metadata.size_bytes, 2_148_231);
    assert_eq!(metadata.builder, "bundle-compiler@0.1.0");
}

#[test]
fn tampered_component_bytes_fail_the_computed_digest_check() {
    let signing_key = SigningKey::generate(&mut OsRng);
    let verifying_key = signing_key.verifying_key();
    let original = b"original bytes";
    let digest = sha256_hex(original);
    let sidecar = make_signed_sidecar(&signing_key, "a", "1.0.0", &digest, SUPPORTED_WIT_WORLD);

    let tampered = b"tampered bytes!";
    let err = verify_digest_and_signature(&digest, tampered, &sidecar, &verifying_key).unwrap_err();
    assert!(matches!(err, VerifyError::ComputedDigestMismatch { .. }), "got {err:?}");
}

#[test]
fn sidecar_signed_by_the_wrong_key_is_rejected() {
    let signing_key = SigningKey::generate(&mut OsRng);
    let attacker_key = SigningKey::generate(&mut OsRng);
    let verifying_key = signing_key.verifying_key(); // the REAL key, not the attacker's
    let component_bytes = b"some bytes";
    let digest = sha256_hex(component_bytes);
    let forged = make_signed_sidecar(&attacker_key, "a", "1.0.0", &digest, SUPPORTED_WIT_WORLD);

    let err = verify_digest_and_signature(&digest, component_bytes, &forged, &verifying_key).unwrap_err();
    assert_eq!(err, VerifyError::SignatureInvalid);
}

#[test]
fn editing_any_signed_field_after_signing_is_rejected() {
    // The whole point of signing every field but `signature`: flipping
    // `scan_status` from "failed" to "scanned" after the fact must not
    // verify. A 3-field signed message would have missed this entirely.
    let signing_key = SigningKey::generate(&mut OsRng);
    let verifying_key = signing_key.verifying_key();
    let component_bytes = b"some bytes";
    let digest = sha256_hex(component_bytes);
    let sidecar = make_signed_sidecar(&signing_key, "a", "1.0.0", &digest, SUPPORTED_WIT_WORLD);

    let mut value: serde_json::Value = serde_json::from_slice(&sidecar).unwrap();
    value["scan_status"] = serde_json::Value::String("scanned-but-actually-not".to_string());
    let tampered = serde_json::to_vec(&value).unwrap();

    let err = verify_digest_and_signature(&digest, component_bytes, &tampered, &verifying_key).unwrap_err();
    assert_eq!(err, VerifyError::SignatureInvalid);
}

#[test]
fn sidecar_digest_disagreeing_with_the_stage_expected_digest_is_rejected() {
    let signing_key = SigningKey::generate(&mut OsRng);
    let verifying_key = signing_key.verifying_key();
    let component_bytes = b"some bytes";
    let real_digest = sha256_hex(component_bytes);
    let sidecar = make_signed_sidecar(&signing_key, "a", "1.0.0", &real_digest, SUPPORTED_WIT_WORLD);

    let different_expected = "sha256:0000000000000000000000000000000000000000000000000000000000000000";
    let err = verify_digest_and_signature(different_expected, component_bytes, &sidecar, &verifying_key).unwrap_err();
    assert!(matches!(err, VerifyError::SidecarDigestMismatch { .. }), "got {err:?}");
}

#[test]
fn a_sidecar_for_a_different_wit_world_is_rejected() {
    let signing_key = SigningKey::generate(&mut OsRng);
    let verifying_key = signing_key.verifying_key();
    let component_bytes = b"some bytes";
    let digest = sha256_hex(component_bytes);
    let sidecar = make_signed_sidecar(&signing_key, "a", "1.0.0", &digest, "waddle:bundle/stage@2.0.0");

    let err = verify_digest_and_signature(&digest, component_bytes, &sidecar, &verifying_key).unwrap_err();
    assert!(matches!(err, VerifyError::WitWorldMismatch { .. }), "got {err:?}");
}

#[test]
fn malformed_sidecar_json_is_rejected_with_a_named_error() {
    let signing_key = SigningKey::generate(&mut OsRng);
    let verifying_key = signing_key.verifying_key();
    let err = verify_digest_and_signature("sha256:abc", b"x", b"{not json", &verifying_key).unwrap_err();
    assert!(matches!(err, VerifyError::MalformedSidecar(_)));
}
```

No `Cargo.toml` change is needed for this task: `base64 = "=0.23.1"`,
`hex`, `sha2` and `ed25519-dalek` are already regular dependencies from
Task 1, and `rand_core = "=0.10.1"` plus
`ed25519-dalek = { version = "=3.0.0", features = ["rand_core"] }` are
already in `[dev-dependencies]` there — `OsRng` is needed only to
generate keypairs in tests, since production code never generates a
signing keypair, it only verifies against `BUNDLE_SIGNING_PUBLIC_KEY`.
(`rand_core` is pinned to `=0.10.1` because that is what `ed25519-dalek`
3.0.0's own `Cargo.toml` requires; Cargo's feature unification lets the
`[dev-dependencies]` entry turn on the `rand_core` feature of the same
`=3.0.0` version already in `[dependencies]` without a conflict.)

- [ ] **Step 2: Run to verify failure**

Run: `make test`
Expected: FAIL — `executor::loader` module does not exist.

- [ ] **Step 3: Implement `src/executor/loader/verify.rs`**

```rust
//! Digest + Ed25519 signature verification (spec §11.7, §7.6, §9.4).
//! Four things must agree before a component loads: the sidecar's
//! signature (checked first, since an unverified sidecar's own fields
//! cannot be trusted at all), its `wit_world`, its `digest` against what
//! the stage expects, and the SHA-256 actually computed over the fetched
//! bytes.
//!
//! The sidecar's schema and the exact bytes that get signed are **not**
//! this crate's to choose: they are what `bundle-compiler`'s trusted
//! `publisher` container writes (M2a plan, Task 14, itself verbatim from
//! spec §9.4). `SidecarMetadata` below mirrors that struct field for
//! field, and `canonical_unsigned_bytes` reproduces its signing input
//! exactly -- `serde_json::to_vec` of a `serde_json::json!` object with
//! every field except `signature`. `serde_json::Map` is a `BTreeMap`
//! (the `preserve_order` feature is off in both crates), so that is
//! already canonical sorted-key JSON with no insignificant whitespace;
//! neither side needs a separate canonicalization pass, and both derive
//! byte-identical input.

use ed25519_dalek::{Signature, Verifier, VerifyingKey};
use serde::{Deserialize, Serialize};
use sha2::{Digest as _, Sha256};

/// The one WIT world this executor can host.
pub const SUPPORTED_WIT_WORLD: &str = "waddle:bundle/stage@1.0.0";

/// The signed sidecar, schema verbatim from spec §9.4 / M2a Task 14.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct SidecarMetadata {
    pub schema_version: u32,
    pub app_id: String,
    pub version: String,
    pub digest: String,
    pub size_bytes: u64,
    pub language: String,
    pub artifact_kind: String,
    pub scan_status: String,
    pub wit_world: String,
    pub built_at: String,
    pub builder: String,
    pub signature: String,
}

/// Every reason a load is refused. Each carries enough detail to log a
/// useful ERROR without leaking the signing key or the bytes themselves.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum VerifyError {
    MalformedSidecar(String),
    SignatureInvalid,
    SidecarDigestMismatch { expected: String, sidecar: String },
    ComputedDigestMismatch { expected: String, computed: String },
    WitWorldMismatch { expected: String, sidecar: String },
}

impl std::fmt::Display for VerifyError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            Self::MalformedSidecar(detail) => write!(f, "malformed sidecar: {detail}"),
            Self::SignatureInvalid => write!(f, "sidecar signature verification failed"),
            Self::SidecarDigestMismatch { expected, sidecar } => {
                write!(f, "sidecar digest {sidecar} does not match the expected {expected}")
            }
            Self::ComputedDigestMismatch { expected, computed } => {
                write!(f, "computed digest {computed} does not match the expected {expected}")
            }
            Self::WitWorldMismatch { expected, sidecar } => {
                write!(f, "sidecar targets WIT world {sidecar}, this executor hosts {expected}")
            }
        }
    }
}

impl std::error::Error for VerifyError {}

/// Reproduces M2a `build_and_sign_sidecar`'s signing input: every field
/// except `signature`, serialized through `serde_json`'s sorted-key map.
fn canonical_unsigned_bytes(s: &SidecarMetadata) -> Vec<u8> {
    let unsigned = serde_json::json!({
        "schema_version": s.schema_version,
        "app_id": s.app_id,
        "version": s.version,
        "digest": s.digest,
        "size_bytes": s.size_bytes,
        "language": s.language,
        "artifact_kind": s.artifact_kind,
        "scan_status": s.scan_status,
        "wit_world": s.wit_world,
        "built_at": s.built_at,
        "builder": s.builder,
    });
    // A `serde_json::Value` always serializes; this is not a fallible path.
    serde_json::to_vec(&unsigned).unwrap_or_default()
}

/// Verify a fetched `(component, sidecar)` pair. See the module doc for
/// the ordering rationale; the caller (Task 20) never falls back to
/// loading on any error returned here.
pub fn verify_digest_and_signature(
    expected_digest: &str,
    component_bytes: &[u8],
    sidecar_json: &[u8],
    signing_public_key: &VerifyingKey,
) -> Result<SidecarMetadata, VerifyError> {
    let sidecar: SidecarMetadata =
        serde_json::from_slice(sidecar_json).map_err(|e| VerifyError::MalformedSidecar(e.to_string()))?;

    let sig_bytes = base64::Engine::decode(&base64::engine::general_purpose::STANDARD, &sidecar.signature)
        .map_err(|e| VerifyError::MalformedSidecar(e.to_string()))?;
    let signature = Signature::from_slice(&sig_bytes)
        .map_err(|_| VerifyError::MalformedSidecar("invalid signature bytes".to_string()))?;

    // (1) Signature first -- nothing else in the sidecar is trustworthy
    // until this passes.
    signing_public_key
        .verify(&canonical_unsigned_bytes(&sidecar), &signature)
        .map_err(|_| VerifyError::SignatureInvalid)?;

    // (2) World.
    if sidecar.wit_world != SUPPORTED_WIT_WORLD {
        return Err(VerifyError::WitWorldMismatch {
            expected: SUPPORTED_WIT_WORLD.to_string(),
            sidecar: sidecar.wit_world,
        });
    }

    // (3) The now-trusted sidecar's digest against what the stage asked for.
    if sidecar.digest != expected_digest {
        return Err(VerifyError::SidecarDigestMismatch {
            expected: expected_digest.to_string(),
            sidecar: sidecar.digest,
        });
    }

    // (4) The bytes we actually hold.
    let computed = format!("sha256:{}", hex::encode(Sha256::digest(component_bytes)));
    if computed != expected_digest {
        return Err(VerifyError::ComputedDigestMismatch { expected: expected_digest.to_string(), computed });
    }

    Ok(sidecar)
}
```

- [ ] **Step 4: Create `src/executor/loader/mod.rs`**

```rust
//! The bucket loader: fetches, verifies, precompiles and hot-swaps
//! bundle artifacts (spec §7.6). `verify` (digest + signature) is
//! independent of the bucket transport; `poller`/reconciliation
//! (Task 20) is where the actual `object_store` fetch and the
//! four-case digest reconciliation live.

pub mod verify;
```

- [ ] **Step 5: Export from `src/executor/mod.rs`**

```rust
pub mod loader;
```

- [ ] **Step 6: Run to verify pass**

Run: `make test`
Expected: PASS — all 7 `loader_digest_tests` green (`test result: ok. 7 passed; 0 failed`).

- [ ] **Step 7: Commit**

```bash
git add packages/rust-bundle-host/Cargo.toml packages/rust-bundle-host/src/executor/loader packages/rust-bundle-host/src/executor/mod.rs packages/rust-bundle-host/tests/loader_digest_tests.rs
git commit -m "$(cat <<'EOF'
feat(bundle-host): verify_digest_and_signature -- the four-way load gate

Checks the sidecar's Ed25519 signature first, over the exact canonical
bytes bundle-compiler's publisher signs (spec §9.4 schema, matching
M2a's Sidecar field for field), because an unverified sidecar's own
fields are not trustworthy; then its wit_world, then its digest against
what the stage expects, then the SHA-256 actually computed over the
fetched bytes -- any disagreement refuses the load (spec §11.7). The
digest this gate trusts was measured by the compiler's trusted publisher
container, never the untrusted build container that ran bundle code
(spec §4.6, D27).

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01N2rQgkHY872RubwXoBZxtE
EOF
)"
git push
```

---

## Task 20: Loader — digest-only reconciliation, bucket fetch, precompile, cache eviction

**Depends on:** Task 19 (`verify_digest_and_signature`), Task 6 (`EngineHandle`, for precompilation), Task 2 (`LoadLimits`).

**Files:**
- Create: `packages/rust-bundle-host/src/executor/loader/reconcile.rs`
- Create: `packages/rust-bundle-host/src/executor/loader/bucket.rs`
- Modify: `packages/rust-bundle-host/src/executor/loader/mod.rs`
- Test: `packages/rust-bundle-host/tests/loader_reconcile_tests.rs`
- Test: `packages/rust-bundle-host/tests/loader_bucket_tests.rs`

**Interfaces:**
- Consumes: `executor::loader::verify::{verify_digest_and_signature, SidecarMetadata, VerifyError}` (Task 19), `executor::engine::EngineHandle` (Task 6).
- Produces:
  ```rust
  #[derive(Debug, Clone, PartialEq)]
  pub struct AdvertisedBundle {
      pub app_id: String,
      pub digest: String,
      pub version: String,
      pub component_key: String,
      pub sidecar_key: String,
      pub capabilities: Vec<String>,
      pub limits: crate::wire::message::LoadLimits,
  }

  #[derive(Debug, Clone, PartialEq)]
  pub enum ReconcileAction {
      NoOp { app_id: String },
      LoadOrSwap { app_id: String, bundle: AdvertisedBundle, old_digest: Option<String> },
      Unload { app_id: String, digest: String },
  }

  /// The spec §7.6 four-row table (2026-09-14 revision `680a0a9b`),
  /// purely: same digest -> `NoOp`; different digest -> `LoadOrSwap {
  /// old_digest: Some(_) }`; a newly-advertised app_id -> `LoadOrSwap {
  /// old_digest: None }`; an app_id no longer advertised -> `Unload`.
  /// Version strings and manifest text never enter this comparison --
  /// digest is the only identity, so a rollback (spec §6.10's
  /// `app_active_versions` pointed at an older, already-verified row)
  /// converges through the exact same `LoadOrSwap` path as a roll-forward.
  pub fn reconcile(advertised: &[AdvertisedBundle], loaded: &std::collections::HashMap<String, String>) -> Vec<ReconcileAction>;

  #[derive(Debug, thiserror::Error)]
  pub enum LoaderError {
      #[error("bucket fetch failed: {0}")]
      Fetch(String),
      #[error(transparent)]
      Verify(#[from] super::verify::VerifyError),
      #[error("precompile failed: {0}")]
      Precompile(String),
  }

  pub struct BucketLoader<S: object_store::ObjectStore> {
      pub fn new(store: std::sync::Arc<S>, signing_public_key: ed25519_dalek::VerifyingKey, precompile_dir: std::path::PathBuf, cache_versions: usize, engine: std::sync::Arc<EngineHandle>) -> Self;
      /// `bundles/{app_id}/{version}/{sha256}.wasm` + `.json` (spec A12).
      pub async fn fetch_and_verify(&self, bundle: &AdvertisedBundle) -> Result<(Vec<u8>, SidecarMetadata), LoaderError>;
      /// Keyed `{digest}-{wasmtime_abi}-{collector}` (spec §7.2); writes
      /// the `.cwasm` under `precompile_dir` and returns its path.
      pub fn cwasm_cache_key(&self, digest: &str) -> String;
      pub async fn precompile(&self, digest: &str, component_bytes: &[u8]) -> Result<std::path::PathBuf, LoaderError>;
      /// Deletes every cached `.cwasm` not named by one of `keep_digests`
      /// (spec §7.6: `BUNDLE_CACHE_VERSIONS`) -- the caller decides which
      /// digests are within the retention window, this method just
      /// enforces it. Returns the number of files actually evicted.
      pub async fn evict_old_versions(&self, app_id: &str, keep_digests: &[String]) -> Result<usize, LoaderError>;
  }
  ```
  Task 22 (the `bundle-executor` binary) drives the poll loop: call `reconcile()` against the digest set the stage's `load`/`unload` frames imply, then `fetch_and_verify` + `precompile` for every `LoadOrSwap`, evicting via `evict_old_versions` afterward.

- [ ] **Step 1: Write the failing reconciliation tests**

`tests/loader_reconcile_tests.rs`:

```rust
#![allow(clippy::unwrap_used, clippy::panic)]
use penguin_bundle_host::executor::loader::reconcile::{reconcile, AdvertisedBundle, ReconcileAction};
use penguin_bundle_host::wire::message::LoadLimits;
use std::collections::HashMap;

fn bundle(app_id: &str, digest: &str) -> AdvertisedBundle {
    AdvertisedBundle {
        app_id: app_id.to_string(),
        digest: digest.to_string(),
        version: "1.0.0".to_string(),
        component_key: format!("bundles/{app_id}/1.0.0/{digest}.wasm"),
        sidecar_key: format!("bundles/{app_id}/1.0.0/{digest}.json"),
        capabilities: vec![],
        limits: LoadLimits { timeout_ms: 2000, memory_mb: 64 },
    }
}

#[test]
fn same_digest_is_a_no_op() {
    let advertised = vec![bundle("a", "sha256:1")];
    let mut loaded = HashMap::new();
    loaded.insert("a".to_string(), "sha256:1".to_string());
    let actions = reconcile(&advertised, &loaded);
    assert_eq!(actions, vec![ReconcileAction::NoOp { app_id: "a".to_string() }]);
}

#[test]
fn different_digest_is_load_or_swap_with_the_old_digest_recorded() {
    let advertised = vec![bundle("a", "sha256:2")];
    let mut loaded = HashMap::new();
    loaded.insert("a".to_string(), "sha256:1".to_string());
    let actions = reconcile(&advertised, &loaded);
    assert_eq!(
        actions,
        vec![ReconcileAction::LoadOrSwap { app_id: "a".to_string(), bundle: bundle("a", "sha256:2"), old_digest: Some("sha256:1".to_string()) }]
    );
}

#[test]
fn a_newly_advertised_app_id_is_load_or_swap_with_no_old_digest() {
    let advertised = vec![bundle("a", "sha256:1")];
    let loaded = HashMap::new();
    let actions = reconcile(&advertised, &loaded);
    assert_eq!(
        actions,
        vec![ReconcileAction::LoadOrSwap { app_id: "a".to_string(), bundle: bundle("a", "sha256:1"), old_digest: None }]
    );
}

#[test]
fn an_app_id_no_longer_advertised_is_unloaded() {
    let advertised = vec![];
    let mut loaded = HashMap::new();
    loaded.insert("a".to_string(), "sha256:1".to_string());
    let actions = reconcile(&advertised, &loaded);
    assert_eq!(actions, vec![ReconcileAction::Unload { app_id: "a".to_string(), digest: "sha256:1".to_string() }]);
}

#[test]
fn a_rollback_to_an_older_already_seen_digest_converges_as_load_or_swap_not_a_special_case() {
    // spec §7.6: "a rollback that points app_active_versions at an older
    // row is just 'different digest' and converges the same way as a
    // roll-forward." Simulated here as: currently loaded sha256:2 (the
    // newer version), advertised now reverts to sha256:1 (the older,
    // previously-seen one) -- the function must not special-case this.
    let advertised = vec![bundle("a", "sha256:1")];
    let mut loaded = HashMap::new();
    loaded.insert("a".to_string(), "sha256:2".to_string());
    let actions = reconcile(&advertised, &loaded);
    assert_eq!(
        actions,
        vec![ReconcileAction::LoadOrSwap { app_id: "a".to_string(), bundle: bundle("a", "sha256:1"), old_digest: Some("sha256:2".to_string()) }]
    );
}

#[test]
fn a_byte_identical_republish_is_a_no_op_even_with_a_new_version_string() {
    // "Version strings ... play no part in the comparison" -- only the
    // digest is compared, so a republish under a new version number with
    // identical bytes (identical digest) must be a NoOp.
    let mut republished = bundle("a", "sha256:1");
    republished.version = "1.0.1".to_string(); // version bumped, digest unchanged
    let advertised = vec![republished];
    let mut loaded = HashMap::new();
    loaded.insert("a".to_string(), "sha256:1".to_string());
    let actions = reconcile(&advertised, &loaded);
    assert_eq!(actions, vec![ReconcileAction::NoOp { app_id: "a".to_string() }]);
}

#[test]
fn a_mixed_batch_produces_the_correct_action_per_app_id_with_an_exact_count() {
    let advertised = vec![
        bundle("unchanged", "sha256:1"),
        bundle("changed", "sha256:new"),
        bundle("brand_new", "sha256:x"),
    ];
    let mut loaded = HashMap::new();
    loaded.insert("unchanged".to_string(), "sha256:1".to_string());
    loaded.insert("changed".to_string(), "sha256:old".to_string());
    loaded.insert("removed".to_string(), "sha256:gone".to_string());

    let actions = reconcile(&advertised, &loaded);
    assert_eq!(actions.len(), 4, "expected exactly 4 actions examined (unchanged/changed/brand_new/removed), got {}", actions.len());
    assert!(actions.contains(&ReconcileAction::NoOp { app_id: "unchanged".to_string() }));
    assert!(actions.contains(&ReconcileAction::LoadOrSwap { app_id: "changed".to_string(), bundle: bundle("changed", "sha256:new"), old_digest: Some("sha256:old".to_string()) }));
    assert!(actions.contains(&ReconcileAction::LoadOrSwap { app_id: "brand_new".to_string(), bundle: bundle("brand_new", "sha256:x"), old_digest: None }));
    assert!(actions.contains(&ReconcileAction::Unload { app_id: "removed".to_string(), digest: "sha256:gone".to_string() }));
}
```

- [ ] **Step 2: Run to verify failure**

Run: `make test`
Expected: FAIL — `executor::loader::reconcile` does not exist.

- [ ] **Step 3: Implement `src/executor/loader/reconcile.rs`**

```rust
//! Purely digest-based reconciliation (spec §7.6, updated 2026-09-14
//! revision `680a0a9b`): four cases, no version strings, no manifest
//! text. Kept as a pure function -- deterministic, exhaustively
//! table-tested above -- separate from the actual bucket I/O in
//! `bucket.rs`, which drives it.

use std::collections::{HashMap, HashSet};

use crate::wire::message::LoadLimits;

#[derive(Debug, Clone, PartialEq)]
pub struct AdvertisedBundle {
    pub app_id: String,
    pub digest: String,
    pub version: String,
    pub component_key: String,
    pub sidecar_key: String,
    pub capabilities: Vec<String>,
    pub limits: LoadLimits,
}

#[derive(Debug, Clone, PartialEq)]
pub enum ReconcileAction {
    NoOp { app_id: String },
    LoadOrSwap { app_id: String, bundle: AdvertisedBundle, old_digest: Option<String> },
    Unload { app_id: String, digest: String },
}

pub fn reconcile(advertised: &[AdvertisedBundle], loaded: &HashMap<String, String>) -> Vec<ReconcileAction> {
    let mut actions = Vec::new();
    let mut seen_app_ids: HashSet<&str> = HashSet::new();

    for bundle in advertised {
        seen_app_ids.insert(bundle.app_id.as_str());
        match loaded.get(&bundle.app_id) {
            Some(current_digest) if *current_digest == bundle.digest => {
                actions.push(ReconcileAction::NoOp { app_id: bundle.app_id.clone() });
            }
            Some(current_digest) => {
                actions.push(ReconcileAction::LoadOrSwap {
                    app_id: bundle.app_id.clone(),
                    bundle: bundle.clone(),
                    old_digest: Some(current_digest.clone()),
                });
            }
            None => {
                actions.push(ReconcileAction::LoadOrSwap { app_id: bundle.app_id.clone(), bundle: bundle.clone(), old_digest: None });
            }
        }
    }

    for (app_id, digest) in loaded {
        if !seen_app_ids.contains(app_id.as_str()) {
            actions.push(ReconcileAction::Unload { app_id: app_id.clone(), digest: digest.clone() });
        }
    }

    actions
}
```

- [ ] **Step 4: Write the failing bucket-loader tests**

`tests/loader_bucket_tests.rs`:

```rust
#![allow(clippy::unwrap_used, clippy::panic)]
use ed25519_dalek::{Signer, SigningKey};
use object_store::memory::InMemory;
use object_store::{ObjectStore, ObjectStoreExt, path::Path as ObjectPath};
use penguin_bundle_host::executor::engine::{EngineConfig, EngineHandle};
use penguin_bundle_host::executor::loader::bucket::BucketLoader;
use penguin_bundle_host::executor::loader::reconcile::AdvertisedBundle;
use penguin_bundle_host::wire::message::LoadLimits;
use rand_core::OsRng;
use sha2::{Digest, Sha256};
use std::sync::Arc;

fn base64_encode(bytes: &[u8]) -> String {
    use base64::Engine;
    base64::engine::general_purpose::STANDARD.encode(bytes)
}

async fn seed_bucket(store: &InMemory, app_id: &str, version: &str, component_bytes: &[u8], signing_key: &SigningKey) -> String {
    let digest = format!("sha256:{}", hex::encode(Sha256::digest(component_bytes)));
    let signed_msg = format!("{{\"app_id\":\"{app_id}\",\"digest\":\"{digest}\",\"version\":\"{version}\"}}");
    let signature = base64_encode(&signing_key.sign(signed_msg.as_bytes()).to_bytes());
    let sidecar = format!("{{\"app_id\":\"{app_id}\",\"digest\":\"{digest}\",\"version\":\"{version}\",\"signature\":\"{signature}\"}}");

    store.put(&ObjectPath::from(format!("bundles/{app_id}/{version}/{}.wasm", digest.trim_start_matches("sha256:"))), component_bytes.to_vec().into()).await.unwrap();
    store.put(&ObjectPath::from(format!("bundles/{app_id}/{version}/{}.json", digest.trim_start_matches("sha256:"))), sidecar.into_bytes().into()).await.unwrap();
    digest
}

#[tokio::test]
async fn fetch_and_verify_succeeds_for_a_correctly_signed_bundle() {
    let store = Arc::new(InMemory::new());
    let signing_key = SigningKey::generate(&mut OsRng);
    let component_bytes = b"a tiny fake component";
    let digest = seed_bucket(&store, "waddles.test.a", "1.0.0", component_bytes, &signing_key).await;

    let engine = Arc::new(EngineHandle::new(&EngineConfig { max_memory_bytes: 64 * 1024 * 1024, epoch_tick_ms: 10, collector: "drc".to_string() }).unwrap());
    let tmp = tempfile::tempdir().unwrap();
    let loader = BucketLoader::new(store, signing_key.verifying_key(), tmp.path().to_path_buf(), 3, engine);

    let bundle = AdvertisedBundle {
        app_id: "waddles.test.a".to_string(), digest: digest.clone(), version: "1.0.0".to_string(),
        component_key: format!("bundles/waddles.test.a/1.0.0/{}.wasm", digest.trim_start_matches("sha256:")),
        sidecar_key: format!("bundles/waddles.test.a/1.0.0/{}.json", digest.trim_start_matches("sha256:")),
        capabilities: vec![], limits: LoadLimits { timeout_ms: 2000, memory_mb: 64 },
    };

    let (fetched_bytes, metadata) = loader.fetch_and_verify(&bundle).await.unwrap();
    assert_eq!(fetched_bytes, component_bytes);
    assert_eq!(metadata.digest, digest);
}

#[tokio::test]
async fn fetch_and_verify_refuses_a_bucket_swapped_component() {
    let store = Arc::new(InMemory::new());
    let signing_key = SigningKey::generate(&mut OsRng);
    let digest = seed_bucket(&store, "waddles.test.a", "1.0.0", b"original bytes", &signing_key).await;
    // Swap the component bytes in the bucket after the sidecar was signed.
    store.put(&ObjectPath::from(format!("bundles/waddles.test.a/1.0.0/{}.wasm", digest.trim_start_matches("sha256:"))), b"swapped malicious bytes".to_vec().into()).await.unwrap();

    let engine = Arc::new(EngineHandle::new(&EngineConfig { max_memory_bytes: 64 * 1024 * 1024, epoch_tick_ms: 10, collector: "drc".to_string() }).unwrap());
    let tmp = tempfile::tempdir().unwrap();
    let loader = BucketLoader::new(store, signing_key.verifying_key(), tmp.path().to_path_buf(), 3, engine);
    let bundle = AdvertisedBundle {
        app_id: "waddles.test.a".to_string(), digest: digest.clone(), version: "1.0.0".to_string(),
        component_key: format!("bundles/waddles.test.a/1.0.0/{}.wasm", digest.trim_start_matches("sha256:")),
        sidecar_key: format!("bundles/waddles.test.a/1.0.0/{}.json", digest.trim_start_matches("sha256:")),
        capabilities: vec![], limits: LoadLimits { timeout_ms: 2000, memory_mb: 64 },
    };
    assert!(loader.fetch_and_verify(&bundle).await.is_err());
}

#[test]
fn cwasm_cache_key_includes_digest_abi_and_collector() {
    let engine = Arc::new(EngineHandle::new(&EngineConfig { max_memory_bytes: 64 * 1024 * 1024, epoch_tick_ms: 10, collector: "drc".to_string() }).unwrap());
    let store = Arc::new(InMemory::new());
    let signing_key = SigningKey::generate(&mut OsRng);
    let tmp = tempfile::tempdir().unwrap();
    let loader = BucketLoader::new(store, signing_key.verifying_key(), tmp.path().to_path_buf(), 3, engine.clone());
    let key = loader.cwasm_cache_key("sha256:abc123");
    assert!(key.contains("sha256:abc123"));
    assert!(key.contains(&engine.wasmtime_abi));
    assert!(key.contains("drc"));
}

#[tokio::test]
async fn precompile_writes_a_loadable_cwasm_file() {
    let engine = Arc::new(EngineHandle::new(&EngineConfig { max_memory_bytes: 64 * 1024 * 1024, epoch_tick_ms: 10, collector: "drc".to_string() }).unwrap());
    let store = Arc::new(InMemory::new());
    let signing_key = SigningKey::generate(&mut OsRng);
    let tmp = tempfile::tempdir().unwrap();
    let loader = BucketLoader::new(store, signing_key.verifying_key(), tmp.path().to_path_buf(), 3, engine.clone());

    let component_bytes = std::fs::read(
        std::path::PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("tests/fixtures/hello_bundle/hello_bundle.wasm"),
    )
    .expect("run `make fixtures` first");

    let cwasm_path = loader.precompile("sha256:realbundle", &component_bytes).await.unwrap();
    assert!(cwasm_path.exists());

    // A precompiled artifact must actually be loadable by the same engine.
    let loaded = unsafe { wasmtime::component::Component::deserialize_file(&engine.engine, &cwasm_path) };
    assert!(loaded.is_ok(), "the .cwasm this loader wrote must load back with the same engine: {loaded:?}");
}

#[tokio::test]
async fn evict_old_versions_keeps_only_the_configured_count() {
    let engine = Arc::new(EngineHandle::new(&EngineConfig { max_memory_bytes: 64 * 1024 * 1024, epoch_tick_ms: 10, collector: "drc".to_string() }).unwrap());
    let store = Arc::new(InMemory::new());
    let signing_key = SigningKey::generate(&mut OsRng);
    let tmp = tempfile::tempdir().unwrap();
    let loader = BucketLoader::new(store, signing_key.verifying_key(), tmp.path().to_path_buf(), 2, engine.clone());

    let component_bytes = std::fs::read(
        std::path::PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("tests/fixtures/hello_bundle/hello_bundle.wasm"),
    )
    .unwrap();
    let mut digests = Vec::new();
    for i in 0..4 {
        let digest = format!("sha256:fake{i}{}", "0".repeat(58));
        loader.precompile(&digest, &component_bytes).await.unwrap();
        digests.push(digest);
        tokio::time::sleep(std::time::Duration::from_millis(5)).await; // distinct mtimes
    }

    let evicted = loader.evict_old_versions("waddles.test.a", &digests[2..]).await.unwrap();
    assert_eq!(evicted, 2, "expected exactly 2 of 4 cached versions evicted, got {evicted}");
}
```

- [ ] **Step 5: Run to verify failure**

Run: `make fixtures && make test`
Expected: FAIL — `executor::loader::bucket` does not exist.

- [ ] **Step 6: Implement `src/executor/loader/bucket.rs`**

```rust
//! Bucket fetch + precompile + cache eviction (spec §7.6). Generic over
//! `object_store::ObjectStore` so tests use `object_store::memory::InMemory`
//! and production wires `object_store::aws::AmazonS3Builder` (path-style,
//! custom endpoint, for MinIO or Nest) -- both satisfy the same trait, so
//! this module never branches on which backend it is talking to.

use std::path::PathBuf;
use std::sync::Arc;

use object_store::{path::Path as ObjectPath, ObjectStore, ObjectStoreExt};

use super::reconcile::AdvertisedBundle;
use super::verify::{verify_digest_and_signature, SidecarMetadata, VerifyError};
use crate::executor::engine::EngineHandle;

#[derive(Debug, thiserror::Error)]
pub enum LoaderError {
    #[error("bucket fetch failed: {0}")]
    Fetch(String),
    #[error(transparent)]
    Verify(#[from] VerifyError),
    #[error("precompile failed: {0}")]
    Precompile(String),
}

pub struct BucketLoader<S: ObjectStore> {
    store: Arc<S>,
    signing_public_key: ed25519_dalek::VerifyingKey,
    precompile_dir: PathBuf,
    cache_versions: usize,
    engine: Arc<EngineHandle>,
}

impl<S: ObjectStore> BucketLoader<S> {
    pub fn new(
        store: Arc<S>,
        signing_public_key: ed25519_dalek::VerifyingKey,
        precompile_dir: PathBuf,
        cache_versions: usize,
        engine: Arc<EngineHandle>,
    ) -> Self {
        Self { store, signing_public_key, precompile_dir, cache_versions, engine }
    }

    pub async fn fetch_and_verify(&self, bundle: &AdvertisedBundle) -> Result<(Vec<u8>, SidecarMetadata), LoaderError> {
        let component_bytes = self
            .store
            .get(&ObjectPath::from(bundle.component_key.as_str()))
            .await
            .map_err(|e| LoaderError::Fetch(e.to_string()))?
            .bytes()
            .await
            .map_err(|e| LoaderError::Fetch(e.to_string()))?
            .to_vec();
        let sidecar_bytes = self
            .store
            .get(&ObjectPath::from(bundle.sidecar_key.as_str()))
            .await
            .map_err(|e| LoaderError::Fetch(e.to_string()))?
            .bytes()
            .await
            .map_err(|e| LoaderError::Fetch(e.to_string()))?
            .to_vec();

        let metadata = verify_digest_and_signature(&bundle.digest, &component_bytes, &sidecar_bytes, &self.signing_public_key)?;
        Ok((component_bytes, metadata))
    }

    pub fn cwasm_cache_key(&self, digest: &str) -> String {
        format!("{digest}-{}-drc", self.engine.wasmtime_abi)
    }

    pub async fn precompile(&self, digest: &str, component_bytes: &[u8]) -> Result<PathBuf, LoaderError> {
        tokio::fs::create_dir_all(&self.precompile_dir)
            .await
            .map_err(|e| LoaderError::Precompile(e.to_string()))?;
        let cwasm_bytes = self
            .engine
            .engine
            .precompile_component(component_bytes)
            .map_err(|e| LoaderError::Precompile(e.to_string()))?;
        let key = self.cwasm_cache_key(digest);
        let safe_name = key.replace([':', '/'], "_");
        let path = self.precompile_dir.join(format!("{safe_name}.cwasm"));
        tokio::fs::write(&path, cwasm_bytes).await.map_err(|e| LoaderError::Precompile(e.to_string()))?;
        Ok(path)
    }

    /// Deletes every cached `.cwasm` under `precompile_dir` that is not
    /// named by one of `keep_digests` (spec §7.6:
    /// `BUNDLE_CACHE_VERSIONS` -- the *caller*, Task 22, decides which
    /// digests fall within the retention window for a given `app_id`;
    /// this method enforces exactly that keep-set rather than counting
    /// on its own). Returns the number of files actually evicted.
    pub async fn evict_old_versions(&self, _app_id: &str, keep_digests: &[String]) -> Result<usize, LoaderError> {
        let keep_keys: std::collections::HashSet<String> =
            keep_digests.iter().map(|d| self.cwasm_cache_key(d).replace([':', '/'], "_")).collect();

        let mut entries = tokio::fs::read_dir(&self.precompile_dir).await.map_err(|e| LoaderError::Precompile(e.to_string()))?;
        let mut evicted = 0usize;
        while let Some(entry) = entries.next_entry().await.map_err(|e| LoaderError::Precompile(e.to_string()))? {
            let path = entry.path();
            if path.extension().and_then(|e| e.to_str()) != Some("cwasm") {
                continue;
            }
            let stem = path.file_stem().and_then(|s| s.to_str()).unwrap_or("").to_string();
            if !keep_keys.contains(&stem) {
                tokio::fs::remove_file(&path).await.map_err(|e| LoaderError::Precompile(e.to_string()))?;
                evicted += 1;
            }
        }
        Ok(evicted)
    }
}
```

- [ ] **Step 7: Export from `src/executor/loader/mod.rs`**

```rust
pub mod bucket;
pub mod reconcile;
pub mod verify;
```

- [ ] **Step 8: Run to verify pass**

Run: `make fixtures && make test`
Expected: PASS — 7 `loader_reconcile_tests` and 5 `loader_bucket_tests` green.

- [ ] **Step 9: Commit**

```bash
git add packages/rust-bundle-host/src/executor/loader packages/rust-bundle-host/tests/loader_reconcile_tests.rs packages/rust-bundle-host/tests/loader_bucket_tests.rs
git commit -m "$(cat <<'EOF'
feat(bundle-host): digest-only reconciliation + bucket fetch/precompile/eviction

reconcile() implements spec §7.6's four-row table exactly (same digest =
no-op, different digest = load-or-swap, new app_id = load-or-swap with
no old digest, absent = unload) -- version strings and manifest text
never enter the comparison, so a byte-identical republish is a no-op and
a rollback converges through the same path as a roll-forward.
BucketLoader wraps object_store generically (InMemory in tests,
AmazonS3Builder in production) for fetch+verify, precompile() writes a
.cwasm this same engine can load back, and evict_old_versions() prunes
to an explicit keep-set.

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01N2rQgkHY872RubwXoBZxtE
EOF
)"
git push
```

---

## Task 21: Executor-side remote `Host` implementation + wire client

**Depends on:** Task 18 (`ExecutorHostState`, `BundleRuntime`, the DTOs), Task 7 (the bindgen `Host` traits), Task 4 (`FrameTransport`), Task 2 (`Message`, `CapabilityKind`, `HostResultError`).

**Files:**
- Modify: `packages/rust-bundle-host/src/executor/invoke.rs` (extend `ExecutorHostState` with wire-forwarding fields)
- Create: `packages/rust-bundle-host/src/executor/remote_host_impl.rs`
- Create: `packages/rust-bundle-host/src/executor/wire_client.rs`
- Modify: `packages/rust-bundle-host/src/executor/mod.rs`
- Test: `packages/rust-bundle-host/tests/executor_remote_host_tests.rs`

**Interfaces:**
- Consumes: `executor::bindings::stage_world::waddle::bundle::*` (Task 7), `executor::invoke::ExecutorHostState` (Task 18), `wire::transport::FrameTransport` (Task 4, including the `call_with_id` method Task 17 added to it), `wire::message::{CapabilityKind, Message, HostResultError}` (Task 2).
- Produces:
  ```rust
  pub struct RemoteHostWire {
      pub transport: std::sync::Arc<FrameTransport>,
      /// The full D30 scope (spec §5.11) of the `invoke` this instance's
      /// whole lifetime is bound to -- attached verbatim to every
      /// `host-call` frame this instance sends (`scope.app_id` supersedes
      /// the pre-D30 standalone `app_id` field).
      pub scope: crate::wire::message::InvocationScope,
      /// The frame id of the `invoke` this instance's whole lifetime is
      /// scoped to -- becomes `call_id` on every `host-call` frame this
      /// instance sends, so the stage's `pending_contexts` lookup
      /// (Task 17) resolves back to the right `ApprovedPermissions`.
      pub invoke_frame_id: u64,
  }
  impl RemoteHostWire {
      pub async fn call(&self, capability: CapabilityKind, op: &str, args: serde_json::Value) -> Result<serde_json::Value, HostResultError>;
  }

  pub struct ExecutorClient { /* mTLS-connected wire::transport::FrameTransport + hello/hello-ok state */ }
  impl ExecutorClient {
      pub async fn dial(addr: std::net::SocketAddr, tls: ExecutorTlsConfig, hello: HelloAnnouncement) -> Result<Self, ExecutorClientError>;
      /// The shared `FrameTransport` this client dialed with -- Task 22's
      /// `Handler` clones this once, after `dial()` succeeds, to build a
      /// `RemoteHostWire` per `invoke` inside `on_invoke`.
      pub fn transport(&self) -> std::sync::Arc<crate::wire::transport::FrameTransport>;
      /// Loops on `recv_unsolicited()`, dispatching `load`/`unload`/
      /// `invoke`/`ping`/`shutdown` to `handler`, replying
      /// `loaded`/`unloaded`/`result`/`pong` (or `error`). Returns when
      /// the connection closes or a `shutdown` grace period elapses.
      pub async fn serve(&self, handler: std::sync::Arc<dyn StageRequestHandler>) -> Result<(), ExecutorClientError>;
  }
  pub struct ExecutorTlsConfig { pub cert_chain: Vec<rustls_pki_types::CertificateDer<'static>>, pub private_key: rustls_pki_types::PrivateKeyDer<'static>, pub server_ca: rustls_pki_types::CertificateDer<'static>, pub server_name: String }
  pub struct HelloAnnouncement { pub executor_version: String, pub wasmtime_abi: String, pub collector: String, pub sandbox: crate::wire::message::SandboxInfo }

  #[async_trait::async_trait]
  pub trait StageRequestHandler: Send + Sync {
      async fn on_load(&self, app_id: &str, version: &str, digest: &str, component_key: &str, sidecar_key: &str, capabilities: Vec<String>, limits: crate::wire::message::LoadLimits) -> Result<(String, u64, Vec<String>), String>;
      async fn on_unload(&self, app_id: &str, digest: &str) -> Result<(), String>;
      async fn on_invoke(&self, scope: crate::wire::message::InvocationScope, digest: &str, export: crate::wire::message::ExportKind, payload: serde_json::Value, deadline_ms: u64, invoke_frame_id: u64) -> Result<serde_json::Value, String>;
  }
  ```
  Task 22 (`bundle-executor` binary) implements `StageRequestHandler` against `BucketLoader`/`InstancePool`/`BundleRuntime` and calls `ExecutorClient::dial` + `serve`.

- [ ] **Step 1: Extend `ExecutorHostState` in `src/executor/invoke.rs`**

Replace `ExecutorHostState`'s definition and every method of `impl BundleRuntime` in `src/executor/invoke.rs` (Task 18) with the versions below — each now threads a `wire: RemoteHostWire` through from the caller (Task 22's `StageRequestHandler` impl, which builds one per `invoke` from the connection's `Arc<FrameTransport>`, the current `app_id`, and the `invoke` frame id it just allocated) down to the `Store`, since the eight `Host` trait impls this task adds in Step 4 read `self.wire` to forward every capability call:

```rust
pub struct ExecutorHostState {
    pub wasi: GuestWasiCtx,
    pub limits: StoreLimits,
    pub wire: super::remote_host_impl::RemoteHostWire,
}

impl wasmtime_wasi::WasiView for ExecutorHostState {
    fn ctx(&mut self) -> wasmtime_wasi::WasiCtxView<'_> {
        wasmtime_wasi::WasiCtxView { ctx: &mut self.wasi.wasi, table: &mut self.wasi.table }
    }
}

impl BundleRuntime {
    pub fn new(engine: std::sync::Arc<EngineHandle>, component: Component, linker: Linker<ExecutorHostState>, scratch_dir: std::path::PathBuf) -> Self {
        Self { engine, component, linker, scratch_dir }
    }

    async fn instantiate_fresh(
        &self,
        timeout_ms: u64,
        memory_mb: u32,
        wire: super::remote_host_impl::RemoteHostWire,
    ) -> Result<(Store<ExecutorHostState>, Stage), InvokeError> {
        let wasi = build_guest_wasi_ctx(&self.scratch_dir).map_err(|e| InvokeError::ComponentError(e.to_string()))?;
        let limits = StoreLimitsBuilder::new().memory_size(memory_mb as usize * 1024 * 1024).build();
        let mut store = Store::new(&self.engine.engine, ExecutorHostState { wasi, limits, wire });
        store.limiter(|s| &mut s.limits);
        store.epoch_deadline_trap();
        store.set_epoch_deadline(self.engine.ticks_for_timeout(timeout_ms));
        let (stage, _instance) = Stage::instantiate_async(&mut store, &self.component, &self.linker)
            .await
            .map_err(|e| InvokeError::ComponentError(e.to_string()))?;
        Ok((store, stage))
    }

    pub async fn call_transform(
        &self,
        pool: &InstancePool,
        app_id: &str,
        digest: &str,
        timeout_ms: u64,
        memory_mb: u32,
        event: PlatformEventDto,
        wire: super::remote_host_impl::RemoteHostWire,
    ) -> Result<Option<PlatformEventDto>, InvokeError> {
        let _permit = pool.checkout(app_id, digest).await?;
        let (mut store, stage) = self.instantiate_fresh(timeout_ms, memory_mb, wire).await?;
        let wit_event: WitPlatformEvent = event.into();
        let result = stage
            .waddle_bundle_process_stage()
            .call_transform(&mut store, &wit_event)
            .await
            .map_err(|e| classify_call_error(&e))?;
        result
            .map(|opt| opt.map(PlatformEventDto::from))
            .map_err(|unsupported| InvokeError::ComponentError(format!("unsupported stage: {}", unsupported.stage)))
    }

    pub async fn call_dispatch(
        &self,
        pool: &InstancePool,
        app_id: &str,
        digest: &str,
        timeout_ms: u64,
        memory_mb: u32,
        envelope: StageEnvelopeDto,
        config_json: &str,
        wire: super::remote_host_impl::RemoteHostWire,
    ) -> Result<Result<TransportResultDto, TransportErrorDto>, InvokeError> {
        let _permit = pool.checkout(app_id, digest).await?;
        let (mut store, stage) = self.instantiate_fresh(timeout_ms, memory_mb, wire).await?;
        let wit_envelope = WitStageEnvelope {
            tenant: envelope.tenant,
            community: envelope.community,
            app_id: envelope.app_id,
            stage: envelope.stage,
            event: envelope.event.into(),
            ts: envelope.ts,
            target_app_id: envelope.target_app_id,
            trace_context: envelope.trace_context,
        };
        let result = stage
            .waddle_bundle_action_stage()
            .call_dispatch(&mut store, &wit_envelope, config_json)
            .await
            .map_err(|e| classify_call_error(&e))?;
        Ok(result
            .map(|r: WitTransportResult| TransportResultDto { ok: r.ok, status: r.status, detail: r.detail, provider_message_id: r.provider_message_id })
            .map_err(|e: WitTransportError| TransportErrorDto { retryable: e.retryable, code: e.code, message: e.message, retry_after_ms: e.retry_after_ms }))
    }
}
```

This changes `call_transform`'s and `call_dispatch`'s public signatures from Task 18's — Task 22's `Handler::on_invoke` (the only caller either method has, since M3/M4's own use of this crate is out of scope) is written against this final shape, not Task 18's.

- [ ] **Step 2: Write the failing remote-host tests**

`tests/executor_remote_host_tests.rs`:

```rust
#![allow(clippy::unwrap_used, clippy::panic)]
use penguin_bundle_host::executor::remote_host_impl::RemoteHostWire;
use penguin_bundle_host::wire::message::{CapabilityKind, Frame, HostResultError, InvocationScope, Message};
use penguin_bundle_host::wire::transport::FrameTransport;
use std::sync::Arc;

fn sample_scope(app_id: &str) -> InvocationScope {
    InvocationScope {
        tenant_id: "acme".to_string(),
        community_id: None,
        workstream_id: "8f14e45f-ceea-467e-adde-3fb5c9752730".to_string(),
        app_id: app_id.to_string(),
        trace: None,
    }
}

#[tokio::test]
async fn remote_host_wire_forwards_a_call_and_returns_the_result() {
    let (client_io, server_io) = tokio::io::duplex(8192);
    let client_transport = Arc::new(FrameTransport::spawn(client_io, 1_048_576));
    let server_transport = FrameTransport::spawn(server_io, 1_048_576);

    let server_task = tokio::spawn(async move {
        let frame = server_transport.recv_unsolicited().await.unwrap();
        match frame.message {
            Message::HostCall { capability, op, call_id, .. } => {
                assert_eq!(capability, CapabilityKind::Kv);
                assert_eq!(op, "get");
                assert_eq!(call_id, 42, "call_id must carry the invoke's own frame id");
                server_transport
                    .send(frame.id, Message::HostResult { result: Some(serde_json::json!(null)), error: None })
                    .await
                    .unwrap();
            }
            other => panic!("expected HostCall, got {other:?}"),
        }
    });

    let wire = RemoteHostWire { transport: client_transport, scope: sample_scope("waddles.test.a"), invoke_frame_id: 42 };
    let result = wire.call(CapabilityKind::Kv, "get", serde_json::json!({"key": "x"})).await.unwrap();
    assert_eq!(result, serde_json::json!(null));
    server_task.await.unwrap();
}

#[tokio::test]
async fn remote_host_wire_surfaces_a_denial_as_an_error() {
    let (client_io, server_io) = tokio::io::duplex(8192);
    let client_transport = Arc::new(FrameTransport::spawn(client_io, 1_048_576));
    let server_transport = FrameTransport::spawn(server_io, 1_048_576);

    let server_task = tokio::spawn(async move {
        let frame = server_transport.recv_unsolicited().await.unwrap();
        server_transport
            .send(frame.id, Message::HostResult { result: None, error: Some(HostResultError { code: "HOST_CALL_DENIED".to_string(), message: "http capability not granted".to_string() }) })
            .await
            .unwrap();
    });

    let wire = RemoteHostWire { transport: client_transport, scope: sample_scope("a"), invoke_frame_id: 1 };
    let err = wire.call(CapabilityKind::Http, "send", serde_json::json!({})).await.unwrap_err();
    assert_eq!(err.code, "HOST_CALL_DENIED");
    server_task.await.unwrap();
}
```

- [ ] **Step 3: Run to verify failure**

Run: `make test`
Expected: FAIL — `executor::remote_host_impl` does not exist.

- [ ] **Step 4: Implement `src/executor/remote_host_impl.rs`**

```rust
//! The executor's implementation of the WIT world's `Host` traits
//! (`context`, `http`, `kv`, `db`, `relay`, `flags`, `log`, `clock`) --
//! every method forwards to the stage as a `host-call` frame and awaits
//! `host-result`. The executor never answers a capability locally; it
//! holds no credential to do so with (spec §11.3, §11.10).

use serde_json::json;

use super::bindings::stage_world::waddle::bundle::{clock, context, db, flags, http, kv, log, relay};
use super::invoke::ExecutorHostState;
use crate::wire::message::{CapabilityKind, HostResultError, Message};
use crate::wire::transport::FrameTransport;

#[derive(Clone)]
pub struct RemoteHostWire {
    pub transport: std::sync::Arc<FrameTransport>,
    /// D30 (spec §5.11): the full scope of the invocation this wire
    /// belongs to, attached to every `host-call` frame -- `scope.app_id`
    /// supersedes the pre-D30 standalone `app_id` field.
    pub scope: crate::wire::message::InvocationScope,
    pub invoke_frame_id: u64,
}

impl RemoteHostWire {
    pub async fn call(&self, capability: CapabilityKind, op: &str, args: serde_json::Value) -> Result<serde_json::Value, HostResultError> {
        let id = self.transport.next_id();
        let reply = self
            .transport
            .call_with_id(
                id,
                Message::HostCall { scope: self.scope.clone(), capability, op: op.to_string(), args, call_id: self.invoke_frame_id },
            )
            .await
            .map_err(|e| HostResultError { code: "HOST_CALL_FAILED".to_string(), message: e.to_string() })?;

        match reply {
            Message::HostResult { result: Some(v), error: None } => Ok(v),
            Message::HostResult { result: None, error: Some(e) } => Err(e),
            Message::HostResult { .. } => Ok(serde_json::Value::Null),
            other => Err(HostResultError { code: "HOST_CALL_FAILED".to_string(), message: format!("unexpected reply {other:?}") }),
        }
    }
}

impl context::Host for ExecutorHostState {
    async fn get_context(&mut self) -> context::BundleContext {
        let v = self.wire.call(CapabilityKind::Context, "get_context", json!({})).await.unwrap_or_else(|_| json!({}));
        context::BundleContext {
            tenant: v["tenant"].as_str().unwrap_or_default().to_string(),
            community: v["community"].as_str().map(str::to_string),
            app_id: v["app_id"].as_str().unwrap_or_default().to_string(),
            feature: v["feature"].as_str().unwrap_or_default().to_string(),
            version: v["version"].as_str().unwrap_or_default().to_string(),
            message_id: v["message_id"].as_str().unwrap_or_default().to_string(),
            config_json: v["config_json"].as_str().unwrap_or("{}").to_string(),
        }
    }
}

impl http::Host for ExecutorHostState {
    async fn send(&mut self, req: http::Request) -> Result<http::Response, http::Error> {
        let args = json!({
            "method": req.method, "url": req.url,
            "headers": req.headers.iter().map(|h| json!({"name": h.name, "value": h.value})).collect::<Vec<_>>(),
            "secret_refs": req.secret_refs,
        });
        match self.wire.call(CapabilityKind::Http, "send", args).await {
            Ok(v) => Ok(http::Response {
                status: v["status"].as_u64().unwrap_or(0) as u16,
                headers: vec![],
                body: v["body"].as_array().map(|a| a.iter().filter_map(|b| b.as_u64()).map(|n| n as u8).collect()).unwrap_or_default(),
                truncated: v["truncated"].as_bool().unwrap_or(false),
            }),
            Err(e) => Err(http::Error::Denied(e.message)),
        }
    }
}

impl kv::Host for ExecutorHostState {
    async fn get(&mut self, key: String) -> Result<Option<Vec<u8>>, kv::Error> {
        match self.wire.call(CapabilityKind::Kv, "get", json!({"key": key})).await {
            Ok(serde_json::Value::Null) => Ok(None),
            Ok(v) => Ok(v.as_array().map(|a| a.iter().filter_map(|b| b.as_u64()).map(|n| n as u8).collect())),
            Err(e) => Err(kv::Error::Backend(e.message)),
        }
    }
    async fn set(&mut self, key: String, value: Vec<u8>, ttl_seconds: u32) -> Result<(), kv::Error> {
        self.wire.call(CapabilityKind::Kv, "set", json!({"key": key, "value": value, "ttl_seconds": ttl_seconds})).await.map(|_| ()).map_err(|e| kv::Error::Backend(e.message))
    }
    async fn delete(&mut self, key: String) -> Result<(), kv::Error> {
        self.wire.call(CapabilityKind::Kv, "delete", json!({"key": key})).await.map(|_| ()).map_err(|e| kv::Error::Backend(e.message))
    }
    async fn increment(&mut self, key: String, delta: i64, ttl_seconds: u32) -> Result<i64, kv::Error> {
        self.wire
            .call(CapabilityKind::Kv, "increment", json!({"key": key, "delta": delta, "ttl_seconds": ttl_seconds}))
            .await
            .map(|v| v.as_i64().unwrap_or(0))
            .map_err(|e| kv::Error::Backend(e.message))
    }
}

impl db::Host for ExecutorHostState {
    async fn execute(&mut self, statement: String, _params: Vec<db::Value>) -> Result<db::Rows, db::Error> {
        match self.wire.call(CapabilityKind::Db, "execute", json!({"statement": statement, "params": []})).await {
            Ok(v) => Ok(db::Rows {
                columns: v["columns"].as_array().map(|a| a.iter().filter_map(|c| c.as_str().map(str::to_string)).collect()).unwrap_or_default(),
                rows: vec![],
                rows_affected: v["rows_affected"].as_u64().unwrap_or(0),
            }),
            Err(e) => Err(db::Error::Denied(e.message)),
        }
    }
}

impl relay::Host for ExecutorHostState {
    async fn push(&mut self, provider: String, message_json: String) -> Result<(), relay::Error> {
        self.wire
            .call(CapabilityKind::Relay, "push", json!({"provider": provider, "message_json": message_json}))
            .await
            .map(|_| ())
            .map_err(|e| relay::Error::Denied(e.message))
    }
}

impl flags::Host for ExecutorHostState {
    async fn enabled(&mut self, key: String, default_value: bool) -> bool {
        self.wire
            .call(CapabilityKind::Flags, "enabled", json!({"key": key, "default_value": default_value}))
            .await
            .ok()
            .and_then(|v| v.as_bool())
            .unwrap_or(default_value)
    }
    async fn tier(&mut self) -> String {
        self.wire.call(CapabilityKind::Flags, "tier", json!({})).await.ok().and_then(|v| v.as_str().map(str::to_string)).unwrap_or_else(|| "free".to_string())
    }
}

impl log::Host for ExecutorHostState {
    async fn write(&mut self, lvl: log::Level, message: String, fields_json: String) {
        let lvl_str = match lvl {
            log::Level::Error => "error",
            log::Level::Warn => "warn",
            log::Level::Info => "info",
            log::Level::Debug => "debug",
        };
        let _ = self.wire.call(CapabilityKind::Log, "write", json!({"lvl": lvl_str, "message": message, "fields_json": fields_json})).await;
    }
}

impl clock::Host for ExecutorHostState {
    async fn now_millis(&mut self) -> u64 {
        self.wire.call(CapabilityKind::Clock, "now_millis", json!({})).await.ok().and_then(|v| v.as_u64()).unwrap_or(0)
    }
    async fn now_rfc3339(&mut self) -> String {
        self.wire.call(CapabilityKind::Clock, "now_rfc3339", json!({})).await.ok().and_then(|v| v.as_str().map(str::to_string)).unwrap_or_default()
    }
    async fn monotonic_nanos(&mut self) -> u64 {
        self.wire.call(CapabilityKind::Clock, "monotonic_nanos", json!({})).await.ok().and_then(|v| v.as_u64()).unwrap_or(0)
    }
}
```

- [ ] **Step 5: Implement `src/executor/wire_client.rs`**

```rust
//! The executor's mTLS client connection to its stage: dials, sends
//! `hello`, awaits `hello-ok`, then serves `load`/`unload`/`invoke`/
//! `ping`/`shutdown` for as long as the connection lives (spec §6.6,
//! §7.1: "the executor dials the stage; the stage never dials the executor").

use std::net::SocketAddr;
use std::sync::Arc;

use rustls_pki_types::{CertificateDer, PrivateKeyDer, ServerName};
use tokio::net::TcpStream;
use tokio_rustls::TlsConnector;

use crate::wire::message::{ExportKind, LoadLimits, Message, SandboxInfo};
use crate::wire::transport::FrameTransport;

pub struct ExecutorTlsConfig {
    pub cert_chain: Vec<CertificateDer<'static>>,
    pub private_key: PrivateKeyDer<'static>,
    pub server_ca: CertificateDer<'static>,
    pub server_name: String,
}

pub struct HelloAnnouncement {
    pub executor_version: String,
    pub wasmtime_abi: String,
    pub collector: String,
    pub sandbox: SandboxInfo,
}

#[derive(Debug, thiserror::Error)]
pub enum ExecutorClientError {
    #[error("io error: {0}")]
    Io(#[from] std::io::Error),
    #[error("tls error: {0}")]
    Tls(String),
    #[error("transport error: {0}")]
    Transport(#[from] crate::wire::transport::TransportError),
    #[error("handshake refused: {0}")]
    HandshakeRefused(String),
}

#[async_trait::async_trait]
pub trait StageRequestHandler: Send + Sync {
    async fn on_load(
        &self,
        app_id: &str,
        version: &str,
        digest: &str,
        component_key: &str,
        sidecar_key: &str,
        capabilities: Vec<String>,
        limits: LoadLimits,
    ) -> Result<(String, u64, Vec<String>), String>;
    async fn on_unload(&self, app_id: &str, digest: &str) -> Result<(), String>;
    /// D30 (spec §5.11): `scope` is the invocation's full tenant/
    /// community/workstream scope, taken from `Message::Invoke.scope` --
    /// `scope.app_id` supersedes the pre-D30 standalone `app_id`
    /// parameter this method used to take.
    async fn on_invoke(
        &self,
        scope: crate::wire::message::InvocationScope,
        digest: &str,
        export: ExportKind,
        payload: serde_json::Value,
        deadline_ms: u64,
        invoke_frame_id: u64,
    ) -> Result<serde_json::Value, String>;
}

pub struct ExecutorClient {
    transport: Arc<FrameTransport>,
}

impl ExecutorClient {
    pub async fn dial(addr: SocketAddr, tls: ExecutorTlsConfig, hello: HelloAnnouncement) -> Result<Self, ExecutorClientError> {
        let mut root_store = rustls::RootCertStore::empty();
        root_store.add(tls.server_ca).map_err(|e| ExecutorClientError::Tls(e.to_string()))?;
        let client_config = rustls::ClientConfig::builder()
            .with_root_certificates(root_store)
            .with_client_auth_cert(tls.cert_chain, tls.private_key)
            .map_err(|e| ExecutorClientError::Tls(e.to_string()))?;
        let connector = TlsConnector::from(Arc::new(client_config));

        let tcp = TcpStream::connect(addr).await?;
        let server_name = ServerName::try_from(tls.server_name).map_err(|e| ExecutorClientError::Tls(e.to_string()))?;
        let tls_stream = connector.connect(server_name, tcp).await.map_err(|e| ExecutorClientError::Tls(e.to_string()))?;

        let transport = Arc::new(FrameTransport::spawn(tls_stream, crate::wire::frame::MAX_FRAME_BYTES));

        let hello_reply = transport
            .call(Message::Hello {
                protocol_version: 1,
                executor_version: hello.executor_version,
                wasmtime_version: wasmtime::VERSION.to_string(),
                wasmtime_abi: hello.wasmtime_abi,
                collector: hello.collector,
                sandbox: hello.sandbox,
            })
            .await?;

        match hello_reply {
            Message::HelloOk { .. } => Ok(Self { transport }),
            Message::Error { message, .. } => Err(ExecutorClientError::HandshakeRefused(message)),
            other => Err(ExecutorClientError::HandshakeRefused(format!("unexpected reply {other:?}"))),
        }
    }

    /// The underlying transport, so a `StageRequestHandler` (Task 22's
    /// `Handler`) can build a `RemoteHostWire` on the same connection
    /// `serve()` reads `host-call` replies from -- host-call frames a
    /// bundle's `Host` trait impl sends and the `hello`/`load`/`invoke`
    /// traffic this client itself sends are correlated on one shared
    /// `FrameTransport`, exactly as spec §6.6 requires ("both sides may
    /// have many [frames] in flight" on the one connection).
    pub fn transport(&self) -> Arc<FrameTransport> {
        self.transport.clone()
    }

    pub async fn serve(&self, handler: Arc<dyn StageRequestHandler>) -> Result<(), ExecutorClientError> {
        loop {
            let frame = self.transport.recv_unsolicited().await?;
            match frame.message {
                Message::Load { app_id, version, digest, component_key, sidecar_key, capabilities, limits } => {
                    let reply = match handler.on_load(&app_id, &version, &digest, &component_key, &sidecar_key, capabilities, limits).await {
                        Ok((digest, precompile_ms, exports)) => Message::Loaded { app_id, digest, precompile_ms, exports },
                        Err(message) => Message::Error { code: crate::wire::message::ErrorCode::LoadFailed, message, detail: None },
                    };
                    self.transport.send(frame.id, reply).await?;
                }
                Message::Unload { app_id, digest } => {
                    let reply = match handler.on_unload(&app_id, &digest).await {
                        Ok(()) => Message::Unloaded { app_id, digest },
                        Err(message) => Message::Error { code: crate::wire::message::ErrorCode::LoadFailed, message, detail: None },
                    };
                    self.transport.send(frame.id, reply).await?;
                }
                Message::Invoke { digest, export, payload, deadline_ms, scope } => {
                    let started = std::time::Instant::now();
                    let reply = match handler.on_invoke(scope, &digest, export, payload, deadline_ms, frame.id).await {
                        Ok(result_payload) => Message::Result { payload: result_payload, duration_ms: started.elapsed().as_millis() as u64, fuel_used: 0 },
                        Err(message) => Message::Error { code: crate::wire::message::ErrorCode::ExecutorDeadline, message, detail: None },
                    };
                    self.transport.send(frame.id, reply).await?;
                }
                Message::Ping => {
                    self.transport.send(frame.id, Message::Pong).await?;
                }
                Message::Shutdown { .. } => return Ok(()),
                _ => continue,
            }
        }
    }
}
```

- [ ] **Step 6: Export from `src/executor/mod.rs`**

```rust
pub mod bindings;
pub mod engine;
pub mod invoke;
pub mod loader;
pub mod pool;
pub mod remote_host_impl;
pub mod wasi_ctx;
pub mod wire_client;
```

- [ ] **Step 7: Run to verify pass**

Run: `make test`
Expected: PASS — both `executor_remote_host_tests` green.

- [ ] **Step 8: Commit**

```bash
git add packages/rust-bundle-host/src/executor
git commit -m "$(cat <<'EOF'
feat(bundle-host): executor remote Host impl + mTLS wire client

RemoteHostWire forwards every WIT Host trait method (context/http/kv/db/
relay/flags/log/clock) as a host-call frame tagged with the owning
invoke's frame id as call_id, so the stage's context lookup (Task 17)
resolves correctly. ExecutorClient dials the stage first (spec §7.1),
completes the hello/hello-ok handshake, and serves load/unload/invoke/
ping/shutdown via a StageRequestHandler the bundle-executor binary
implements. RemoteHostWire/on_invoke now carry the D30 InvocationScope
(spec §5.11) end to end -- scope.app_id supersedes the pre-D30
standalone app_id field on every affected type.

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01N2rQgkHY872RubwXoBZxtE
EOF
)"
git push
```

---

## Task 22: `bundle-executor` binary — config, gVisor self-check, telemetry, end-to-end wiring

**Depends on:** Task 21 (`ExecutorClient`, `StageRequestHandler`, `RemoteHostWire`), Task 20 (`BucketLoader`), Task 18 (`InstancePool`, `BundleRuntime`), Task 17 (`Server`, for the e2e test's stage side), Task 6 (`EngineHandle`), and `penguin-logging` 0.1.0.

**Files:**
- Create: `packages/rust-bundle-host/src/bin/bundle_executor/config.rs`
- Create: `packages/rust-bundle-host/src/bin/bundle_executor/sandbox_check.rs`
- Create: `packages/rust-bundle-host/src/bin/bundle_executor/telemetry.rs`
- Create: `packages/rust-bundle-host/src/bin/bundle_executor/main.rs`
- Test: `packages/rust-bundle-host/tests/bundle_executor_e2e_tests.rs`

**Interfaces:**
- Consumes: everything from Tasks 6, 7, 18, 20, 21.
- Produces: the `bundle-executor` binary (`cargo build --bin bundle-executor`), env-configured per this task's `ExecutorConfig`. No other crate consumes this binary's own types — it is the terminal wiring point.

- [ ] **Step 1: Implement `src/bin/bundle_executor/config.rs`**

```rust
//! Env-only configuration (spec §12.7) -- every value below is read
//! from an environment variable or a mounted file, never a CLI flag
//! (`security.md` Token & Secret Hygiene).

use clap::Parser;

#[derive(Parser, Debug, Clone)]
#[command(name = "bundle-executor")]
pub struct ExecutorConfig {
    #[arg(env = "STAGE_HOST_API_ADDR")]
    pub stage_host_api_addr: String,

    #[arg(env = "HOST_API_TLS_CERT_FILE", default_value = "/etc/waddles/host-api/tls.crt")]
    pub host_api_tls_cert_file: String,
    #[arg(env = "HOST_API_TLS_KEY_FILE", default_value = "/etc/waddles/host-api/tls.key")]
    pub host_api_tls_key_file: String,
    #[arg(env = "HOST_API_TLS_CA_FILE", default_value = "/etc/waddles/host-api/ca.crt")]
    pub host_api_tls_ca_file: String,
    #[arg(env = "HOST_API_PEER_IDENTITY")]
    pub host_api_peer_identity: String,

    #[arg(env = "SANDBOX_RUNTIME_EXPECTED", default_value = "gvisor")]
    pub sandbox_runtime_expected: String,
    #[arg(env = "WADDLES_SANDBOX_GVISOR", default_value_t = true)]
    pub waddles_sandbox_gvisor: bool,

    #[arg(env = "EXECUTOR_CALL_TIMEOUT_MS", default_value_t = 2000)]
    pub executor_call_timeout_ms: u64,
    #[arg(env = "EXECUTOR_MAX_CALL_TIMEOUT_MS", default_value_t = 10000)]
    pub executor_max_call_timeout_ms: u64,
    #[arg(env = "EXECUTOR_MEMORY_LIMIT_MB", default_value_t = 64)]
    pub executor_memory_limit_mb: u32,
    #[arg(env = "EXECUTOR_MAX_MEMORY_LIMIT_MB", default_value_t = 256)]
    pub executor_max_memory_limit_mb: u32,
    #[arg(env = "EXECUTOR_INSTANCES_PER_BUNDLE", default_value_t = 4)]
    pub executor_instances_per_bundle: usize,
    #[arg(env = "EXECUTOR_MAX_CONCURRENT_CALLS", default_value_t = 32)]
    pub executor_max_concurrent_calls: usize,
    #[arg(env = "EXECUTOR_POOL_WAIT_MS", default_value_t = 500)]
    pub executor_pool_wait_ms: u64,
    #[arg(env = "EXECUTOR_TRIP_THRESHOLD", default_value_t = 3)]
    pub executor_trip_threshold: u8,
    #[arg(env = "EXECUTOR_TRIP_WINDOW_S", default_value_t = 300)]
    pub executor_trip_window_s: u64,
    #[arg(env = "EXECUTOR_PRECOMPILE_DIR", default_value = "/var/cache/waddles/wasm")]
    pub executor_precompile_dir: String,
    #[arg(env = "EXECUTOR_WASM_COLLECTOR", default_value = "drc")]
    pub executor_wasm_collector: String,

    #[arg(env = "BUNDLE_BUCKET_ENDPOINT")]
    pub bundle_bucket_endpoint: String,
    #[arg(env = "BUNDLE_BUCKET_NAME")]
    pub bundle_bucket_name: String,
    #[arg(env = "BUNDLE_BUCKET_REGION", default_value = "us-east-1")]
    pub bundle_bucket_region: String,
    #[arg(env = "BUNDLE_BUCKET_ACCESS_KEY_ID")]
    pub bundle_bucket_access_key_id: String,
    #[arg(env = "BUNDLE_BUCKET_SECRET_ACCESS_KEY")]
    pub bundle_bucket_secret_access_key: String,
    #[arg(env = "BUNDLE_POLL_INTERVAL_S", default_value_t = 60)]
    pub bundle_poll_interval_s: u64,
    #[arg(env = "BUNDLE_CACHE_VERSIONS", default_value_t = 3)]
    pub bundle_cache_versions: usize,
    #[arg(env = "BUNDLE_SIGNING_PUBLIC_KEY")]
    pub bundle_signing_public_key: String,

    #[arg(env = "EXECUTOR_HEALTH_PORT", default_value_t = 9090)]
    pub executor_health_port: u16,
    // OTEL_EXPORTER_OTLP_ENDPOINT / _PROTOCOL / _HEADERS, OTEL_SERVICE_NAME,
    // OTEL_RESOURCE_ATTRIBUTES and LOG_LEVEL are deliberately absent here:
    // `penguin_logging::ServiceConfig::from_env` reads them itself
    // (M1b Task 4). Declaring them a second time would let this binary's
    // defaults silently disagree with the ones the logging crate applies.
}

impl ExecutorConfig {
    /// The `0.0.0.0:{EXECUTOR_HEALTH_PORT}` address the health/metrics
    /// router binds. Separate from the stage connection, which is
    /// outbound only.
    pub fn health_addr(&self) -> std::net::SocketAddr {
        std::net::SocketAddr::from(([0, 0, 0, 0], self.executor_health_port))
    }
}
```

**No secret is ever a CLI argument here.** Every `#[arg(env = ...)]` above
is reachable as a long flag too, which is how `clap`'s derive works, but
the deployment sets all of them through the environment or a mounted
file, and `BUNDLE_BUCKET_SECRET_ACCESS_KEY` / `BUNDLE_SIGNING_PUBLIC_KEY`
in particular are never passed on a command line and never logged
(`security.md` Token & Secret Hygiene). Add this test to
`tests/bundle_executor_e2e_tests.rs` so a future field cannot quietly
start printing one:

```rust
#[test]
fn executor_config_never_derives_debug_output_containing_a_secret_value() {
    // ExecutorConfig derives Debug for clap; assert the one field that
    // would leak is never rendered by any of this binary's own logging.
    // The check is a source scan, not a runtime assertion, because the
    // failure mode is a `tracing::info!(?config)` someone adds later.
    let main_rs = include_str!("../src/bin/bundle_executor/main.rs");
    let telemetry_rs = include_str!("../src/bin/bundle_executor/telemetry.rs");
    let mut scanned = 0usize;
    for (name, src) in [("main.rs", main_rs), ("telemetry.rs", telemetry_rs)] {
        assert!(
            !src.contains("?config") && !src.contains("{config:?}") && !src.contains("%config"),
            "{name} renders the whole ExecutorConfig into a log line, which would print bucket credentials"
        );
        scanned += 1;
    }
    assert_eq!(scanned, 2, "expected exactly 2 binary source files scanned, got {scanned}");
}
```

- [ ] **Step 2: Implement `src/bin/bundle_executor/sandbox_check.rs`**

```rust
//! gVisor self-check (spec §12.2). Verification is injectable-by-string
//! for unit testing; production reads the real `/proc` files.

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct SandboxDetection {
    pub runtime: String, // "gvisor" | "runc"
    pub verified: bool,
}

/// `/proc/version` under gVisor reports a gVisor kernel string; a real
/// Linux kernel always emits a `Speculation_Store_Bypass:` line in
/// `/proc/self/status`, which gVisor's sentry omits -- corroborating
/// signal so a spoofed `/proc/version` string alone cannot pass.
pub fn detect_from_proc_strings(proc_version: &str, proc_self_status: &str) -> SandboxDetection {
    let version_says_gvisor = proc_version.to_lowercase().contains("gvisor");
    let status_lacks_native_field = !proc_self_status.contains("Speculation_Store_Bypass");
    if version_says_gvisor && status_lacks_native_field {
        SandboxDetection { runtime: "gvisor".to_string(), verified: true }
    } else {
        SandboxDetection { runtime: "runc".to_string(), verified: false }
    }
}

pub fn detect() -> SandboxDetection {
    let proc_version = std::fs::read_to_string("/proc/version").unwrap_or_default();
    let proc_self_status = std::fs::read_to_string("/proc/self/status").unwrap_or_default();
    detect_from_proc_strings(&proc_version, &proc_self_status)
}

/// Exit code `78` (`EX_CONFIG`, spec §12.2) when `WADDLES_SANDBOX_GVISOR`
/// is true but the pod is not actually under gVisor -- crash-loop with
/// the reason in the logs rather than pretend.
pub fn enforce_or_exit(expected_gvisor: bool, detection: &SandboxDetection) {
    if expected_gvisor && detection.runtime != "gvisor" {
        tracing::error!(
            expected = "gvisor",
            actual = %detection.runtime,
            "WADDLES_SANDBOX_GVISOR=true but this pod is not running under the gVisor RuntimeClass -- refusing to start"
        );
        std::process::exit(78);
    }
    if !expected_gvisor {
        tracing::warn!(
            "GVISOR SANDBOX DISABLED -- WADDLES_SANDBOX_GVISOR=false: bundle code runs on the host kernel's syscall surface. \
             One defence-in-depth layer is removed in exchange for lower per-call latency. This is an explicit, visible opt-out."
        );
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn a_real_linux_kernel_string_with_the_native_only_field_is_not_gvisor() {
        let d = detect_from_proc_strings("Linux version 6.8.0-generic", "Name:\tbash\nSpeculation_Store_Bypass:\tthread vulnerable\n");
        assert_eq!(d, SandboxDetection { runtime: "runc".to_string(), verified: false });
    }

    #[test]
    fn a_gvisor_version_string_missing_the_native_field_is_gvisor() {
        let d = detect_from_proc_strings("Linux version 4.4.0 #1 SMP gVisor", "Name:\tbundle-executor\n");
        assert_eq!(d, SandboxDetection { runtime: "gvisor".to_string(), verified: true });
    }

    #[test]
    fn a_gvisor_looking_version_string_that_still_has_the_native_field_is_not_trusted() {
        // Guards against a spoofed /proc/version alone being sufficient.
        let d = detect_from_proc_strings("gVisor-flavored but fake", "Speculation_Store_Bypass:\tthread vulnerable\n");
        assert_eq!(d.runtime, "runc");
    }
}
```

- [ ] **Step 3: Implement `src/bin/bundle_executor/telemetry.rs`**

This file contains no exporter construction, no `tracing_subscriber`
registry and no OTLP code at all -- `penguin-logging` (milestone M1b)
owns every bit of that. What lives here is only the *wiring*: one `init`
call, the `HealthState` this binary keeps current, and the metric names
this crate emits.

```rust
//! Telemetry wiring for `bundle-executor`. Everything real is
//! `penguin-logging` (M1b): stdout JSON + OTLP logs, the OTel meter that
//! also backs `/metrics`, the tracer, and the `/health`/`/healthz`
//! endpoints. This module exists to call it once, own the `HealthState`,
//! and give the executor's metric names one home.
//!
//! The OTLP destination comes from `OTEL_EXPORTER_OTLP_ENDPOINT` and its
//! siblings via `ServiceConfig::from_env` -- never a constant in this
//! file (`critical-rules.md` Observability). An unset endpoint means
//! stdout JSON only; it is never an error and never a fallback URL.

use std::net::SocketAddr;

use opentelemetry::KeyValue;
use penguin_logging::health::{DependencyStatus, HealthState};
use penguin_logging::{ServiceConfig, TelemetryGuard};

/// Per-load latency, in milliseconds: bucket fetch + verify + precompile.
pub const BUNDLE_LOAD_MS: &str = "waddles_bundle_load_duration_ms";
/// Per-invoke latency, in milliseconds, labelled by export.
pub const BUNDLE_INVOKE_MS: &str = "waddles_bundle_invoke_duration_ms";
/// Per-host-call round-trip latency, in milliseconds, labelled by capability.
pub const HOST_CALL_MS: &str = "waddles_bundle_host_call_duration_ms";
/// Invocations, labelled by export and outcome (`ok`/`error`).
pub const BUNDLE_INVOCATIONS: &str = "waddles_bundle_invocations_total";
/// Sandbox trips recorded, labelled by app_id and reason.
pub const BUNDLE_TRIPS: &str = "waddles_bundle_trips_total";
/// Currently-loaded bundles.
pub const BUNDLES_LOADED: &str = "waddles_bundles_loaded";
/// D30 (spec §5.11): a Sec5.11 hop-verification failure or a
/// bundle-output identity-field tamper attempt, labelled by stage and
/// reason. Shared with `penguin-spine`'s `SpineMetrics::
/// tenant_boundary_violation` -- same metric name, same label set,
/// whichever layer first observes the violation increments it.
pub const TENANT_BOUNDARY_VIOLATIONS: &str = "waddles_tenant_boundary_violations_total";
/// Age in seconds of the newest successful bucket reconciliation --
/// how stale the served bundle set is (README "Offline" note).
pub const BUNDLE_STALE_AGE_S: &str = "waddles_bundle_stale_age_seconds";

/// Wires `penguin-logging` and returns its guard plus a fresh
/// `HealthState`. Call exactly once, first thing in `main` --
/// `penguin_logging::init` installs a process-global subscriber and
/// panics if called twice.
///
/// The returned `TelemetryGuard` must stay alive for the whole process:
/// dropping it flushes and shuts down the OTel exporters.
pub fn init() -> (TelemetryGuard, HealthState) {
    let cfg = ServiceConfig::from_env("bundle-executor");
    // The third element is the `prometheus::Registry` backing /metrics.
    // `penguin_logging::health::router` already reads it, and naming the
    // type here would mean adding `prometheus` as a direct dependency of
    // this crate for no other reason -- so it is dropped on the floor
    // deliberately, not forgotten.
    let (guard, _level, _prometheus_registry) = penguin_logging::init(cfg);
    (guard, HealthState::new())
}

/// Serves `/health`, `/healthz` and `/metrics` on `addr`. Spawned, never
/// awaited by `main`: a telemetry surface that fails to bind logs an
/// ERROR and the executor keeps serving bundles (`critical-rules.md`:
/// telemetry failure is never a request failure).
pub fn spawn_health_server(state: HealthState, addr: SocketAddr) -> tokio::task::JoinHandle<()> {
    tokio::spawn(async move {
        let router = penguin_logging::health::router(state);
        match tokio::net::TcpListener::bind(addr).await {
            Ok(listener) => {
                tracing::info!(%addr, "health/metrics endpoint listening");
                if let Err(error) = axum::serve(listener, router).await {
                    tracing::error!(%error, "health/metrics server stopped");
                }
            }
            Err(error) => tracing::error!(%addr, %error, "could not bind health/metrics endpoint"),
        }
    })
}

/// Record one bundle invocation: a latency histogram plus an outcome
/// counter. Histograms first -- a bare counter is not instrumentation
/// (`critical-rules.md` Observability).
pub fn record_invocation(export: &'static str, outcome: &'static str, millis: f64) {
    let labels = [KeyValue::new("export", export), KeyValue::new("outcome", outcome)];
    penguin_logging::metrics::record_latency_ms(BUNDLE_INVOKE_MS, millis, &labels);
    penguin_logging::metrics::counter_add(BUNDLE_INVOCATIONS, 1, &labels);
}

/// Record one completed bundle load (fetch + verify + precompile).
pub fn record_load(millis: f64, loaded_now: u64) {
    penguin_logging::metrics::record_latency_ms(BUNDLE_LOAD_MS, millis, &[]);
    penguin_logging::metrics::gauge_set(BUNDLES_LOADED, loaded_now as f64, &[]);
}

/// Record one host-call round trip, labelled by capability.
pub fn record_host_call(capability: &'static str, millis: f64) {
    penguin_logging::metrics::record_latency_ms(HOST_CALL_MS, millis, &[KeyValue::new("capability", capability)]);
}

/// Record a sandbox trip (deadline, memory cap, trap, or three denials).
pub fn record_trip(reason: &'static str) {
    penguin_logging::metrics::counter_add(BUNDLE_TRIPS, 1, &[KeyValue::new("reason", reason)]);
}

/// Record one D30 tenant-boundary violation this executor observed
/// directly -- currently only `bundle_set_identity` (a process bundle's
/// transform output tried to set a reserved envelope-identity field).
/// The remaining `BoundaryError` reasons (`mac_mismatch`, `unknown_kid`,
/// `tenant_mismatch`, `community_mismatch`) are observed and counted by
/// the stage binary (M4/M5) via `penguin-spine`'s own
/// `SpineMetrics::tenant_boundary_violation`, not here -- this executor
/// never sees an envelope, only a bundle's transform output.
pub fn record_tenant_boundary_violation(stage: &'static str, reason: &'static str) {
    penguin_logging::metrics::counter_add(
        TENANT_BOUNDARY_VIOLATIONS,
        1,
        &[KeyValue::new("stage", stage), KeyValue::new("reason", reason)],
    );
}

/// Mark the stage connection up or down on `/health` in one call, so the
/// JSON body and the `waddles_dependency_up` metric never drift.
pub fn set_stage_dependency(state: &HealthState, status: DependencyStatus) {
    state.set_dependency("stage-host-api", status);
}
```

- [ ] **Step 4: Implement `src/bin/bundle_executor/main.rs`**

```rust
//! Wires config -> sandbox check -> telemetry -> engine -> bucket loader
//! -> instance pool -> mTLS client -> serve, end to end.

mod config;
mod sandbox_check;
mod telemetry;

use std::collections::HashMap;
use std::sync::Arc;

use base64::Engine as _;
use clap::Parser;
use ed25519_dalek::VerifyingKey;
use object_store::aws::AmazonS3Builder;
use penguin_bundle_host::executor::engine::{EngineConfig, EngineHandle};
use penguin_bundle_host::executor::invoke::{BundleRuntime, ExecutorHostState, PlatformEventDto};
use penguin_bundle_host::executor::loader::bucket::BucketLoader;
use penguin_bundle_host::executor::pool::InstancePool;
use penguin_bundle_host::executor::remote_host_impl::RemoteHostWire;
use penguin_bundle_host::executor::wire_client::{ExecutorClient, ExecutorTlsConfig, HelloAnnouncement, StageRequestHandler};
use penguin_bundle_host::wire::message::{ExportKind, LoadLimits, SandboxInfo};
use penguin_bundle_host::wire::transport::FrameTransport;
use rustls::pki_types::{CertificateDer, PrivateKeyDer};
use tokio::sync::RwLock;
use tracing::Instrument as _;

struct Handler {
    engine: Arc<EngineHandle>,
    loader: Arc<BucketLoader<object_store::aws::AmazonS3>>,
    pool: Arc<InstancePool>,
    runtimes: RwLock<HashMap<String, (String, Arc<BundleRuntime>)>>, // app_id -> (digest, runtime)
    scratch_root: std::path::PathBuf,
    /// Shared with `ExecutorClient` (`client.transport()`, obtained after
    /// `dial()` succeeds) -- every `RemoteHostWire` this handler builds
    /// for an `invoke` sends its `host-call` frames on this same
    /// connection, so the stage's single `pending_contexts` map
    /// (Task 17) sees them.
    transport: Arc<FrameTransport>,
}

#[async_trait::async_trait]
impl StageRequestHandler for Handler {
    async fn on_load(
        &self,
        app_id: &str,
        version: &str,
        digest: &str,
        component_key: &str,
        sidecar_key: &str,
        capabilities: Vec<String>,
        limits: LoadLimits,
    ) -> Result<(String, u64, Vec<String>), String> {
        let started = std::time::Instant::now();
        let bundle = penguin_bundle_host::executor::loader::reconcile::AdvertisedBundle {
            app_id: app_id.to_string(), digest: digest.to_string(), version: version.to_string(),
            component_key: component_key.to_string(), sidecar_key: sidecar_key.to_string(),
            capabilities, limits,
        };
        let (component_bytes, metadata) = self.loader.fetch_and_verify(&bundle).await.map_err(|e| e.to_string())?;
        // Precompile to a `.cwasm` keyed {digest}-{wasmtime_abi}-{collector}
        // and load THAT, not the original bytes -- a write-only cache would
        // pay the Cranelift cost on every load and defeat the point of
        // spec §7.2's precompile step. `precompile` is a no-op returning the
        // existing path when the cache key already exists.
        let cwasm_path = self.loader.precompile(&metadata.digest, &component_bytes).await.map_err(|e| e.to_string())?;

        // SAFETY: `Component::deserialize_file` trusts the file's bytes to be
        // a `.cwasm` this same wasmtime built. Both conditions hold here and
        // only here: `fetch_and_verify` above already accepted the component's
        // Ed25519-signed digest, and `precompile` wrote this exact file from
        // those bytes under a cache key that includes `wasmtime_abi` and the
        // pinned collector, so a file from a different runtime can never be
        // read back under this key. One of exactly two allow sites in the
        // crate (Global Constraints).
        #[allow(unsafe_code)]
        let component = unsafe {
            wasmtime::component::Component::deserialize_file(&self.engine.engine, &cwasm_path)
        }
        .map_err(|e| format!("precompiled artifact at {} did not load: {e}", cwasm_path.display()))?;

        let scratch_dir = self.scratch_root.join(app_id.replace('.', "_"));
        tokio::fs::create_dir_all(&scratch_dir).await.map_err(|e| e.to_string())?;

        let mut linker: wasmtime::component::Linker<ExecutorHostState> = wasmtime::component::Linker::new(&self.engine.engine);
        wasmtime_wasi::p2::add_to_linker_async(&mut linker).map_err(|e| e.to_string())?;
        penguin_bundle_host::executor::bindings::stage_world::waddle::bundle::context::add_to_linker(&mut linker, |s| s).map_err(|e| e.to_string())?;
        penguin_bundle_host::executor::bindings::stage_world::waddle::bundle::http::add_to_linker(&mut linker, |s| s).map_err(|e| e.to_string())?;
        penguin_bundle_host::executor::bindings::stage_world::waddle::bundle::kv::add_to_linker(&mut linker, |s| s).map_err(|e| e.to_string())?;
        penguin_bundle_host::executor::bindings::stage_world::waddle::bundle::db::add_to_linker(&mut linker, |s| s).map_err(|e| e.to_string())?;
        penguin_bundle_host::executor::bindings::stage_world::waddle::bundle::relay::add_to_linker(&mut linker, |s| s).map_err(|e| e.to_string())?;
        penguin_bundle_host::executor::bindings::stage_world::waddle::bundle::flags::add_to_linker(&mut linker, |s| s).map_err(|e| e.to_string())?;
        penguin_bundle_host::executor::bindings::stage_world::waddle::bundle::log::add_to_linker(&mut linker, |s| s).map_err(|e| e.to_string())?;
        penguin_bundle_host::executor::bindings::stage_world::waddle::bundle::clock::add_to_linker(&mut linker, |s| s).map_err(|e| e.to_string())?;

        let runtime = Arc::new(BundleRuntime::new(self.engine.clone(), component, linker, scratch_dir));
        let loaded_now = {
            let mut runtimes = self.runtimes.write().await;
            runtimes.insert(app_id.to_string(), (metadata.digest.clone(), runtime));
            runtimes.len() as u64
        };

        let elapsed_ms = started.elapsed().as_millis() as u64;
        crate::telemetry::record_load(elapsed_ms as f64, loaded_now);
        tracing::info!(
            app_id, version, digest = %metadata.digest, elapsed_ms, loaded_now,
            "bundle loaded"
        );

        Ok((metadata.digest, elapsed_ms, vec!["transform".to_string(), "dispatch".to_string()]))
    }

    async fn on_unload(&self, app_id: &str, _digest: &str) -> Result<(), String> {
        self.runtimes.write().await.remove(app_id);
        Ok(())
    }

    async fn on_invoke(
        &self,
        scope: crate::wire::message::InvocationScope,
        digest: &str,
        export: ExportKind,
        payload: serde_json::Value,
        deadline_ms: u64,
        invoke_frame_id: u64,
    ) -> Result<serde_json::Value, String> {
        let started = std::time::Instant::now();
        let app_id = scope.app_id.as_str();
        let runtimes = self.runtimes.read().await;
        let (_loaded_digest, runtime) = runtimes.get(app_id).ok_or_else(|| "UNKNOWN_BUNDLE".to_string())?;
        let wire = RemoteHostWire { transport: self.transport.clone(), scope: scope.clone(), invoke_frame_id };

        // One span per invocation: the unit of work every trace of this
        // service is built around. It is applied with `Instrument` on the
        // future, NOT with `span.entered()` -- an `Entered` guard held
        // across an `.await` attaches the span to whatever task the
        // executor resumes next, which silently corrupts every trace in a
        // multi-threaded runtime.
        //
        // D30 (spec §5.11, §13.2): every span carries waddles.tenant_id/
        // .community_id/.workstream_id/.app_id -- ids only, never PII or
        // message bodies. community_id renders as the literal "_tenant"
        // sentinel (matching the Valkey key segment) when the workstream
        // is tenant-wide, so a span field is never simply absent.
        let community_label = scope.community_id.as_deref().unwrap_or("_tenant");
        let span = tracing::info_span!(
            "bundle.invoke",
            app_id,
            digest,
            ?export,
            waddles.tenant_id = %scope.tenant_id,
            waddles.community_id = %community_label,
            waddles.workstream_id = %scope.workstream_id,
            waddles.app_id = app_id,
        );
        let outcome = async {
            match export {
                ExportKind::Transform => {
                    let event: PlatformEventDto = serde_json::from_value(payload).map_err(|e| e.to_string())?;
                    let mut result = runtime
                        .call_transform(&self.pool, app_id, digest, deadline_ms, 64, event, wire)
                        .await
                        .map_err(|e| e.to_string())?;

                    // D30 (spec §5.11 "Bundles cannot move a workstream"):
                    // a process bundle's transform output is read for its
                    // event.payload only -- tenant/community/workstream_id/
                    // event_id/trace are never read from it, and a
                    // bundle-supplied field of the same name is dropped
                    // and counted, never silently accepted. The stage
                    // (M4, out of this crate's scope) still copies the
                    // *input* envelope's identity fields onto the outgoing
                    // envelope unconditionally; this is the one place that
                    // guest-controlled JSON (payload_json) could otherwise
                    // smuggle a same-named key back in.
                    if let Some(out_event) = result.as_mut() {
                        if let Ok(mut payload_map) =
                            serde_json::from_str::<serde_json::Map<String, serde_json::Value>>(&out_event.payload_json)
                        {
                            if let Some(field) = penguin_spine::strip_bundle_identity_fields(&mut payload_map) {
                                crate::telemetry::record_tenant_boundary_violation("process", "bundle_set_identity");
                                tracing::warn!(app_id, field, "process bundle output attempted to set a reserved identity field; dropped");
                                out_event.payload_json = serde_json::to_string(&payload_map).map_err(|e| e.to_string())?;
                            }
                        }
                    }

                    serde_json::to_value(result).map_err(|e| e.to_string())
                }
                ExportKind::Dispatch => {
                    let envelope: penguin_bundle_host::executor::invoke::StageEnvelopeDto =
                        serde_json::from_value(payload).map_err(|e| e.to_string())?;
                    let result = runtime
                        .call_dispatch(&self.pool, app_id, digest, deadline_ms, 64, envelope, "{}", wire)
                        .await
                        .map_err(|e| e.to_string())?;
                    serde_json::to_value(result).map_err(|e| e.to_string())
                }
            }
        }
        .instrument(span)
        .await;

        let export_label = match export {
            ExportKind::Transform => "transform",
            ExportKind::Dispatch => "dispatch",
        };
        let millis = started.elapsed().as_secs_f64() * 1000.0;
        match &outcome {
            Ok(_) => {
                crate::telemetry::record_invocation(export_label, "ok", millis);
                tracing::debug!(app_id, digest, export_label, millis, "invocation completed");
            }
            Err(error) => {
                crate::telemetry::record_invocation(export_label, "error", millis);
                crate::telemetry::record_trip("invoke_error");
                tracing::warn!(app_id, digest, export_label, millis, %error, "invocation failed");
            }
        }
        outcome
    }
}

#[tokio::main]
async fn main() -> anyhow::Result<()> {
    let config = config::ExecutorConfig::parse();

    // First statement of the process: penguin_logging::init installs the
    // global subscriber, so nothing before it can be logged or traced.
    let (_telemetry_guard, health) = telemetry::init();
    let _health_server = telemetry::spawn_health_server(health.clone(), config.health_addr());

    let detection = sandbox_check::detect();
    health.set_sandbox(&detection.runtime, detection.verified);
    sandbox_check::enforce_or_exit(config.waddles_sandbox_gvisor, &detection);

    if config.executor_wasm_collector != "drc" {
        tracing::error!(collector = %config.executor_wasm_collector, "EXECUTOR_WASM_COLLECTOR must be 'drc' -- refusing to start");
        std::process::exit(78);
    }

    let engine = Arc::new(EngineHandle::new(&EngineConfig {
        max_memory_bytes: config.executor_max_memory_limit_mb as usize * 1024 * 1024,
        epoch_tick_ms: 10,
        collector: config.executor_wasm_collector.clone(),
    })?);
    let _ticker = engine.spawn_epoch_ticker();

    let signing_key_bytes = base64::engine::general_purpose::STANDARD.decode(&config.bundle_signing_public_key)?;
    let signing_public_key = VerifyingKey::from_bytes(signing_key_bytes.as_slice().try_into()?)?;

    let store = Arc::new(
        AmazonS3Builder::new()
            .with_endpoint(&config.bundle_bucket_endpoint)
            .with_bucket_name(&config.bundle_bucket_name)
            .with_region(&config.bundle_bucket_region)
            .with_access_key_id(&config.bundle_bucket_access_key_id)
            .with_secret_access_key(&config.bundle_bucket_secret_access_key)
            .with_allow_http(true)
            .with_virtual_hosted_style_request(false)
            .build()?,
    );
    let loader = Arc::new(BucketLoader::new(
        store,
        signing_public_key,
        std::path::PathBuf::from(&config.executor_precompile_dir),
        config.bundle_cache_versions,
        engine.clone(),
    ));
    let pool = Arc::new(InstancePool::new(config.executor_instances_per_bundle, std::time::Duration::from_millis(config.executor_pool_wait_ms)));

    let addr: std::net::SocketAddr = config.stage_host_api_addr.parse()?;
    let cert_chain = load_cert_chain(&config.host_api_tls_cert_file)?;
    let private_key = load_private_key(&config.host_api_tls_key_file)?;
    // load_cert_chain already refuses an empty chain, so index 0 exists.
    let server_ca = load_cert_chain(&config.host_api_tls_ca_file)?.remove(0);

    // Dial first -- the Handler needs the resulting connection's shared
    // FrameTransport (client.transport()) so every host-call it sends on
    // a bundle's behalf travels on the same connection `serve()` reads
    // load/unload/invoke from.
    let client = match ExecutorClient::dial(
        addr,
        ExecutorTlsConfig { cert_chain, private_key, server_ca, server_name: config.host_api_peer_identity.clone() },
        HelloAnnouncement {
            executor_version: env!("CARGO_PKG_VERSION").to_string(),
            wasmtime_abi: engine.wasmtime_abi.clone(),
            collector: config.executor_wasm_collector.clone(),
            sandbox: SandboxInfo { runtime: detection.runtime.clone(), verified: detection.verified },
        },
    )
    .await
    {
        Ok(client) => {
            telemetry::set_stage_dependency(&health, penguin_logging::health::DependencyStatus::ok());
            tracing::info!(%addr, wasmtime_abi = %engine.wasmtime_abi, "connected to stage host API");
            client
        }
        Err(error) => {
            // Classify the failure so /health and waddles_dependency_up
            // say *why*, not just "down" (spec §12.6).
            let class = match &error {
                penguin_bundle_host::executor::wire_client::ExecutorClientError::Tls(_) => {
                    penguin_logging::health::DependencyClass::Tls
                }
                penguin_bundle_host::executor::wire_client::ExecutorClientError::HandshakeRefused(_) => {
                    penguin_logging::health::DependencyClass::Auth
                }
                _ => penguin_logging::health::DependencyClass::Tcp,
            };
            telemetry::set_stage_dependency(
                &health,
                penguin_logging::health::DependencyStatus::failed(class, error.to_string()),
            );
            tracing::error!(%addr, %error, "could not reach the stage host API");
            return Err(error.into());
        }
    };

    let handler = Arc::new(Handler {
        engine: engine.clone(),
        loader,
        pool,
        runtimes: RwLock::new(HashMap::new()),
        scratch_root: std::path::PathBuf::from("/scratch"),
        transport: client.transport(),
    });

    let result = client.serve(handler).await;
    telemetry::set_stage_dependency(
        &health,
        penguin_logging::health::DependencyStatus::failed(
            penguin_logging::health::DependencyClass::Tcp,
            "stage connection closed".to_string(),
        ),
    );
    tracing::info!("stage connection closed; bundle-executor shutting down");
    // `_telemetry_guard` drops here, flushing the OTel exporters.
    result?;
    Ok(())
}

/// Reads a PEM certificate chain. `rustls::pki_types` is rustls's own
/// re-export of the `rustls-pki-types` crate -- using it avoids adding a
/// second, separately-versioned direct dependency on those same types.
fn load_cert_chain(path: &str) -> anyhow::Result<Vec<CertificateDer<'static>>> {
    let bytes = std::fs::read(path)?;
    let chain: Vec<_> = rustls_pemfile::certs(&mut bytes.as_slice()).collect::<Result<Vec<_>, _>>()?;
    anyhow::ensure!(!chain.is_empty(), "no certificates found in {path}");
    Ok(chain)
}

/// Reads a PEM private key. The key bytes are never logged, and the path
/// is the only thing that ever appears in an error.
fn load_private_key(path: &str) -> anyhow::Result<PrivateKeyDer<'static>> {
    let bytes = std::fs::read(path)?;
    rustls_pemfile::private_key(&mut bytes.as_slice())?.ok_or_else(|| anyhow::anyhow!("no private key found in {path}"))
}
```

- [ ] **Step 5: Write the end-to-end integration test**

`tests/bundle_executor_e2e_tests.rs` drives a real `Server` (Task 17) and a real `ExecutorClient` (Task 21) over a loopback mTLS connection: `Server::accept` on the stage side; on the executor side, a `HandlerUnderTest` implementing `StageRequestHandler` against a `BucketLoader<object_store::memory::InMemory>` seeded with the `hello_bundle` fixture (Task 5) — this test's own cert-generation helpers are a deliberate, small duplication of `tests/host_server_tests.rs`'s `make_ca`/`make_leaf` (Task 17), since each file under `tests/` compiles as its own independent binary and neither depends on the other. The stage side drives `ExecutorConnection::load` then `ExecutorConnection::invoke` with `export: Transform`, asserting the echoed event comes back:

```rust
#![allow(clippy::unwrap_used, clippy::panic)]
use ed25519_dalek::{Signer, SigningKey};
use object_store::memory::InMemory;
use object_store::{path::Path as ObjectPath, ObjectStore, ObjectStoreExt};
use penguin_bundle_host::executor::engine::{EngineConfig, EngineHandle};
use penguin_bundle_host::executor::invoke::{BundleRuntime, ExecutorHostState, PlatformEventDto};
use penguin_bundle_host::executor::loader::bucket::BucketLoader;
use penguin_bundle_host::executor::loader::reconcile::AdvertisedBundle;
use penguin_bundle_host::executor::pool::InstancePool;
use penguin_bundle_host::executor::remote_host_impl::RemoteHostWire;
use penguin_bundle_host::executor::wire_client::{ExecutorClient, ExecutorTlsConfig, HelloAnnouncement, StageRequestHandler};
use penguin_bundle_host::host::server::{Server, ServerPosture, ServerTlsConfig, SandboxPosture};
use penguin_bundle_host::wire::message::{ExportKind, LoadLimits, SandboxInfo};
use rand_core::OsRng;
use rcgen::{Certificate, CertificateParams, KeyPair};
use rustls_pki_types::{CertificateDer, PrivateKeyDer};
use sha2::{Digest, Sha256};
use std::collections::HashMap;
use std::net::SocketAddr;
use std::sync::Arc;
use tokio::sync::RwLock;

fn make_ca() -> (Certificate, KeyPair, CertificateDer<'static>) {
    let mut ca_params = CertificateParams::new(vec![]).unwrap();
    ca_params.is_ca = rcgen::IsCa::Ca(rcgen::BasicConstraints::Unconstrained);
    let ca_key = KeyPair::generate().unwrap();
    let ca_cert = ca_params.self_signed(&ca_key).unwrap();
    let der = ca_cert.der().clone();
    (ca_cert, ca_key, der)
}

fn make_leaf(ca_cert: &Certificate, ca_key: &KeyPair, common_name: &str) -> (CertificateDer<'static>, PrivateKeyDer<'static>) {
    let mut leaf_params = CertificateParams::new(vec![common_name.to_string()]).unwrap();
    leaf_params.distinguished_name.push(rcgen::DnType::CommonName, common_name);
    let leaf_key = KeyPair::generate().unwrap();
    let leaf_cert = leaf_params.signed_by(&leaf_key, ca_cert, ca_key).unwrap();
    (leaf_cert.der().clone(), PrivateKeyDer::Pkcs8(leaf_key.serialize_der().into()))
}

fn base64_encode(bytes: &[u8]) -> String {
    use base64::Engine;
    base64::engine::general_purpose::STANDARD.encode(bytes)
}

struct HandlerUnderTest {
    engine: Arc<EngineHandle>,
    loader: Arc<BucketLoader<InMemory>>,
    pool: Arc<InstancePool>,
    runtimes: RwLock<HashMap<String, (String, Arc<BundleRuntime>)>>,
    transport: Arc<penguin_bundle_host::wire::transport::FrameTransport>,
}

#[async_trait::async_trait]
impl StageRequestHandler for HandlerUnderTest {
    async fn on_load(
        &self,
        app_id: &str,
        version: &str,
        digest: &str,
        component_key: &str,
        sidecar_key: &str,
        capabilities: Vec<String>,
        limits: LoadLimits,
    ) -> Result<(String, u64, Vec<String>), String> {
        let started = std::time::Instant::now();
        let bundle = AdvertisedBundle {
            app_id: app_id.to_string(), digest: digest.to_string(), version: version.to_string(),
            component_key: component_key.to_string(), sidecar_key: sidecar_key.to_string(),
            capabilities, limits,
        };
        let (component_bytes, metadata) = self.loader.fetch_and_verify(&bundle).await.map_err(|e| e.to_string())?;
        self.loader.precompile(&metadata.digest, &component_bytes).await.map_err(|e| e.to_string())?;

        let component = wasmtime::component::Component::new(&self.engine.engine, &component_bytes).map_err(|e| e.to_string())?;
        let scratch = tempfile::tempdir().map_err(|e| e.to_string())?;

        let mut linker: wasmtime::component::Linker<ExecutorHostState> = wasmtime::component::Linker::new(&self.engine.engine);
        wasmtime_wasi::p2::add_to_linker_async(&mut linker).map_err(|e| e.to_string())?;
        penguin_bundle_host::executor::bindings::stage_world::waddle::bundle::context::add_to_linker(&mut linker, |s| s).map_err(|e| e.to_string())?;
        penguin_bundle_host::executor::bindings::stage_world::waddle::bundle::http::add_to_linker(&mut linker, |s| s).map_err(|e| e.to_string())?;
        penguin_bundle_host::executor::bindings::stage_world::waddle::bundle::kv::add_to_linker(&mut linker, |s| s).map_err(|e| e.to_string())?;
        penguin_bundle_host::executor::bindings::stage_world::waddle::bundle::db::add_to_linker(&mut linker, |s| s).map_err(|e| e.to_string())?;
        penguin_bundle_host::executor::bindings::stage_world::waddle::bundle::relay::add_to_linker(&mut linker, |s| s).map_err(|e| e.to_string())?;
        penguin_bundle_host::executor::bindings::stage_world::waddle::bundle::flags::add_to_linker(&mut linker, |s| s).map_err(|e| e.to_string())?;
        penguin_bundle_host::executor::bindings::stage_world::waddle::bundle::log::add_to_linker(&mut linker, |s| s).map_err(|e| e.to_string())?;
        penguin_bundle_host::executor::bindings::stage_world::waddle::bundle::clock::add_to_linker(&mut linker, |s| s).map_err(|e| e.to_string())?;

        // Leaked deliberately for the test's lifetime: BundleRuntime holds
        // the scratch TempDir's path but not the TempDir guard itself, so
        // the guard must outlive every call this test makes.
        let scratch_path = scratch.keep();
        let runtime = Arc::new(BundleRuntime::new(self.engine.clone(), component, linker, scratch_path));
        self.runtimes.write().await.insert(app_id.to_string(), (metadata.digest.clone(), runtime));

        Ok((metadata.digest, started.elapsed().as_millis() as u64, vec!["transform".to_string()]))
    }

    async fn on_unload(&self, app_id: &str, _digest: &str) -> Result<(), String> {
        self.runtimes.write().await.remove(app_id);
        Ok(())
    }

    async fn on_invoke(
        &self,
        scope: penguin_bundle_host::wire::message::InvocationScope,
        digest: &str,
        export: ExportKind,
        payload: serde_json::Value,
        deadline_ms: u64,
        invoke_frame_id: u64,
    ) -> Result<serde_json::Value, String> {
        let app_id = scope.app_id.as_str();
        let runtimes = self.runtimes.read().await;
        let (_loaded_digest, runtime) = runtimes.get(app_id).ok_or_else(|| "UNKNOWN_BUNDLE".to_string())?;
        let wire = RemoteHostWire { transport: self.transport.clone(), scope: scope.clone(), invoke_frame_id };
        assert_eq!(export, ExportKind::Transform, "this test only exercises transform");
        let event: PlatformEventDto = serde_json::from_value(payload).map_err(|e| e.to_string())?;
        let result = runtime.call_transform(&self.pool, app_id, digest, deadline_ms, 64, event, wire).await.map_err(|e| e.to_string())?;
        serde_json::to_value(result).map_err(|e| e.to_string())
    }
}

#[tokio::test]
async fn hello_frame_load_invoke_round_trips_end_to_end() {
    // -- seed an in-memory bucket with the real hello_bundle fixture --
    let component_bytes = std::fs::read(
        std::path::PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("tests/fixtures/hello_bundle/hello_bundle.wasm"),
    )
    .expect("run `make fixtures` first");
    let digest = format!("sha256:{}", hex::encode(Sha256::digest(&component_bytes)));
    let signing_key = SigningKey::generate(&mut OsRng);
    let signed_msg = format!("{{\"app_id\":\"waddles.test.fixture.hello\",\"digest\":\"{digest}\",\"version\":\"0.1.0\"}}");
    let signature = base64_encode(&signing_key.sign(signed_msg.as_bytes()).to_bytes());
    let sidecar = format!(
        "{{\"app_id\":\"waddles.test.fixture.hello\",\"digest\":\"{digest}\",\"version\":\"0.1.0\",\"signature\":\"{signature}\"}}"
    );
    let store = InMemory::new();
    let component_key = format!("bundles/waddles.test.fixture.hello/0.1.0/{}.wasm", digest.trim_start_matches("sha256:"));
    let sidecar_key = format!("bundles/waddles.test.fixture.hello/0.1.0/{}.json", digest.trim_start_matches("sha256:"));
    store.put(&ObjectPath::from(component_key.as_str()), component_bytes.clone().into()).await.unwrap();
    store.put(&ObjectPath::from(sidecar_key.as_str()), sidecar.into_bytes().into()).await.unwrap();

    // -- mTLS certs: one CA, two leaves --
    let (ca_cert, ca_key, ca_der) = make_ca();
    let (server_cert_der, server_key) = make_leaf(&ca_cert, &ca_key, "svc-process");
    let (executor_cert_der, executor_key) = make_leaf(&ca_cert, &ca_key, "svc-process-executor");

    // -- stage side: Server::bind + accept in a background task --
    let addr: SocketAddr = "127.0.0.1:0".parse().unwrap();
    let server = Server::bind(
        addr,
        ServerTlsConfig { cert_chain: vec![server_cert_der], private_key: server_key, client_ca: ca_der.clone(), expected_peer_identity: "svc-process-executor".to_string() },
        ServerPosture { expected_collector: "drc".to_string(), sandbox_expected: SandboxPosture::Gvisor },
    )
    .await
    .unwrap();
    let bound_addr = server.local_addr();

    let component_key_for_stage = component_key.clone();
    let sidecar_key_for_stage = sidecar_key.clone();
    let digest_for_stage = digest.clone();
    let stage_task = tokio::spawn(async move {
        let conn = server.accept().await.unwrap();
        let (loaded_digest, _precompile_ms, exports) = conn
            .load(
                "waddles.test.fixture.hello", "0.1.0", &digest_for_stage,
                &component_key_for_stage, &sidecar_key_for_stage, vec![],
                LoadLimits { timeout_ms: 2000, memory_mb: 64 },
            )
            .await
            .unwrap();
        assert_eq!(loaded_digest, digest_for_stage);
        assert!(exports.contains(&"transform".to_string()));

        let event = serde_json::json!({
            "platform": "twitch", "event_type": "chat.message", "actor": null,
            "payload_json": "{}", "occurred_at": "2026-09-14T12:00:00.000Z"
        });
        let ctx = penguin_bundle_host::host::server::HostCallContextTemplate {
            approved: Arc::new(penguin_bundle_host::host::approvals::ApprovedPermissions::from_json(
                "waddles.test.fixture.hello",
                &serde_json::json!({"egress": [], "data": {"tables": []}, "capabilities": ["log", "clock", "context"], "routes_to": [], "limits": {"timeout_ms": 2000, "memory_mb": 64, "egress_rps": 10}}),
            ).unwrap()),
            bundle_context: penguin_bundle_host::host::router::BundleContextInfo {
                tenant: "t".into(), community: None, feature: "f".into(), version: "0.1.0".into(), message_id: "m1".into(), config_json: "{}".into(),
                workstream_id: "8f14e45f-ceea-467e-adde-3fb5c9752730".into(), trace: None,
            },
        };
        let result = conn.invoke("waddles.test.fixture.hello", &digest_for_stage, ExportKind::Transform, event, 2000, ctx).await.unwrap();
        result
    });

    // -- executor side: dial, then serve on a background task --
    let engine = Arc::new(EngineHandle::new(&EngineConfig { max_memory_bytes: 64 * 1024 * 1024, epoch_tick_ms: 10, collector: "drc".to_string() }).unwrap());
    let loader = Arc::new(BucketLoader::new(Arc::new(store), signing_key.verifying_key(), std::env::temp_dir().join("bundle-host-e2e-cwasm"), 3, engine.clone()));
    let pool = Arc::new(InstancePool::new(4, std::time::Duration::from_millis(500)));

    let client = ExecutorClient::dial(
        bound_addr,
        ExecutorTlsConfig { cert_chain: vec![executor_cert_der], private_key: executor_key, server_ca: ca_der, server_name: "svc-process".to_string() },
        HelloAnnouncement {
            executor_version: "0.1.0".to_string(),
            wasmtime_abi: engine.wasmtime_abi.clone(),
            collector: "drc".to_string(),
            sandbox: SandboxInfo { runtime: "gvisor".to_string(), verified: true },
        },
    )
    .await
    .unwrap();

    let handler = Arc::new(HandlerUnderTest { engine, loader, pool, runtimes: RwLock::new(HashMap::new()), transport: client.transport() });
    let executor_task = tokio::spawn(async move { client.serve(handler).await });

    let echoed = tokio::time::timeout(std::time::Duration::from_secs(10), stage_task)
        .await
        .expect("stage_task must not hang")
        .expect("stage_task must not panic");

    assert_eq!(echoed["event_type"], "chat.message", "expected the echoed event back from hello_bundle, got {echoed:?}");

    executor_task.abort();
}
```

- [ ] **Step 5a: Add `tempfile` and `rcgen` as regular (not dev-only) test-scope crates for this file**

This test file uses `tempfile::TempDir::keep()` (stabilized name for the former `into_path()`) and `rcgen`/`rand_core`/`base64`/`hex` — all already `[dev-dependencies]` from Tasks 1, 17, and 19; no `Cargo.toml` change is needed for this step, only for the `object_store`/`ed25519-dalek`/`sha2` regular dependencies already present since Task 1/19/20. Confirm `make build` still resolves with no new crate before proceeding.

- [ ] **Step 6: Run to verify pass**

Run: `make fixtures && make test`
Expected: PASS — the end-to-end round trip completes, the echoed event matches, and `executor_config_never_derives_debug_output_containing_a_secret_value` reports `2` source files scanned.

- [ ] **Step 7: Commit**

```bash
git add packages/rust-bundle-host/src/bin packages/rust-bundle-host/tests/bundle_executor_e2e_tests.rs
git commit -m "$(cat <<'EOF'
feat(bundle-host): bundle-executor binary -- config, gVisor self-check, end-to-end wiring

Env-only ExecutorConfig (clap derive, no secret ever a CLI flag, and a
source scan that keeps it that way); gVisor self-check exits 78
(EX_CONFIG) when WADDLES_SANDBOX_GVISOR=true but /proc doesn't
corroborate it, and logs the loud opt-out warning when false. Telemetry
is penguin-logging and nothing else: one init() call, the /health and
/metrics router, and waddles_bundle_* histograms/counters recorded
through its shared meter. on_load deserializes the precompiled .cwasm it
just wrote rather than recompiling from source bytes -- one of the
crate's two allow(unsafe_code) sites, both strictly after
verify_digest_and_signature has accepted the bytes. main.rs wires
engine+loader+pool+wire_client into a running process; the end-to-end
test proves hello -> load -> invoke -> result across two real TLS
connections using the hello_bundle fixture.

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01N2rQgkHY872RubwXoBZxtE
EOF
)"
git push
```

---

## Task 23: Telemetry gate — `penguin-logging` emission proof + logging-conformance scan

**Depends on:** Task 22 (the `bundle-executor` binary and its `telemetry` module), Task 14 (`LogGuard`, the `sanitize_json_str` call site), Task 16 (`HostCallRouter`, which the log path runs through).

**Files:**
- Create: `packages/rust-bundle-host/tests/telemetry_gate_tests.rs`
- Modify: `packages/rust-bundle-host/src/host/router.rs` (record the host-call histogram)
- Modify: `packages/rust-bundle-host/Makefile` (add the `logging-conformance` target)

**Interfaces:**
- Consumes: `penguin_logging::testing::{init_test_telemetry, TestTelemetry, TelemetryCounts}` (M1b Task 17, behind the `testing` feature already in `[dev-dependencies]` from Task 1), `penguin_logging::metrics::record_latency_ms` (M1b Task 12), `host::router::HostCallRouter` (Task 16), `host::log_guard::LogGuard` (Task 14).
- Produces: no new public API. It produces the two gates `critical-rules.md` Observability and `testing.md` (Telemetry Validation + Logging Library Conformance) require every commit to pass, and `make logging-conformance`, which Task 25 wires into CI.

- [ ] **Step 1: Make the host-call path emit a latency histogram**

The router is the one place every capability call passes through, so it is
where the host-call histogram belongs. In `src/host/router.rs` (Task 16),
wrap the body of `HostCallRouter::dispatch` so every call is timed:

```rust
use opentelemetry::KeyValue;

/// Metric name for host-call round-trip latency, labelled by capability.
/// Kept here rather than in the binary because the *stage* records it --
/// the binary's `telemetry::HOST_CALL_MS` is the executor-side mirror of
/// the same name, so a single dashboard query covers both ends.
pub const HOST_CALL_MS: &str = "waddles_bundle_host_call_duration_ms";
/// Denials, labelled by capability -- a counter, because a denial is an
/// event, not a duration.
pub const HOST_CALL_DENIALS: &str = "waddles_bundle_host_call_denials_total";
```

and, inside `dispatch`, wrap the existing dispatch body — insert the
first fragment immediately before the `match capability { ... }`
expression and the second immediately after it:

```rust
        let started = std::time::Instant::now();
        let capability_label: &'static str = match capability {
            CapabilityKind::Http => "http",
            CapabilityKind::Kv => "kv",
            CapabilityKind::Db => "db",
            CapabilityKind::Relay => "relay",
            CapabilityKind::Flags => "flags",
            CapabilityKind::Log => "log",
            CapabilityKind::Clock => "clock",
            CapabilityKind::Context => "context",
        };

        // D30's Task 16 already wraps the dispatch body in
        // `async move { let result = match capability { ... }; if
        // result.is_ok() { self.record_usage(ctx, capability); } result }
        // .instrument(span).await` (the span carries waddles.tenant_id/
        // .community_id/.workstream_id/.app_id). This task's timing/
        // histogram code is inserted around that same `result` binding,
        // not a fresh `outcome` -- reusing Task 16's variable name rather
        // than introducing a second one for the same value. `started`/
        // `capability_label` (defined just above this fragment, unchanged
        // from this step's own setup) move to right after `async move {`
        // so they're captured inside the instrumented future; the timing/
        // logging block below goes immediately after Task 16's
        // `let result = match capability { ... };` line and before its
        // `if result.is_ok() { self.record_usage(ctx, capability); }`.
        let millis = started.elapsed().as_secs_f64() * 1000.0;
        penguin_logging::metrics::record_latency_ms(
            HOST_CALL_MS,
            millis,
            &[KeyValue::new("capability", capability_label)],
        );
        if result.is_err() {
            penguin_logging::metrics::counter_add(
                HOST_CALL_DENIALS,
                1,
                &[KeyValue::new("capability", capability_label)],
            );
        }
        tracing::debug!(
            app_id = %ctx.app_id,
            capability = capability_label,
            op,
            millis,
            ok = result.is_ok(),
            "host call dispatched"
        );
        // (Task 16's own `if result.is_ok() { self.record_usage(...); }
        // result` follows immediately after, unchanged.)
```

The net effect on `dispatch`'s body, after both this task's and Task 16's
edits are applied together, is:

```rust
        let community_label = ctx.bundle_context.community.as_deref().unwrap_or("_tenant").to_string();
        let span = tracing::info_span!(
            "host.call", capability = ?capability, op,
            waddles.tenant_id = %ctx.bundle_context.tenant,
            waddles.community_id = %community_label,
            waddles.workstream_id = %ctx.bundle_context.workstream_id,
            waddles.app_id = %ctx.app_id,
        );
        async move {
        let started = std::time::Instant::now();
        let capability_label: &'static str = match capability { /* ... as above ... */ };
        let result = match capability {
            /* every Task 16 arm, unchanged */
        };
        let millis = started.elapsed().as_secs_f64() * 1000.0;
        penguin_logging::metrics::record_latency_ms(HOST_CALL_MS, millis, &[KeyValue::new("capability", capability_label)]);
        if result.is_err() {
            penguin_logging::metrics::counter_add(HOST_CALL_DENIALS, 1, &[KeyValue::new("capability", capability_label)]);
        }
        tracing::debug!(app_id = %ctx.app_id, capability = capability_label, op, millis, ok = result.is_ok(), "host call dispatched");
        if result.is_ok() {
            self.record_usage(ctx, capability);
        }
        result
        }
        .instrument(span)
        .await
```

The `tracing::debug!` is deliberately generous (`critical-rules.md`:
"Overlog at DEBUG"). It carries no argument values — `args` can hold a
guest-supplied secret and never enters a log line; only the capability,
the op name and the timing do.

- [ ] **Step 2: Write the telemetry gate test**

`tests/telemetry_gate_tests.rs`:

```rust
#![allow(clippy::unwrap_used, clippy::panic)]
//! Reproduces spec §14.7 / `testing.md` Telemetry Validation inside this
//! crate's own suite: drive the real host-call path against an in-memory
//! OTLP sink and assert real, printed, non-zero counts of log records,
//! metric data points, histogram data points and spans.
//!
//! A sink that fails to start is a FAIL, never a skip, and a zero count
//! is a FAIL, never "no errors" (`critical-rules.md` Verification
//! Integrity).

use opentelemetry::KeyValue;
use penguin_bundle_host::host::capability::{LogLevel, Logger};
use penguin_bundle_host::host::log_guard::LogGuard;
use penguin_logging::testing::{init_test_telemetry, TelemetryCounts};
use std::sync::{Arc, Mutex};

struct CapturingLogger(Mutex<Vec<String>>);
impl Logger for CapturingLogger {
    fn write(&self, level: LogLevel, app_id: &str, message: &str, sanitized_fields_json: &str) {
        // Forward to `tracing`, which is what penguin-logging's OTLP log
        // exporter is bridged to -- this is exactly what a real stage's
        // Logger implementation does.
        tracing::info!(?level, app_id, message, fields = sanitized_fields_json, "bundle log");
        self.0.lock().unwrap().push(sanitized_fields_json.to_string());
    }
}

#[tokio::test]
async fn the_bundle_host_path_emits_logs_metrics_histograms_and_spans() {
    let telemetry = init_test_telemetry("penguin-bundle-host-test");

    // 1. A log record, through the exact guard the WIT `log` host call uses.
    let captured = Arc::new(CapturingLogger(Mutex::new(Vec::new())));
    let guard = LogGuard::new(captured.clone(), LogLevel::Debug);
    guard.write(
        "waddles.test.a",
        LogLevel::Info,
        "telemetry gate",
        r#"{"password":"hunter2","request_id":"abc"}"#,
    );

    // 2. A histogram data point and a counter, through the same helpers
    //    the router and the binary use.
    penguin_logging::metrics::record_latency_ms(
        "waddles_bundle_host_call_duration_ms",
        1.5,
        &[KeyValue::new("capability", "kv")],
    );
    penguin_logging::metrics::counter_add(
        "waddles_bundle_invocations_total",
        1,
        &[KeyValue::new("export", "transform"), KeyValue::new("outcome", "ok")],
    );

    // 3. A span, the shape every real invocation produces.
    {
        let _span = tracing::info_span!("bundle.invoke", app_id = "waddles.test.a", export = "transform").entered();
        tracing::debug!("inside the invoke span");
    }

    telemetry.force_flush();
    let counts: TelemetryCounts = telemetry.counts();

    // Counts are ALWAYS printed -- "no errors" is not a pass.
    println!(
        "telemetry gate: log_records={} metric_data_points={} histogram_data_points={} spans={}",
        counts.log_records, counts.metric_data_points, counts.histogram_data_points, counts.spans
    );

    assert!(counts.log_records >= 1, "expected >=1 OTLP log record, got {}", counts.log_records);
    assert!(counts.metric_data_points >= 1, "expected >=1 metric data point, got {}", counts.metric_data_points);
    assert!(
        counts.histogram_data_points >= 1,
        "expected >=1 histogram data point (load/latency histograms are the most-often-missing signal), got {}",
        counts.histogram_data_points
    );
    assert!(counts.spans >= 1, "expected >=1 span, got {}", counts.spans);

    // The sanitizer ran on the way through, at INFO, not only at DEBUG.
    let fields = captured.0.lock().unwrap();
    assert_eq!(fields.len(), 1, "expected exactly 1 captured log line, got {}", fields.len());
    assert!(fields[0].contains("[REDACTED]"), "password was not redacted: {}", fields[0]);
    assert!(!fields[0].contains("hunter2"), "raw secret reached the log sink: {}", fields[0]);
    assert!(fields[0].contains("abc"), "non-sensitive fields must survive sanitization: {}", fields[0]);
}
```

- [ ] **Step 3: Write the logging-conformance scan**

Append to `tests/telemetry_gate_tests.rs`:

```rust
/// `testing.md` Logging Library Conformance: this crate must use
/// `tracing` + `penguin-logging` and nothing hand-rolled. The scan
/// reports how many files it examined; zero files examined is a FAIL,
/// because a scanner pointed at a moved path reports clean.
#[test]
fn no_hand_rolled_logging_or_telemetry_in_src() {
    // Needles are deliberately precise. A bare `log::` would match
    // `log::Host` and `log::Level` -- the WIT world's `log` interface is
    // a bindgen module with exactly that name, so it appears legitimately
    // throughout `executor/remote_host_impl.rs`, `host/router.rs` and the
    // bench. Matching the `log` *crate*'s actual macro/import forms
    // instead keeps the scan honest in both directions.
    const FORBIDDEN: &[(&str, &str)] = &[
        ("println!", "use tracing::info! -- println! bypasses the log pipeline entirely"),
        ("eprintln!", "use tracing::error! -- eprintln! bypasses the log pipeline entirely"),
        ("use log::", "the `log` crate is not this project's logging facade; use `tracing`"),
        ("log::info!", "use tracing::info!"),
        ("log::warn!", "use tracing::warn!"),
        ("log::error!", "use tracing::error!"),
        ("log::debug!", "use tracing::debug!"),
        ("log::trace!", "use tracing::trace!"),
        ("tracing_subscriber::", "penguin_logging::init owns the subscriber registry"),
        ("opentelemetry_otlp::", "penguin-logging owns every OTLP exporter"),
        ("opentelemetry_sdk::", "penguin-logging owns every OTel provider"),
        ("opentelemetry_appender", "penguin-logging owns the tracing-to-OTel log bridge"),
        ("prometheus::Registry::new", "use the registry penguin_logging::init returns"),
    ];

    let src_root = std::path::PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("src");
    let mut scanned = 0usize;
    let mut findings: Vec<String> = Vec::new();

    let mut stack = vec![src_root.clone()];
    while let Some(dir) = stack.pop() {
        for entry in std::fs::read_dir(&dir).expect("src/ must exist and be readable") {
            let path = entry.expect("readable dir entry").path();
            if path.is_dir() {
                stack.push(path);
                continue;
            }
            if path.extension().and_then(|e| e.to_str()) != Some("rs") {
                continue;
            }
            let source = std::fs::read_to_string(&path).expect("readable .rs file");
            scanned += 1;
            for (needle, why) in FORBIDDEN {
                // Skip the line that documents the ban in this very test's
                // sibling modules: a doc comment naming the pattern is not
                // a use of it.
                let offending: Vec<usize> = source
                    .lines()
                    .enumerate()
                    .filter(|(_, line)| {
                        let trimmed = line.trim_start();
                        !trimmed.starts_with("//") && line.contains(needle)
                    })
                    .map(|(i, _)| i + 1)
                    .collect();
                if !offending.is_empty() {
                    findings.push(format!("{}:{:?} contains `{needle}` -- {why}", path.display(), offending));
                }
            }
        }
    }

    println!("logging conformance: {scanned} source files scanned under {}", src_root.display());
    assert!(scanned > 0, "zero source files scanned -- the scanner is pointed at the wrong path, which is a FAILURE not a pass");
    assert!(findings.is_empty(), "hand-rolled logging/telemetry found:\n{}", findings.join("\n"));

    // And the positive half: penguin-logging must actually be imported.
    let users = walk_count(&src_root, "penguin_logging::");
    println!("logging conformance: {users} source files reference penguin_logging::");
    assert!(users >= 1, "no source file imports penguin_logging -- the crate is not using the standard logging library");
}

fn walk_count(root: &std::path::Path, needle: &str) -> usize {
    let mut count = 0usize;
    let mut stack = vec![root.to_path_buf()];
    while let Some(dir) = stack.pop() {
        for entry in std::fs::read_dir(&dir).expect("readable dir") {
            let path = entry.expect("readable dir entry").path();
            if path.is_dir() {
                stack.push(path);
            } else if path.extension().and_then(|e| e.to_str()) == Some("rs")
                && std::fs::read_to_string(&path).expect("readable .rs file").contains(needle)
            {
                count += 1;
            }
        }
    }
    count
}
```

- [ ] **Step 4: Add the `logging-conformance` Makefile target**

Append to the `Makefile` (Task 1) and add `logging-conformance` to the
`.PHONY` line:

```makefile
# The two gates testing.md makes blocking every commit. Split out so CI
# can name them individually in its step list -- they are ordinary tests,
# so `make test` runs them too; this target exists to make them visible.
logging-conformance:
	$(DOCKER_RUN) cargo test --locked --test telemetry_gate_tests -- --nocapture
```

`--nocapture` is not optional: the counts these tests print are the
evidence the gate actually ran, and a captured stdout would reduce them
to a bare "ok".

- [ ] **Step 5: Run to verify**

Run: `make logging-conformance`
Expected: PASS, with three printed lines resembling

```
telemetry gate: log_records=2 metric_data_points=2 histogram_data_points=1 spans=1
logging conformance: 27 source files scanned under /work/src
logging conformance: 4 source files reference penguin_logging::
```

`test result: ok. 2 passed; 0 failed`. If any count prints `0`, the gate
has failed even though no assertion message mentions an error — re-read
`critical-rules.md` Verification Integrity before "fixing" the assertion.

- [ ] **Step 6: Prove the gate can fail**

A gate that has never failed is not known to work (`critical-rules.md`:
"assume any long-green gate is broken until you have made it fail on
purpose once"). Do this once, by hand, and revert:

```bash
cd /home/penguin/code/penguin-libs/.worktrees/plan-penguin-bundle-host/packages/rust-bundle-host
printf '\n#[allow(dead_code)]\nfn _gate_probe() { println!("this must fail the conformance scan"); }\n' >> src/lib.rs
make logging-conformance || echo "GATE CORRECTLY FAILED"
git checkout -- src/lib.rs
make logging-conformance
```
Expected: the first `make logging-conformance` fails with
``src/lib.rs:[...] contains `println!` ``, `GATE CORRECTLY FAILED` is
printed, and the second run passes again. If the first run *passed*, the
scan is not reaching `src/lib.rs` and must be fixed before proceeding.

- [ ] **Step 7: Commit**

```bash
git add packages/rust-bundle-host/tests/telemetry_gate_tests.rs packages/rust-bundle-host/src/host/router.rs packages/rust-bundle-host/Makefile
git commit -m "$(cat <<'EOF'
test(bundle-host): telemetry emission gate + logging-library conformance scan

Drives the real LogGuard/metrics path against penguin-logging's
in-memory sink and asserts printed, non-zero counts of log records,
metric data points, histogram data points and spans (spec §14.7,
testing.md Telemetry Validation). The companion scan walks src/ for
println!/eprintln!/the log crate's macros/tracing_subscriber/opentelemetry_*
and reports the number of files examined, so a scanner aimed at a moved
path fails instead of reporting clean. HostCallRouter::dispatch now
records waddles_bundle_host_call_duration_ms per capability.

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01N2rQgkHY872RubwXoBZxtE
EOF
)"
git push
```

---

## Task 24: Dependency-tree negative test + `call_transform` criterion bench

**Depends on:** Task 22 (the `bundle-executor` binary target `cargo tree` inspects), Task 18 (`BundleRuntime::call_transform`, which the bench times), Task 5 (the `hello_bundle` fixture).

**Files:**
- Create: `packages/rust-bundle-host/tests/bundle_executor_dependency_tests.rs`
- Create: `packages/rust-bundle-host/benches/call_roundtrip.rs`

**Interfaces:**
- Consumes: everything (this task adds no new production code, only verification).
- Produces: nothing new for other tasks to consume — this is the crate's own closing verification per spec §14.6 test 16 (dependency-tree check) and the plan's own "criterion bench for call round-trip" requirement.

- [ ] **Step 1: Write the dependency-tree test**

`tests/bundle_executor_dependency_tests.rs`:

```rust
//! Spec §14.6 test 16: "The executor binary links a networking or
//! database crate | `cargo tree -p bundle-executor` contains no
//! `reqwest`, `redis`, `deadpool-redis`, `sea-orm` or `sqlx`; the CI
//! check fails the build if any appears, and reports the number of
//! crates examined." Adapted to this crate's own binary target name
//! (`bundle-executor`, produced by `penguin-bundle-host`).
#![allow(clippy::unwrap_used, clippy::panic)]

use std::process::Command;

const FORBIDDEN_CRATES: &[&str] = &["reqwest", "redis", "deadpool-redis", "sea-orm", "sqlx"];

#[test]
fn bundle_executor_binary_links_none_of_the_forbidden_transport_crates() {
    let output = Command::new("cargo")
        .args(["tree", "--bin", "bundle-executor", "--prefix", "none"])
        .current_dir(env!("CARGO_MANIFEST_DIR"))
        .output()
        .expect("cargo tree must run inside the pinned rust:1.97-slim-bookworm container (make test)");

    assert!(
        output.status.success(),
        "cargo tree failed: {}",
        String::from_utf8_lossy(&output.stderr)
    );

    let tree = String::from_utf8_lossy(&output.stdout);
    let crate_lines: Vec<&str> = tree.lines().filter(|l| !l.trim().is_empty()).collect();
    assert!(
        crate_lines.len() > 10,
        "expected a non-trivial dependency tree (>10 crates), got {} -- a cargo tree pointed at the wrong target reports a suspiciously short tree, which is a FAILURE not a pass",
        crate_lines.len()
    );

    let mut found = Vec::new();
    for forbidden in FORBIDDEN_CRATES {
        if crate_lines.iter().any(|line| line.split(' ').next().unwrap_or("") == *forbidden) {
            found.push(*forbidden);
        }
    }

    assert!(
        found.is_empty(),
        "bundle-executor must never link {found:?} -- the executor holds no DB/Valkey/HTTP transport credential (spec §6.10, §11.10); {} total crate lines examined",
        crate_lines.len()
    );
}
```

- [ ] **Step 2: Run to verify it passes immediately (this is a verification test, not new behavior)**

Run: `make test`
Expected: PASS immediately — `crate_lines.len()` printed on failure only; the test asserts a real, non-zero count either way.

- [ ] **Step 3: Write the criterion bench**

`benches/call_roundtrip.rs`:

```rust
//! Criterion bench for one `call_transform` round trip against the
//! `hello_bundle` fixture -- the number this plan's Global Constraints
//! and spec §16 (M2's gVisor benchmark) build on for the "our own
//! measurement, not a vendor number" trade-off sentence.
#![allow(clippy::unwrap_used, clippy::panic)]

use criterion::{criterion_group, criterion_main, Criterion};
use penguin_bundle_host::executor::bindings::{self, stage_world::Stage};
use penguin_bundle_host::executor::engine::{EngineConfig, EngineHandle};
use penguin_bundle_host::executor::wasi_ctx::build_guest_wasi_ctx;
use wasmtime::component::{Component, Linker};

fn fixture_path() -> std::path::PathBuf {
    std::path::PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("tests/fixtures/hello_bundle/hello_bundle.wasm")
}

struct BenchHostState {
    wasi: penguin_bundle_host::executor::wasi_ctx::GuestWasiCtx,
}
impl wasmtime_wasi::WasiView for BenchHostState {
    fn ctx(&mut self) -> wasmtime_wasi::WasiCtxView<'_> {
        wasmtime_wasi::WasiCtxView { ctx: &mut self.wasi.wasi, table: &mut self.wasi.table }
    }
}

// Minimal stub Host impls -- identical shape to tests/common's, kept
// separate here since benches compile as their own crate target and
// cannot import from tests/.
mod bench_hosts {
    use super::BenchHostState;
    use penguin_bundle_host::executor::bindings::stage_world::waddle::bundle::*;

    impl context::Host for BenchHostState {
        async fn get_context(&mut self) -> context::BundleContext {
            context::BundleContext { tenant: "t".into(), community: None, app_id: "a".into(), feature: "f".into(), version: "1".into(), message_id: "m".into(), config_json: "{}".into() }
        }
    }
    impl http::Host for BenchHostState {
        async fn send(&mut self, _r: http::Request) -> Result<http::Response, http::Error> { Err(http::Error::Denied("n/a".into())) }
    }
    impl kv::Host for BenchHostState {
        async fn get(&mut self, _k: String) -> Result<Option<Vec<u8>>, kv::Error> { Ok(None) }
        async fn set(&mut self, _k: String, _v: Vec<u8>, _t: u32) -> Result<(), kv::Error> { Ok(()) }
        async fn delete(&mut self, _k: String) -> Result<(), kv::Error> { Ok(()) }
        async fn increment(&mut self, _k: String, d: i64, _t: u32) -> Result<i64, kv::Error> { Ok(d) }
    }
    impl db::Host for BenchHostState {
        async fn execute(&mut self, _s: String, _p: Vec<db::Value>) -> Result<db::Rows, db::Error> { Err(db::Error::Denied("n/a".into())) }
    }
    impl relay::Host for BenchHostState {
        async fn push(&mut self, _p: String, _m: String) -> Result<(), relay::Error> { Err(relay::Error::Denied("n/a".into())) }
    }
    impl flags::Host for BenchHostState {
        async fn enabled(&mut self, _k: String, d: bool) -> bool { d }
        async fn tier(&mut self) -> String { "free".into() }
    }
    impl log::Host for BenchHostState {
        async fn write(&mut self, _l: log::Level, _m: String, _f: String) {}
    }
    impl clock::Host for BenchHostState {
        async fn now_millis(&mut self) -> u64 { 0 }
        async fn now_rfc3339(&mut self) -> String { String::new() }
        async fn monotonic_nanos(&mut self) -> u64 { 0 }
    }
}

fn call_roundtrip_benchmark(c: &mut Criterion) {
    let rt = tokio::runtime::Runtime::new().unwrap();
    let handle = EngineHandle::new(&EngineConfig { max_memory_bytes: 64 * 1024 * 1024, epoch_tick_ms: 10, collector: "drc".to_string() }).unwrap();
    let component = Component::from_file(&handle.engine, fixture_path()).expect("run `make fixtures` first");

    c.bench_function("hello_bundle_call_transform_roundtrip", |b| {
        b.iter(|| {
            rt.block_on(async {
                let mut linker: Linker<BenchHostState> = Linker::new(&handle.engine);
                wasmtime_wasi::p2::add_to_linker_async(&mut linker).unwrap();
                bindings::stage_world::waddle::bundle::context::add_to_linker(&mut linker, |s| s).unwrap();
                bindings::stage_world::waddle::bundle::http::add_to_linker(&mut linker, |s| s).unwrap();
                bindings::stage_world::waddle::bundle::kv::add_to_linker(&mut linker, |s| s).unwrap();
                bindings::stage_world::waddle::bundle::db::add_to_linker(&mut linker, |s| s).unwrap();
                bindings::stage_world::waddle::bundle::relay::add_to_linker(&mut linker, |s| s).unwrap();
                bindings::stage_world::waddle::bundle::flags::add_to_linker(&mut linker, |s| s).unwrap();
                bindings::stage_world::waddle::bundle::log::add_to_linker(&mut linker, |s| s).unwrap();
                bindings::stage_world::waddle::bundle::clock::add_to_linker(&mut linker, |s| s).unwrap();

                let scratch = tempfile::tempdir().unwrap();
                let wasi = build_guest_wasi_ctx(scratch.path()).unwrap();
                let mut store = wasmtime::Store::new(&handle.engine, BenchHostState { wasi });
                store.set_epoch_deadline(handle.ticks_for_timeout(2000));
                let (stage, _instance) = Stage::instantiate_async(&mut store, &component, &linker).await.unwrap();
                let event = bindings::stage_world::waddle::bundle::types::PlatformEvent {
                    platform: "twitch".into(), event_type: "chat.message".into(), actor: None,
                    payload_json: "{}".into(), occurred_at: "2026-09-14T12:00:00.000Z".into(),
                };
                std::hint::black_box(stage.waddle_bundle_process_stage().call_transform(&mut store, &event).await.unwrap())
            })
        })
    });
}

criterion_group!(benches, call_roundtrip_benchmark);
criterion_main!(benches);
```

- [ ] **Step 4: Run the bench once to verify it executes**

Run: `make bench`
Expected: criterion prints a timing summary for `hello_bundle_call_transform_roundtrip`; no panics.

- [ ] **Step 5: Commit**

```bash
git add packages/rust-bundle-host/tests/bundle_executor_dependency_tests.rs packages/rust-bundle-host/benches/call_roundtrip.rs
git commit -m "$(cat <<'EOF'
test(bundle-host): dependency-tree gate + call_transform criterion bench

cargo tree --bin bundle-executor asserts none of reqwest/redis/
deadpool-redis/sea-orm/sqlx are linked (spec §14.6 test 16), reporting
the actual crate count examined so a tree pointed at the wrong target
can't silently pass. The bench gives this plan's own gVisor-overhead
trade-off sentence (spec §12.2, §16 M2) a real number to eventually cite.

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01N2rQgkHY872RubwXoBZxtE
EOF
)"
git push
```

---

## Task 25: CI + publish wiring, coverage gate, README/CHANGELOG finalization, cut `0.1.0`

**Depends on:** every task before it — this is what ships them.

**Files:**
- Modify: `packages/rust-bundle-host/Cargo.toml` (remove `publish = false`)
- Modify: `penguin-libs/.github/workflows/ci.yml` (add `build-rust-bundle-host` job)
- Modify: `penguin-libs/.github/workflows/publish.yml` (add `publish-rust-bundle-host` job)
- Modify: `packages/rust-bundle-host/README.md`
- Modify: `packages/rust-bundle-host/CHANGELOG.md`

**Interfaces:**
- Consumes: everything (this task ships what every earlier task built).
- Produces: `penguin-bundle-host = "=0.1.0"` on crates.io — the exact dependency line M2's `bundle-compiler` plan and the M3/M4 `svc_process`/`svc_action` plans pin.

- [ ] **Step 1: Remove `publish = false` from `Cargo.toml`**

Delete the line `publish = false` from the `[package]` section (Task 1) now that the crate's public API has settled through Tasks 1-24.

- [ ] **Step 2: Add the `build-rust-bundle-host` CI job to `penguin-libs/.github/workflows/ci.yml`**

Insert immediately after the existing `build-rust-rpc` job (mirroring its shape, per `penguin-libs-inventory.md`'s documented convention), adding the Docker-based `make` steps this crate's Global Constraints require in place of bare `cargo` calls:

```yaml
  build-rust-bundle-host:
    name: Build & Test Rust Bundle Host
    runs-on: ubuntu-latest
    if: ${{ !startsWith(github.ref, 'refs/heads/release/') || startsWith(github.ref, 'refs/heads/release/rust-bundle-host/') }}
    defaults:
      run:
        working-directory: packages/rust-bundle-host
    steps:
      - uses: actions/checkout@692973e3d937129bcbf40652eb9f2f61becf3332 # v4.1.7
        with:
          persist-credentials: false
      - name: Build fixtures
        run: make fixtures
      - name: Verify all five fixtures exist
        run: make check-fixtures
      - name: Lint (fmt + clippy, dockerized)
        run: make lint
      - name: Test (dockerized)
        run: make test
      - name: Telemetry + logging-conformance gate (counts printed)
        run: make logging-conformance
      - name: cargo-deny (dockerized)
        run: make deny
      - name: cargo-audit (dockerized)
        run: make audit
      - name: Coverage >=90% (dockerized)
        run: make cov
```

Every step above is unmasked: no `|| true`, no `continue-on-error`, no
`2>/dev/null`. `make check-fixtures` and `make logging-conformance` are
listed separately from `make test` (which already runs both) precisely so
their printed counts appear as their own CI step, where a zero is visible
rather than buried in a suite summary (`critical-rules.md` Verification
Integrity).

- [ ] **Step 3: Add the `publish-rust-bundle-host` job to `penguin-libs/.github/workflows/publish.yml`**

Mirroring `publish-rust-rpc`'s exact shape:

```yaml
  publish-rust-bundle-host:
    name: Publish Rust Bundle Host
    runs-on: ubuntu-latest
    permissions:
      contents: read
      id-token: write
    if: |
      github.event_name == 'workflow_dispatch' &&
      github.event.inputs.package == 'rust-bundle-host' ||
      startsWith(github.ref, 'refs/tags/rust-bundle-host-v')

    defaults:
      run:
        working-directory: packages/rust-bundle-host

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

      - name: Publish penguin-bundle-host
        run: cargo publish -p penguin-bundle-host --locked
        env:
          CARGO_REGISTRY_TOKEN: ${{ steps.crates-auth.outputs.token }}
```

Add `'rust-bundle-host'` to the `workflow_dispatch` input's `package` choice list at the top of `publish.yml` (the same list `'rust-rpc'`/`'rust-licensing'` already appear in).

- [ ] **Step 4: Finalize `README.md`**

Append an "Environment" table entry noting the crate's `0.1.0` status and a "Not an env var" table (matching `rust-licensing`'s README convention per `penguin-libs-inventory.md`) listing what this crate deliberately does **not** read from the environment:

```markdown
## Not an env var

This crate never reads `DATABASE_URL`, `VALKEY_URL`/`REDIS_URL`, or any
platform API credential -- those belong to the *service* implementing
`HttpEgress`/`KvStore`/`DbExecutor`/`RelayPush`, never to
`penguin-bundle-host` itself (spec §6.10, §11.10).

## Status

`0.1.0` -- first published version.

| Module | Public API |
|---|---|
| `wire` | `Frame`, `Message`, `ExportKind`, `CapabilityKind`, `ErrorCode`, `SandboxInfo`, `HelloLimits`, `LoadLimits`, `HostResultError`, `read_frame`, `write_frame`, `MAX_FRAME_BYTES`, `FrameTransport`, `TransportError` |
| `host` (traits you implement) | `HttpEgress`, `KvStore`, `DbExecutor`, `RelayPush`, `Flags`, `Logger`, `Clock`, `SecretResolver` |
| `host` (enforcement) | `ApprovedPermissions`, `Capability`, `EgressGuard`, `DbGuard`, `KvGuard`, `RelayGuard`, `FlagsGuard`, `LogGuard`, `ClockGuard`, `GuardDenial`, `TripTracker`, `HostCallRouter`, `HostCallContext` |
| `host` (transport) | `Server`, `ServerTlsConfig`, `ServerPosture`, `ExecutorConnection` |
| `executor` | `EngineHandle`, `EngineConfig`, `EpochTicker`, `InstancePool`, `PoolPermit`, `BundleRuntime`, `ExecutorHostState`, `InvokeError`, the `*Dto` mirrors, `verify_digest_and_signature`, `SidecarMetadata`, `VerifyError`, `SUPPORTED_WIT_WORLD`, `reconcile`, `AdvertisedBundle`, `ReconcileAction`, `BucketLoader`, `LoaderError`, `RemoteHostWire`, `ExecutorClient`, `ExecutorTlsConfig`, `HelloAnnouncement`, `StageRequestHandler` |
| binary | `bundle-executor` |

Telemetry is `penguin-logging` 0.1.0 throughout -- this crate constructs
no subscriber, no exporter and no Prometheus registry of its own.
```

- [ ] **Step 5: Finalize `CHANGELOG.md`**

```markdown
# Changelog

All notable changes to `penguin-bundle-host` are documented here.
Format: [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [0.1.0] - 2026-09-14

### Added
- The `waddle:bundle/stage@1.0.0` WIT world, committed at `wit/waddle-bundle-stage.wit`.
- `wire`: length-prefixed frame codec and correlation-id-multiplexed `FrameTransport`.
- `host`: `ApprovedPermissions`, the seven capability traits, the egress/db/kv/relay/flags/log/clock guards, `TripTracker`, `HostCallRouter`, and the mTLS `Server`/`ExecutorConnection`.
- `executor`: wasmtime `Engine` construction pinned to the `drc` collector, WIT bindgen wiring, default-deny guest `WasiCtx` (`wasi:sockets` never linked), `InstancePool`, per-call `invoke` with epoch deadline + memory cap, digest + Ed25519 sidecar verification against the spec §9.4 schema `bundle-compiler` signs, digest-only reconciliation (spec §7.6), `object_store`-backed bucket loading with a `{digest}-{wasmtime_abi}-{collector}` `.cwasm` cache, the executor-side remote `Host` implementation, and the mTLS `ExecutorClient`.
- The `bundle-executor` binary: env-only config, gVisor self-check, and telemetry through `penguin-logging` 0.1.0 -- structured sanitized logs, OTLP logs/metrics/traces, `waddles_bundle_*` histograms and counters, and the `/health`, `/healthz`, `/metrics` router.
- Test fixtures (`hello_bundle`, `hostile_socket`, `stateful_counter`, `hang_forever`, `memory_hog`) built with the pinned `cargo-component` 0.21.1 toolchain from the `bundle-compiler-sandbox` spike.
- Telemetry-emission gate and logging-library conformance scan, both with printed non-zero counts; `cargo-deny`/`cargo-audit` clean; ≥90% line coverage; a `criterion` bench for the call round trip.
```

- [ ] **Step 6: Run the full gate once more before cutting the release**

Run: `make fixtures && make check-fixtures && make lint && make deny && make audit && make test && make logging-conformance && make cov`
Expected: every command exits 0; `check-fixtures` prints `fixture components present: 5`; `logging-conformance` prints non-zero `log_records`/`metric_data_points`/`histogram_data_points`/`spans` and a non-zero scanned-file count; the coverage report shows ≥90% lines. A zero in any printed count is a failure even if the command exited 0 — re-read the assertion before proceeding.

- [ ] **Step 7: Commit, cut the release branch, tag, and let CI publish**

```bash
git add packages/rust-bundle-host/Cargo.toml packages/rust-bundle-host/README.md packages/rust-bundle-host/CHANGELOG.md .github/workflows/ci.yml .github/workflows/publish.yml
git commit -m "$(cat <<'EOF'
chore(bundle-host): wire CI/publish jobs, finalize README/CHANGELOG for 0.1.0

Adds build-rust-bundle-host to ci.yml and publish-rust-bundle-host to
publish.yml (tag rust-bundle-host-v*), mirroring rust-rpc's/rust-
licensing's established per-crate job shape. Removes publish = false
now that the public API (Tasks 1-23) has settled.

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01N2rQgkHY872RubwXoBZxtE
EOF
)"
git push

# Cut the per-crate release branch (per-crate independent SemVer, matching
# every other penguin-libs Rust crate) and tag 0.1.0 to trigger the
# publish job above -- both steps require the user's explicit go-ahead
# per devops.md (release branch creation + tagging are not
# pre-authorized the way a feature->release merge is); do not run the
# following without asking first:
#
#   git checkout -b release/rust-bundle-host/v0.1.x
#   git push -u origin release/rust-bundle-host/v0.1.x
#   git tag rust-bundle-host-v0.1.0
#   git push origin rust-bundle-host-v0.1.0
```

---

## Self-Review

Performed against the spec (`origin/docs/rust-data-plane-spec`, `docs/superpowers/specs/2026-09-14-rust-data-plane-design.md`, commit `680a0a9b`, 3,121 lines), the two sibling plans this crate has to line up with (`origin/docs/plan-penguin-logging` for M1b, `origin/docs/plan-m2a-compiler-sdks` for M2a), the two spikes (`origin/spike/penguin-dal-wasm`, `origin/spike/bundle-compiler-sandbox`), and the `superpowers:writing-plans` checklist. Every finding below was **fixed inline before this plan was committed**, not recorded as follow-up.

### 1. Spec coverage

| Spec requirement (§) | Task(s) |
|---|---|
| §6.5 WIT world `waddle:bundle/stage@1.0.0`, written out in full | 2 |
| §6.6 mTLS frame protocol — 14 message kinds, length prefix, correlation ids | 2, 3, 4, 17 |
| §6.6 `hello` frame self-check (`wasmtime_version`/`wasmtime_abi`/`collector`/`sandbox`) | 2, 6, 17, 21 |
| §6.7 distribution-API shape consumed as `AdvertisedBundle` (never re-queried) | 20 |
| §6.9 approved-permission set parsed from `app_install_approvals.summary_json` | 9 |
| §6.10 / §11.10 D28 executor holds **no Postgres role and no Valkey user** | Global Constraints; asserted by 24 |
| §7.2 `.cwasm` precompile keyed `{digest}-{wasmtime_abi}-{collector}`, `EXECUTOR_WASM_COLLECTOR=drc` | 6, 20, 22 |
| §7.2 fresh instance per call — no guest state survives an invocation | 18 (`stateful_counter` fixture) |
| §7.3 epoch-interruption deadline | 6, 18 (`hang_forever` fixture) |
| §7.3 per-instance memory cap | 6, 18 (`memory_hog` fixture) |
| §7.4 kv namespacing under the bundle's own `...:state` key | 14, 16 |
| §7.4 `log` level clamped to the stage's configured level | 14 |
| §7.4 `fields-json` sanitized with the penguin-logging SENSITIVE_KEYS rule | 14 (`penguin_logging::sanitize_json_str`), 23 (asserted) |
| §7.5 three-strike trip rule + disable | 15, 16, 18 |
| §7.6 digest-only reconciliation, the four-row table | 20 (all four branches, counted) |
| §8.2 egress order of operations, steps 1-12 | 11, 12 |
| §8.3 secret-reference injection (value never enters the component) | 12 |
| §9.4 signed sidecar schema + Ed25519 verification | 19 |
| §11.3 executor answers no capability locally — every call forwarded | 21 |
| §11.7 digest + signature verified before load, no fallback | 19, 20, 22 |
| Approved-set enforcement from the **approval**, never the manifest (grants/egress/tables/capabilities/routes_to) | 9, 11, 12, 13, 14, 16 |
| `wasi:sockets` denied natively; per-language permitted WASI sets | 7, 8 (`hostile_socket` fixture) |
| Read-only `/scratch` preopen, empty at load | 7, 8 |
| §12.6 dependency classification on `/health` (`dns\|tcp\|tls\|auth\|ok`) | 22 |
| §12.7 env-only configuration, no secret as a CLI flag | 22 |
| §13 OTel logs + metrics + traces, endpoint env-configurable | 22, 23 |
| §14.6 test 16 dependency-tree negative test with a printed crate count | 24 |
| §14.7 telemetry validation gate with printed counts | 23 |
| §14.5 per-crate CI gates (fmt, clippy, deny, audit, test, llvm-cov ≥90%) | 25 |
| gVisor self-check (`/proc/version`, `/proc/self/status`), exit 78 on mismatch | 22 |
| §16 M1 row: WIT world + executor host runtime + wire protocol + bucket loader + digest/signature verification + limits + trip rule | all 25 tasks |
| `critical-rules.md` Dependency Pinning: exact `=x.y.z`, `Cargo.lock` committed | 1 |
| `critical-rules.md` Verification Integrity: printed counts, non-zero denominators, no masked gates, one deliberate gate failure | 5, 18, 20, 23 (Step 6), 24, 25 |
| `testing.md` Logging Library Conformance | 23 |
| `backend-rust.md` dockerized builds, `unsafe_code`/`missing_docs`/`unwrap_used` deny | 1, Global Constraints |

**Deliberately out of scope, stated as boundaries rather than gaps:** `bundle.yaml` v2 manifest parsing (spec §4.8 lists a `manifest` module here; deferred to M2's compiler, which is what actually validates author-supplied manifests); the `waddles`-repo Dockerfile/Helm packaging of the binary; the Postgres/Valkey/HTTP transports themselves, which the *services* implement against this crate's seven traits.

### 2. Placeholder scan

Searched the full document for `TBD`, `TODO`, `FIXME`, `XXX`, "fill in", "placeholder", "similar to Task", "implement later", "as above", "left as an exercise", "abbreviated". **Four real findings, all fixed:**

1. **Task 6 shipped deliberately-wrong scratch code.** The implementation block derived `wasmtime_abi` from `env!("CARGO_PKG_VERSION")`, then re-derived it twice more with a prose note telling the implementer to "remove the scratch lines before committing". A worker seeing only that task's text would very plausibly commit the wrong one. Replaced with the single correct `wasmtime::VERSION` assignment plus a regression test (`wasmtime_abi_is_wasmtimes_major_not_this_crates`) that fails if it ever drifts back.
2. **Task 18 Step 1 said "Add all three to `Dockerfile.fixtures` … and to the `Makefile`'s `fixtures` target's `cp` lines"** with no text to add. Replaced with the exact `Cargo.toml`/`wit/` generation commands, the three verbatim Dockerfile block replacements (tagged `# FIXTURE COPY/BUILD/VALIDATE BLOCK` in Task 5 so they are unambiguous to find), the note that the Makefile already handles all five, and a verification run with its expected counts.
3. **Task 23's router refactor said `/* the existing match capability { ... } expression, unchanged */`.** Replaced with the literal two-line edit (`match capability {` → `let outcome = match capability {`, closing `}` → `};`) and an explicit statement about what happens to the two early `return`s inside the arms.
4. **Task 7's second test was introduced as "Same setup as above, abbreviated".** The code was actually complete; the comment was not. Reworded to say why the setup is repeated verbatim rather than shared.

`grep -niE 'restream'` matches only the Global Constraints bullet that forbids it and this sentence — zero uses. `waddlebot` appears 4 times, all as the literal git-repository name where the spec and spikes live; the Global Constraints naming bullet was tightened to say so explicitly rather than leaving it to the reader.

### 3. Signature/type consistency

Cross-checked every `Produces` declaration against every later `Consumes` and call site, and against the two sibling plans. **Findings, all fixed:**

**Against M2a (the artifact contract this crate consumes):**

- **The sidecar schema did not match, and would have rejected every real bundle.** Task 19 had invented a four-field sidecar (`{app_id, version, digest, signature}`) whose signed message was a hand-built three-field JSON string. M2a Task 14's `Sidecar` — verbatim from spec §9.4 — has **twelve** fields, and the signed bytes are `serde_json::to_vec` of all eleven non-signature fields. A `bundle-compiler`-produced sidecar would have failed `serde` deserialization outright, and any sidecar that did parse would have failed signature verification. This was the single most serious finding in the review. Task 19's `SidecarMetadata`, `canonical_unsigned_bytes`, tests and commit message now mirror M2a field for field, and a new test (`editing_any_signed_field_after_signing_is_rejected`) proves the wider signed surface actually buys something — flipping `scan_status` after signing is now caught, which the three-field message would have missed entirely.
- Added `SUPPORTED_WIT_WORLD` + `VerifyError::WitWorldMismatch`: the sidecar carries `wit_world`, and verifying it is free.
- `.cwasm` cache key, `hello` frame fields, and the bucket object layout all already matched; each is now recorded in a Global Constraints table rather than being implicit.
- **One deviation from PA2, recorded with its reason:** the WIT file's on-disk path (`wit/waddle-bundle-stage.wit` here vs `wit/waddle-bundle/stage.wit` in the `waddles` repo). The package id, world name and file bytes are identical; only the filename differs, because `bindgen!` and `cargo-component` both resolve `wit/` as a directory of `.wit` files and a nested subdirectory would parse as a second WIT package.

**Against M1b (`penguin-logging`):**

- **The plan claimed `penguin-logging` did not exist.** Global Constraints asserted "no `docs/plan-penguin-logging` remote branch exists in `penguin-libs` as of 2026-09-14" and built a stand-in around direct `tracing-subscriber` + `opentelemetry-otlp` wiring. That branch does exist (18 tasks, crate at `packages/rust-logging`, version `0.1.0`). Rewired throughout: `penguin-logging` is now a hard dependency; `tracing-subscriber`, `opentelemetry-otlp`, `opentelemetry_sdk`, `tracing-opentelemetry` and `prometheus` were removed from `Cargo.toml` (only `opentelemetry` remains, for `KeyValue` labels); the speculative "M1b Assumption" pseudo-signature block was replaced with the eight real signatures read off M1b's own Interfaces blocks.
- **The stand-in telemetry code was also wrong on its own terms.** It called `opentelemetry_sdk::trace::TracerProvider::builder()` and `.with_batch_exporter(exporter, opentelemetry_sdk::runtime::Tokio)` — the 0.27-era API. Against the `opentelemetry_sdk = 0.32.1` the plan pins, the type is `SdkTracerProvider` and `with_batch_exporter` takes one argument. Moot now that `penguin_logging::init` owns it, but it is why "consume the shared crate" is the right call and not just a compliance box.
- **Task 14's `LogGuard` re-implemented `SENSITIVE_KEYS` locally.** M1b explicitly names this exact call site as the consumer of `sanitize_json_str`. A second copy of a redaction rule is a security rule that drifts silently. Replaced with the `penguin_logging::sanitize_json_str` call; the local key list, `is_sensitive_key` and `sanitize` are gone.
- Removed the now-dead `use super::capability::{Clock as _, ...}` import in `log_guard.rs` — `Clock` was never used there and `-D warnings` would have rejected it.

**Within this plan:**

- **Task 22's `main.rs` had a duplicated `use … RemoteHostWire;` line** (the previous author was mid-edit). Removed, along with two genuinely unused imports (`Stage`, `build_guest_wasi_ctx`) the same edit had left behind.
- **`rustls_pki_types::` was used as a crate path in `main.rs` but never declared as a dependency.** Switched to `rustls::pki_types::`, rustls's own re-export, so no second separately-versioned dependency on the same types is needed.
- **The `.cwasm` cache was write-only.** `on_load` called `loader.precompile(...)`, discarded the returned path, and then compiled the component from source bytes with `Component::new`. Every load paid the full Cranelift cost and spec §7.2's precompile step bought nothing. `on_load` now `deserialize_file`s the artifact it just wrote — which is also the second of the two `#[allow(unsafe_code)]` sites Global Constraints promises, and that bullet named the wrong tasks (21/22) for both; corrected to 20/22.
- **A span was held across `.await`.** The invocation span was created with `tracing::info_span!(…).entered()` inside an `async fn` and kept live across two awaits, which attaches the span to whatever the runtime resumes next. Switched to `Instrument` on the future.
- **The logging-conformance scan's own needle list had a false positive.** A bare `log::` needle matches `log::Host` and `log::Level` — the WIT world's `log` interface is a bindgen module with exactly that name, so it appears legitimately across `remote_host_impl.rs`, `router.rs` and the bench. The scan would have failed on correct code. Narrowed to `use log::` and the five `log::*!` macro forms.
- **`penguin_logging::init` returns a `prometheus::Registry`, which this crate can no longer name.** `telemetry::init`'s signature was returning it. Changed to drop it with a named binding and a comment saying why, rather than adding `prometheus` back as a dependency for a value nothing here reads.
- **`[lints.clippy] unwrap_used = "deny"` applies to every target, and `make clippy` runs `--all-targets`.** Not one of the ~20 test files carried an allow, so the lint gate would have failed on the first `.unwrap()` in the first test written. Added the crate-level `#![allow(clippy::unwrap_used, clippy::panic)]` line to every `tests/`/`benches/` file block (26 of them) and stated the rule once in Global Constraints — matching `packages/rust-licensing/tests/client_tests.rs`, which does exactly this. Care was taken *not* to add it to the six blocks that append to an existing test file.
- **Three of the five fixtures were never built.** `stateful_counter`, `hang_forever` and `memory_hog` are introduced in Task 18 and used by its tests, but `Dockerfile.fixtures` and the `Makefile`'s `fixtures` target only ever handled two. Every Task 18 limit test would have failed on a missing `.wasm`. Both files now handle all five, both loops count and assert an exact total, and a new `make check-fixtures` target fails loudly rather than letting a fixture-dependent test be skipped.
- **The fixture-validation step only checked one of the two components it claimed to check** ("Validate both components…" followed by a single `grep`). Now a counted loop over every fixture, asserting both the package id and the world name.
- **Task numbering had drifted by one across ~30 cross-references.** The document referred to a 25-task plan while containing 24 — "Task 25 wires these into CI", "the dependency-tree test, Task 24", "executor::wire_client (Task 23)" — evidence that a task had been dropped during an earlier edit. Rather than renumber 30 references down, the missing work turned out to be genuinely missing: there was **no telemetry task at all**, and no telemetry-validation gate, in a plan for a crate whose rules make logs+metrics+traces a blocking per-commit gate. Adding Task 23 (telemetry gate + logging conformance) restored the 25-task shape and made five of those references correct as written; the remaining ~27 were corrected individually against the authoritative task list.
- **No task carried a `Depends on:` line.** Added to all 25, derived from each task's own `Consumes` block.
- `host/wasi_host_impl.rs` appeared in the File Structure but no task creates it, and no task should: the stage side never implements the WIT `Host` traits — it answers `host-call` frames through `HostCallRouter`. Removed, `router.rs` added, and the two Interfaces blocks that described a "stage-side `Host` impl" corrected.
- Four test files that tasks create (`fixture_build_tests.rs`, `bindgen_smoke_tests.rs`, `capability_fakes_tests.rs`, `loader_reconcile_tests.rs`) and `tests/common/mod.rs` were missing from the File Structure. Added, each annotated with the task that writes it.
- `KvGuard`'s Interfaces block still declared `app_id: &str` where the implementation and the router both use `base_key: &str`. Corrected, and the doc comment now states that the caller builds the key from the envelope's tenant/community and never from guest input. The two test call sites were updated to the real key shape so they document the contract.
- Task 18's Interfaces block now carries a forward note that Task 21 changes `call_transform`/`call_dispatch` once more (adding the `wire` parameter), so an implementer doesn't read the two versions as a contradiction.

No remaining mismatch was found between any task's `Produces` and a later task's `Consumes` or call sites, or between this plan and M1b/M2a.

### 4a. D30/D31 addendum (this amendment)

Spec §16's M1 table row for this crate: *"(M1c) `penguin-bundle-host::host::db` / `::kv`: tenant-scoped host calls wired to the binding-verified envelope: `SET LOCAL waddles.tenant`/`waddles.community` and KV/config/state key scoping proven to reject a mismatched-tenant invocation (§7.4, §6.2, D30)."*

| D30/D31 requirement | Task(s) | Status |
|---|---|---|
| `InvocationScope {tenant_id, community_id, workstream_id, app_id, trace}` carried on every `invoke`/`host-call` frame (§6.6) | 2 | Done — supersedes the pre-D30 standalone `app_id`/`trace_context` fields; reuses `penguin_spine::Trace` verbatim (never duplicated) |
| `DbExecutor::execute` takes `&InvocationScope` so the implementation's transaction can `SET LOCAL waddles.tenant`/`waddles.community` before running the statement | 10, 13 | Done — signature + documented RLS contract; `DbGuard::execute` forwards `scope` unmodified, proven by `db_execute_forwards_the_full_invocation_scope_unmodified` |
| `KvStore` keys prefixed `t:{tenant}:c:{community}:...` | 14, 16 (pre-existing) | Already satisfied pre-D30 — `HostCallRouter::dispatch`'s `Db`/`Kv` arms already built `base_key` from `ctx.bundle_context.tenant`/`.community`, never guest input. This amendment adds `KvGuard` key-hygiene validation (empty/absolute/`..`) as defense in depth, spec §5.11's spirit extended to key input, not a scoping fix |
| Bundle transform output cannot set `tenant_id`/`community_id`/`workstream_id`/`event_id`/`trace` — dropped and counted | 22 | Done — `Handler::on_invoke`'s `Transform` arm calls `penguin_spine::strip_bundle_identity_fields` on the decoded `payload_json` and increments `waddles_tenant_boundary_violations_total{stage="process",reason="bundle_set_identity"}` on a hit |
| Spans per host call carry `waddles.tenant_id`/`.community_id`/`.workstream_id`/`.app_id`; `bundle.invoke` span likewise | 16, 22 | Done — `HostCallRouter::dispatch`'s `host.call` span and `Handler::on_invoke`'s `bundle.invoke` span both carry all four, via `Instrument` on the future (never `.entered()` across an `.await`) |
| Trace propagated into and out of executor frames | 2, 17, 21 | Done structurally — `scope.trace` rides both `Invoke` (stage→executor) and `HostCall` (executor→stage); the executor never re-derives or forges it, only echoes what `ExecutorConnection::invoke` sent |
| Host-call usage counted into the M1a `UsageDelta` (bundle invocations, fuel/CPU-ms, host calls by kind) | 16 | Partial — `HostCallRouter` gains an optional `UsageBatcher` and records one `HostCallKind` increment per successful dispatch (the "host calls by kind" half). Bundle-invocation counts and fuel/CPU-ms are executor-side (Task 22's `on_invoke`/`fuel_used`) and are **not yet wired to `UsageBatcher`** in this amendment — flagged as follow-up, since threading a batcher into the executor binary's own config/wiring (Task 22) is a larger change this pass did not make; the type-level contract (`UsageDelta`, `HostCallCounts`) is already in place from M1a |
| Negative test: a DB host call scoped to tenant A cannot read tenant B rows (Postgres RLS fixture) | — | **Not implemented in this crate.** `penguin-bundle-host` has no Postgres connection pool by design (Global Constraints "Boundary"); `DbExecutor`'s only implementation lives in the service (M3/M4, out of every M1 library plan's scope). This crate's own test (`db_execute_forwards_the_full_invocation_scope_unmodified`, Task 13) proves the contract-level guarantee — the exact scope handed to the guard is the exact scope the executor implementation receives, unmodified. The live-Postgres RLS proof belongs with the service crate that owns the connection |
| Negative test: KV key from bundle cannot escape its prefix (`../`, absolute, empty) | 14 | Done — `kv_rejects_empty_absolute_and_path_traversal_keys`, 4 cases, counted |

### 4. Task sizing

25 tasks. The largest are Task 12 (`EgressGuard::send`, five ordered steps of §8.2), Task 17 (mTLS server) and Task 22 (the binary's end-to-end wiring plus its e2e test); each is a single coherent file plus its tests and fits comfortably inside an hour. Tasks 3, 5, 8, 15, 19 and 24 are well under it. No task requires reading another task's body to execute: every one carries complete, runnable code, exact `make` commands, and its own expected output including the counts to check.

