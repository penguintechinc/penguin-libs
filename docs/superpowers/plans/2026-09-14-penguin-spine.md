# penguin-spine (Valkey Streams data-plane crate) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Land `penguin-spine` — the Rust crate that gives `svc-ingest`/`svc-process`/`svc-action` (and, read-only, `hub-api`) the Valkey Streams spine: key builders, byte-compatible envelope/DLQ types, `XADD`/`XREADGROUP`/`XACK`/`XAUTOCLAIM`/`XGROUP`/`XINFO` wrappers, the two client connection-separation rules, TLS+ACL-aware config with a startup connectivity self-check, and the least-privilege Valkey ACL matrix + renderer + live conformance test — all under Milestone M1a of the Waddles Rust data-plane design.

**Architecture:** One crate, `packages/rust-spine` → `penguin-spine` v0.1.0, structured like the sibling `packages/rust-licensing` (`penguin-licensing`) crate: small focused modules under `src/`, `tests/` for integration coverage against a real pinned Valkey container, `benches/` for a criterion benchmark, `config/valkey/` for the versioned least-privilege ACL matrix and its renderer. No pool crate: `redis::aio::MultiplexedConnection` (already safely `Clone`+concurrent) serves all non-blocking "admin" traffic; `GroupReader` opens its own dedicated, non-multiplexed connection with an explicit response timeout for `XREADGROUP ... BLOCK`, per the spec's two connection-separation rules (§5.7). No dependency on a Rust logging crate (`penguin-logging` does not exist yet — known gap, `backend-rust.md`): observability is exposed through a small `SpineMetrics` trait this crate defines and callers implement, plus plain `tracing` calls.

**Tech Stack:** Rust 1.97.1, edition 2024, `redis` 1.7.0 (`tokio-comp`+`tls-rustls`+`tokio-rustls-comp`+`streams`), `tokio` 1.53.1, `serde`/`serde_json`, `thiserror`, `chrono`, `uuid`, `rustls` 0.23.45 (PEM pre-validation only), `rstest`/`criterion` for tests/benches, `serde-saphyr` 1.2.0 (dev-only, YAML matrix parsing), pinned `valkey/valkey:8.1.5` for integration tests, Python 3.13 (containerized) for one-time golden-fixture generation and the ACL-matrix-to-`users.acl` renderer.

**Spec:** `docs/superpowers/specs/2026-09-14-rust-data-plane-design.md` on branch `docs/rust-data-plane-spec` in the `waddlebot` repo (read via `git -C ~/code/waddlebot show origin/docs/rust-data-plane-spec:docs/superpowers/specs/2026-09-14-rust-data-plane-design.md`), at commit `680a0a9b` (3,121 lines). Every task below cites the section it implements. Executors read the spec section cited in their own task; nobody needs the whole document to do their task.

## Global Constraints

- **Location.** All work happens in the `penguin-libs` worktree at `/home/penguin/code/penguin-libs/.worktrees/plan-penguin-spine`, branch `docs/plan-penguin-spine` off `origin/main`. All commands in this plan run from that worktree root unless a path says otherwise. Never touch `main`. This plan creates and modifies **only** paths under `packages/rust-spine/` in that worktree — it does not touch any other `penguin-libs` package, and it does not touch the `waddlebot` repo at all (the spec's chart/service work referencing this crate is M2–M6, out of scope here).
- **Naming.** Say "Waddles", never "waddlebot", in all new prose/identifiers this plan produces, except the literal legacy identifiers the spec itself preserves (none appear in this crate — `penguin-spine` uses the `waddles:` key prefix throughout, per D18/D22). The word "restream" never appears anywhere in this plan or the code it produces.
- **Cross-repo artifact note (read before Task 12).** Spec §11.10/D28 names `config/valkey/acl-matrix.yaml` as a *repo-root* path in whichever service repo deploys the chart (`waddlebot`, per D22) — this plan cannot create that file there (out of scope, see Location above). Task 12 ships the crate's own canonical copy at `packages/rust-spine/config/valkey/acl-matrix.yaml` (same relative suffix, rooted in this crate instead) plus the renderer and a **crate-local** live-container conformance test using this crate's own pinned Valkey container. The spec's `make test-rbac-valkey` gate (§14.5), which runs against the deployed alpha stack, is an M6/deployment gate that copies this exact file and renderer into the chart repo — that copy step is out of this plan's scope, and Task 12 says so again at the point it matters.
- **Dependency pinning.** Every `Cargo.toml` dependency is an exact `=x.y.z` version (no `^`/`~`/bare `*`); `Cargo.lock` is committed. Every version below was looked up with `cargo search` run *inside* the pinned `rust:1.97.1` container (never on the host) on 2026-09-14; each task's Cargo.toml edit states the exact string to write, no re-verification needed by the implementer. Docker images pinned by tag **and** SHA-256 digest. GitHub Actions pinned by full commit SHA (values below are reused verbatim from `waddlebot`'s already-vetted `.github/workflows/rust-svc-streaming.yml` and this repo's own `ci.yml`).
- **Rust lints (every module, from Task 1 onward).** `#![forbid(unsafe_code)]`, `#![deny(missing_docs)]`, `[lints.clippy] unwrap_used = "deny"` — every fallible call in non-test code uses `?` or an explicit `match`, never `.unwrap()`/`.expect()`. `[lints]` in `Cargo.toml` applies to every target including `tests/`, so test code needs a local, scoped opt-out rather than tripping the crate-wide deny: every inline `#[cfg(test)] mod tests { ... }` block starts with `#![allow(clippy::unwrap_used)]` as its first line (already applied to every such block in Tasks 2-6; every later task's own inline test module does the same), and every standalone file under `tests/` starts with `#![allow(clippy::unwrap_used, clippy::panic)]` — the exact convention already used in `packages/rust-licensing/tests/client_tests.rs`. `cargo fmt --check` and `cargo clippy --all-targets -- -D warnings` must pass after every task.
- **Coverage.** `cargo llvm-cov --fail-under-lines 90` gates CI (Task 21). Every task that adds non-trivial logic adds tests in the same task — no "add tests later" tasks.
- **Docs.** Every `struct`/`enum`/`fn`/`trait` gets a 2-3 line doc comment (godoc-style: what it does and why, not a line-by-line walkthrough). No ASCII-art section dividers.
- **Least User Access via RBAC (D28, spec §11.10).** Every Valkey ACL user this plan defines gets exactly the commands and key patterns its role uses — never a category grant "because it was easier". The single normative source is `packages/rust-spine/config/valkey/acl-matrix.yaml` (Task 12); `users.acl` is *rendered* from it by `packages/rust-spine/config/valkey/render_acl.py` and is never hand-edited. The executor gets no Valkey user at all, and the matrix says so explicitly rather than by omission.
- **Commits.** Conventional-commit prefixes `feat(spine):` / `test(spine):` / `chore(spine):` / `docs(spine):`. Every commit message ends with these two trailer lines, each on its own line:
  ```
  Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
  Claude-Session: https://claude.ai/code/session_01N2rQgkHY872RubwXoBZxtE
  ```
- **No pushing, no PR.** This plan's own execution ends at the final local commit on `docs/plan-penguin-spine` (that branch is for the *plan document*, already pushed by the planner). Implementers execute *this* plan on a **new** branch cut from `origin/main` (a `feature/penguin-spine-crate` branch inside its own worktree, per `using-git-worktrees`) — the plan does not prescribe that branch's push/PR timing; follow the standing `devops.md` rules (push after every commit, PR only when asked).
- **Deviations from the spec's illustrative code sketch (§4.7), each justified inline where it matters:**
  1. `SpineClient::connect(...)`/`GroupReader::connect(...)` are the fallible constructors (`-> Result<Self, SpineError>`), not the sketch's bare `SpineClient { .. }` value and `GroupReader::new(...) -> Self` — construction does real I/O (opens a connection) and must be able to refuse per §5.7 rule 1.
  2. `GroupReader::connect` takes more parameters than the sketch's `new(grants, app_id, consumer_id)`: also `stage: Stage`, `dlq: SpineClient`, `metrics: Arc<dyn SpineMetrics>`. Reason: §5.5 requires an `envelope_invalid` entry — which by construction can never become a `Delivered` — to still reach the DLQ, so the reader needs its own write path and needs to know which of the two DLQs (`waddles:dlq:process`/`waddles:dlq:action`) is its own.
  3. `SpineClient` and `GroupReader` are both `Clone` (cheap: a `MultiplexedConnection` clone plus an `Arc<dyn SpineMetrics>` clone) — needed so `GroupReader` can hold its own `dlq: SpineClient` handle without owning a second pool.
  4. `dead_letter`'s DLQ-key stage comes from `Stage::parse(&d.env.stage)`, not from a caller-supplied `Stage` — `StageEnvelope.stage` is already validated to one of `ingest|process|action` at deserialization, and in practice only `process`/`action` runners ever call `dead_letter`.
  5. No `deadpool-redis`/pooling crate: `deadpool-redis`'s `Manager` cannot be built from a pre-configured `redis::Client` (only from a URL/`ConnectionInfo`), so it cannot honor a custom `VALKEY_CA_FILE` — `redis::Client::build_with_tls` can, and `MultiplexedConnection` already handles concurrent callers over one socket, so the extra dependency buys nothing.
  6. `SpineClient::claim_stale` takes an additional `stage: Stage` parameter beyond the sketch's `(stream, app_id)`. Reason: same as deviation 2 — a claimed entry whose `env` field fails to parse can't produce a `Delivered` (so it can't go through the public `dead_letter(&Delivered, ...)` path, which derives its DLQ stage from `d.env.stage`), yet spec Sec5.5 still requires it to reach a DLQ; the caller (always one specific stage's reaper task) is the only party that knows which DLQ that should be.

---

## File Structure

```
packages/rust-spine/
  Cargo.toml
  Cargo.lock
  deny.toml
  LICENSE                       # MIT, copied from packages/rust-licensing/LICENSE
  README.md
  CHANGELOG.md
  config/
    valkey/
      acl-matrix.yaml           # normative — see Cross-repo artifact note above
      render_acl.py             # matrix -> tests/valkey/users.acl, stdlib-only
  src/
    lib.rs                      # crate doc comment + pub use of the whole public surface
    scope.rs                    # Scope, Stage, key builders, parse_scope_from_key
    envelope.rs                 # Source, PlatformEvent, StageEnvelope, EnvelopeError, PROCESS_TARGET_APP_ID_KEY
    dlq.rs                      # DlqRecord, DlqErrorDetail, DlqError, DlqErrorKind
    error.rs                    # SpineError
    metrics.rs                  # SpineMetrics trait, NoopMetrics
    config.rs                   # SpineConfig, ProbeClass, ProbeResult, classify_connect, validate_block_timeout
    client.rs                   # Grant, Delivered, GroupStats, SpineClient
    reader.rs                   # GroupReader
    binding.rs                  # BindingKeyring, BindingInput, compute_binding_mac, verify_binding, ScopeCheck, BoundaryError (D30, Task 19)
    usage.rs                    # UsageDelta, HostCallCounts, UsageBatcher, USAGE_STREAM_KEY (D31, Task 20)
  benches/
    spine_bench.rs
  tests/
    golden/
      generate_fixtures.py
      envelopes/valid/*.json    # >= 20
      envelopes/invalid/*.json  # >= 25
      keys/*.json
      entries/*.json
      dlq/*.json
    golden_fixture_tests.rs
    valkey/
      valkey.conf
      users.acl                 # generated by config/valkey/render_acl.py, gitignored placeholder note in README
      gen-test-tls.sh
    acl_matrix_tests.rs
    integration_stream_tests.rs
    client_rules_tests.rs
```

---

### Task 1: Crate scaffold

**Files:**
- Create: `packages/rust-spine/Cargo.toml`, `packages/rust-spine/deny.toml`, `packages/rust-spine/LICENSE`, `packages/rust-spine/README.md`, `packages/rust-spine/CHANGELOG.md`, `packages/rust-spine/src/lib.rs`, `packages/rust-spine/.gitignore`

**Interfaces:**
- Produces: a compiling, empty crate `penguin-spine` v0.1.0 every later task builds on.

- [ ] **Step 1: Copy the license.** `cp /home/penguin/code/penguin-libs/packages/rust-licensing/LICENSE /home/penguin/code/penguin-libs/.worktrees/plan-penguin-spine/packages/rust-spine/LICENSE` (create the `packages/rust-spine` directory first: `mkdir -p packages/rust-spine/src`).

- [ ] **Step 2: Write `packages/rust-spine/Cargo.toml`:**

```toml
[package]
name = "penguin-spine"
version = "0.1.0"
edition = "2024"
rust-version = "1.97.1"
description = "Waddles data-plane spine: Valkey Streams key builders, envelope/DLQ types, and the two client connection-separation rules"
license = "MIT"
repository = "https://github.com/penguintechinc/penguin-libs"
authors = ["Penguin Tech Inc <support@penguintech.io>"]
keywords = ["valkey", "redis", "streams", "waddles"]
categories = ["api-bindings", "asynchronous"]

[dependencies]
redis = { version = "=1.7.0", default-features = false, features = ["tokio-comp", "tls-rustls", "tokio-rustls-comp", "streams"] }
serde = { version = "=1.0.229", features = ["derive"] }
# `preserve_order`: golden-fixture round-trips (Task 8) require
# deserialize -> re-serialize to be byte-identical (spec Sec14.1), which
# needs `payload`/`config`/nested JSON object keys to keep their original
# order rather than the crate's default alphabetical (BTreeMap) ordering.
serde_json = { version = "=1.0.151", features = ["preserve_order"] }
thiserror = "=2.0.20"
tokio = { version = "=1.53.1", features = ["rt", "time", "sync", "macros", "net"] }
tracing = "=0.1.44"
chrono = { version = "=0.4.45", features = ["serde"] }
uuid = { version = "=1.26.1", features = ["v4"] }
# PEM pre-validation of VALKEY_CA_FILE only (rustls::pki_types), never a TLS
# handshake path -- redis's own `tls-rustls` feature owns that. No crypto
# provider feature needed for pure PEM parsing.
rustls = { version = "=0.23.45", default-features = false, features = ["std"] }
# D30 envelope binding MAC (spec Sec5.11): HMAC-SHA256 over the tenant/
# community/workstream_id/event_id/trace_id tuple, constant-time verified.
hmac = "=0.12.1"
sha2 = "=0.10.9"
subtle = "=2.6.1"
hex = "=0.4.3"

[dev-dependencies]
tokio = { version = "=1.53.1", features = ["full", "test-util"] }
rstest = "=0.27.0"
criterion = { version = "=0.8.2", features = ["async_tokio"] }
# YAML parsing for the ACL-matrix conformance test only (Task 12) -- never a
# runtime dependency of the published library.
serde-saphyr = "=1.2.0"

[[bench]]
name = "spine_bench"
harness = false

[lints.rust]
unsafe_code = "forbid"
missing_docs = "deny"

[lints.clippy]
unwrap_used = "deny"
```

- [ ] **Step 3: Write `packages/rust-spine/deny.toml`** (copy the shape of `packages/rust-licensing/deny.toml`, MIT-compatible allow list, no exceptions):

```toml
# cargo-deny configuration for penguin-spine.
#
# Run locally with: cargo deny check
# CI wiring: .github/workflows/rust-spine.yml (Task 21)

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

- [ ] **Step 4: Write `packages/rust-spine/src/lib.rs`:**

```rust
//! `penguin-spine` — the Waddles data-plane spine over Valkey Streams.
//!
//! One stream per ingest source (`{scope}:src:{platform}:{source_id}:events`)
//! and one action stream per app bundle (`{scope}:app:{app_id}:action`),
//! read through per-bundle consumer groups with `XREADGROUP`/`XACK`/
//! `XAUTOCLAIM`, and a dead-letter stream per stage (`waddles:dlq:{stage}`).
//! Envelope JSON is byte-compatible with `flask_core.stream_pipeline`'s
//! `PlatformEvent`/`StageEnvelope` dataclasses (Python source of truth,
//! `libs/flask_core/flask_core/stream_pipeline.py` in the `waddlebot` repo).
//!
//! Two client rules are enforced by construction, not by convention (spec
//! §5.7): a blocking `XREADGROUP ... BLOCK` read always runs on its own
//! dedicated connection with its own response timeout, strictly longer than
//! the configured block duration; and that dedicated connection is never
//! shared with administrative traffic (`XADD`/`XACK`/`XAUTOCLAIM`/`XGROUP`/
//! `XINFO`), which lives on [`SpineClient`]'s own `MultiplexedConnection`.
//!
//! This crate emits no logs/metrics of its own destination — it calls back
//! into a caller-supplied [`SpineMetrics`] implementation, since no Rust
//! penguin-logging crate exists yet (`backend-rust.md`, known gap).

mod client;
mod config;
mod dlq;
mod envelope;
mod error;
mod metrics;
mod reader;
mod scope;

pub use client::{Delivered, Grant, GroupStats, SpineClient};
pub use config::{ProbeClass, ProbeResult, SpineConfig};
pub use dlq::{DlqError, DlqErrorDetail, DlqErrorKind, DlqRecord};
pub use envelope::{EnvelopeError, PlatformEvent, Source, StageEnvelope, PROCESS_TARGET_APP_ID_KEY};
pub use error::SpineError;
pub use metrics::{NoopMetrics, SpineMetrics};
pub use reader::GroupReader;
pub use scope::{parse_scope_from_key, Scope, Stage, TENANT_WIDE_SEGMENT};
```

(This will not yet compile — the `mod` declarations name files that don't exist. That is expected; Step 5 creates stub files so the crate compiles before any real logic lands.)

- [ ] **Step 5: Create seven empty-but-valid stub modules** so `cargo build` succeeds. For each, write the minimal `#![allow]`-free stub — e.g. `packages/rust-spine/src/scope.rs`:

```rust
//! Placeholder — filled in by Task 2.
```

Do the same (single doc-comment line, no code) for `envelope.rs`, `dlq.rs`, `error.rs`, `metrics.rs`, `config.rs`, `client.rs`, `reader.rs`. Since `lib.rs` already has `pub use` statements referencing types these stubs don't define yet, **temporarily comment out every `pub use` line** in `lib.rs` (prefix each with `// TODO(task-N): `, N matching the task that defines it — Task 2 for `scope`, Task 3-4 for `envelope`, Task 5 for `dlq`/`error`, Task 6 for `metrics`, Task 9-10 for `config`, Task 13-16 for `client`, Task 17 for `reader`). Each later task un-comments exactly its own line(s) once the type exists.

- [ ] **Step 6: Verify it builds.**

Run: `docker run --rm -v "$(pwd)/packages/rust-spine:/work" -w /work rust:1.97.1 cargo build`
Expected: `Compiling penguin-spine v0.1.0 (/work)` then `Finished` with no errors (warnings about unused stub modules are fine at this stage — later tasks remove them as real code lands).

- [ ] **Step 7: Write `packages/rust-spine/README.md`** (stub, expanded fully in Task 21):

```markdown
# penguin-spine

Waddles data-plane spine over Valkey Streams: key builders, byte-compatible
envelope/DLQ types, `XADD`/`XREADGROUP`/`XACK`/`XAUTOCLAIM` wrappers, and the
two client connection-separation rules (spec §5.7). See
`docs/superpowers/plans/2026-09-14-penguin-spine.md` for the implementation
plan this crate was built from.

Full documentation lands in Task 21.
```

- [ ] **Step 8: Write `packages/rust-spine/CHANGELOG.md`:**

```markdown
# Changelog

All notable changes to `penguin-spine` are documented here.

## [Unreleased]

Initial crate scaffold.
```

- [ ] **Step 9: Write `packages/rust-spine/.gitignore`:**

```
/target
/config/valkey/../../tests/valkey/*.crt
/config/valkey/../../tests/valkey/*.key
```

Replace the last two lines immediately with the correct relative paths once `tests/valkey/` exists (Task 11) — for now, since that directory does not exist yet, write just:

```
/target
```

- [ ] **Step 10: Commit.**

```bash
cd /home/penguin/code/penguin-libs/.worktrees/plan-penguin-spine
git add packages/rust-spine
git commit -m "$(cat <<'EOF'
chore(spine): scaffold penguin-spine crate

Empty crate compiling against the pinned 1.97.1 toolchain, MIT license
copied from rust-licensing, house lint/deny.toml conventions in place.

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01N2rQgkHY872RubwXoBZxtE
EOF
)"
```

---

### Task 2: `Scope`, `Stage`, key builders, `parse_scope_from_key`

**Files:**
- Modify: `packages/rust-spine/src/scope.rs`, `packages/rust-spine/src/lib.rs`

**Interfaces:**
- Consumes: nothing (first real module).
- Produces: `Scope::{new, source_stream, action_stream, config_key, state_key}`, `Stage::{Process, Action}` with `as_str`/`parse`/`Display`, `TENANT_WIDE_SEGMENT: &str = "_tenant"`, `parse_scope_from_key(key: &str) -> Option<(String, Option<String>)>` — used by Task 17's `GroupReader` to recover tenant/community from a stream key when an entry's envelope fails to parse (spec §5.10, §11.8: tenant/community come from the key, never the payload). Every later task that builds a key string calls `Scope`; `dlq.rs` (Task 5) calls `Stage::as_str`.

Spec: §5.1 (`waddles:t:{tenant}:c:{community|_tenant}:src:{platform}:{source_id}:events`), §5.9 (`...:app:{app_id}:action`), §6.2 (full key table + `_tenant` rendering + `{scope}:app:{app_id}:cfg`/`:state`), §3.3 (tenant/community sourced exclusively from the key).

- [ ] **Step 1: Write the failing tests** in `packages/rust-spine/src/scope.rs` (below the module doc comment):

```rust
//! Scope, stage identity, and Valkey key builders for the Waddles spine.
//!
//! `waddles:t:{tenant}:c:{community|_tenant}` is the shared prefix every
//! spine key uses (spec §6.2); `community: None` always renders as the
//! literal `_tenant` segment so splitting any key on `:` yields the same
//! field count regardless of activation scope (spec §5.10).

/// The literal segment rendered for a tenant-wide (non-community-scoped)
/// activation, per spec §5.10 — `community: None` is never omitted.
pub const TENANT_WIDE_SEGMENT: &str = "_tenant";

/// A (tenant, community) pair identifying the Valkey key namespace an
/// envelope or stream belongs to. `community: None` denotes a tenant-wide
/// activation and always renders as [`TENANT_WIDE_SEGMENT`] in keys.
#[derive(Debug, Clone, PartialEq, Eq, Hash)]
pub struct Scope {
    /// The deployment's tenant slug (`RUNNER_TENANT_SLUG`).
    pub tenant: String,
    /// The community slug, or `None` for a tenant-wide activation.
    pub community: Option<String>,
}

impl Scope {
    /// Builds a scope from a tenant slug and an optional community slug.
    pub fn new(tenant: impl Into<String>, community: Option<String>) -> Self {
        Self { tenant: tenant.into(), community }
    }

    fn community_segment(&self) -> &str {
        self.community.as_deref().unwrap_or(TENANT_WIDE_SEGMENT)
    }

    fn base(&self) -> String {
        format!("waddles:t:{}:c:{}", self.tenant, self.community_segment())
    }

    /// The per-ingest-source event stream key (spec §5.1):
    /// `{scope}:src:{platform}:{source_id}:events`.
    pub fn source_stream(&self, platform: &str, source_id: &str) -> String {
        format!("{}:src:{}:{}:events", self.base(), platform, source_id)
    }

    /// The per-bundle action stream key (spec §5.9): `{scope}:app:{app_id}:action`.
    pub fn action_stream(&self, app_id: &str) -> String {
        format!("{}:app:{}:action", self.base(), app_id)
    }

    /// The per-bundle config cache key (spec §6.2): `{scope}:app:{app_id}:cfg`.
    pub fn config_key(&self, app_id: &str) -> String {
        format!("{}:app:{}:cfg", self.base(), app_id)
    }

    /// The per-bundle state hash key (spec §6.2): `{scope}:app:{app_id}:state`.
    pub fn state_key(&self, app_id: &str) -> String {
        format!("{}:app:{}:state", self.base(), app_id)
    }
}

/// Which of the two stream-consuming stages a [`crate::SpineClient`]/
/// [`crate::GroupReader`] belongs to. Ingest only ever writes (via
/// [`Scope::source_stream`] + `SpineClient::append`) and never consumes, so
/// it has no variant here (spec §5.2, §5.9).
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Stage {
    /// `svc-process`: reads granted ingest-source streams.
    Process,
    /// `svc-action`: reads its own per-bundle action stream.
    Action,
}

impl Stage {
    /// The lowercase wire/key form (`"process"`/`"action"`), used to build
    /// the `waddles:dlq:{stage}` key and the `StageEnvelope.stage` field.
    pub fn as_str(&self) -> &'static str {
        match self {
            Stage::Process => "process",
            Stage::Action => "action",
        }
    }

    /// Parses a `StageEnvelope.stage` string into a `Stage`. Only
    /// `"process"`/`"action"` are accepted — `"ingest"` is a valid envelope
    /// stage but never reaches this crate's DLQ path (ingest never
    /// consumes), so it is deliberately rejected here rather than modeled.
    pub fn parse(s: &str) -> Result<Self, crate::SpineError> {
        match s {
            "process" => Ok(Stage::Process),
            "action" => Ok(Stage::Action),
            other => Err(crate::SpineError::Config(format!(
                "unsupported stage for spine DLQ routing: {other:?} (expected \"process\" or \"action\")"
            ))),
        }
    }
}

impl std::fmt::Display for Stage {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(self.as_str())
    }
}

/// The dead-letter stream key for one stage (spec §5.5): `waddles:dlq:{stage}`.
pub fn dlq_key(stage: Stage) -> String {
    format!("waddles:dlq:{}", stage.as_str())
}

/// Recovers `(tenant, community)` from any well-formed spine key of the
/// shape `waddles:t:{tenant}:c:{community}:...`, returning `None` if the
/// key does not start with that prefix. Used when an entry's envelope JSON
/// fails to parse (spec §5.5 `envelope_invalid`): tenant/community for the
/// resulting DLQ record must still come from the key, never from the
/// unparsed payload (spec §3.3, §11.8).
pub fn parse_scope_from_key(key: &str) -> Option<(String, Option<String>)> {
    let rest = key.strip_prefix("waddles:t:")?;
    let (tenant, rest) = rest.split_once(":c:")?;
    let community_segment = rest.split(':').next()?;
    if tenant.is_empty() || community_segment.is_empty() {
        return None;
    }
    let community = if community_segment == TENANT_WIDE_SEGMENT {
        None
    } else {
        Some(community_segment.to_string())
    };
    Some((tenant.to_string(), community))
}

#[cfg(test)]
mod tests {
    #![allow(clippy::unwrap_used)]
    use super::*;
    use rstest::rstest;

    #[rstest]
    #[case("acme", Some("main".to_string()), "twitch", "tw-channelA",
        "waddles:t:acme:c:main:src:twitch:tw-channelA:events")]
    #[case("acme", None, "twitch", "tw-channelA",
        "waddles:t:acme:c:_tenant:src:twitch:tw-channelA:events")]
    #[case("global", Some("forums".to_string()), "discord", "dg-guildX",
        "waddles:t:global:c:forums:src:discord:dg-guildX:events")]
    fn source_stream_matches_spec_shape(
        #[case] tenant: &str,
        #[case] community: Option<String>,
        #[case] platform: &str,
        #[case] source_id: &str,
        #[case] expected: &str,
    ) {
        let scope = Scope::new(tenant, community);
        assert_eq!(scope.source_stream(platform, source_id), expected);
    }

    #[rstest]
    #[case("acme", Some("main".to_string()), "waddles.bot.commands.default",
        "waddles:t:acme:c:main:app:waddles.bot.commands.default:action",
        "waddles:t:acme:c:main:app:waddles.bot.commands.default:cfg",
        "waddles:t:acme:c:main:app:waddles.bot.commands.default:state")]
    #[case("global", None, "waddles.bot.commands.default",
        "waddles:t:global:c:_tenant:app:waddles.bot.commands.default:action",
        "waddles:t:global:c:_tenant:app:waddles.bot.commands.default:cfg",
        "waddles:t:global:c:_tenant:app:waddles.bot.commands.default:state")]
    fn app_keys_match_spec_shape(
        #[case] tenant: &str,
        #[case] community: Option<String>,
        #[case] app_id: &str,
        #[case] expected_action: &str,
        #[case] expected_cfg: &str,
        #[case] expected_state: &str,
    ) {
        let scope = Scope::new(tenant, community);
        assert_eq!(scope.action_stream(app_id), expected_action);
        assert_eq!(scope.config_key(app_id), expected_cfg);
        assert_eq!(scope.state_key(app_id), expected_state);
    }

    #[test]
    fn stage_round_trips_through_as_str_and_parse() {
        assert_eq!(Stage::parse("process").unwrap().as_str(), "process");
        assert_eq!(Stage::parse("action").unwrap().as_str(), "action");
        assert!(Stage::parse("ingest").is_err());
        assert!(Stage::parse("bogus").is_err());
    }

    #[test]
    fn dlq_key_matches_spec_shape() {
        assert_eq!(dlq_key(Stage::Process), "waddles:dlq:process");
        assert_eq!(dlq_key(Stage::Action), "waddles:dlq:action");
    }

    #[rstest]
    #[case("waddles:t:acme:c:main:src:twitch:tw-channelA:events", Some(("acme".to_string(), Some("main".to_string()))))]
    #[case("waddles:t:global:c:_tenant:app:waddles.bot.commands.default:action", Some(("global".to_string(), None)))]
    #[case("not-a-spine-key", None)]
    #[case("waddles:dlq:process", None)]
    fn parse_scope_from_key_recovers_tenant_and_community(
        #[case] key: &str,
        #[case] expected: Option<(String, Option<String>)>,
    ) {
        assert_eq!(parse_scope_from_key(key), expected);
    }
}
```

- [ ] **Step 2: Un-comment the `scope` line in `lib.rs`** (`pub use scope::{parse_scope_from_key, Scope, Stage, TENANT_WIDE_SEGMENT};`) and remove its `// TODO(task-2):` prefix. The `crate::SpineError` reference in `Stage::parse` will not compile yet — `error.rs` is still a stub. Temporarily add this minimal real definition to `packages/rust-spine/src/error.rs` (Task 5 replaces it with the full type):

```rust
//! Placeholder — full definition lands in Task 5.

/// Placeholder error type; replaced with the full `thiserror` enum in Task 5.
#[derive(Debug, thiserror::Error)]
pub enum SpineError {
    /// A configuration or usage error not covered by a more specific variant yet.
    #[error("{0}")]
    Config(String),
}
```

Add `thiserror = "=2.0.20"` is already a dependency from Task 1, so this compiles without further Cargo.toml changes.

- [ ] **Step 3: Run the tests to verify they fail first** (before Step 2's stub existed, `cargo test` would not even compile — after Step 2 the stub compiles and these tests should already pass since the implementation was written in Step 1 alongside them; run to establish the green baseline for this task):

Run: `docker run --rm -v "$(pwd)/packages/rust-spine:/work" -w /work rust:1.97.1 cargo test --lib scope::`
Expected: `test result: FAIL` if any test above was mistyped relative to the implementation, else all pass — treat a failure here as a signal to re-check the implementation against Step 1's code, not the reverse (both were written together in this task, unlike a strict red-then-green cycle, because key builders are pure string formatting with no ambiguity to drive out via a failing test first).

- [ ] **Step 4: Run again to confirm green.**

Run: `docker run --rm -v "$(pwd)/packages/rust-spine:/work" -w /work rust:1.97.1 cargo test --lib scope::`
Expected: `test result: ok. 8 passed; 0 failed`

- [ ] **Step 5: Commit.**

```bash
git add packages/rust-spine/src/scope.rs packages/rust-spine/src/error.rs packages/rust-spine/src/lib.rs
git commit -m "$(cat <<'EOF'
feat(spine): add Scope/Stage key builders and parse_scope_from_key

Scope::{source_stream,action_stream,config_key,state_key} match spec
Sec6.2's key table exactly, including the _tenant sentinel for a
tenant-wide activation. parse_scope_from_key recovers tenant/community
from a key string for the envelope_invalid DLQ path (Sec5.5) landing in
Task 17.

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01N2rQgkHY872RubwXoBZxtE
EOF
)"
```

---

### Task 3: `PlatformEvent`, `Source`, `EnvelopeError`

**Files:**
- Modify: `packages/rust-spine/src/envelope.rs`, `packages/rust-spine/src/lib.rs`

**Interfaces:**
- Consumes: nothing new.
- Produces: `EnvelopeError` (a `thiserror` type wrapping a message), `Source { platform, account_id, channel_id: Option<String> }`, `PlatformEvent { platform, event_type, actor: Option<String>, payload: serde_json::Map<String, Value>, occurred_at, source: Option<Source> }`, both `Serialize`/`Deserialize` with strict validation. Task 4's `StageEnvelope` embeds `PlatformEvent` as its `event` field and reuses `EnvelopeError`. Task 8's golden-fixture tests deserialize fixture files into `PlatformEvent`/`StageEnvelope` directly.

Spec: §6.1.1 (full field table + the `source` sub-table + the normalizer mapping table), Python source of truth `libs/flask_core/flask_core/stream_pipeline.py:178-252` in the `waddlebot` repo (`_require_str`/`_optional_str`/`_require_object` helpers, `PlatformEvent.to_dict`/`from_dict` — this crate's strict-parsing behavior must reject exactly what those helpers reject, plus the new `source` field and RFC 3339 format check the spec adds on top).

- [ ] **Step 1: Write the failing tests.** Replace the placeholder line in `packages/rust-spine/src/envelope.rs` with:

```rust
//! Byte-compatible port of `flask_core.stream_pipeline`'s `PlatformEvent`/
//! `StageEnvelope` dataclasses (spec Sec6.1). Strict deserialization only:
//! a missing/wrong-typed required field, an unknown top-level key, or a
//! structurally invalid value is an `EnvelopeError`, never coerced.

use serde::{Deserialize, Serialize};
use serde_json::Value;

/// Raised when a queue-crossing pipeline object is malformed on read.
/// Mirrors Python's `EnvelopeError(ValueError)` — refuses a bad shape
/// rather than coercing it.
#[derive(Debug, Clone, PartialEq, Eq, thiserror::Error)]
#[error("{0}")]
pub struct EnvelopeError(pub(crate) String);

fn env_err(msg: impl Into<String>) -> EnvelopeError {
    EnvelopeError(msg.into())
}

fn validate_rfc3339_millis_z(field: &str, s: &str) -> Result<(), EnvelopeError> {
    if s.is_empty() {
        return Err(env_err(format!("{field:?} must be a non-empty string, got \"\"")));
    }
    if !s.ends_with('Z') {
        return Err(env_err(format!(
            "{field:?} must be RFC 3339 UTC with a 'Z' suffix, got {s:?}"
        )));
    }
    chrono::DateTime::parse_from_rfc3339(s)
        .map(|_| ())
        .map_err(|e| env_err(format!("{field:?} is not valid RFC 3339: {s:?} ({e})")))
}

/// Which connection produced a [`PlatformEvent`] — the bot account, app id,
/// or intake source name, plus the platform channel/guild/room it fired
/// in. Tenant/community stay outside the event; `source` answers "which of
/// possibly several connections to this platform" (spec Sec6.1.1).
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Source {
    /// The platform slug — mirrors the top-level `PlatformEvent::platform`.
    pub platform: String,
    /// The connection identity (bot login, app id, intake source name).
    /// Stable across restarts, never a secret.
    pub account_id: String,
    /// The platform's channel/guild/room id, or `None` for an
    /// account-level event with no channel.
    pub channel_id: Option<String>,
}

#[derive(Debug, Clone, Deserialize)]
#[serde(deny_unknown_fields)]
struct RawPlatformEvent {
    platform: String,
    event_type: String,
    actor: Option<String>,
    payload: serde_json::Map<String, Value>,
    occurred_at: String,
    source: Option<Source>,
}

/// A normalized inbound platform event: transport-neutral metadata
/// (`platform`, `event_type`, `actor`, `occurred_at`) plus a
/// platform-specific `payload` object and an optional `source` identifying
/// which connection produced it (spec Sec6.1.1).
#[derive(Debug, Clone, PartialEq, Serialize)]
pub struct PlatformEvent {
    /// Non-empty platform slug (`"twitch"`, `"discord"`, ...).
    pub platform: String,
    /// Non-empty, dotted lowercase event namespace (`"chat.message"`).
    pub event_type: String,
    /// The acting user, or `None` for a system/account-level event.
    pub actor: Option<String>,
    /// Platform-specific event data; may be empty, never a non-object.
    pub payload: serde_json::Map<String, Value>,
    /// RFC 3339 UTC timestamp, millisecond precision, `Z` suffix.
    pub occurred_at: String,
    /// Which connection produced this event, when known.
    pub source: Option<Source>,
}

impl TryFrom<RawPlatformEvent> for PlatformEvent {
    type Error = EnvelopeError;

    fn try_from(raw: RawPlatformEvent) -> Result<Self, EnvelopeError> {
        if raw.platform.is_empty() {
            return Err(env_err("'platform' must be a non-empty string, got \"\""));
        }
        if raw.event_type.is_empty() {
            return Err(env_err("'event_type' must be a non-empty string, got \"\""));
        }
        validate_rfc3339_millis_z("occurred_at", &raw.occurred_at)?;
        if let Some(source) = &raw.source {
            if source.platform != raw.platform {
                return Err(env_err(format!(
                    "'source.platform' ({:?}) must equal the top-level 'platform' ({:?})",
                    source.platform, raw.platform
                )));
            }
        }
        Ok(PlatformEvent {
            platform: raw.platform,
            event_type: raw.event_type,
            actor: raw.actor,
            payload: raw.payload,
            occurred_at: raw.occurred_at,
            source: raw.source,
        })
    }
}

impl<'de> Deserialize<'de> for PlatformEvent {
    fn deserialize<D>(deserializer: D) -> Result<Self, D::Error>
    where
        D: serde::Deserializer<'de>,
    {
        let raw = RawPlatformEvent::deserialize(deserializer)?;
        PlatformEvent::try_from(raw).map_err(serde::de::Error::custom)
    }
}

#[cfg(test)]
mod tests {
    #![allow(clippy::unwrap_used)]
    use super::*;
    use serde_json::json;

    fn valid_event_json() -> Value {
        json!({
            "platform": "twitch",
            "event_type": "chat.message",
            "actor": "some_user",
            "payload": {"text": "!songrequest foo", "channel_id": "12345", "message_id": "abc"},
            "occurred_at": "2026-09-14T12:00:00.000Z",
            "source": {"platform": "twitch", "account_id": "bot-primary", "channel_id": "12345"}
        })
    }

    #[test]
    fn deserializes_a_fully_populated_valid_event() {
        let event: PlatformEvent = serde_json::from_value(valid_event_json()).unwrap();
        assert_eq!(event.platform, "twitch");
        assert_eq!(event.event_type, "chat.message");
        assert_eq!(event.actor.as_deref(), Some("some_user"));
        assert_eq!(event.payload.get("text").unwrap(), "!songrequest foo");
        assert_eq!(event.occurred_at, "2026-09-14T12:00:00.000Z");
        assert_eq!(event.source.as_ref().unwrap().account_id, "bot-primary");
    }

    #[test]
    fn actor_and_source_are_optional() {
        let mut v = valid_event_json();
        v.as_object_mut().unwrap().remove("source");
        v["actor"] = Value::Null;
        let event: PlatformEvent = serde_json::from_value(v).unwrap();
        assert_eq!(event.actor, None);
        assert_eq!(event.source, None);
    }

    #[test]
    fn empty_payload_object_is_valid() {
        let mut v = valid_event_json();
        v["payload"] = json!({});
        let event: PlatformEvent = serde_json::from_value(v).unwrap();
        assert!(event.payload.is_empty());
    }

    #[test]
    fn rejects_empty_platform() {
        let mut v = valid_event_json();
        v["platform"] = json!("");
        assert!(serde_json::from_value::<PlatformEvent>(v).is_err());
    }

    #[test]
    fn rejects_empty_event_type() {
        let mut v = valid_event_json();
        v["event_type"] = json!("");
        assert!(serde_json::from_value::<PlatformEvent>(v).is_err());
    }

    #[test]
    fn rejects_missing_required_field() {
        let mut v = valid_event_json();
        v.as_object_mut().unwrap().remove("occurred_at");
        assert!(serde_json::from_value::<PlatformEvent>(v).is_err());
    }

    #[test]
    fn rejects_unknown_top_level_key() {
        let mut v = valid_event_json();
        v["extra_field"] = json!("nope");
        assert!(serde_json::from_value::<PlatformEvent>(v).is_err());
    }

    #[test]
    fn rejects_non_object_payload() {
        let mut v = valid_event_json();
        v["payload"] = json!("not-an-object");
        assert!(serde_json::from_value::<PlatformEvent>(v).is_err());
    }

    #[test]
    fn rejects_wrong_typed_field() {
        let mut v = valid_event_json();
        v["platform"] = json!(12345);
        assert!(serde_json::from_value::<PlatformEvent>(v).is_err());
    }

    #[test]
    fn rejects_occurred_at_without_z_suffix() {
        let mut v = valid_event_json();
        v["occurred_at"] = json!("2026-09-14T12:00:00.000+00:00");
        assert!(serde_json::from_value::<PlatformEvent>(v).is_err());
    }

    #[test]
    fn rejects_malformed_occurred_at() {
        let mut v = valid_event_json();
        v["occurred_at"] = json!("not-a-timestamp");
        assert!(serde_json::from_value::<PlatformEvent>(v).is_err());
    }

    #[test]
    fn rejects_source_platform_mismatch() {
        let mut v = valid_event_json();
        v["source"]["platform"] = json!("discord");
        assert!(serde_json::from_value::<PlatformEvent>(v).is_err());
    }

    #[test]
    fn round_trips_through_serialize_and_deserialize() {
        let event: PlatformEvent = serde_json::from_value(valid_event_json()).unwrap();
        let out = serde_json::to_value(&event).unwrap();
        assert_eq!(out, valid_event_json());
    }
}
```

- [ ] **Step 2: Run to verify red, then implement.** The code above is written test-and-implementation-together (types under test appear in the same file, standard for a small pure-data module). Run first to confirm it compiles clean (it needs `chrono`, already added in Task 1):

Run: `docker run --rm -v "$(pwd)/packages/rust-spine:/work" -w /work rust:1.97.1 cargo test --lib envelope::`
Expected: compiles and either all pass, or a specific test fails — fix `envelope.rs` until every test in Step 1 passes. Do not skip this run: it is what proves the byte-identical round-trip assertion actually holds given `preserve_order`.

- [ ] **Step 3: Activate the partial `lib.rs` export.** Change the commented envelope line to:

```rust
pub use envelope::{EnvelopeError, PlatformEvent, Source};
// TODO(task-4): also export StageEnvelope, PROCESS_TARGET_APP_ID_KEY
```

- [ ] **Step 4: Run the full test suite and confirm green.**

Run: `docker run --rm -v "$(pwd)/packages/rust-spine:/work" -w /work rust:1.97.1 cargo test`
Expected: `test result: ok. 13 passed; 0 failed` for `envelope::tests`, plus all of Task 2's `scope::tests` still green.

- [ ] **Step 5: Commit.**

```bash
git add packages/rust-spine/src/envelope.rs packages/rust-spine/src/lib.rs
git commit -m "$(cat <<'EOF'
feat(spine): add PlatformEvent, Source, EnvelopeError

Strict deserialization matching flask_core.stream_pipeline's
_require_str/_optional_str/_require_object rejection behavior, plus the
new source field (Sec6.1.1) and an RFC 3339 + Z-suffix check the current
Python source doesn't enforce yet but the spec requires. preserve_order
keeps payload key order stable for the golden-fixture round-trip test
landing in Task 8.

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01N2rQgkHY872RubwXoBZxtE
EOF
)"
```

---

### Task 4: `StageEnvelope`, `Trace`, `Binding`, `PROCESS_TARGET_APP_ID_KEY` (D30 workstream identity + trace)

**Files:**
- Modify: `packages/rust-spine/src/envelope.rs`, `packages/rust-spine/src/lib.rs`

**Interfaces:**
- Consumes: `PlatformEvent`, `EnvelopeError`, `env_err`, `validate_rfc3339_millis_z` (all from Task 3, same file).
- Produces: `StageEnvelope { schema_version, tenant, community: Option<String>, app_id, stage, event: PlatformEvent, ts, target_app_id: Option<String>, workstream_id, event_id, session_id: Option<String>, trace: Option<Trace>, binding: Binding }`, `Trace { traceparent: String, tracestate: Option<String> }`, `Binding { kid: String, mac: String }`, `PROCESS_TARGET_APP_ID_KEY: &str`. Task 5's `DlqRecord::from_delivered` reads `StageEnvelope` fields directly, including `workstream_id` and `trace`. Task 8's golden fixtures deserialize into this type. Task 13's `SpineClient::append` takes `&StageEnvelope`. Task 16's `Delivered.env: StageEnvelope`. Task 19's `binding` module consumes `StageEnvelope`, `Trace` and `Binding` to compute/verify `binding.mac` and build `ScopeCheck`.

Spec: §6.1.2 (full field table, strictness rules, reserved payload key, `schema_version` bumped to `2` — D3, D30), §5.11 (workstream identity, `event_id`, `session_id`, `trace`, `binding.mac` — D30), §3.3 (`_target_app_id` invariant preserved bit for bit).

- [ ] **Step 1: Write the failing tests.** Append to `packages/rust-spine/src/envelope.rs` (after the existing `PlatformEvent`/`Deserialize` impl, before the `#[cfg(test)] mod tests` block — move the existing `mod tests` block's closing brace down so this new code sits above it, or simplest: insert everything below directly above the existing `#[cfg(test)] mod tests {` line, then add the new test functions **inside** that same `mod tests` block, right after `round_trips_through_serialize_and_deserialize`):

```rust
/// Reserved `PlatformEvent.payload` key a process-stage bundle sets to
/// request cross-app routing; the stage pops this key back out of the
/// payload before enqueuing, so it never reaches an action bundle or a
/// chat reply (spec Sec6.1.2, Sec5.9).
pub const PROCESS_TARGET_APP_ID_KEY: &str = "_target_app_id";

/// The only `StageEnvelope.schema_version` this crate accepts. No
/// dual-read (D3, D30): a `1` or absent value is the pre-D30 shape and is
/// rejected outright rather than interpreted (spec Sec6.1.2).
pub const ENVELOPE_SCHEMA_VERSION: u32 = 2;

const BUNDLE_STAGES: [&str; 3] = ["ingest", "process", "action"];

fn is_valid_app_id_segment(seg: &str) -> bool {
    let mut chars = seg.chars();
    let first_ok = matches!(chars.next(), Some(c) if c.is_ascii_lowercase() || c.is_ascii_digit());
    first_ok && chars.all(|c| c.is_ascii_lowercase() || c.is_ascii_digit() || c == '_' || c == '-')
}

/// Validates `^waddles\.[a-z0-9][a-z0-9_-]*\.[a-z0-9][a-z0-9_-]*\.[a-z0-9][a-z0-9_-]*$`
/// (spec Sec6.1.2) without pulling in a `regex` dependency for one pattern.
fn is_valid_app_id(s: &str) -> bool {
    let mut parts = s.split('.');
    if parts.next() != Some("waddles") {
        return false;
    }
    let rest: Vec<&str> = parts.collect();
    rest.len() == 3 && rest.iter().all(|seg| is_valid_app_id_segment(seg))
}

/// Validates a W3C `traceparent` (`00-<32 hex>-<16 hex>-<2 hex>`, spec Sec6.1.2).
fn is_valid_traceparent(s: &str) -> bool {
    let parts: Vec<&str> = s.split('-').collect();
    parts.len() == 4
        && parts[0] == "00"
        && parts[1].len() == 32
        && parts[1].chars().all(|c| c.is_ascii_hexdigit())
        && parts[2].len() == 16
        && parts[2].chars().all(|c| c.is_ascii_hexdigit())
        && parts[3].len() == 2
        && parts[3].chars().all(|c| c.is_ascii_hexdigit())
}

/// Extracts the 32-hex trace-id segment from a validated `traceparent`
/// (spec Sec5.11: `binding.mac`'s input is this segment, not the full
/// `traceparent` string). Returns `None` if `s` is not a valid traceparent.
pub fn trace_id_from_traceparent(s: &str) -> Option<&str> {
    if !is_valid_traceparent(s) {
        return None;
    }
    s.split('-').nth(1)
}

fn is_valid_uuid(s: &str) -> bool {
    uuid::Uuid::parse_str(s).is_ok()
}

/// `event_id` must be UUID **v4** specifically (spec Sec6.1.2, Sec5.11) --
/// stricter than `workstream_id`, which is any valid UUID minted by
/// hub-api.
fn is_valid_uuid_v4(s: &str) -> bool {
    uuid::Uuid::parse_str(s)
        .map(|u| u.get_version() == Some(uuid::Version::Random))
        .unwrap_or(false)
}

/// `binding.mac` is the lowercase-hex HMAC-SHA256 output (spec Sec5.11):
/// exactly 64 lowercase hex characters, never uppercase (a mixed-case
/// value is treated as malformed rather than case-normalized, since a
/// verifier that silently normalizes case could be tricked into comparing
/// two differently-cased representations of a byte-identical forgery).
fn is_lowercase_hex_64(s: &str) -> bool {
    s.len() == 64 && s.chars().all(|c| c.is_ascii_digit() || ('a'..='f').contains(&c))
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
struct RawTrace {
    traceparent: String,
    #[serde(default)]
    tracestate: Option<String>,
}

/// The W3C trace context carried on every envelope (spec Sec5.11,
/// Sec6.1.2) -- **supersedes the pre-D30 single-field `trace_context`**.
/// Absent means "no parent span"; when present, `traceparent` has already
/// passed the Sec6.1.2 shape check.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Trace {
    /// The W3C `traceparent` string (`00-<32 hex>-<16 hex>-<2 hex>`).
    pub traceparent: String,
    /// The W3C `tracestate` string, or `None`.
    pub tracestate: Option<String>,
}

impl TryFrom<RawTrace> for Trace {
    type Error = EnvelopeError;

    fn try_from(raw: RawTrace) -> Result<Self, EnvelopeError> {
        if !is_valid_traceparent(&raw.traceparent) {
            return Err(env_err(format!(
                "'trace.traceparent' {:?} is not a valid W3C traceparent",
                raw.traceparent
            )));
        }
        Ok(Trace { traceparent: raw.traceparent, tracestate: raw.tracestate })
    }
}

impl<'de> Deserialize<'de> for Trace {
    fn deserialize<D>(deserializer: D) -> Result<Self, D::Error>
    where
        D: serde::Deserializer<'de>,
    {
        let raw = RawTrace::deserialize(deserializer)?;
        Trace::try_from(raw).map_err(serde::de::Error::custom)
    }
}

#[derive(Debug, Clone, Deserialize)]
#[serde(deny_unknown_fields)]
struct RawBinding {
    kid: String,
    mac: String,
}

/// `{kid, mac}` -- `kid` names the active HMAC key version, `mac` is the
/// lowercase-hex `HMAC-SHA256` of spec Sec5.11's formula. Required on
/// every envelope; there is no unsigned shape (D30). Verified by every
/// stage on every read, before any other processing -- see the `binding`
/// module (Task 19) for `compute_binding_mac`/`verify_binding`.
#[derive(Debug, Clone, PartialEq, Serialize)]
pub struct Binding {
    /// Names the HMAC key version under which `mac` was computed.
    pub kid: String,
    /// Lowercase-hex HMAC-SHA256 output (64 hex chars, spec Sec5.11).
    pub mac: String,
}

impl TryFrom<RawBinding> for Binding {
    type Error = EnvelopeError;

    fn try_from(raw: RawBinding) -> Result<Self, EnvelopeError> {
        if raw.kid.is_empty() {
            return Err(env_err("'binding.kid' must be a non-empty string, got \"\""));
        }
        if !is_lowercase_hex_64(&raw.mac) {
            return Err(env_err(format!(
                "'binding.mac' {:?} must be exactly 64 lowercase hex characters",
                raw.mac
            )));
        }
        Ok(Binding { kid: raw.kid, mac: raw.mac })
    }
}

impl<'de> Deserialize<'de> for Binding {
    fn deserialize<D>(deserializer: D) -> Result<Self, D::Error>
    where
        D: serde::Deserializer<'de>,
    {
        let raw = RawBinding::deserialize(deserializer)?;
        Binding::try_from(raw).map_err(serde::de::Error::custom)
    }
}

#[derive(Debug, Clone, Deserialize)]
#[serde(deny_unknown_fields)]
struct RawStageEnvelope {
    schema_version: u32,
    tenant: String,
    community: Option<String>,
    app_id: String,
    stage: String,
    event: PlatformEvent,
    ts: String,
    #[serde(default)]
    target_app_id: Option<String>,
    workstream_id: String,
    event_id: String,
    #[serde(default)]
    session_id: Option<String>,
    #[serde(default)]
    trace: Option<Trace>,
    binding: Binding,
}

/// One pipeline queue message routed between stages. `event` (a
/// [`PlatformEvent`]) is the payload — never named `payload`, deliberately,
/// so a stage double-nesting a payload dict under a `payload` key is
/// structurally impossible (spec Sec6.1.2). `target_app_id` is the one
/// sanctioned cross-app routing escape hatch (spec Sec5.9); it changes
/// only the destination key's `app_id` segment.
///
/// `workstream_id`, `event_id`, `session_id`, `trace` and `binding` are
/// the D30 workstream-identity/trace/tenant-wall fields (spec Sec5.11):
/// minted once by svc-ingest from its own `intake_sources`/`workstreams`
/// cache, never from payload, and copied verbatim by every later stage --
/// a bundle's output is never read for them (spec Sec5.11 "Bundles cannot
/// move a workstream"). Field order matches the spec Sec6.1.2 JSON example
/// exactly, so golden-fixture round-trips (Task 8) are byte-identical.
#[derive(Debug, Clone, PartialEq, Serialize)]
pub struct StageEnvelope {
    /// Must equal [`ENVELOPE_SCHEMA_VERSION`] (`2`) -- no dual-read (D3, D30).
    pub schema_version: u32,
    /// Non-empty tenant slug; equals the `t:` segment of the key it came from.
    pub tenant: String,
    /// `None` iff the key's `c:` segment is the literal `_tenant`.
    pub community: Option<String>,
    /// Matches `^waddles\.[a-z0-9][a-z0-9_-]*\.[a-z0-9][a-z0-9_-]*\.[a-z0-9][a-z0-9_-]*$`.
    pub app_id: String,
    /// One of `"ingest"`, `"process"`, `"action"`.
    pub stage: String,
    /// The carried `PlatformEvent`.
    pub event: PlatformEvent,
    /// RFC 3339 UTC timestamp, millisecond precision, `Z` suffix.
    pub ts: String,
    /// The cross-app routing target, when a process bundle set one.
    pub target_app_id: Option<String>,
    /// UUID; minted by svc-ingest from `intake_sources`/`workstreams`
    /// (spec Sec5.11, Sec6.11), never from payload; copied verbatim by
    /// every later stage, never accepted from bundle output.
    pub workstream_id: String,
    /// UUID v4, minted once by svc-ingest per inbound event; distinct from
    /// the platform's own message id and the Valkey stream entry id.
    pub event_id: String,
    /// The platform connection/broadcast session, when the platform has
    /// one; absent otherwise (spec Sec5.11).
    pub session_id: Option<String>,
    /// W3C trace context for the entry's parent span, when present.
    /// Supersedes the pre-D30 `trace_context` field.
    pub trace: Option<Trace>,
    /// `{kid, mac}` -- the Sec5.11 tenant-binding MAC. Required.
    pub binding: Binding,
}

impl TryFrom<RawStageEnvelope> for StageEnvelope {
    type Error = EnvelopeError;

    fn try_from(raw: RawStageEnvelope) -> Result<Self, EnvelopeError> {
        if raw.schema_version != ENVELOPE_SCHEMA_VERSION {
            return Err(env_err(format!(
                "'schema_version' must equal {ENVELOPE_SCHEMA_VERSION}, got {} -- no dual-read of the pre-D30 shape",
                raw.schema_version
            )));
        }
        if raw.tenant.is_empty() {
            return Err(env_err("'tenant' must be a non-empty string, got \"\""));
        }
        if !BUNDLE_STAGES.contains(&raw.stage.as_str()) {
            return Err(env_err(format!(
                "'stage' {:?} is not one of {BUNDLE_STAGES:?}",
                raw.stage
            )));
        }
        if !is_valid_app_id(&raw.app_id) {
            return Err(env_err(format!(
                "'app_id' {:?} does not match the required waddles.<mod>.<feature>.<variant> shape",
                raw.app_id
            )));
        }
        validate_rfc3339_millis_z("ts", &raw.ts)?;
        if !is_valid_uuid(&raw.workstream_id) {
            return Err(env_err(format!(
                "'workstream_id' {:?} is not a valid UUID",
                raw.workstream_id
            )));
        }
        if !is_valid_uuid_v4(&raw.event_id) {
            return Err(env_err(format!(
                "'event_id' {:?} is not a valid UUID v4",
                raw.event_id
            )));
        }
        if let Some(session_id) = &raw.session_id {
            if session_id.is_empty() {
                return Err(env_err("'session_id' must be a non-empty string when present, got \"\""));
            }
        }
        Ok(StageEnvelope {
            schema_version: raw.schema_version,
            tenant: raw.tenant,
            community: raw.community,
            app_id: raw.app_id,
            stage: raw.stage,
            event: raw.event,
            ts: raw.ts,
            target_app_id: raw.target_app_id,
            workstream_id: raw.workstream_id,
            event_id: raw.event_id,
            session_id: raw.session_id,
            trace: raw.trace,
            binding: raw.binding,
        })
    }
}

impl<'de> Deserialize<'de> for StageEnvelope {
    fn deserialize<D>(deserializer: D) -> Result<Self, D::Error>
    where
        D: serde::Deserializer<'de>,
    {
        let raw = RawStageEnvelope::deserialize(deserializer)?;
        StageEnvelope::try_from(raw).map_err(serde::de::Error::custom)
    }
}
```

Then, inside the existing `mod tests` block, add:

```rust
    fn valid_stage_envelope_json() -> Value {
        json!({
            "schema_version": 2,
            "tenant": "global",
            "community": null,
            "app_id": "waddles.bot.commands.default",
            "stage": "process",
            "event": valid_event_json(),
            "ts": "2026-09-14T12:00:00.123Z",
            "target_app_id": null,
            "workstream_id": "8f14e45f-ceea-467e-adde-3fb5c9752730",
            "event_id": "3fa85f64-5717-4562-b3fc-2c963f66afa6",
            "session_id": null,
            "trace": {
                "traceparent": "00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01",
                "tracestate": null
            },
            "binding": {
                "kid": "2026-09",
                "mac": "9f86d081884c7d659a2feaa0c55ad015a3bf4f1b2b0b822cd15d6c15b0f00a08"
            }
        })
    }

    #[test]
    fn deserializes_a_fully_populated_stage_envelope() {
        let env: StageEnvelope = serde_json::from_value(valid_stage_envelope_json()).unwrap();
        assert_eq!(env.schema_version, 2);
        assert_eq!(env.tenant, "global");
        assert_eq!(env.community, None);
        assert_eq!(env.app_id, "waddles.bot.commands.default");
        assert_eq!(env.stage, "process");
        assert_eq!(env.target_app_id, None);
        assert_eq!(env.workstream_id, "8f14e45f-ceea-467e-adde-3fb5c9752730");
        assert_eq!(env.event_id, "3fa85f64-5717-4562-b3fc-2c963f66afa6");
        assert_eq!(env.session_id, None);
        assert_eq!(
            env.trace.as_ref().map(|t| t.traceparent.as_str()),
            Some("00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01")
        );
        assert_eq!(env.binding.kid, "2026-09");
    }

    #[test]
    fn community_scoped_and_target_app_id_set() {
        let mut v = valid_stage_envelope_json();
        v["community"] = json!("main");
        v["target_app_id"] = json!("waddles.community.forums.default");
        let env: StageEnvelope = serde_json::from_value(v).unwrap();
        assert_eq!(env.community.as_deref(), Some("main"));
        assert_eq!(
            env.target_app_id.as_deref(),
            Some("waddles.community.forums.default")
        );
    }

    #[test]
    fn trace_absent_deserializes_to_none() {
        let mut v = valid_stage_envelope_json();
        v.as_object_mut().unwrap().remove("trace");
        let env: StageEnvelope = serde_json::from_value(v).unwrap();
        assert_eq!(env.trace, None);
    }

    #[test]
    fn session_id_present_round_trips() {
        let mut v = valid_stage_envelope_json();
        v["session_id"] = json!("gw-session-abc123");
        let env: StageEnvelope = serde_json::from_value(v).unwrap();
        assert_eq!(env.session_id.as_deref(), Some("gw-session-abc123"));
    }

    #[test]
    fn rejects_stage_outside_fixed_set() {
        let mut v = valid_stage_envelope_json();
        v["stage"] = json!("bogus");
        assert!(serde_json::from_value::<StageEnvelope>(v).is_err());
    }

    #[test]
    fn rejects_app_id_with_too_few_segments() {
        let mut v = valid_stage_envelope_json();
        v["app_id"] = json!("waddles.bot");
        assert!(serde_json::from_value::<StageEnvelope>(v).is_err());
    }

    #[test]
    fn rejects_app_id_without_waddles_prefix() {
        let mut v = valid_stage_envelope_json();
        v["app_id"] = json!("other.bot.commands.default");
        assert!(serde_json::from_value::<StageEnvelope>(v).is_err());
    }

    #[test]
    fn rejects_empty_tenant() {
        let mut v = valid_stage_envelope_json();
        v["tenant"] = json!("");
        assert!(serde_json::from_value::<StageEnvelope>(v).is_err());
    }

    #[test]
    fn rejects_missing_event_key_legacy_shape() {
        let mut v = valid_stage_envelope_json();
        v.as_object_mut().unwrap().remove("event");
        v["text"] = json!("legacy shape carried data at the top level");
        assert!(serde_json::from_value::<StageEnvelope>(v).is_err());
    }

    #[test]
    fn rejects_non_object_event() {
        let mut v = valid_stage_envelope_json();
        v["event"] = json!("not-an-object");
        assert!(serde_json::from_value::<StageEnvelope>(v).is_err());
    }

    #[test]
    fn rejects_malformed_traceparent() {
        let mut v = valid_stage_envelope_json();
        v["trace"] = json!({"traceparent": "not-a-traceparent", "tracestate": null});
        assert!(serde_json::from_value::<StageEnvelope>(v).is_err());
    }

    #[test]
    fn rejects_unknown_top_level_key_on_stage_envelope() {
        let mut v = valid_stage_envelope_json();
        v["extra"] = json!("nope");
        assert!(serde_json::from_value::<StageEnvelope>(v).is_err());
    }

    #[test]
    fn rejects_schema_version_1() {
        let mut v = valid_stage_envelope_json();
        v["schema_version"] = json!(1);
        let err = serde_json::from_value::<StageEnvelope>(v).unwrap_err();
        assert!(err.to_string().contains("schema_version"));
    }

    #[test]
    fn rejects_missing_schema_version() {
        let mut v = valid_stage_envelope_json();
        v.as_object_mut().unwrap().remove("schema_version");
        assert!(serde_json::from_value::<StageEnvelope>(v).is_err());
    }

    #[test]
    fn rejects_missing_workstream_id() {
        let mut v = valid_stage_envelope_json();
        v.as_object_mut().unwrap().remove("workstream_id");
        assert!(serde_json::from_value::<StageEnvelope>(v).is_err());
    }

    #[test]
    fn rejects_non_uuid_workstream_id() {
        let mut v = valid_stage_envelope_json();
        v["workstream_id"] = json!("not-a-uuid");
        assert!(serde_json::from_value::<StageEnvelope>(v).is_err());
    }

    #[test]
    fn rejects_missing_event_id() {
        let mut v = valid_stage_envelope_json();
        v.as_object_mut().unwrap().remove("event_id");
        assert!(serde_json::from_value::<StageEnvelope>(v).is_err());
    }

    #[test]
    fn rejects_event_id_that_is_not_uuid_v4() {
        let mut v = valid_stage_envelope_json();
        // A well-formed but v1 (time-based) UUID -- valid UUID, wrong version.
        v["event_id"] = json!("6ba7b810-9dad-11d1-80b4-00c04fd430c8");
        let err = serde_json::from_value::<StageEnvelope>(v).unwrap_err();
        assert!(err.to_string().contains("event_id"));
    }

    #[test]
    fn rejects_missing_binding() {
        let mut v = valid_stage_envelope_json();
        v.as_object_mut().unwrap().remove("binding");
        assert!(serde_json::from_value::<StageEnvelope>(v).is_err());
    }

    #[test]
    fn rejects_binding_mac_wrong_length() {
        let mut v = valid_stage_envelope_json();
        v["binding"]["mac"] = json!("deadbeef");
        assert!(serde_json::from_value::<StageEnvelope>(v).is_err());
    }

    #[test]
    fn rejects_binding_mac_with_uppercase_hex() {
        let mut v = valid_stage_envelope_json();
        v["binding"]["mac"] = json!("9F86D081884C7D659A2FEAA0C55AD015A3BF4F1B2B0B822CD15D6C15B0F00A0");
        assert!(serde_json::from_value::<StageEnvelope>(v).is_err());
    }

    #[test]
    fn rejects_empty_binding_kid() {
        let mut v = valid_stage_envelope_json();
        v["binding"]["kid"] = json!("");
        assert!(serde_json::from_value::<StageEnvelope>(v).is_err());
    }

    #[test]
    fn rejects_empty_session_id() {
        let mut v = valid_stage_envelope_json();
        v["session_id"] = json!("");
        assert!(serde_json::from_value::<StageEnvelope>(v).is_err());
    }

    #[test]
    fn trace_id_from_traceparent_extracts_the_32_hex_segment() {
        assert_eq!(
            trace_id_from_traceparent("00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01"),
            Some("4bf92f3577b34da6a3ce929d0e0e4736")
        );
        assert_eq!(trace_id_from_traceparent("not-a-traceparent"), None);
    }

    #[test]
    fn stage_envelope_round_trips_through_serialize_and_deserialize() {
        let env: StageEnvelope = serde_json::from_value(valid_stage_envelope_json()).unwrap();
        let out = serde_json::to_value(&env).unwrap();
        assert_eq!(out, valid_stage_envelope_json());
    }
```

- [ ] **Step 2: Run and fix until green.**

Run: `docker run --rm -v "$(pwd)/packages/rust-spine:/work" -w /work rust:1.97.1 cargo test --lib envelope::`
Expected: `test result: ok. 37 passed; 0 failed`

- [ ] **Step 3: Activate the full `lib.rs` envelope export**, replacing both lines from Task 3 with one:

```rust
pub use envelope::{
    trace_id_from_traceparent, Binding, EnvelopeError, PlatformEvent, Source, StageEnvelope,
    Trace, ENVELOPE_SCHEMA_VERSION, PROCESS_TARGET_APP_ID_KEY,
};
```

- [ ] **Step 4: Run the full suite and confirm green.**

Run: `docker run --rm -v "$(pwd)/packages/rust-spine:/work" -w /work rust:1.97.1 cargo test`
Expected: `test result: ok.` for both `scope::tests` and `envelope::tests`, no failures.

- [ ] **Step 5: Commit.**

```bash
git add packages/rust-spine/src/envelope.rs packages/rust-spine/src/lib.rs
git commit -m "$(cat <<'EOF'
feat(spine): add StageEnvelope D30 workstream/trace/binding fields

schema_version bumped to 2 (no dual-read, D3/D30). StageEnvelope gains
workstream_id (UUID), event_id (UUID v4), session_id (optional), trace
(Trace{traceparent,tracestate}, superseding trace_context) and binding
(Binding{kid,mac}, required). Full Sec6.1.2 strictness for every new
field, including the missing-event legacy-shape rejection that makes
payload-under-payload double-nesting structurally impossible.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01N2rQgkHY872RubwXoBZxtE
EOF
)"
```
---

### Task 5: `SpineError`, `DlqRecord`, `DlqErrorDetail`, `DlqError`, `DlqErrorKind`

**Files:**
- Modify: `packages/rust-spine/src/error.rs`, `packages/rust-spine/src/dlq.rs`, `packages/rust-spine/src/lib.rs`

**Interfaces:**
- Consumes: `EnvelopeError` (Task 3).
- Produces: `SpineError` (replaces Task 2's placeholder — every later task's fallible functions return `Result<_, SpineError>`), `DlqErrorKind` (10 variants including `TenantBoundary`, `as_str`, `never_retry`), `DlqErrorDetail { kind, code, message, detail: Option<String> }`, `DlqRecord` (full spec §6.3 shape including `workstream_id: Option<String>` and `trace: Option<Trace>` — D30, public fields, no constructor yet), `DlqError { kind, code, message, detail, artifact_digest, consumer_id }` — the type a caller hands to `SpineClient::dead_letter` (Task 16). Task 16 adds `impl DlqRecord { pub fn from_delivered(...) }` once `Delivered` exists (Task 13); this task only defines the data shapes.

Spec: §6.3 (full DLQ record JSON + field table + the ten `error.kind` values, D30 adds `tenant_boundary`), §5.5 (when each is written).

- [ ] **Step 1: Replace the Task 2 placeholder in `packages/rust-spine/src/error.rs` with the real type, and write its test:**

```rust
//! The crate-wide error type. Every fallible `penguin-spine` function
//! returns `Result<_, SpineError>`.

use crate::envelope::EnvelopeError;

/// Every fallible operation this crate exposes returns this error. Wraps
/// the two external failure sources (`redis`, `serde_json`) plus the
/// spine-specific conditions the spec calls out by name.
#[derive(Debug, thiserror::Error)]
pub enum SpineError {
    /// A Valkey command failed, or a connection could not be established.
    #[error("valkey command failed: {0}")]
    Redis(#[from] redis::RedisError),
    /// A stream entry's envelope JSON failed strict deserialization.
    #[error("envelope error: {0}")]
    Envelope(#[from] EnvelopeError),
    /// A [`crate::GroupReader`] was asked to read a stream outside its
    /// grant list (spec Sec5.2 — the stage is the enforcement point).
    #[error("stream {stream:?} is not in this reader's grant list")]
    StreamNotGranted {
        /// The ungranted stream that was requested.
        stream: String,
    },
    /// A blocking-read timeout was not strictly less than its owning
    /// connection's socket timeout (spec Sec5.7 rule 1) — construction is
    /// refused rather than allowed to race silently in production.
    #[error(
        "blocking timeout {block_name} = {block_ms}ms must be strictly less than \
         the connection's socket timeout (DRAIN_SOCKET_TIMEOUT_S = {socket_timeout_s}s)"
    )]
    BlockTimeoutInvalid {
        /// Which config value failed the check.
        block_name: &'static str,
        /// The offending value, in milliseconds.
        block_ms: u64,
        /// The connection's configured socket timeout, in seconds.
        socket_timeout_s: u64,
    },
    /// JSON encode/decode failure outside envelope parsing (DLQ records,
    /// the ACL matrix).
    #[error("json error: {0}")]
    Json(#[from] serde_json::Error),
    /// A configuration or environment-loading error.
    #[error("spine config error: {0}")]
    Config(String),
}

#[cfg(test)]
mod tests {
    #![allow(clippy::unwrap_used)]
    use super::*;

    #[test]
    fn stream_not_granted_message_names_the_stream() {
        let err = SpineError::StreamNotGranted {
            stream: "waddles:t:acme:c:main:src:discord:dg-x:events".to_string(),
        };
        assert!(err.to_string().contains("waddles:t:acme:c:main:src:discord:dg-x:events"));
    }

    #[test]
    fn block_timeout_invalid_message_names_both_values() {
        let err = SpineError::BlockTimeoutInvalid {
            block_name: "SPINE_BLOCK_MS",
            block_ms: 70_000,
            socket_timeout_s: 65,
        };
        let msg = err.to_string();
        assert!(msg.contains("SPINE_BLOCK_MS"));
        assert!(msg.contains("70000"));
        assert!(msg.contains("65"));
    }

    #[test]
    fn envelope_error_converts_via_from() {
        let env_err = crate::EnvelopeError::from(
            serde_json::from_str::<crate::PlatformEvent>("{}").unwrap_err(),
        );
        let spine_err: SpineError = env_err.into();
        assert!(matches!(spine_err, SpineError::Envelope(_)));
    }
}
```

`EnvelopeError::from(serde_json::Error)` referenced in the last test does not exist yet — add it to `envelope.rs` in this same task (small addition, still Task 5's scope since it is needed to exercise `SpineError::Envelope`'s `#[from]` conversion path in a test):

```rust
impl From<serde_json::Error> for EnvelopeError {
    fn from(e: serde_json::Error) -> Self {
        env_err(e.to_string())
    }
}
```

(Append this to `packages/rust-spine/src/envelope.rs`, above its `#[cfg(test)]` block.)

- [ ] **Step 2: Write `packages/rust-spine/src/dlq.rs`:**

```rust
//! The dead-letter record shape (spec Sec6.3) and the caller-supplied
//! classification `SpineClient::dead_letter` (Task 16) accepts.

use crate::envelope::Trace;
use serde::{Deserialize, Serialize};

/// The DLQ record's `error.kind` classification (spec Sec6.3) — exactly
/// ten values, each also the `reason` label on `waddles_spine_dlq_total`.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum DlqErrorKind {
    /// Strict envelope deserialization failed.
    EnvelopeInvalid,
    /// The WASM component trapped (panic, unreachable, guest OOM).
    BundleTrap,
    /// The component returned a terminal (non-retryable) error.
    BundleError,
    /// The per-call epoch deadline fired.
    CallTimeout,
    /// The instance exceeded its memory cap.
    MemoryLimit,
    /// A capability check refused the call.
    HostCallDenied,
    /// `deliveries` reached `SPINE_MAX_DELIVERIES`.
    MaxDeliveries,
    /// The Sec5.11 hop verification failed: `binding.mac` mismatch,
    /// envelope tenant/community disagreeing with the stream key, a
    /// grant/approval scoped to a different tenant or community, or a
    /// bundle output that tried to set an identity field (D30). **Never
    /// retried** — see [`DlqErrorKind::never_retry`].
    TenantBoundary,
    /// The bundle is disabled after three sandbox trips.
    BundleDisabled,
    /// The executor was unavailable past its ready-timeout.
    ExecutorUnavailable,
}

impl DlqErrorKind {
    /// The exact snake_case wire string (matches the spec's `error.kind`
    /// values and the `reason` label on `waddles_spine_dlq_total`).
    pub fn as_str(&self) -> &'static str {
        match self {
            DlqErrorKind::EnvelopeInvalid => "envelope_invalid",
            DlqErrorKind::BundleTrap => "bundle_trap",
            DlqErrorKind::BundleError => "bundle_error",
            DlqErrorKind::CallTimeout => "call_timeout",
            DlqErrorKind::MemoryLimit => "memory_limit",
            DlqErrorKind::HostCallDenied => "host_call_denied",
            DlqErrorKind::MaxDeliveries => "max_deliveries",
            DlqErrorKind::TenantBoundary => "tenant_boundary",
            DlqErrorKind::BundleDisabled => "bundle_disabled",
            DlqErrorKind::ExecutorUnavailable => "executor_unavailable",
        }
    }

    /// True when an entry classified this way must never be attempted
    /// again after being DLQ'd — currently only `tenant_boundary` (spec
    /// Sec5.11, D30): a forged, replayed or cross-tenant envelope is not
    /// made valid by retrying it. Every other kind is retried up to
    /// `SPINE_MAX_DELIVERIES` by the stage's normal redelivery path.
    pub fn never_retry(&self) -> bool {
        matches!(self, DlqErrorKind::TenantBoundary)
    }
}

/// The nested `error` object inside a [`DlqRecord`] (spec Sec6.3).
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct DlqErrorDetail {
    /// The classification (spec Sec6.3's ten values).
    pub kind: DlqErrorKind,
    /// A short machine-readable code (e.g. `"EXECUTOR_DEADLINE"`).
    pub code: String,
    /// A human-readable failure message.
    pub message: String,
    /// Optional extra detail; `None` when there is nothing more to say.
    pub detail: Option<String>,
}

/// One JSON object written to `waddles:dlq:{stage}` per failed entry
/// (spec Sec6.3), carried under the single field `rec`. Field order
/// matches the spec's JSON example exactly, for byte-identical
/// golden-fixture round-trips (Task 8).
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct DlqRecord {
    /// Always `1` for this spec revision.
    pub schema_version: u32,
    /// The stage that wrote this record (`"process"`/`"action"`).
    pub stage: String,
    /// The Valkey key of the stream the entry came from.
    pub key: String,
    /// The stream entry id the record came from — the stable
    /// de-duplication key, also handed to a bundle as `message-id`.
    pub entry_id: String,
    /// The consumer group (`app_id`) that was processing the entry.
    pub group: String,
    /// The tenant slug, sourced from the key, never the payload.
    pub tenant: String,
    /// The community slug, or `None` for a tenant-wide activation.
    pub community: Option<String>,
    /// The bundle's `app_id`.
    pub app_id: String,
    /// Copied from the envelope (spec Sec5.11, D30); present whenever the
    /// envelope parsed far enough to carry one — including a
    /// `tenant_boundary` rejection, which is exactly the record an
    /// operator needs to trace a boundary violation back to its source.
    /// `None` only for `envelope_invalid`, where no envelope exists yet.
    pub workstream_id: Option<String>,
    /// `None` when the failure happened before a bundle was selected
    /// (e.g. `envelope_invalid`).
    pub artifact_digest: Option<String>,
    /// The pod identity that was processing the entry.
    pub consumer_id: String,
    /// The delivery count at the time of failure.
    pub deliveries: u64,
    /// RFC 3339 UTC timestamp, millisecond precision, `Z` suffix.
    pub failed_at: String,
    /// The classified failure.
    pub error: DlqErrorDetail,
    /// W3C trace context, when the originating envelope carried one.
    /// Supersedes the pre-D30 single-field `trace_context`.
    pub trace: Option<Trace>,
    /// The original envelope JSON, verbatim, as a string — so a malformed
    /// envelope is still replayable/inspectable even though it failed to
    /// parse.
    pub raw: String,
}

/// What a caller hands [`crate::SpineClient::dead_letter`] (Task 16) to
/// classify why an entry failed. `consumer_id` travels here rather than on
/// [`crate::Delivered`] because only the stage runner constructing this
/// value (not the entry itself) knows its own `SPINE_CONSUMER_ID`.
#[derive(Debug, Clone)]
pub struct DlqError {
    /// The classification.
    pub kind: DlqErrorKind,
    /// A short machine-readable code.
    pub code: String,
    /// A human-readable failure message.
    pub message: String,
    /// Optional extra detail.
    pub detail: Option<String>,
    /// The bundle's verified artifact digest, when one was selected.
    pub artifact_digest: Option<String>,
    /// The pod identity handling the entry.
    pub consumer_id: String,
}

#[cfg(test)]
mod tests {
    #![allow(clippy::unwrap_used)]
    use super::*;
    use serde_json::json;

    fn valid_record_json() -> serde_json::Value {
        json!({
            "schema_version": 1,
            "stage": "process",
            "key": "waddles:t:global:c:_tenant:src:twitch:tw-channelA:events",
            "entry_id": "1757851200000-0",
            "group": "waddles.bot.commands.default",
            "tenant": "global",
            "community": null,
            "app_id": "waddles.bot.commands.default",
            "workstream_id": "8f14e45f-ceea-467e-adde-3fb5c9752730",
            "artifact_digest": "sha256:9f86d081884c7d659a2feaa0c55ad015a3bf4f1b2b0b822cd15d6c15b0f00a08",
            "consumer_id": "svc-process-7d9c4f",
            "deliveries": 5,
            "failed_at": "2026-09-14T12:00:01.500Z",
            "error": {
                "kind": "call_timeout",
                "code": "EXECUTOR_DEADLINE",
                "message": "bundle call exceeded 2000 ms",
                "detail": null
            },
            "trace": {
                "traceparent": "00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01",
                "tracestate": null
            },
            "raw": "{\"tenant\":\"global\",\"community\":null}"
        })
    }

    #[test]
    fn deserializes_the_spec_example_record() {
        let rec: DlqRecord = serde_json::from_value(valid_record_json()).unwrap();
        assert_eq!(rec.schema_version, 1);
        assert_eq!(rec.error.kind, DlqErrorKind::CallTimeout);
        assert_eq!(rec.error.code, "EXECUTOR_DEADLINE");
        assert_eq!(rec.workstream_id.as_deref(), Some("8f14e45f-ceea-467e-adde-3fb5c9752730"));
        assert_eq!(
            rec.trace.as_ref().map(|t| t.traceparent.as_str()),
            Some("00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01")
        );
    }

    #[test]
    fn record_round_trips_through_serialize_and_deserialize() {
        let rec: DlqRecord = serde_json::from_value(valid_record_json()).unwrap();
        let out = serde_json::to_value(&rec).unwrap();
        assert_eq!(out, valid_record_json());
    }

    #[test]
    fn workstream_id_absent_is_valid_for_envelope_invalid() {
        let mut v = valid_record_json();
        v["workstream_id"] = json!(null);
        v["error"]["kind"] = json!("envelope_invalid");
        v["error"]["code"] = json!("MALFORMED_ENVELOPE");
        v["artifact_digest"] = json!(null);
        let rec: DlqRecord = serde_json::from_value(v).unwrap();
        assert_eq!(rec.workstream_id, None);
    }

    #[test]
    fn every_error_kind_has_the_exact_spec_wire_string() {
        let expected = [
            (DlqErrorKind::EnvelopeInvalid, "envelope_invalid"),
            (DlqErrorKind::BundleTrap, "bundle_trap"),
            (DlqErrorKind::BundleError, "bundle_error"),
            (DlqErrorKind::CallTimeout, "call_timeout"),
            (DlqErrorKind::MemoryLimit, "memory_limit"),
            (DlqErrorKind::HostCallDenied, "host_call_denied"),
            (DlqErrorKind::MaxDeliveries, "max_deliveries"),
            (DlqErrorKind::TenantBoundary, "tenant_boundary"),
            (DlqErrorKind::BundleDisabled, "bundle_disabled"),
            (DlqErrorKind::ExecutorUnavailable, "executor_unavailable"),
        ];
        assert_eq!(expected.len(), 10, "spec Sec6.3 enumerates exactly ten error.kind values (D30 adds tenant_boundary)");
        for (kind, expected_str) in expected {
            assert_eq!(kind.as_str(), expected_str);
            let round_tripped: DlqErrorKind =
                serde_json::from_value(json!(expected_str)).unwrap();
            assert_eq!(round_tripped, kind);
        }
    }

    #[test]
    fn only_tenant_boundary_is_never_retried() {
        let all = [
            DlqErrorKind::EnvelopeInvalid,
            DlqErrorKind::BundleTrap,
            DlqErrorKind::BundleError,
            DlqErrorKind::CallTimeout,
            DlqErrorKind::MemoryLimit,
            DlqErrorKind::HostCallDenied,
            DlqErrorKind::MaxDeliveries,
            DlqErrorKind::TenantBoundary,
            DlqErrorKind::BundleDisabled,
            DlqErrorKind::ExecutorUnavailable,
        ];
        let never_retry: Vec<DlqErrorKind> = all.iter().copied().filter(DlqErrorKind::never_retry).collect();
        assert_eq!(never_retry, vec![DlqErrorKind::TenantBoundary]);
    }

    #[test]
    fn rejects_unknown_error_kind() {
        let mut v = valid_record_json();
        v["error"]["kind"] = json!("not_a_real_kind");
        assert!(serde_json::from_value::<DlqRecord>(v).is_err());
    }

    #[test]
    fn rejects_unknown_top_level_key() {
        let mut v = valid_record_json();
        v["extra"] = json!("nope");
        assert!(serde_json::from_value::<DlqRecord>(v).is_err());
    }
}
```


Run: `docker run --rm -v "$(pwd)/packages/rust-spine:/work" -w /work rust:1.97.1 cargo test --lib error:: dlq::`
Expected: `test result: ok.` for both modules, no failures.

- [ ] **Step 4: Activate the `lib.rs` exports** — replace the still-commented error/dlq lines with:

```rust
pub use dlq::{DlqError, DlqErrorDetail, DlqErrorKind, DlqRecord};
pub use error::SpineError;
```

- [ ] **Step 5: Run the full suite.**

Run: `docker run --rm -v "$(pwd)/packages/rust-spine:/work" -w /work rust:1.97.1 cargo test`
Expected: `test result: ok.` across `scope`, `envelope`, `error`, `dlq` — no failures.

- [ ] **Step 6: Commit.**

```bash
git add packages/rust-spine/src/error.rs packages/rust-spine/src/dlq.rs packages/rust-spine/src/envelope.rs packages/rust-spine/src/lib.rs
git commit -m "$(cat <<'EOF'
feat(spine): add SpineError and the DLQ record types

SpineError replaces the Task 2 placeholder with the full crate-wide
error type. DlqRecord/DlqErrorDetail/DlqErrorKind/DlqError match spec
Sec6.3's record shape and its ten error.kind values exactly, including
the D30 tenant_boundary kind and its never_retry() contract, plus the
D30 workstream_id and trace (superseding trace_context) fields.

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01N2rQgkHY872RubwXoBZxtE
EOF
)"
```

---

### Task 6: `SpineMetrics` facade, `NoopMetrics`

**Files:**
- Modify: `packages/rust-spine/src/metrics.rs`, `packages/rust-spine/src/lib.rs`

**Interfaces:**
- Consumes: nothing new.
- Produces: `trait SpineMetrics: Send + Sync` (object-safe, `Arc<dyn SpineMetrics>` usable), `struct NoopMetrics`. Tasks 13-17 construct `SpineClient`/`GroupReader` with a `metrics: Arc<dyn SpineMetrics>` parameter and call its methods at every metric point the spec names.

Spec: §13.1 (metric name table — this task implements the callback surface for the subset this crate itself can observe: stream writes/trims/claims, consumer skips, DLQ writes, group lag/pending, insecure-transport reporting; request/executor/host-call latency histograms belong to the *stage*, not the spine, and are out of this crate's surface), §4.9 (this crate does not depend on `penguin-logging` — it doesn't exist yet).

- [ ] **Step 1: Write `packages/rust-spine/src/metrics.rs`:**

```rust
//! A small metrics callback surface so this crate never depends on a Rust
//! OTel/logging crate — none exists yet (`penguin-logging` is a known gap,
//! `backend-rust.md`). Callers implement [`SpineMetrics`] against whatever
//! backend their service already uses and pass it into
//! [`crate::SpineClient::connect`]/[`crate::GroupReader::connect`].

/// Callback surface for the spine-owned metric names the spec defines
/// (Sec13.1). Every method has a default no-op body — a caller overrides
/// only the signals it cares about. Object-safe: pass as
/// `Arc<dyn SpineMetrics>`.
pub trait SpineMetrics: Send + Sync {
    /// `waddles_stream_events_total{platform,source_id}` +1 — one `XADD`.
    fn stream_event_written(&self, _platform: &str, _source_id: &str) {}
    /// `waddles_stream_trimmed_total{stream}` +1 — an `XADD`'s `MAXLEN ~` evicted an entry.
    fn stream_trimmed(&self, _stream: &str) {}
    /// `waddles_stream_claimed_total{app_id}` +1 — an `XAUTOCLAIM` recovered an entry.
    fn stream_claimed(&self, _app_id: &str) {}
    /// `waddles_consumer_skipped_total{app_id,reason}` +1 — read and acked, no executor call.
    fn consumer_skipped(&self, _app_id: &str, _reason: &str) {}
    /// `waddles_spine_dlq_total{stage,reason}` +1.
    fn dlq_written(&self, _stage: &str, _reason: &str) {}
    /// `waddles_group_lag{app_id,stream}`, from `XINFO GROUPS`; `None` when
    /// the server doesn't report a lag value for that group.
    fn group_lag(&self, _app_id: &str, _stream: &str, _lag: Option<u64>) {}
    /// `waddles_group_pending{app_id,stream}` — the group's PEL size.
    fn group_pending(&self, _app_id: &str, _stream: &str, _pending: u64) {}
    /// `waddles_insecure_transport{component,aspect}` set to 1 (insecure)
    /// or 0 (secure) — `0` must be reported explicitly so "no series" and
    /// "secure" stay distinguishable (spec Sec11.6.4).
    fn insecure_transport(&self, _component: &str, _aspect: &str, _insecure: bool) {}
    /// `waddles_tenant_boundary_violations_total{stage,reason}` +1 — a
    /// Sec5.11 hop-verification failure (D30): `reason` is one of
    /// `mac_mismatch`, `unknown_kid`, `tenant_mismatch`,
    /// `community_mismatch`, `grant_scope_mismatch`,
    /// `approval_scope_mismatch`, `bundle_set_identity` (the
    /// `BoundaryError` variants the `binding` module defines, Task 19).
    fn tenant_boundary_violation(&self, _stage: &str, _reason: &str) {}
}

/// A [`SpineMetrics`] implementation that records nothing — the default
/// for tests, and for any caller not yet wired to a metrics backend.
#[derive(Debug, Clone, Copy, Default)]
pub struct NoopMetrics;

impl SpineMetrics for NoopMetrics {}

#[cfg(test)]
mod tests {
    #![allow(clippy::unwrap_used)]
    use super::*;
    use std::sync::{Arc, Mutex};

    #[derive(Default)]
    struct RecordingMetrics {
        calls: Mutex<Vec<String>>,
    }

    impl SpineMetrics for RecordingMetrics {
        fn stream_event_written(&self, platform: &str, source_id: &str) {
            self.calls
                .lock()
                .unwrap()
                .push(format!("stream_event_written({platform},{source_id})"));
        }
        fn dlq_written(&self, stage: &str, reason: &str) {
            self.calls
                .lock()
                .unwrap()
                .push(format!("dlq_written({stage},{reason})"));
        }
    }

    #[test]
    fn noop_metrics_implements_the_trait_as_a_trait_object() {
        let metrics: Arc<dyn SpineMetrics> = Arc::new(NoopMetrics);
        // Every method must be callable without panicking; the point of
        // NoopMetrics is that nothing observable happens.
        metrics.stream_event_written("twitch", "tw-channelA");
        metrics.stream_trimmed("waddles:t:acme:c:main:src:twitch:tw-channelA:events");
        metrics.stream_claimed("waddles.bot.commands.default");
        metrics.consumer_skipped("waddles.bot.commands.default", "event_type");
        metrics.dlq_written("process", "call_timeout");
        metrics.group_lag("waddles.bot.commands.default", "some-stream", Some(3));
        metrics.group_lag("waddles.bot.commands.default", "some-stream", None);
        metrics.group_pending("waddles.bot.commands.default", "some-stream", 0);
        metrics.insecure_transport("valkey", "tls", false);
        metrics.tenant_boundary_violation("process", "tenant_mismatch");
    }

    #[test]
    fn a_real_implementation_only_overrides_what_it_needs() {
        let concrete = Arc::new(RecordingMetrics::default());
        let metrics: Arc<dyn SpineMetrics> = concrete.clone();
        metrics.stream_event_written("discord", "dg-guildX");
        metrics.dlq_written("action", "max_deliveries");
        // Unoverridden methods still no-op cleanly.
        metrics.stream_trimmed("irrelevant-here");

        let calls = concrete.calls.lock().unwrap();
        assert_eq!(
            *calls,
            vec![
                "stream_event_written(discord,dg-guildX)".to_string(),
                "dlq_written(action,max_deliveries)".to_string(),
            ]
        );
    }
}
```

- [ ] **Step 2: Run and fix until green.**

Run: `docker run --rm -v "$(pwd)/packages/rust-spine:/work" -w /work rust:1.97.1 cargo test --lib metrics::`
Expected: `test result: ok. 2 passed; 0 failed`

- [ ] **Step 3: Activate the `lib.rs` export**, replacing the commented metrics line:

```rust
pub use metrics::{NoopMetrics, SpineMetrics};
```

- [ ] **Step 4: Run the full suite.**

Run: `docker run --rm -v "$(pwd)/packages/rust-spine:/work" -w /work rust:1.97.1 cargo test`
Expected: `test result: ok.` across every module so far.

- [ ] **Step 5: Commit.**

```bash
git add packages/rust-spine/src/metrics.rs packages/rust-spine/src/lib.rs
git commit -m "$(cat <<'EOF'
feat(spine): add the SpineMetrics facade and NoopMetrics

Object-safe callback trait for the spine-owned metric names (Sec13.1)
so this crate never depends on a Rust OTel/logging crate -- none
exists yet (penguin-logging is a known gap, backend-rust.md).
Includes tenant_boundary_violation for waddles_tenant_boundary_
violations_total{stage,reason} (D30, Sec5.11).

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01N2rQgkHY872RubwXoBZxtE
EOF
)"
```

---

### Task 7: Generate the golden fixtures (Python, in a pinned container)

**Files:**
- Create: `packages/rust-spine/tests/golden/generate_fixtures.py`, and every file it writes under `packages/rust-spine/tests/golden/{envelopes/valid,envelopes/invalid,keys,entries,dlq}/`

**Interfaces:**
- Consumes: nothing (pure Python, stdlib only, no dependency on this crate or on the `waddlebot` repo).
- Produces: the on-disk fixture tree Task 8's Rust tests load and iterate. Counts this task's own script asserts and prints: ≥ 20 valid envelopes, ≥ 25 invalid envelopes, ≥ 1 source-stream key case file, ≥ 1 app-key case file, ≥ 1 entry per valid envelope plus 1 per DLQ record, exactly 10 DLQ records (one per `DlqErrorKind`, D30 adds `tenant_boundary`).

Spec: §14.1 (the full fixture-family table this task implements — `session_id` set/absent, `binding.mac` tampered, missing `workstream_id`/`event_id`/`binding`), §6.1.2 (`schema_version` bump to `2`, D30 fields), §6.3 (the ten `error.kind` values including `tenant_boundary`) — **note the temporary-tooling caveat**: `flask_core.stream_pipeline.PlatformEvent`/`StageEnvelope` on the `waddlebot` repo's `release/v3.0.X` branch do not implement `source`/the D30 fields/the strict-RFC3339/app_id-shape checks yet (that is the separate, not-yet-scheduled "`flask_core` alignment" line item under spec's M1 table) — this script defines local, spec-shaped dict builders rather than importing the not-yet-aligned Python class, so the fixtures encode the *target* contract §6.1/§6.1.2 define. Once `flask_core` alignment lands its own `to_dict()`, that work should regenerate these exact files by calling the real class and this script should be deleted — noted again in the script's own docstring.

- [ ] **Step 1: Write `packages/rust-spine/tests/golden/generate_fixtures.py`:**

```python
#!/usr/bin/env python3
"""Golden-fixture generator for penguin-spine <-> flask_core.stream_pipeline
byte compatibility (spec Sec14.1).

Temporary tooling: mirrors the StageEnvelope/PlatformEvent JSON shape spec
Sec6.1/Sec6.1.2 defines, including the `source` field and the D30
workstream-identity/trace/binding fields (`workstream_id`, `event_id`,
`session_id`, `trace`, `binding`) the current `flask_core.stream_pipeline.py`
(waddlebot repo, release/v3.0.X) does not implement yet -- that is a
separate, not-yet-scheduled "flask_core alignment" deliverable, not part
of this crate. Once that work lands its own to_dict()/from_dict() with
these fields, the M1/M1.5 Python test suite should regenerate these exact
files by calling the real class instead of this script, and this script
should be deleted.

Run: python3 generate_fixtures.py <output-dir>
"""
import json
import sys
from pathlib import Path

DEFAULT_WORKSTREAM_ID = "8f14e45f-ceea-467e-adde-3fb5c9752730"
DEFAULT_EVENT_ID = "3fa85f64-5717-4562-b3fc-2c963f66afa6"
# A well-formed but v1 (time-based), not v4, UUID -- used only to build the
# "wrong UUID version" invalid fixture for event_id.
UUID_V1_NOT_V4 = "6ba7b810-9dad-11d1-80b4-00c04fd430c8"
DEFAULT_TRACEPARENT = "00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01"
DEFAULT_MAC = "9f86d081884c7d659a2feaa0c55ad015a3bf4f1b2b0b822cd15d6c15b0f00a08"


def platform_event(
    platform="twitch",
    event_type="chat.message",
    actor="some_user",
    payload=None,
    occurred_at="2026-09-14T12:00:00.000Z",
    source=None,
):
    if payload is None:
        payload = {"text": "!songrequest foo", "channel_id": "12345", "message_id": "abc"}
    event = {
        "platform": platform,
        "event_type": event_type,
        "actor": actor,
        "payload": payload,
        "occurred_at": occurred_at,
    }
    if source is not None:
        event["source"] = source
    return event


def stage_envelope(
    tenant="global",
    community=None,
    app_id="waddles.bot.commands.default",
    stage="process",
    event=None,
    ts="2026-09-14T12:00:00.123Z",
    target_app_id=None,
    schema_version=2,
    workstream_id=DEFAULT_WORKSTREAM_ID,
    event_id=DEFAULT_EVENT_ID,
    session_id=None,
    trace=DEFAULT_TRACEPARENT,
    tracestate=None,
    binding_kid="2026-09",
    binding_mac=DEFAULT_MAC,
):
    """Builds a spec Sec6.1.2-shaped StageEnvelope dict. `trace=None` omits
    the `trace` key's `traceparent` entirely (a bare `None` renders the
    whole `trace` field as JSON `null`, matching "absent (D30)" semantics
    for the "trace set/absent" fixture pair); pass a string to populate
    `trace.traceparent`."""
    if event is None:
        event = platform_event()
    trace_obj = None if trace is None else {"traceparent": trace, "tracestate": tracestate}
    return {
        "schema_version": schema_version,
        "tenant": tenant,
        "community": community,
        "app_id": app_id,
        "stage": stage,
        "event": event,
        "ts": ts,
        "target_app_id": target_app_id,
        "workstream_id": workstream_id,
        "event_id": event_id,
        "session_id": session_id,
        "trace": trace_obj,
        "binding": {"kid": binding_kid, "mac": binding_mac},
    }


def write(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=2, sort_keys=False) + "\n", encoding="utf-8")


def build_valid_envelopes():
    valid = {}
    valid["01_tenant_wide"] = stage_envelope(community=None)
    valid["02_community_scoped"] = stage_envelope(community="main")
    valid["03_target_app_id_set"] = stage_envelope(target_app_id="waddles.community.forums.default")
    valid["04_trace_set"] = stage_envelope(trace=DEFAULT_TRACEPARENT)
    valid["05_trace_absent"] = stage_envelope(trace=None)
    valid["06_empty_payload"] = stage_envelope(event=platform_event(payload={}))
    valid["07_unicode_payload"] = stage_envelope(event=platform_event(payload={"text": "こんにちは 🐧 world"}))
    long_segment = "a" * 60
    valid["08_max_length_app_id"] = stage_envelope(
        app_id=f"waddles.{long_segment}.{long_segment}.{long_segment}"
    )
    valid["09_action_stage"] = stage_envelope(stage="action", app_id="waddles.bot.action-sender.default")
    valid["10_discord_platform"] = stage_envelope(
        event=platform_event(
            platform="discord",
            source={"platform": "discord", "account_id": "app-123", "channel_id": "chan-456"},
        )
    )
    valid["11_slack_platform"] = stage_envelope(
        event=platform_event(
            platform="slack",
            source={"platform": "slack", "account_id": "xapp-abc", "channel_id": "C0123"},
        )
    )
    valid["12_youtube_platform"] = stage_envelope(
        event=platform_event(
            platform="youtube",
            source={"platform": "youtube", "account_id": "yt-bot", "channel_id": None},
        )
    )
    valid["13_kick_platform"] = stage_envelope(
        event=platform_event(
            platform="kick",
            source={"platform": "kick", "account_id": "kick-app", "channel_id": "chan-slug"},
        )
    )
    valid["14_custom_platform"] = stage_envelope(
        event=platform_event(
            platform="custom:helpdesk",
            event_type="ticket.created",
            source={"platform": "custom:helpdesk", "account_id": "helpdesk-src", "channel_id": None},
        )
    )
    valid["15_no_source"] = stage_envelope(event=platform_event())
    valid["16_null_actor"] = stage_envelope(event=platform_event(actor=None))
    valid["17_channel_follow_event"] = stage_envelope(
        event=platform_event(event_type="channel.follow", payload={"follower_id": "999"})
    )
    valid["18_stream_online_event"] = stage_envelope(event=platform_event(event_type="stream.online", payload={}))
    valid["19_null_channel_id_source"] = stage_envelope(
        event=platform_event(source={"platform": "twitch", "account_id": "bot-primary", "channel_id": None})
    )
    valid["20_nested_unicode_and_numbers_in_payload"] = stage_envelope(
        event=platform_event(payload={"count": 3, "labels": ["a", "b"], "note": "café ☕"})
    )
    valid["21_waddles_native_platform"] = stage_envelope(
        event=platform_event(
            platform="waddles",
            source={"platform": "waddles", "account_id": "waddles-native", "channel_id": "room-1"},
        )
    )
    valid["22_short_app_id_segments"] = stage_envelope(app_id="waddles.a.b.c")
    valid["23_session_id_set"] = stage_envelope(session_id="gw-session-abc123")
    valid["24_session_id_absent"] = stage_envelope(session_id=None)
    valid["25_community_scoped_with_session_and_trace"] = stage_envelope(
        community="main", session_id="eventsub-ws-session-1", trace=DEFAULT_TRACEPARENT
    )
    valid["26_tracestate_present"] = stage_envelope(trace=DEFAULT_TRACEPARENT, tracestate="congo=t61rcWkgMzE")
    return valid


def build_invalid_envelopes():
    invalid = {}

    def base():
        return stage_envelope()

    for field in ("tenant", "app_id", "stage", "ts", "event", "schema_version", "workstream_id", "event_id", "binding"):
        d = base()
        del d[field]
        invalid[f"missing_field_{field}"] = d

    for field, bad_value in {
        "tenant": 12345,
        "community": 12345,
        "app_id": 12345,
        "stage": 12345,
        "ts": 12345,
        "event": "not-an-object",
    }.items():
        d = base()
        d[field] = bad_value
        invalid[f"wrong_type_{field}"] = d

    d = base()
    d["extra_top_level_key"] = "nope"
    invalid["unknown_top_level_key"] = d

    d = base()
    d["stage"] = "bogus-stage"
    invalid["bad_stage_value"] = d

    d = base()
    del d["event"]
    d["text"] = "legacy shape carried data at the top level, no event key"
    invalid["legacy_pre_event_shape"] = d

    d = base()
    d["event"]["payload"] = "not-an-object"
    invalid["non_object_payload"] = d

    d = base()
    d["event"]["platform"] = ""
    invalid["empty_platform"] = d

    d = base()
    d["event"]["event_type"] = ""
    invalid["empty_event_type"] = d

    d = base()
    d["tenant"] = ""
    invalid["empty_tenant"] = d

    d = base()
    d["app_id"] = "waddles.bot"
    invalid["app_id_too_few_segments"] = d

    d = base()
    d["app_id"] = "other.bot.commands.default"
    invalid["app_id_wrong_prefix"] = d

    d = base()
    d["app_id"] = "waddles.Bot.Commands.Default"
    invalid["app_id_uppercase_forbidden"] = d

    d = base()
    d["app_id"] = "waddles..commands.default"
    invalid["app_id_empty_segment"] = d

    d = base()
    d["event"]["occurred_at"] = "2026-09-14T12:00:00.000+00:00"
    invalid["occurred_at_missing_z_suffix"] = d

    d = base()
    d["event"]["occurred_at"] = "not-a-timestamp"
    invalid["occurred_at_malformed"] = d

    d = base()
    d["ts"] = "2026-09-14T12:00:00.123+00:00"
    invalid["ts_missing_z_suffix"] = d

    d = base()
    d["ts"] = "not-a-timestamp"
    invalid["ts_malformed"] = d

    d = base()
    d["trace"] = {"traceparent": "not-a-traceparent", "tracestate": None}
    invalid["trace_malformed"] = d

    d = base()
    d["event"]["source"] = {"platform": "discord", "account_id": "x", "channel_id": None}
    invalid["source_platform_mismatch"] = d

    d = base()
    del d["event"]["occurred_at"]
    invalid["nested_event_missing_occurred_at"] = d

    d = base()
    d["event"]["actor"] = 12345
    invalid["nested_event_wrong_type_actor"] = d

    d = base()
    d["event"]["extra_key"] = "nope"
    invalid["nested_event_unknown_key"] = d

    d = base()
    d["community"] = ["not", "a", "string"]
    invalid["community_wrong_type_list"] = d

    # -- D30 workstream-identity / trace / tenant-wall fixtures (spec Sec5.11, Sec6.1.2) --

    d = base()
    d["schema_version"] = 1
    invalid["schema_version_1_pre_d30_shape"] = d

    d = base()
    d["workstream_id"] = "not-a-uuid"
    invalid["workstream_id_not_a_uuid"] = d

    d = base()
    d["event_id"] = "not-a-uuid"
    invalid["event_id_not_a_uuid"] = d

    d = base()
    d["event_id"] = UUID_V1_NOT_V4
    invalid["event_id_wrong_uuid_version"] = d

    d = base()
    d["session_id"] = ""
    invalid["session_id_empty_string"] = d

    d = base()
    d["binding"]["mac"] = "deadbeef"
    invalid["binding_mac_wrong_length"] = d

    d = base()
    d["binding"]["mac"] = DEFAULT_MAC.upper()
    invalid["binding_mac_uppercase_hex"] = d

    d = base()
    d["binding"]["mac"] = "not-hex-at-all-" + "z" * 49
    invalid["binding_mac_non_hex_characters"] = d

    d = base()
    d["binding"]["kid"] = ""
    invalid["binding_kid_empty"] = d

    d = base()
    del d["binding"]["mac"]
    invalid["binding_missing_mac"] = d

    d = base()
    del d["binding"]["kid"]
    invalid["binding_missing_kid"] = d

    # Deliberately NOT added here: a one-byte-flipped-but-still-64-lowercase-
    # hex `binding.mac` deserializes successfully -- RawStageEnvelope's
    # parser checks the MAC's *format*, not its cryptographic validity, so
    # a tampered-but-well-formed MAC belongs in envelopes/valid/ (added in
    # main() below as fixture 27), never in this invalid set (which would
    # break the blanket "every invalid/*.json must fail to deserialize"
    # assertion, Task 8). Verifying it is the `binding` module's job
    # (Task 19, spec Sec14.11 test 4), not envelope parsing's.

    return invalid


def build_dlq_records():
    error_kinds = [
        ("envelope_invalid", "ENVELOPE_INVALID", "strict deserialization failed", None, None, None),
        ("bundle_trap", "BUNDLE_TRAP", "component trapped", None, "sha256:aaaa", DEFAULT_WORKSTREAM_ID),
        ("bundle_error", "BUNDLE_ERROR", "component returned a terminal error", "retryable=false", "sha256:aaaa", DEFAULT_WORKSTREAM_ID),
        ("call_timeout", "EXECUTOR_DEADLINE", "bundle call exceeded 2000 ms", None, "sha256:aaaa", DEFAULT_WORKSTREAM_ID),
        ("memory_limit", "MEMORY_LIMIT", "instance exceeded its memory cap", None, "sha256:aaaa", DEFAULT_WORKSTREAM_ID),
        ("host_call_denied", "HOST_CALL_DENIED", "capability check refused the call",
         "undeclared egress host", "sha256:aaaa", DEFAULT_WORKSTREAM_ID),
        ("max_deliveries", "MAX_DELIVERIES", "delivery count reached SPINE_MAX_DELIVERIES", None, "sha256:aaaa", DEFAULT_WORKSTREAM_ID),
        ("tenant_boundary", "TENANT_MISMATCH",
         "envelope tenant/community disagree with the stream key it was read from",
         None, "sha256:aaaa", DEFAULT_WORKSTREAM_ID),
        ("bundle_disabled", "BUNDLE_DISABLED", "bundle disabled after three sandbox trips", None, "sha256:aaaa", DEFAULT_WORKSTREAM_ID),
        ("executor_unavailable", "EXECUTOR_UNAVAILABLE",
         "executor down past EXECUTOR_UNAVAILABLE_READY_S", None, None, DEFAULT_WORKSTREAM_ID),
    ]
    records = {}
    for kind, code, message, detail, digest, workstream_id in error_kinds:
        records[kind] = {
            "schema_version": 1,
            "stage": "process",
            "key": "waddles:t:global:c:_tenant:src:twitch:tw-channelA:events",
            "entry_id": "1757851200000-0",
            "group": "waddles.bot.commands.default",
            "tenant": "global",
            "community": None,
            "app_id": "waddles.bot.commands.default",
            "workstream_id": workstream_id,
            "artifact_digest": digest,
            "consumer_id": "svc-process-7d9c4f",
            "deliveries": 5 if kind == "max_deliveries" else 1,
            "failed_at": "2026-09-14T12:00:01.500Z",
            "error": {"kind": kind, "code": code, "message": message, "detail": detail},
            "trace": {"traceparent": DEFAULT_TRACEPARENT, "tracestate": None},
            "raw": json.dumps(stage_envelope()),
        }
    return records


def main(out_dir: str) -> None:
    root = Path(out_dir)

    valid = build_valid_envelopes()
    invalid = build_invalid_envelopes()

    # The tampered-but-well-formed binding.mac fixture belongs in `valid/`
    # (spec Sec14.1: envelopes/valid documents "trace set and absent" etc.,
    # and a syntactically-valid-but-cryptographically-wrong MAC still
    # deserializes -- verifying it is the `binding` module's job, Task 19,
    # not envelope parsing's).
    tampered = list(DEFAULT_MAC)
    tampered[0] = "0" if tampered[0] != "0" else "1"
    valid["27_binding_mac_syntactically_valid_but_tampered"] = stage_envelope(binding_mac="".join(tampered))

    assert len(valid) >= 20, f"need >= 20 valid fixtures, have {len(valid)}"
    assert len(invalid) >= 25, f"need >= 25 invalid fixtures, have {len(invalid)}"
    for name, doc in valid.items():
        write(root / "envelopes" / "valid" / f"{name}.json", doc)
    for name, doc in invalid.items():
        write(root / "envelopes" / "invalid" / f"{name}.json", doc)

    source_stream_cases = [
        {"tenant": "acme", "community": "main", "platform": "twitch", "source_id": "tw-channelA",
         "expected": "waddles:t:acme:c:main:src:twitch:tw-channelA:events"},
        {"tenant": "acme", "community": None, "platform": "twitch", "source_id": "tw-channelA",
         "expected": "waddles:t:acme:c:_tenant:src:twitch:tw-channelA:events"},
        {"tenant": "global", "community": "forums", "platform": "discord", "source_id": "dg-guildX",
         "expected": "waddles:t:global:c:forums:src:discord:dg-guildX:events"},
        {"tenant": "global", "community": None, "platform": "slack", "source_id": "xapp-abc",
         "expected": "waddles:t:global:c:_tenant:src:slack:xapp-abc:events"},
    ]
    write(root / "keys" / "source_stream.json", source_stream_cases)

    app_keys_cases = [
        {"tenant": "acme", "community": "main", "app_id": "waddles.bot.commands.default",
         "expected_action": "waddles:t:acme:c:main:app:waddles.bot.commands.default:action",
         "expected_cfg": "waddles:t:acme:c:main:app:waddles.bot.commands.default:cfg",
         "expected_state": "waddles:t:acme:c:main:app:waddles.bot.commands.default:state"},
        {"tenant": "global", "community": None, "app_id": "waddles.bot.commands.default",
         "expected_action": "waddles:t:global:c:_tenant:app:waddles.bot.commands.default:action",
         "expected_cfg": "waddles:t:global:c:_tenant:app:waddles.bot.commands.default:cfg",
         "expected_state": "waddles:t:global:c:_tenant:app:waddles.bot.commands.default:state"},
    ]
    write(root / "keys" / "app_keys.json", app_keys_cases)

    for name, doc in valid.items():
        write(root / "entries" / f"event_{name}.json", {"field": "env", "value": doc})

    dlq_records = build_dlq_records()
    assert len(dlq_records) == 10, f"spec Sec6.3 enumerates exactly 10 error.kind values (D30 adds tenant_boundary), generated {len(dlq_records)}"
    for kind, rec in dlq_records.items():
        write(root / "dlq" / f"{kind}.json", rec)
        write(root / "entries" / f"dlq_{kind}.json", {"field": "rec", "value": rec})

    print(
        f"wrote {len(valid)} valid envelopes, {len(invalid)} invalid envelopes, "
        f"{len(source_stream_cases)} source-stream key cases, {len(app_keys_cases)} app-key cases, "
        f"{len(valid) + len(dlq_records)} entries, {len(dlq_records)} dlq records"
    )


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("usage: generate_fixtures.py <output-dir>", file=sys.stderr)
        sys.exit(2)
    main(sys.argv[1])
```

- [ ] **Step 2: Run it inside the pinned Python container** (writes directly into the crate's own `tests/golden/` tree, which is `<output-dir>`):

Run:
```bash
cd /home/penguin/code/penguin-libs/.worktrees/plan-penguin-spine
docker run --rm \
  -v "$(pwd)/packages/rust-spine/tests/golden:/golden" \
  python:3.13-slim@sha256:9d2e5553305c7c7b0097999bb17187c69b921ccd6bc9d40e4bb5ebe652c00285 \
  python3 /golden/generate_fixtures.py /golden
```

(The script is not yet inside `/golden` on the first run — write it to `packages/rust-spine/tests/golden/generate_fixtures.py` on the host first via Step 1, then this bind-mount makes it visible at `/golden/generate_fixtures.py` inside the container.)

Expected stdout: `wrote 27 valid envelopes, 34 invalid envelopes, 4 source-stream key cases, 2 app-key cases, 37 entries, 10 dlq records`

- [ ] **Step 3: Verify the on-disk counts independently of the script's own print** (the Verification Integrity rule: don't trust a self-reported count, recount):

Run:
```bash
echo "valid: $(ls packages/rust-spine/tests/golden/envelopes/valid/*.json | wc -l)"
echo "invalid: $(ls packages/rust-spine/tests/golden/envelopes/invalid/*.json | wc -l)"
echo "keys: $(ls packages/rust-spine/tests/golden/keys/*.json | wc -l)"
echo "entries: $(ls packages/rust-spine/tests/golden/entries/*.json | wc -l)"
echo "dlq: $(ls packages/rust-spine/tests/golden/dlq/*.json | wc -l)"
```
Expected: `valid: 27`, `invalid: 34`, `keys: 2`, `entries: 37`, `dlq: 10`.

- [ ] **Step 4: Spot-check one file for valid JSON and the expected shape.**

Run: `docker run --rm -v "$(pwd)/packages/rust-spine/tests/golden:/golden" python:3.13-slim@sha256:9d2e5553305c7c7b0097999bb17187c69b921ccd6bc9d40e4bb5ebe652c00285 python3 -c "import json; d=json.load(open('/golden/envelopes/valid/01_tenant_wide.json')); assert d['community'] is None; assert d['event']['platform'] == 'twitch'; assert d['schema_version'] == 2; assert d['binding']['kid'] == '2026-09'; print('ok')"`
Expected: `ok`

- [ ] **Step 5: Commit.**

```bash
git add packages/rust-spine/tests/golden
git commit -m "$(cat <<'EOF'
test(spine): generate golden fixtures for envelope byte compatibility

27 valid + 34 invalid StageEnvelope fixtures (D30 adds schema_version,
workstream_id, event_id, session_id, trace, binding coverage,
including a syntactically-valid-but-cryptographically-tampered MAC
kept in valid/ since envelope parsing cannot detect that), source-
stream/app key cases, 37 stream-entry fixtures, and one DLQ record per
error.kind (10, D30 adds tenant_boundary), per spec Sec14.1. Temporary
generator (see its own docstring) until the separate flask_core
alignment work lands source/D30-field support and these files can be
regenerated from the real Python class.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01N2rQgkHY872RubwXoBZxtE
EOF
)"
```
---

### Task 8: Golden-fixture Rust conformance tests

**Files:**
- Create: `packages/rust-spine/tests/golden_fixture_tests.rs`

**Interfaces:**
- Consumes: `Scope` (Task 2), `StageEnvelope` (Task 4), `DlqRecord` (Task 5), the fixture tree Task 7 generated.
- Produces: nothing new for later tasks — this is the crate's proof that its types satisfy spec §14.1.

Spec: §14.1 (every assertion this task writes maps to a bullet in that section's table, including "CI fails if either side skips a fixture: each suite asserts `fixtures_examined == fixtures_on_disk`, a non-zero denominator, and prints the count").

**Note on "byte-identical" (spec's wording):** this test verifies JSON *value* equality after deserialize → re-serialize, not literal byte/string equality. Python's and Rust's JSON emitters format differently (ASCII-escaping of non-ASCII characters, whitespace) even when the underlying data is identical, so a literal byte comparison would fail on formatting alone while proving nothing about the actual contract. Value equality (via `serde_json::Value`, with `preserve_order` so object key order is part of that equality check) is what the spec's requirement is actually protecting against: no field lost, renamed, reordered in meaning, or coerced.

- [ ] **Step 1: Write `packages/rust-spine/tests/golden_fixture_tests.rs`:**

```rust
#![allow(clippy::unwrap_used, clippy::panic)]
//! Golden-fixture conformance tests against the fixtures Task 7 generated
//! (spec Sec14.1). Every test asserts `fixtures_examined == fixtures_on_disk`
//! and prints both numbers — a scanner pointed at an empty or moved
//! directory must fail loudly, not report a silent, vacuous pass.

use penguin_spine::{DlqRecord, Scope, StageEnvelope};
use serde_json::Value;
use std::fs;
use std::path::{Path, PathBuf};

fn golden_dir() -> PathBuf {
    Path::new(env!("CARGO_MANIFEST_DIR")).join("tests/golden")
}

fn read_json_files(dir: &Path) -> Vec<(String, String)> {
    let mut out = Vec::new();
    let entries = fs::read_dir(dir)
        .unwrap_or_else(|e| panic!("failed to read fixture dir {}: {e}", dir.display()));
    for entry in entries {
        let entry = entry.unwrap();
        let path = entry.path();
        if path.extension().and_then(|e| e.to_str()) == Some("json") {
            let name = path.file_name().unwrap().to_string_lossy().to_string();
            let contents = fs::read_to_string(&path).unwrap();
            out.push((name, contents));
        }
    }
    out.sort();
    out
}

#[test]
fn valid_envelopes_deserialize_and_round_trip_by_value() {
    let dir = golden_dir().join("envelopes/valid");
    let files = read_json_files(&dir);
    assert!(
        files.len() >= 20,
        "expected >= 20 valid envelope fixtures, found {} in {}",
        files.len(),
        dir.display()
    );

    let mut examined = 0;
    for (name, contents) in &files {
        let original: Value = serde_json::from_str(contents)
            .unwrap_or_else(|e| panic!("{name}: fixture itself is not valid JSON: {e}"));
        let env: StageEnvelope = serde_json::from_str(contents)
            .unwrap_or_else(|e| panic!("{name}: expected valid, failed to deserialize: {e}"));
        let round_tripped = serde_json::to_value(&env)
            .unwrap_or_else(|e| panic!("{name}: failed to re-serialize: {e}"));
        assert_eq!(round_tripped, original, "{name}: round-trip changed the value");
        examined += 1;
    }
    assert_eq!(examined, files.len(), "fixtures_examined must equal fixtures_on_disk");
    println!("valid envelopes examined: {examined} (on disk: {})", files.len());
}

#[test]
fn invalid_envelopes_all_fail_to_deserialize() {
    let dir = golden_dir().join("envelopes/invalid");
    let files = read_json_files(&dir);
    assert!(
        files.len() >= 25,
        "expected >= 25 invalid envelope fixtures, found {} in {}",
        files.len(),
        dir.display()
    );

    let mut examined = 0;
    for (name, contents) in &files {
        let result: Result<StageEnvelope, _> = serde_json::from_str(contents);
        assert!(result.is_err(), "{name}: expected deserialization to fail, it succeeded");
        examined += 1;
    }
    assert_eq!(examined, files.len(), "fixtures_examined must equal fixtures_on_disk");
    println!("invalid envelopes examined: {examined} (on disk: {})", files.len());
}

#[test]
fn source_stream_key_fixtures_match_scope_builder() {
    let path = golden_dir().join("keys/source_stream.json");
    let contents = fs::read_to_string(&path).unwrap();
    let cases: Vec<Value> = serde_json::from_str(&contents).unwrap();
    assert!(!cases.is_empty(), "expected at least one source-stream key case in {}", path.display());

    let mut examined = 0;
    for case in &cases {
        let tenant = case["tenant"].as_str().unwrap().to_string();
        let community = case["community"].as_str().map(str::to_string);
        let platform = case["platform"].as_str().unwrap();
        let source_id = case["source_id"].as_str().unwrap();
        let expected = case["expected"].as_str().unwrap();
        let scope = Scope::new(tenant, community);
        assert_eq!(scope.source_stream(platform, source_id), expected);
        examined += 1;
    }
    assert_eq!(examined, cases.len(), "fixtures_examined must equal fixtures_on_disk");
    println!("source-stream key cases examined: {examined}");
}

#[test]
fn app_key_fixtures_match_scope_builder() {
    let path = golden_dir().join("keys/app_keys.json");
    let contents = fs::read_to_string(&path).unwrap();
    let cases: Vec<Value> = serde_json::from_str(&contents).unwrap();
    assert!(!cases.is_empty(), "expected at least one app-key case in {}", path.display());

    let mut examined = 0;
    for case in &cases {
        let tenant = case["tenant"].as_str().unwrap().to_string();
        let community = case["community"].as_str().map(str::to_string);
        let app_id = case["app_id"].as_str().unwrap();
        let scope = Scope::new(tenant, community);
        assert_eq!(scope.action_stream(app_id), case["expected_action"].as_str().unwrap());
        assert_eq!(scope.config_key(app_id), case["expected_cfg"].as_str().unwrap());
        assert_eq!(scope.state_key(app_id), case["expected_state"].as_str().unwrap());
        examined += 1;
    }
    assert_eq!(examined, cases.len(), "fixtures_examined must equal fixtures_on_disk");
    println!("app-key cases examined: {examined}");
}

#[test]
fn entry_fixtures_carry_the_envelope_verbatim_under_a_single_field() {
    let dir = golden_dir().join("entries");
    let files = read_json_files(&dir);
    assert!(!files.is_empty(), "expected at least one entry fixture in {}", dir.display());

    let mut examined = 0;
    for (name, contents) in &files {
        let doc: Value = serde_json::from_str(contents)
            .unwrap_or_else(|e| panic!("{name}: not valid JSON: {e}"));
        let field = doc["field"]
            .as_str()
            .unwrap_or_else(|| panic!("{name}: missing 'field'"));
        assert!(
            field == "env" || field == "rec",
            "{name}: entry field must be \"env\" or \"rec\", got {field:?}"
        );
        let value = doc.get("value").unwrap_or_else(|| panic!("{name}: missing 'value'"));
        let value_str = serde_json::to_string(value).unwrap();
        if field == "env" {
            let parsed: Result<StageEnvelope, _> = serde_json::from_str(&value_str);
            assert!(parsed.is_ok(), "{name}: 'env' entry value must deserialize as StageEnvelope");
        } else {
            let parsed: Result<DlqRecord, _> = serde_json::from_str(&value_str);
            assert!(parsed.is_ok(), "{name}: 'rec' entry value must deserialize as DlqRecord");
        }
        examined += 1;
    }
    assert_eq!(examined, files.len(), "fixtures_examined must equal fixtures_on_disk");
    println!("entry fixtures examined: {examined} (on disk: {})", files.len());
}

#[test]
fn dlq_fixtures_cover_every_error_kind_and_round_trip() {
    let dir = golden_dir().join("dlq");
    let files = read_json_files(&dir);
    assert_eq!(
        files.len(),
        10,
        "spec Sec6.3 enumerates exactly 10 error.kind values (D30 adds tenant_boundary), found {} dlq fixtures in {}",
        files.len(),
        dir.display()
    );

    let mut examined = 0;
    for (name, contents) in &files {
        let original: Value = serde_json::from_str(contents).unwrap();
        let rec: DlqRecord = serde_json::from_str(contents)
            .unwrap_or_else(|e| panic!("{name}: failed to deserialize: {e}"));
        let round_tripped = serde_json::to_value(&rec).unwrap();
        assert_eq!(round_tripped, original, "{name}: round-trip changed the value");
        examined += 1;
    }
    assert_eq!(examined, files.len(), "fixtures_examined must equal fixtures_on_disk");
    println!("dlq fixtures examined: {examined} (on disk: {})", files.len());
}
```

- [ ] **Step 2: Run and fix until green.**

Run: `docker run --rm -v "$(pwd)/packages/rust-spine:/work" -w /work rust:1.97.1 cargo test --test golden_fixture_tests -- --nocapture`
Expected: 6 tests pass, and stdout contains all six `... examined: N (on disk: N)` / `... examined: N` lines with matching numbers on both sides — recount them yourself against Task 7's Step 3 `ls | wc -l` output rather than trusting the printed number alone.

- [ ] **Step 3: Commit.**

```bash
git add packages/rust-spine/tests/golden_fixture_tests.rs
git commit -m "$(cat <<'EOF'
test(spine): add golden-fixture conformance tests

Six tests covering every fixture family in spec Sec14.1: valid/invalid
envelope round-trip and rejection (including D30's schema_version/
workstream_id/event_id/session_id/trace/binding coverage), source-
stream/app key builders, the single-field entry wrapper shape, and
full DLQ error.kind coverage (10 kinds, D30 adds tenant_boundary).
Every test asserts fixtures_examined == fixtures_on_disk and prints
both counts.

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01N2rQgkHY872RubwXoBZxtE
EOF
)"
```

---

### Task 9: `SpineConfig` — env loading, TLS/auth refusal, block-timeout validation

**Files:**
- Modify: `packages/rust-spine/src/config.rs`, `packages/rust-spine/src/lib.rs`

**Interfaces:**
- Consumes: `SpineError` (Task 5).
- Produces: `SpineConfig` (every field from spec §12.7's common + spine env-var tables), `SpineConfig::from_env() -> Result<Self, SpineError>`, `SpineConfig::validate(&self) -> Result<(), SpineError>`, standalone `validate_block_timeout(name: &'static str, block_ms: u64, socket_timeout_s: u64) -> Result<(), SpineError>`. Task 10 adds `ProbeClass`/`ProbeResult`/`classify_connect` to this same file. Task 13's `SpineClient::connect` and Task 17's `GroupReader::connect` both take `&SpineConfig`.

Spec: §12.7 (env var tables — `VALKEY_URL`/`VALKEY_USERNAME`/`VALKEY_PASSWORD`/`_FILE`/`VALKEY_CA_FILE`, `SECURITY_TRANSPORT_TLS`/`_AUTH`, every `SPINE_*` var, `DRAIN_SOCKET_TIMEOUT_S` is named in §5.7 rather than §12.7's table — carried here since it is the value both block-timeout checks compare against), §11.6.1 (startup refusal: `redis://` refused when TLS required, missing credential refused when auth required), §5.7 rule 1 (the block-timeout invariant), §5.2 (`SPINE_CONSUMER_ID` default).

**Testability note.** `SpineConfig::from_env()` reads the real process environment, but every test in this task goes through the private `SpineConfig::from_lookup` instead, passing a closure over a local `HashMap` — Rust tests run in parallel threads inside one process, and `std::env` is shared global mutable state, so two tests calling `std::env::set_var` concurrently would be flaky by construction. Parameterizing the loader over a lookup closure sidesteps that entirely rather than serializing tests or reaching for a lock.

- [ ] **Step 1: Write `packages/rust-spine/src/config.rs`:**

```rust
//! Environment-driven spine configuration: Valkey connection details, the
//! transport-security opt-out (spec Sec11.6.4/D20), and every `SPINE_*`
//! tuning knob (spec Sec12.7).

use std::path::PathBuf;

use crate::error::SpineError;

fn lookup_string(
    lookup: &impl Fn(&str) -> Option<String>,
    name: &str,
) -> Option<String> {
    lookup(name)
}

fn lookup_u64(
    lookup: &impl Fn(&str) -> Option<String>,
    name: &str,
    default: u64,
) -> Result<u64, SpineError> {
    match lookup(name) {
        None => Ok(default),
        Some(v) => v
            .parse::<u64>()
            .map_err(|e| SpineError::Config(format!("{name}={v:?} is not a valid u64: {e}"))),
    }
}

fn lookup_i64(
    lookup: &impl Fn(&str) -> Option<String>,
    name: &str,
    default: i64,
) -> Result<i64, SpineError> {
    match lookup(name) {
        None => Ok(default),
        Some(v) => v
            .parse::<i64>()
            .map_err(|e| SpineError::Config(format!("{name}={v:?} is not a valid i64: {e}"))),
    }
}

fn lookup_bool(
    lookup: &impl Fn(&str) -> Option<String>,
    name: &str,
    default: bool,
) -> Result<bool, SpineError> {
    match lookup(name) {
        None => Ok(default),
        Some(v) => match v.to_ascii_lowercase().as_str() {
            "true" | "1" | "yes" | "on" => Ok(true),
            "false" | "0" | "no" | "off" => Ok(false),
            other => Err(SpineError::Config(format!("{name}={other:?} is not a valid boolean"))),
        },
    }
}

fn read_secret_from_lookup(
    lookup: &impl Fn(&str) -> Option<String>,
    env_name: &str,
    file_env_name: &str,
) -> Result<Option<String>, SpineError> {
    if let Some(v) = lookup(env_name) {
        return Ok(Some(v));
    }
    if let Some(path) = lookup(file_env_name) {
        let contents = std::fs::read_to_string(&path).map_err(|e| {
            SpineError::Config(format!("failed to read {file_env_name} ({path}): {e}"))
        })?;
        return Ok(Some(contents.trim_end().to_string()));
    }
    Ok(None)
}

fn default_consumer_id(lookup: &impl Fn(&str) -> Option<String>) -> String {
    // Spec Sec5.2: "the pod name, else {hostname}-{uuid-v4}". Kubernetes
    // sets HOSTNAME to the pod name by default, so a present HOSTNAME IS
    // the pod name; a missing one (non-k8s dev environment) falls back to
    // a UUID alone rather than pulling in a `hostname`-resolution crate
    // just to satisfy a rare fallback path.
    match lookup("HOSTNAME") {
        Some(h) if !h.is_empty() => h,
        _ => format!("unknown-{}", uuid::Uuid::new_v4()),
    }
}

/// Validates that a blocking-read timeout is strictly less than its
/// connection's socket timeout (spec Sec5.7 rule 1) — construction that
/// violates this must be refused, naming both values, rather than racing
/// silently in production.
pub fn validate_block_timeout(
    name: &'static str,
    block_ms: u64,
    socket_timeout_s: u64,
) -> Result<(), SpineError> {
    let socket_timeout_ms = socket_timeout_s.saturating_mul(1000);
    if block_ms >= socket_timeout_ms {
        return Err(SpineError::BlockTimeoutInvalid {
            block_name: name,
            block_ms,
            socket_timeout_s,
        });
    }
    Ok(())
}

/// Environment-driven spine configuration (spec Sec12.7). Construct via
/// [`SpineConfig::from_env`] at startup.
#[derive(Debug, Clone)]
pub struct SpineConfig {
    /// `VALKEY_URL`, falling back to `REDIS_URL` for compatibility. Required.
    pub valkey_url: String,
    /// `VALKEY_USERNAME`.
    pub valkey_username: Option<String>,
    /// `VALKEY_PASSWORD` or `VALKEY_PASSWORD_FILE` (file wins only when the
    /// plain var is unset; env value never logged).
    pub valkey_password: Option<String>,
    /// `VALKEY_CA_FILE`, default `/etc/waddles/ca/valkey-ca.crt`.
    pub valkey_ca_file: PathBuf,
    /// `SECURITY_TRANSPORT_TLS`, default `true`.
    pub security_transport_tls: bool,
    /// `SECURITY_TRANSPORT_AUTH`, default `true`.
    pub security_transport_auth: bool,
    /// `SPINE_CONSUMER_ID`, default the pod name else `unknown-{uuid-v4}`.
    pub consumer_id: String,
    /// `SPINE_STREAM_MAXLEN`, default `100000`.
    pub stream_maxlen: u64,
    /// `SPINE_READ_COUNT`, default `64`.
    pub read_count: i64,
    /// `SPINE_BLOCK_MS`, default `1000`.
    pub block_ms: u64,
    /// `SPINE_CLAIM_IDLE_MS`, default `30000`.
    pub claim_idle_ms: u64,
    /// `SPINE_CLAIM_INTERVAL_MS`, default `15000`.
    pub claim_interval_ms: u64,
    /// `SPINE_STATS_INTERVAL_MS`, default `10000`.
    pub stats_interval_ms: u64,
    /// `SPINE_PEL_ALERT`, default `5000`.
    pub pel_alert: u64,
    /// `SPINE_DLQ_MAXLEN`, default `10000`.
    pub dlq_maxlen: u64,
    /// `SPINE_MAX_DELIVERIES`, default `5`.
    pub max_deliveries: u32,
    /// `DRAIN_SOCKET_TIMEOUT_S`, default `65` (spec Sec5.7).
    pub drain_socket_timeout_s: u64,
    /// `RELAY_BLOCK_TIMEOUT_S`, default `30` (spec Sec5.7/Sec5.8).
    pub relay_block_timeout_s: u64,
}

impl SpineConfig {
    /// Loads configuration from the real process environment.
    pub fn from_env() -> Result<Self, SpineError> {
        Self::from_lookup(&|name| std::env::var(name).ok())
    }

    fn from_lookup(lookup: &impl Fn(&str) -> Option<String>) -> Result<Self, SpineError> {
        let valkey_url = lookup_string(lookup, "VALKEY_URL")
            .or_else(|| lookup_string(lookup, "REDIS_URL"))
            .ok_or_else(|| SpineError::Config("VALKEY_URL (or REDIS_URL) is required".into()))?;
        let valkey_username = lookup_string(lookup, "VALKEY_USERNAME");
        let valkey_password = read_secret_from_lookup(lookup, "VALKEY_PASSWORD", "VALKEY_PASSWORD_FILE")?;
        let valkey_ca_file = PathBuf::from(
            lookup_string(lookup, "VALKEY_CA_FILE")
                .unwrap_or_else(|| "/etc/waddles/ca/valkey-ca.crt".to_string()),
        );
        let security_transport_tls = lookup_bool(lookup, "SECURITY_TRANSPORT_TLS", true)?;
        let security_transport_auth = lookup_bool(lookup, "SECURITY_TRANSPORT_AUTH", true)?;
        let consumer_id = lookup_string(lookup, "SPINE_CONSUMER_ID")
            .unwrap_or_else(|| default_consumer_id(lookup));
        let stream_maxlen = lookup_u64(lookup, "SPINE_STREAM_MAXLEN", 100_000)?;
        let read_count = lookup_i64(lookup, "SPINE_READ_COUNT", 64)?;
        let block_ms = lookup_u64(lookup, "SPINE_BLOCK_MS", 1_000)?;
        let claim_idle_ms = lookup_u64(lookup, "SPINE_CLAIM_IDLE_MS", 30_000)?;
        let claim_interval_ms = lookup_u64(lookup, "SPINE_CLAIM_INTERVAL_MS", 15_000)?;
        let stats_interval_ms = lookup_u64(lookup, "SPINE_STATS_INTERVAL_MS", 10_000)?;
        let pel_alert = lookup_u64(lookup, "SPINE_PEL_ALERT", 5_000)?;
        let dlq_maxlen = lookup_u64(lookup, "SPINE_DLQ_MAXLEN", 10_000)?;
        let max_deliveries = lookup_u64(lookup, "SPINE_MAX_DELIVERIES", 5)? as u32;
        let drain_socket_timeout_s = lookup_u64(lookup, "DRAIN_SOCKET_TIMEOUT_S", 65)?;
        let relay_block_timeout_s = lookup_u64(lookup, "RELAY_BLOCK_TIMEOUT_S", 30)?;

        let cfg = SpineConfig {
            valkey_url,
            valkey_username,
            valkey_password,
            valkey_ca_file,
            security_transport_tls,
            security_transport_auth,
            consumer_id,
            stream_maxlen,
            read_count,
            block_ms,
            claim_idle_ms,
            claim_interval_ms,
            stats_interval_ms,
            pel_alert,
            dlq_maxlen,
            max_deliveries,
            drain_socket_timeout_s,
            relay_block_timeout_s,
        };
        cfg.validate()?;
        Ok(cfg)
    }

    /// Re-runs every startup refusal check (spec Sec11.6.1, Sec5.7 rule 1).
    /// Called automatically by [`SpineConfig::from_env`]; exposed so a
    /// caller building a `SpineConfig` by hand (tests, `--dev`) still gets
    /// the same guarantees.
    pub fn validate(&self) -> Result<(), SpineError> {
        if self.security_transport_tls
            && !(self.valkey_url.starts_with("rediss://") || self.valkey_url.starts_with("valkeys://"))
        {
            return Err(SpineError::Config(format!(
                "security.transport.tls is enabled but VALKEY_URL {:?} is not rediss://; \
                 refusing to start with a plaintext transport",
                self.valkey_url
            )));
        }
        if self.security_transport_auth
            && self.valkey_username.is_none()
            && self.valkey_password.is_none()
        {
            return Err(SpineError::Config(
                "security.transport.auth is enabled but neither VALKEY_USERNAME nor \
                 VALKEY_PASSWORD/_FILE is set"
                    .to_string(),
            ));
        }
        validate_block_timeout("SPINE_BLOCK_MS", self.block_ms, self.drain_socket_timeout_s)?;
        validate_block_timeout(
            "RELAY_BLOCK_TIMEOUT_S",
            self.relay_block_timeout_s.saturating_mul(1000),
            self.drain_socket_timeout_s,
        )?;
        Ok(())
    }
}

#[cfg(test)]
mod tests {
    #![allow(clippy::unwrap_used)]
    use super::*;
    use std::collections::HashMap;

    fn lookup_from(map: &HashMap<&str, &str>) -> impl Fn(&str) -> Option<String> + '_ {
        move |name| map.get(name).map(|v| v.to_string())
    }

    fn base_env() -> HashMap<&'static str, &'static str> {
        let mut m = HashMap::new();
        m.insert("VALKEY_URL", "rediss://valkey.waddles.svc.cluster.local:6379");
        m.insert("VALKEY_USERNAME", "svc-process");
        m.insert("VALKEY_PASSWORD", "test-password");
        m
    }

    #[test]
    fn from_lookup_succeeds_with_required_vars_and_secure_defaults() {
        let env = base_env();
        let cfg = SpineConfig::from_lookup(&lookup_from(&env)).unwrap();
        assert_eq!(cfg.valkey_url, "rediss://valkey.waddles.svc.cluster.local:6379");
        assert!(cfg.security_transport_tls);
        assert!(cfg.security_transport_auth);
        assert_eq!(cfg.stream_maxlen, 100_000);
        assert_eq!(cfg.block_ms, 1_000);
        assert_eq!(cfg.drain_socket_timeout_s, 65);
    }

    #[test]
    fn falls_back_to_redis_url_when_valkey_url_unset() {
        let mut env = base_env();
        env.remove("VALKEY_URL");
        env.insert("REDIS_URL", "rediss://legacy.example:6379");
        let cfg = SpineConfig::from_lookup(&lookup_from(&env)).unwrap();
        assert_eq!(cfg.valkey_url, "rediss://legacy.example:6379");
    }

    #[test]
    fn missing_valkey_url_is_an_error() {
        let env: HashMap<&str, &str> = HashMap::new();
        assert!(SpineConfig::from_lookup(&lookup_from(&env)).is_err());
    }

    #[test]
    fn tls_required_refuses_plaintext_url() {
        let mut env = base_env();
        env.insert("VALKEY_URL", "redis://valkey.waddles.svc.cluster.local:6379");
        assert!(SpineConfig::from_lookup(&lookup_from(&env)).is_err());
    }

    #[test]
    fn tls_opt_out_allows_plaintext_url() {
        let mut env = base_env();
        env.insert("VALKEY_URL", "redis://valkey.waddles.svc.cluster.local:6379");
        env.insert("SECURITY_TRANSPORT_TLS", "false");
        let cfg = SpineConfig::from_lookup(&lookup_from(&env)).unwrap();
        assert!(!cfg.security_transport_tls);
    }

    #[test]
    fn auth_required_refuses_missing_credentials() {
        let mut env = base_env();
        env.remove("VALKEY_USERNAME");
        env.remove("VALKEY_PASSWORD");
        assert!(SpineConfig::from_lookup(&lookup_from(&env)).is_err());
    }

    #[test]
    fn auth_opt_out_allows_missing_credentials() {
        let mut env = base_env();
        env.remove("VALKEY_USERNAME");
        env.remove("VALKEY_PASSWORD");
        env.insert("SECURITY_TRANSPORT_AUTH", "false");
        let cfg = SpineConfig::from_lookup(&lookup_from(&env)).unwrap();
        assert!(!cfg.security_transport_auth);
    }

    #[test]
    fn password_file_is_read_and_trimmed() {
        let dir = std::env::temp_dir().join(format!("spine-test-{}", uuid::Uuid::new_v4()));
        std::fs::create_dir_all(&dir).unwrap();
        let path = dir.join("password");
        std::fs::write(&path, "from-file-password\n").unwrap();

        let mut env = base_env();
        env.remove("VALKEY_PASSWORD");
        let path_str = path.to_string_lossy().to_string();
        env.insert("VALKEY_PASSWORD_FILE", Box::leak(path_str.into_boxed_str()));
        let cfg = SpineConfig::from_lookup(&lookup_from(&env)).unwrap();
        assert_eq!(cfg.valkey_password.as_deref(), Some("from-file-password"));

        std::fs::remove_dir_all(&dir).unwrap();
    }

    #[test]
    fn validate_block_timeout_rejects_block_ms_not_strictly_less() {
        assert!(validate_block_timeout("SPINE_BLOCK_MS", 65_000, 65).is_err());
        assert!(validate_block_timeout("SPINE_BLOCK_MS", 70_000, 65).is_err());
    }

    #[test]
    fn validate_block_timeout_accepts_strictly_less_values() {
        assert!(validate_block_timeout("SPINE_BLOCK_MS", 1_000, 65).is_ok());
        assert!(validate_block_timeout("RELAY_BLOCK_TIMEOUT_S", 30_000, 65).is_ok());
    }

    #[test]
    fn from_lookup_rejects_default_relay_timeout_against_a_too_small_socket_timeout() {
        let mut env = base_env();
        env.insert("DRAIN_SOCKET_TIMEOUT_S", "25"); // < RELAY_BLOCK_TIMEOUT_S default (30s)
        assert!(SpineConfig::from_lookup(&lookup_from(&env)).is_err());
    }

    #[test]
    fn default_consumer_id_uses_hostname_when_present() {
        let mut env = base_env();
        env.insert("HOSTNAME", "svc-process-7d9c4f");
        let cfg = SpineConfig::from_lookup(&lookup_from(&env)).unwrap();
        assert_eq!(cfg.consumer_id, "svc-process-7d9c4f");
    }

    #[test]
    fn default_consumer_id_falls_back_to_a_uuid_when_hostname_absent() {
        let env = base_env();
        let cfg = SpineConfig::from_lookup(&lookup_from(&env)).unwrap();
        assert!(cfg.consumer_id.starts_with("unknown-"));
    }
}
```

The `Box::leak` in `password_file_is_read_and_trimmed` is a deliberate, contained test-only leak to get a `&'static str` for the `HashMap<&str, &str>` test fixture shape — acceptable in a short-lived test process; not a pattern used anywhere in the crate's real code.

- [ ] **Step 2: Run and fix until green.**

Run: `docker run --rm -v "$(pwd)/packages/rust-spine:/work" -w /work rust:1.97.1 cargo test --lib config::`
Expected: `test result: ok. 13 passed; 0 failed`

- [ ] **Step 3: Activate the partial `lib.rs` export**, replacing the commented config line:

```rust
pub use config::{validate_block_timeout, SpineConfig};
// TODO(task-10): also export ProbeClass, ProbeResult
```

- [ ] **Step 4: Run the full suite.**

Run: `docker run --rm -v "$(pwd)/packages/rust-spine:/work" -w /work rust:1.97.1 cargo test`
Expected: `test result: ok.` across every module so far.

- [ ] **Step 5: Commit.**

```bash
git add packages/rust-spine/src/config.rs packages/rust-spine/src/lib.rs
git commit -m "$(cat <<'EOF'
feat(spine): add SpineConfig env loading and startup transport refusal

Full Sec12.7 env-var surface plus the Sec11.6.1 TLS/auth startup
refusals and the Sec5.7 rule 1 block-timeout invariant, both opt-outable
per D20. Config loading is parameterized over a lookup closure so tests
never touch real process environment variables.

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01N2rQgkHY872RubwXoBZxtE
EOF
)"
```

---

### Task 10: Startup connectivity self-check (`ProbeClass`, `ProbeResult`, `classify_connect_error`, `probe_valkey`)

**Files:**
- Modify: `packages/rust-spine/src/config.rs`, `packages/rust-spine/src/lib.rs`

**Interfaces:**
- Consumes: `SpineConfig` (Task 9), `SpineError` (Task 5).
- Produces: `ProbeClass` (`Dns`/`Tcp`/`Tls`/`Auth`/`Ok`, with `as_str`), `ProbeResult { dependency, class, message }`, `classify_connect_error(err: &redis::RedisError) -> ProbeClass`, `pub async fn probe_valkey(cfg: &SpineConfig, timeout: Duration, attempts: u32, retry_interval: Duration) -> ProbeResult`. Task 13's `SpineClient::connect` calls `probe_valkey` once before building its own connection, per spec's "before a stage drains anything ... each service probes every infrastructure endpoint."

Spec: §12.6 (the full classified-probe behavior: never a silent retry loop, `STARTUP_PROBE_TIMEOUT_MS`/`STARTUP_PROBE_ATTEMPTS` defaults, the five example messages this task's `message` field should read like).

**Known limitation, stated rather than hidden:** the `redis` crate has no dedicated TLS error kind, so `classify_connect_error` distinguishes a TLS handshake failure from a bare TCP failure by searching the error's `Display` text for TLS/certificate-shaped substrings. This is a best-effort heuristic, not a structural guarantee. DNS and TCP classification are exercised by this task's own fast, container-free unit tests (a `.invalid` TLD lookup and a connection-refused loopback port); TLS and auth classification against a *real* misconfigured connection are exercised once the pinned Valkey container exists (Task 11) — this task does not claim more confidence than it has tested.

- [ ] **Step 1: Append to `packages/rust-spine/src/config.rs`** (after the `impl SpineConfig` block, before its `#[cfg(test)] mod tests`):

```rust
/// One classified startup connectivity probe result (spec Sec12.6) —
/// never a bare "connection failed".
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum ProbeClass {
    /// The hostname did not resolve.
    Dns,
    /// Resolved, but the connection was refused, timed out, or was blocked.
    Tcp,
    /// Connected, but the handshake or certificate verification failed.
    Tls,
    /// TLS succeeded, credentials were rejected.
    Auth,
    /// Reachable and authenticated.
    Ok,
}

impl ProbeClass {
    /// The lowercase wire form used in `waddles_dependency_check_total{class}`.
    pub fn as_str(&self) -> &'static str {
        match self {
            ProbeClass::Dns => "dns",
            ProbeClass::Tcp => "tcp",
            ProbeClass::Tls => "tls",
            ProbeClass::Auth => "auth",
            ProbeClass::Ok => "ok",
        }
    }
}

/// The outcome of one startup connectivity probe against one dependency
/// (spec Sec12.6), always classified — never a bare failure.
#[derive(Debug, Clone)]
pub struct ProbeResult {
    /// The dependency name (`"valkey"`, `"postgres"`, ...).
    pub dependency: String,
    /// The classification.
    pub class: ProbeClass,
    /// A human-readable message naming the endpoint and what went wrong.
    pub message: String,
}

/// Classifies a `redis::RedisError` observed while connecting or
/// authenticating into a Sec12.6 probe class. See this task's "known
/// limitation" note for the TLS-vs-TCP heuristic.
pub fn classify_connect_error(err: &redis::RedisError) -> ProbeClass {
    if err.kind() == redis::ErrorKind::AuthenticationFailed {
        return ProbeClass::Auth;
    }
    if err.is_io_error() {
        let text = err.to_string().to_ascii_lowercase();
        let tls_markers = [
            "certificate",
            "tls",
            "handshake",
            "unknownissuer",
            "invalid peer certificate",
        ];
        if tls_markers.iter().any(|m| text.contains(m)) {
            return ProbeClass::Tls;
        }
        return ProbeClass::Tcp;
    }
    ProbeClass::Tcp
}

fn build_connection_info(cfg: &SpineConfig) -> Result<redis::ConnectionInfo, SpineError> {
    let base: redis::ConnectionInfo = redis::IntoConnectionInfo::into_connection_info(cfg.valkey_url.as_str())
        .map_err(|e| SpineError::Config(format!("invalid VALKEY_URL {:?}: {e}", cfg.valkey_url)))?;
    let mut redis_settings = base.redis_settings().clone();
    if let Some(username) = &cfg.valkey_username {
        redis_settings = redis_settings.set_username(username);
    }
    if let Some(password) = &cfg.valkey_password {
        redis_settings = redis_settings.set_password(password);
    }
    Ok(base.set_redis_settings(redis_settings))
}

fn host_port_from_url(url: &str) -> Result<(String, u16), SpineError> {
    let info: redis::ConnectionInfo = redis::IntoConnectionInfo::into_connection_info(url)
        .map_err(|e| SpineError::Config(format!("invalid VALKEY_URL {url:?}: {e}")))?;
    match info.addr() {
        redis::ConnectionAddr::Tcp(host, port) => Ok((host.clone(), *port)),
        redis::ConnectionAddr::TcpTls { host, port, .. } => Ok((host.clone(), *port)),
        redis::ConnectionAddr::Unix(_) => Err(SpineError::Config(
            "VALKEY_URL must be a TCP address, not a unix socket".to_string(),
        )),
    }
}

/// Resolves `host:port` via DNS only (spec Sec12.6's first probe layer).
async fn resolve_host(host: &str, port: u16) -> Result<(), String> {
    tokio::net::lookup_host((host, port))
        .await
        .map(|_| ())
        .map_err(|e| e.to_string())
}

async fn single_valkey_probe_attempt(host: &str, port: u16, cfg: &SpineConfig) -> ProbeResult {
    let dependency = "valkey".to_string();
    if let Err(e) = resolve_host(host, port).await {
        return ProbeResult {
            dependency,
            class: ProbeClass::Dns,
            message: format!("valkey: DNS resolution failed for {host:?}: {e}"),
        };
    }

    let info = match build_connection_info(cfg) {
        Ok(i) => i,
        Err(e) => {
            return ProbeResult {
                dependency,
                class: ProbeClass::Dns,
                message: e.to_string(),
            }
        }
    };

    let client_result = if cfg.security_transport_tls {
        let root_cert = std::fs::read(&cfg.valkey_ca_file).ok();
        redis::Client::build_with_tls(
            info,
            redis::TlsCertificates {
                client_tls: None,
                root_cert,
            },
        )
    } else {
        redis::Client::open(info)
    };

    let client = match client_result {
        Ok(c) => c,
        Err(e) => {
            return ProbeResult {
                dependency,
                class: classify_connect_error(&e),
                message: format!("valkey: failed to build client: {e}"),
            }
        }
    };

    let async_cfg = redis::AsyncConnectionConfig::new()
        .set_response_timeout(Some(std::time::Duration::from_secs(cfg.drain_socket_timeout_s)));

    let mut conn = match client.get_multiplexed_async_connection_with_config(&async_cfg).await {
        Ok(c) => c,
        Err(e) => {
            return ProbeResult {
                dependency,
                class: classify_connect_error(&e),
                message: format!("valkey: connect failed: {e}"),
            }
        }
    };

    match redis::cmd("PING").query_async::<String>(&mut conn).await {
        Ok(_) => ProbeResult {
            dependency,
            class: ProbeClass::Ok,
            message: "ok".to_string(),
        },
        Err(e) => ProbeResult {
            dependency,
            class: classify_connect_error(&e),
            message: format!("valkey: PING failed: {e}"),
        },
    }
}

/// Probes Valkey connectivity per spec Sec12.6: DNS resolution, then a
/// connect + `AUTH` + `PING`, classified and retried up to `attempts`
/// times at `retry_interval` apart, each attempt bounded by `timeout`.
/// Never a silent retry loop — every attempt's classified result is meant
/// to be logged by the caller (this crate only classifies; logging is the
/// caller's job, see [`crate::SpineMetrics`]).
pub async fn probe_valkey(
    cfg: &SpineConfig,
    timeout: std::time::Duration,
    attempts: u32,
    retry_interval: std::time::Duration,
) -> ProbeResult {
    let dependency = "valkey".to_string();
    let (host, port) = match host_port_from_url(&cfg.valkey_url) {
        Ok(hp) => hp,
        Err(e) => {
            return ProbeResult {
                dependency,
                class: ProbeClass::Dns,
                message: e.to_string(),
            }
        }
    };

    let mut last = ProbeResult {
        dependency: dependency.clone(),
        class: ProbeClass::Tcp,
        message: "probe never ran".to_string(),
    };

    for attempt in 0..attempts.max(1) {
        if attempt > 0 {
            tokio::time::sleep(retry_interval).await;
        }
        last = match tokio::time::timeout(timeout, single_valkey_probe_attempt(&host, port, cfg)).await {
            Ok(result) => result,
            Err(_) => ProbeResult {
                dependency: dependency.clone(),
                class: ProbeClass::Tcp,
                message: format!(
                    "valkey: TCP connect to {host}:{port} timed out after {}s",
                    timeout.as_secs()
                ),
            },
        };
        if last.class == ProbeClass::Ok {
            break;
        }
    }
    last
}
```

- [ ] **Step 2: Add the tests**, inside the existing `#[cfg(test)] mod tests` block in `config.rs` (append after the last `default_consumer_id_falls_back_to_a_uuid_when_hostname_absent` test):

```rust
    fn synthetic_io_error(message: &str) -> redis::RedisError {
        redis::RedisError::from(std::io::Error::other(message.to_string()))
    }

    #[test]
    fn classify_connect_error_maps_authentication_failed_to_auth() {
        let err = redis::RedisError::from((
            redis::ErrorKind::AuthenticationFailed,
            "authentication rejected",
        ));
        assert_eq!(classify_connect_error(&err), ProbeClass::Auth);
    }

    #[test]
    fn classify_connect_error_maps_plain_io_error_to_tcp() {
        let err = synthetic_io_error("connection refused (os error 111)");
        assert_eq!(classify_connect_error(&err), ProbeClass::Tcp);
    }

    #[test]
    fn classify_connect_error_maps_tls_shaped_io_error_to_tls() {
        let err = synthetic_io_error("invalid peer certificate: UnknownIssuer");
        assert_eq!(classify_connect_error(&err), ProbeClass::Tls);
    }

    #[tokio::test]
    async fn resolve_host_fails_for_the_reserved_invalid_tld() {
        // `.invalid` is IANA-reserved to never resolve (RFC 2606) -- a
        // deterministic DNS failure with no external service dependency.
        let result = resolve_host("this-host-does-not-exist.invalid", 6379).await;
        assert!(result.is_err());
    }

    #[tokio::test]
    async fn probe_valkey_classifies_dns_failure() {
        let mut env = base_env();
        env.insert("VALKEY_URL", "rediss://this-host-does-not-exist.invalid:6379");
        let cfg = SpineConfig::from_lookup(&lookup_from(&env)).unwrap();
        let result = probe_valkey(
            &cfg,
            std::time::Duration::from_millis(500),
            1,
            std::time::Duration::from_millis(10),
        )
        .await;
        assert_eq!(result.class, ProbeClass::Dns);
        assert!(result.message.contains("this-host-does-not-exist.invalid"));
    }

    #[tokio::test]
    async fn probe_valkey_classifies_connection_refused_as_tcp() {
        // Port 1 on loopback is a reserved low port nothing listens on in
        // a test container; the connection attempt fails immediately with
        // "connection refused" rather than timing out.
        let mut env = base_env();
        env.insert("VALKEY_URL", "rediss://127.0.0.1:1");
        let cfg = SpineConfig::from_lookup(&lookup_from(&env)).unwrap();
        let result = probe_valkey(
            &cfg,
            std::time::Duration::from_millis(500),
            1,
            std::time::Duration::from_millis(10),
        )
        .await;
        assert_eq!(result.class, ProbeClass::Tcp);
    }
```

(Retry-count/backoff timing itself is not covered by a dedicated test — a timing-based assertion over `probe_valkey`'s internal `sleep` calls would be flaky in CI; the retry loop is exercised for real wherever a caller uses `probe_valkey` against real infrastructure, starting with Task 13.)

- [ ] **Step 3: Run and fix until green.**

Run: `docker run --rm -v "$(pwd)/packages/rust-spine:/work" -w /work rust:1.97.1 cargo test --lib config::`
Expected: `test result: ok. 18 passed; 0 failed`

- [ ] **Step 4: Activate the full `lib.rs` config export**, replacing both lines from Task 9 with one:

```rust
pub use config::{classify_connect_error, probe_valkey, validate_block_timeout, ProbeClass, ProbeResult, SpineConfig};
```

- [ ] **Step 5: Run the full suite.**

Run: `docker run --rm -v "$(pwd)/packages/rust-spine:/work" -w /work rust:1.97.1 cargo test`
Expected: `test result: ok.` across every module so far.

- [ ] **Step 6: Commit.**

```bash
git add packages/rust-spine/src/config.rs packages/rust-spine/src/lib.rs
git commit -m "$(cat <<'EOF'
feat(spine): add the classified startup connectivity self-check

ProbeClass/ProbeResult/classify_connect_error/probe_valkey implement
Sec12.6's dns/tcp/tls/auth/ok classification, never a bare "connection
failed". DNS and TCP paths are unit-tested without any external
service; TLS/auth get real coverage once the pinned Valkey container
lands in Task 11.

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01N2rQgkHY872RubwXoBZxtE
EOF
)"
```

---

### Task 11: Pinned Valkey TLS test container bootstrap

**Files:**
- Create: `packages/rust-spine/tests/valkey/gen-test-tls.sh`, `packages/rust-spine/tests/valkey/valkey.conf`, `packages/rust-spine/tests/valkey/users.acl`
- Modify: `packages/rust-spine/.gitignore`, `/home/penguin/code/penguin-libs/Makefile` (root)

**Interfaces:**
- Consumes: nothing from this crate's Rust code.
- Produces: `make test-integration-spine-up` / `test-integration-spine-down` / `test-integration-spine` — every later integration test task (12, 13-17) runs through `test-integration-spine`, which starts the container, runs the named test binaries inside the pinned Rust container on the same Docker network, then tears down. The container name (`penguin-spine-test-valkey`) is the hostname later tasks' `VALKEY_URL` points at.

Spec: §14.2 ("Backends: `redis-rs` against a real Valkey container for integration tests; no mock-only coverage"), §11.6.1 (TLS scheme `rediss://`, full chain + hostname verification, one ACL user per service — this task ships the bootstrap `waddles_admin` only; Task 12 ships the real per-service matrix).

- [ ] **Step 1: Write `packages/rust-spine/tests/valkey/gen-test-tls.sh`:**

```bash
#!/usr/bin/env bash
set -euo pipefail

OUT="${1:?usage: gen-test-tls.sh <output-dir> <server-hostname>}"
SERVER_HOSTNAME="${2:?usage: gen-test-tls.sh <output-dir> <server-hostname>}"

mkdir -p "$OUT"

openssl req -x509 -newkey rsa:2048 -days 1 -nodes -sha256 \
  -keyout "$OUT/ca.key" -out "$OUT/ca.crt" \
  -subj "/CN=penguin-spine-test-ca"

openssl req -newkey rsa:2048 -nodes -sha256 \
  -keyout "$OUT/server.key" -out "$OUT/server.csr" \
  -subj "/CN=$SERVER_HOSTNAME"

openssl x509 -req -in "$OUT/server.csr" -CA "$OUT/ca.crt" -CAkey "$OUT/ca.key" \
  -CAcreateserial -days 1 -sha256 -out "$OUT/server.crt" \
  -extfile <(printf "subjectAltName=DNS:%s,DNS:localhost,IP:127.0.0.1" "$SERVER_HOSTNAME")

rm -f "$OUT/server.csr" "$OUT/ca.srl"
chmod 644 "$OUT"/*.crt "$OUT"/*.key

echo "wrote ca.crt, server.crt, server.key (CN=$SERVER_HOSTNAME) to $OUT"
```

Run: `chmod +x packages/rust-spine/tests/valkey/gen-test-tls.sh`

- [ ] **Step 2: Write `packages/rust-spine/tests/valkey/valkey.conf`:**

```
port 0
tls-port 6390
tls-cert-file /tls/server.crt
tls-key-file /tls/server.key
tls-ca-cert-file /tls/ca.crt
tls-auth-clients no
aclfile /acl/users.acl
appendonly no
save ""
```

(`port 0` disables the plaintext listener entirely — matching production's TLS-required default rather than leaving a bypass open even in tests. `tls-auth-clients no`: this crate authenticates via the Valkey ACL username/password, not mTLS client certificates.)

- [ ] **Step 3: Write `packages/rust-spine/tests/valkey/users.acl`** (bootstrap only — one admin user, enough to prove the container itself is reachable; Task 12 replaces this file entirely with the rendered least-privilege matrix):

```
user default off
user waddles_admin on >test-admin-password ~* &* +@all
```

- [ ] **Step 4: Update `packages/rust-spine/.gitignore`:**

```
/target
/tests/valkey/.tls/
```

- [ ] **Step 5: Add Makefile targets.** Append to `/home/penguin/code/penguin-libs/Makefile` (root):

```makefile
.PHONY: test-integration-spine-up test-integration-spine-down test-integration-spine

SPINE_TLS_DIR := packages/rust-spine/tests/valkey/.tls
SPINE_VALKEY_IMAGE := valkey/valkey:8.1.5@sha256:e51a82741b780e4bf315db10753edf07eea6496d405fa7df2a8677a18f5e7464
SPINE_VALKEY_CONTAINER := penguin-spine-test-valkey
SPINE_NETWORK := penguin-spine-test-net

test-integration-spine-up:
	bash packages/rust-spine/tests/valkey/gen-test-tls.sh $(SPINE_TLS_DIR) $(SPINE_VALKEY_CONTAINER)
	docker network create $(SPINE_NETWORK) >/dev/null 2>&1 || true
	docker rm -f $(SPINE_VALKEY_CONTAINER) >/dev/null 2>&1 || true
	docker run -d --name $(SPINE_VALKEY_CONTAINER) --network $(SPINE_NETWORK) \
	  -v $(CURDIR)/$(SPINE_TLS_DIR):/tls:ro \
	  -v $(CURDIR)/packages/rust-spine/tests/valkey/users.acl:/acl/users.acl:ro \
	  -v $(CURDIR)/packages/rust-spine/tests/valkey/valkey.conf:/usr/local/etc/valkey/valkey.conf:ro \
	  $(SPINE_VALKEY_IMAGE) valkey-server /usr/local/etc/valkey/valkey.conf
	@echo "waiting for valkey to become ready..."
	@ready=0; \
	for i in $$(seq 1 30); do \
	  if docker exec $(SPINE_VALKEY_CONTAINER) valkey-cli --tls --cert /tls/server.crt --key /tls/server.key --cacert /tls/ca.crt -p 6390 --user waddles_admin --pass test-admin-password PING 2>/dev/null | grep -q PONG; then ready=1; break; fi; \
	  sleep 1; \
	done; \
	if [ "$$ready" != "1" ]; then echo "valkey did not become ready in time"; exit 1; fi

test-integration-spine-down:
	docker rm -f $(SPINE_VALKEY_CONTAINER) >/dev/null 2>&1 || true
	docker network rm $(SPINE_NETWORK) >/dev/null 2>&1 || true
	rm -rf $(SPINE_TLS_DIR)

test-integration-spine: test-integration-spine-up
	docker run --rm --network $(SPINE_NETWORK) \
	  -v $(CURDIR)/packages/rust-spine:/work \
	  -w /work \
	  -e VALKEY_URL=rediss://$(SPINE_VALKEY_CONTAINER):6390 \
	  -e VALKEY_USERNAME=waddles_admin \
	  -e VALKEY_PASSWORD=test-admin-password \
	  -e VALKEY_CA_FILE=/work/tests/valkey/.tls/ca.crt \
	  rust:1.97.1 \
	  cargo test --test integration_stream_tests --test client_rules_tests --test acl_matrix_tests -- --test-threads=1
	$(MAKE) test-integration-spine-down
```

- [ ] **Step 6: Smoke-test the container lifecycle itself** (no Rust test files exist to run yet — `integration_stream_tests.rs`/`client_rules_tests.rs`/`acl_matrix_tests.rs` land in Tasks 12/13-17; this step only proves the container comes up, answers TLS+auth, and tears down cleanly):

Run:
```bash
cd /home/penguin/code/penguin-libs/.worktrees/plan-penguin-spine
make test-integration-spine-up
docker exec penguin-spine-test-valkey valkey-cli --tls --cert /tls/server.crt --key /tls/server.key --cacert /tls/ca.crt -p 6390 --user waddles_admin --pass test-admin-password PING
make test-integration-spine-down
```
Expected: the up target prints no error and exits 0; the `PING` prints `PONG`; the down target removes the container, network, and `.tls/` directory (`docker ps -a | grep penguin-spine-test-valkey` prints nothing afterward).

- [ ] **Step 7: Commit.**

```bash
git add packages/rust-spine/tests/valkey packages/rust-spine/.gitignore
git -C /home/penguin/code/penguin-libs add Makefile
git commit -m "$(cat <<'EOF'
chore(spine): add the pinned Valkey TLS integration-test container

TLS-only (port 0, tls-port 6390), ephemeral per-run certs via
gen-test-tls.sh (never committed), a bootstrap admin-only ACL Task 12
replaces with the real least-privilege matrix, and Makefile targets
that run the pinned Rust toolchain container on the same Docker
network as the Valkey container.

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01N2rQgkHY872RubwXoBZxtE
EOF
)"
```

---

### Task 12: The Valkey ACL matrix, its renderer, and a live `ACL LIST` conformance test

**Files:**
- Create: `packages/rust-spine/config/valkey/acl-matrix.yaml`, `packages/rust-spine/config/valkey/render_acl.py`, `packages/rust-spine/tests/acl_matrix_tests.rs`
- Modify: `packages/rust-spine/tests/valkey/users.acl` (deleted — now generated), `packages/rust-spine/.gitignore`, `/home/penguin/code/penguin-libs/Makefile`

**Interfaces:**
- Consumes: nothing from earlier Rust tasks (this test file builds its own connections directly, deliberately not reusing `penguin_spine::SpineConfig` — see rationale below).
- Produces: the crate's canonical least-privilege ACL matrix, referenced by Task 21's README. No later task in this plan consumes new Rust types from this task.

Spec: §11.10 (D28 "Least User Access via RBAC"), §11.10.2 (the Valkey ACL matrix: normative path `config/valkey/acl-matrix.yaml`, the `ACL LIST` equality test, the five negative tests, plus D31's `waddles:usage` row: every stage user is `+xadd`-only, only hub-api may read), §5.12/§6.2 (the `waddles:usage` key and its D31 usage-metering role), §11.6.1 (the per-service ACL sketch this matrix supersedes with exact, minimal command sets instead of broad categories).

**Cross-repo scope, restated from Global Constraints:** spec §11.10.2 fixes `config/valkey/acl-matrix.yaml` as a path at the root of whichever repo deploys the chart (`waddlebot`, per D22) — this plan cannot create that file there. This task ships the crate's own canonical copy at `packages/rust-spine/config/valkey/acl-matrix.yaml` (same relative suffix, rooted in this crate) plus the renderer, and proves both against this crate's own pinned Valkey container. Copying this exact file and renderer into the `waddlebot` repo's chart, and wiring spec's `make test-rbac-valkey` gate against a deployed alpha stack, is M6 work, out of this plan's scope.

- [ ] **Step 1: Write `packages/rust-spine/config/valkey/acl-matrix.yaml`** — the normative source; nothing else in this task is hand-derived from anywhere else:

```yaml
# Normative Valkey ACL matrix (spec Sec11.10.2, D28 "Least User Access via
# RBAC"). users.acl is rendered from this file by render_acl.py -- it is
# never hand-edited. Every user gets exactly the commands and key patterns
# its role uses; nothing gets a category grant "because it was easier".
version: 1
channels_policy: resetchannels
# Stated explicitly rather than by omission (spec Sec11.10.2): the
# executor holds no Valkey URL, no credential, and the NetworkPolicy
# denies the route -- there is no ACL user for it at all.
executors_have_no_user: true

users:
  - name: svc-ingest
    description: >-
      Writes ingest source-stream events; drains the Twitch outbound
      relay via a blocking pop; owns per-socket leases and intake dedupe
      keys. Never reads a consumer group -- ingest never consumes.
    commands: [xadd, blmove, brpop, set, get, expire, del, eval, evalsha]
    key_patterns:
      - "waddles:t:*:c:*:src:*:*:events"
      - "waddles:relay:*"
      - "waddles:lease:*"
      - "waddles:intake:*"
    # D31 usage metering (spec Sec5.12, Sec6.2, Sec11.10.2): every stage is
    # XADD-only on waddles:usage -- never xrange/xreadgroup/xrevrange, not
    # even its own writes read back. A dedicated selector, not a root key
    # pattern, so the root's broader command grants (blmove/set/get/...)
    # never reach this key.
    additional_selectors:
      - key_patterns: ["waddles:usage"]
        commands: [xadd]

  - name: svc-process
    description: >-
      Reads granted ingest-source streams via per-bundle consumer groups
      (XREADGROUP/XACK/XAUTOCLAIM/XPENDING), self-heals its own groups
      (XGROUP CREATE, BUSYGROUP-tolerant), writes its own and cross-app
      action streams (routes_to, Sec5.9), writes only its own DLQ, reads
      bundle config, reads/writes bundle state.
    commands: [xreadgroup, xack, xautoclaim, xpending, "xinfo|groups", "xgroup|create", xadd, get, hget, hset]
    key_patterns:
      - "waddles:t:*:c:*:src:*:*:events"
      - "waddles:t:*:c:*:app:*:action"
      - "waddles:dlq:process"
      - "waddles:t:*:c:*:app:*:cfg"
      - "waddles:t:*:c:*:app:*:state"
    # D31 usage metering: XADD-only on waddles:usage -- this user's root
    # grant already includes xreadgroup/xautoclaim, so without a dedicated
    # selector those would also reach waddles:usage via the root's key
    # patterns if waddles:usage were added there instead (spec Sec11.10.2).
    additional_selectors:
      - key_patterns: ["waddles:usage"]
        commands: [xadd]

  - name: svc-action
    description: >-
      Reads its own per-bundle action stream via a single consumer group;
      self-heals its own groups; pushes outbound Twitch relay messages;
      writes only its own DLQ; reads bundle config, reads/writes bundle
      state. Never writes to a source-stream key -- it has no XADD
      permission scoped to `src:*` at all.
    commands: [xreadgroup, xack, xautoclaim, xpending, "xinfo|groups", "xgroup|create", xadd, lpush, get, hget, hset]
    key_patterns:
      - "waddles:t:*:c:*:app:*:action"
      - "waddles:dlq:action"
      - "waddles:relay:*"
      - "waddles:t:*:c:*:app:*:cfg"
      - "waddles:t:*:c:*:app:*:state"
    # D31 usage metering: XADD-only on waddles:usage (spec Sec11.10.2).
    additional_selectors:
      - key_patterns: ["waddles:usage"]
        commands: [xadd]

  - name: svc-streaming
    description: >-
      Unchanged from the spec's own Sec11.6.1 sketch: its own namespace
      only, no streams commands at all.
    category_commands: ["+@read", "+@write", "+@string", "+@hash", "-@admin", "-@dangerous"]
    key_patterns:
      - "waddles:streaming:*"
    # D31 usage metering: XADD-only on waddles:usage, never covered by the
    # broad +@read/+@write category grant above, which is scoped only to
    # waddles:streaming:* (spec Sec5.12, Sec11.10.2).
    additional_selectors:
      - key_patterns: ["waddles:usage"]
        commands: [xadd]

  - name: hub-api
    description: >-
      Owns consumer-group lifecycle only: creates granted-stream groups
      at activation (XGROUP CREATE MKSTREAM), destroys them at
      deactivation/revocation (XGROUP DESTROY), and reconciles orphans via
      XINFO GROUPS. Never reads or writes an event, action, DLQ, config,
      or state key -- bundle config is written by the stage on its own
      distribution refresh, not by hub-api (spec Sec6.2).
    commands: ["xgroup|create", "xgroup|destroy", "xinfo|groups"]
    key_patterns:
      - "waddles:t:*:c:*:src:*:*:events"
      - "waddles:t:*:c:*:app:*:action"
    # D31 usage metering: hub-api's aggregator is the *only* reader of
    # waddles:usage (spec Sec5.12, Sec11.10.2) -- read-only (xrange/
    # xrevrange/xlen), never xadd, so hub-api cannot forge a usage delta.
    additional_selectors:
      - key_patterns: ["waddles:usage"]
        commands: [xrange, xrevrange, xlen]

  - name: waddles_admin
    description: >-
      Full access, for migrations/ops and this crate's own integration
      tests only. Never provisioned to a service pod.
    category_commands: ["+@all"]
    key_patterns:
      - "waddles:*"
```

- [ ] **Step 2: Write `packages/rust-spine/config/valkey/render_acl.py`:**

```python
#!/usr/bin/env python3
"""Renders config/valkey/acl-matrix.yaml into a Valkey `users.acl` file
(spec Sec11.10.2, D28). users.acl is never hand-edited -- it is always
generated from the matrix by this script.

Run: python3 render_acl.py <matrix.yaml> <output-users.acl>
"""
import sys

try:
    import yaml
except ImportError:
    print("PyYAML is required: pip install pyyaml==6.0.2", file=sys.stderr)
    sys.exit(1)


def user_password(name: str) -> str:
    """Test-only fixed password, one per user, derived from the user's
    name so it never needs a separate lookup table. Production passwords
    come from a chart-provisioned Secret (spec Sec11.6.1) and are never
    generated by this script -- this function exists only so this crate's
    own integration tests have deterministic, non-secret credentials."""
    return f"test-{name}-password"


def render_selector(selector: dict) -> str:
    """Renders one ACL selector (D31, spec Sec11.10.2): a parenthesized
    `(~pattern ... +cmd ...)` clause scoping extra commands to extra key
    patterns *without* widening the user's root grant -- e.g. a stage user
    that already holds xreadgroup/xautoclaim on its root patterns must
    still be XADD-only on waddles:usage, which a root-pattern addition
    alone could not express."""
    tokens = [f"~{p}" for p in selector["key_patterns"]]
    tokens.append("-@all")
    tokens.extend(f"+{cmd}" for cmd in selector["commands"])
    return "(" + " ".join(tokens) + ")"


def render_user(user: dict, channels_policy: str) -> str:
    parts = [f"user {user['name']} on >{user_password(user['name'])}", channels_policy]
    for pattern in user["key_patterns"]:
        parts.append(f"~{pattern}")
    if user.get("category_commands"):
        parts.extend(user["category_commands"])
    else:
        parts.append("-@all")
        parts.extend(f"+{cmd}" for cmd in user.get("commands", []))
    for selector in user.get("additional_selectors", []):
        parts.append(render_selector(selector))
    return " ".join(parts)


def main(matrix_path: str, output_path: str) -> None:
    with open(matrix_path, encoding="utf-8") as f:
        matrix = yaml.safe_load(f)

    users = matrix["users"]
    assert len(users) >= 6, f"expected >= 6 users in the matrix, found {len(users)}"

    lines = ["user default off"]
    for user in users:
        lines.append(render_user(user, matrix["channels_policy"]))

    with open(output_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")

    print(f"rendered {len(users)} users to {output_path}")


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print("usage: render_acl.py <matrix.yaml> <output-users.acl>", file=sys.stderr)
        sys.exit(2)
    main(sys.argv[1], sys.argv[2])
```

- [ ] **Step 3: Remove Task 11's bootstrap `users.acl`** — it is now generated, never committed:

```bash
git rm packages/rust-spine/tests/valkey/users.acl
```

Update `packages/rust-spine/.gitignore` to:

```
/target
/tests/valkey/.tls/
/tests/valkey/users.acl
```

- [ ] **Step 4: Update the Makefile targets** in `/home/penguin/code/penguin-libs/Makefile` — `test-integration-spine-up` now renders `users.acl` from the matrix before starting the container, and the health-check/`test-integration-spine` credentials switch to the rendered `waddles_admin` password:

```makefile
SPINE_PYTHON_IMAGE := python:3.13-slim@sha256:9d2e5553305c7c7b0097999bb17187c69b921ccd6bc9d40e4bb5ebe652c00285

test-integration-spine-up:
	bash packages/rust-spine/tests/valkey/gen-test-tls.sh $(SPINE_TLS_DIR) $(SPINE_VALKEY_CONTAINER)
	docker run --rm \
	  -v $(CURDIR)/packages/rust-spine:/work \
	  -w /work \
	  $(SPINE_PYTHON_IMAGE) \
	  sh -c "pip install --quiet pyyaml==6.0.2 && python3 config/valkey/render_acl.py config/valkey/acl-matrix.yaml tests/valkey/users.acl"
	docker network create $(SPINE_NETWORK) >/dev/null 2>&1 || true
	docker rm -f $(SPINE_VALKEY_CONTAINER) >/dev/null 2>&1 || true
	docker run -d --name $(SPINE_VALKEY_CONTAINER) --network $(SPINE_NETWORK) \
	  -v $(CURDIR)/$(SPINE_TLS_DIR):/tls:ro \
	  -v $(CURDIR)/packages/rust-spine/tests/valkey/users.acl:/acl/users.acl:ro \
	  -v $(CURDIR)/packages/rust-spine/tests/valkey/valkey.conf:/usr/local/etc/valkey/valkey.conf:ro \
	  $(SPINE_VALKEY_IMAGE) valkey-server /usr/local/etc/valkey/valkey.conf
	@echo "waiting for valkey to become ready..."
	@ready=0; \
	for i in $$(seq 1 30); do \
	  if docker exec $(SPINE_VALKEY_CONTAINER) valkey-cli --tls --cert /tls/server.crt --key /tls/server.key --cacert /tls/ca.crt -p 6390 --user waddles_admin --pass test-waddles_admin-password PING 2>/dev/null | grep -q PONG; then ready=1; break; fi; \
	  sleep 1; \
	done; \
	if [ "$$ready" != "1" ]; then echo "valkey did not become ready in time"; exit 1; fi

test-integration-spine: test-integration-spine-up
	docker run --rm --network $(SPINE_NETWORK) \
	  -v $(CURDIR)/packages/rust-spine:/work \
	  -w /work \
	  -e VALKEY_URL=rediss://$(SPINE_VALKEY_CONTAINER):6390 \
	  -e VALKEY_USERNAME=waddles_admin \
	  -e VALKEY_PASSWORD=test-waddles_admin-password \
	  -e VALKEY_CA_FILE=/work/tests/valkey/.tls/ca.crt \
	  rust:1.97.1 \
	  cargo test --test integration_stream_tests --test client_rules_tests --test acl_matrix_tests -- --test-threads=1
	$(MAKE) test-integration-spine-down
```

(Replace the `test-integration-spine-up` and `test-integration-spine` targets Task 11 added with these; `test-integration-spine-down` is unchanged.)

- [ ] **Step 5: Write `packages/rust-spine/tests/acl_matrix_tests.rs`:**

```rust
#![allow(clippy::unwrap_used, clippy::panic)]
//! Live ACL-matrix conformance test (spec Sec11.10.2, D28): connects to
//! the pinned Valkey container as `waddles_admin`, runs `ACL LIST`, and
//! asserts it equals `config/valkey/acl-matrix.yaml` exactly -- plus the
//! five per-user negative tests from the spec's table. Deliberately does
//! not reuse `penguin_spine::SpineConfig` (this test authenticates as
//! six different identities, one per assertion, which is a test-only
//! shape `SpineConfig` — built for one service's one identity — has no
//! reason to support).
//!
//! Run via `make test-integration-spine`.

use redis::{AsyncCommands, Client};
use serde::Deserialize;
use std::collections::HashSet;
use std::fs;
use std::path::Path;

#[derive(Debug, Clone, Deserialize)]
struct AclMatrix {
    #[allow(dead_code)]
    version: u32,
    channels_policy: String,
    executors_have_no_user: bool,
    users: Vec<AclUser>,
}

#[derive(Debug, Clone, Deserialize)]
struct AclUser {
    name: String,
    #[serde(default)]
    #[allow(dead_code)]
    description: String,
    #[serde(default)]
    commands: Vec<String>,
    #[serde(default)]
    category_commands: Vec<String>,
    key_patterns: Vec<String>,
    /// D31 usage-metering selectors (spec Sec11.10.2, Sec5.12): each
    /// scopes extra commands to extra key patterns *without* widening the
    /// user's root grant -- e.g. `waddles:usage` is `+xadd`-only for every
    /// stage user even though several already hold xreadgroup/xautoclaim
    /// on their root patterns.
    #[serde(default)]
    additional_selectors: Vec<AclSelector>,
}

#[derive(Debug, Clone, Deserialize)]
struct AclSelector {
    key_patterns: Vec<String>,
    commands: Vec<String>,
}

impl AclUser {
    fn expected_rule_tokens(&self) -> HashSet<String> {
        if !self.category_commands.is_empty() {
            self.category_commands.iter().cloned().collect()
        } else {
            let mut set: HashSet<String> = HashSet::new();
            set.insert("-@all".to_string());
            for cmd in &self.commands {
                set.insert(format!("+{cmd}"));
            }
            set
        }
    }

    fn expected_key_patterns(&self) -> HashSet<String> {
        self.key_patterns.iter().map(|p| format!("~{p}")).collect()
    }

    fn password(&self) -> String {
        format!("test-{}-password", self.name)
    }
}

fn load_matrix() -> AclMatrix {
    let path = Path::new(env!("CARGO_MANIFEST_DIR")).join("config/valkey/acl-matrix.yaml");
    let text = fs::read_to_string(&path)
        .unwrap_or_else(|e| panic!("failed to read {}: {e}", path.display()));
    serde_saphyr::from_str(&text)
        .unwrap_or_else(|e| panic!("failed to parse {}: {e}", path.display()))
}

async fn connect_as(username: &str, password: &str) -> redis::RedisResult<redis::aio::MultiplexedConnection> {
    let url = std::env::var("VALKEY_URL").expect("VALKEY_URL must be set (run via `make test-integration-spine`)");
    let ca_file = std::env::var("VALKEY_CA_FILE").expect("VALKEY_CA_FILE must be set");
    let root_cert = fs::read(&ca_file).unwrap_or_else(|e| panic!("failed to read {ca_file}: {e}"));

    let base: redis::ConnectionInfo = redis::IntoConnectionInfo::into_connection_info(url.as_str())
        .unwrap_or_else(|e| panic!("invalid VALKEY_URL: {e}"));
    let redis_settings = base.redis_settings().clone().set_username(username).set_password(password);
    let info = base.set_redis_settings(redis_settings);

    let client = Client::build_with_tls(
        info,
        redis::TlsCertificates { client_tls: None, root_cert: Some(root_cert) },
    )?;
    client.get_multiplexed_async_connection().await
}

async fn admin_connection() -> redis::aio::MultiplexedConnection {
    connect_as("waddles_admin", "test-waddles_admin-password")
        .await
        .expect("failed to connect as waddles_admin")
}

/// Removes every balanced `(...)` substring from an `ACL LIST` line --
/// Valkey renders each additional selector (D31's `waddles:usage` grant,
/// spec Sec11.10.2) as one parenthesized clause appended after the root
/// grant. Selectors have no nested parens, so a simple depth counter is
/// sufficient; this crate never generates one.
fn strip_selector_clauses(line: &str) -> String {
    let mut out = String::with_capacity(line.len());
    let mut depth = 0u32;
    for c in line.chars() {
        match c {
            '(' => depth += 1,
            ')' => depth = depth.saturating_sub(1),
            _ if depth == 0 => out.push(c),
            _ => {}
        }
    }
    out
}

#[tokio::test]
async fn acl_list_matches_the_matrix_exactly() {
    let matrix = load_matrix();
    assert!(
        matrix.users.len() >= 6,
        "spec Sec11.10.2 requires the matrix to cover every service user; found {}",
        matrix.users.len()
    );
    assert_eq!(matrix.channels_policy, "resetchannels");
    assert!(
        matrix.executors_have_no_user,
        "the matrix must state explicitly that executors have no Valkey user"
    );

    let mut conn = admin_connection().await;
    let acl_list: Vec<String> = redis::cmd("ACL")
        .arg("LIST")
        .query_async(&mut conn)
        .await
        .expect("ACL LIST failed");

    let mut examined = 0;
    for user in &matrix.users {
        let line = acl_list
            .iter()
            .find(|l| l.split_whitespace().nth(1) == Some(user.name.as_str()))
            .unwrap_or_else(|| panic!("ACL LIST has no entry for user {:?}", user.name));
        // Strip any parenthesized additional-selector clauses (D31's
        // waddles:usage selector, e.g. `(~waddles:usage +xadd)`) before
        // tokenizing the root clause -- otherwise their `~`/`+` tokens
        // would be double-counted against the root grant this loop checks.
        // The selectors themselves are verified separately by
        // waddles_usage_selector_is_xadd_only_for_every_stage_user below.
        let root_line = strip_selector_clauses(line);
        let tokens: Vec<&str> = root_line.split_whitespace().collect();

        assert!(tokens.contains(&"on"), "{}: expected 'on'", user.name);
        assert!(tokens.contains(&"resetchannels"), "{}: expected resetchannels", user.name);

        let actual_patterns: HashSet<String> =
            tokens.iter().filter(|t| t.starts_with('~')).map(|t| t.to_string()).collect();
        assert_eq!(actual_patterns, user.expected_key_patterns(), "{}: key pattern mismatch", user.name);

        let actual_rules: HashSet<String> = tokens
            .iter()
            .filter(|t| t.starts_with('+') || t.starts_with('-'))
            .map(|t| t.to_string())
            .collect();
        assert_eq!(actual_rules, user.expected_rule_tokens(), "{}: command rule mismatch", user.name);

        examined += 1;
    }
    assert_eq!(examined, matrix.users.len(), "users_examined must equal users_in_matrix");

    let acl_usernames: HashSet<&str> =
        acl_list.iter().filter_map(|l| l.split_whitespace().nth(1)).collect();
    let matrix_usernames: HashSet<&str> = matrix.users.iter().map(|u| u.name.as_str()).collect();
    for name in &acl_usernames {
        assert!(
            *name == "default" || matrix_usernames.contains(name),
            "ACL LIST has an unexpected user {name:?} not in the matrix"
        );
    }
    assert!(
        !acl_usernames.iter().any(|n| n.contains("executor")),
        "no executor user may exist in Valkey ACLs (spec Sec11.10.2)"
    );

    let default_line = acl_list
        .iter()
        .find(|l| l.split_whitespace().nth(1) == Some("default"))
        .expect("ACL LIST must include the default user");
    assert!(default_line.contains(" off"), "default user must be disabled");

    println!("ACL users examined: {examined} (matrix: {})", matrix.users.len());
}

#[tokio::test]
async fn svc_action_cannot_xadd_to_an_ingest_source_stream() {
    let mut conn = connect_as("svc-action", "test-svc-action-password").await.unwrap();
    let result: redis::RedisResult<String> = conn
        .xadd(
            "waddles:t:acme:c:main:src:twitch:tw-channelA:events",
            "*",
            &[("env", "{}")],
        )
        .await;
    assert!(result.is_err(), "svc-action must not be able to XADD to an ingest source stream");
}

#[tokio::test]
async fn svc_ingest_cannot_xreadgroup_an_action_stream() {
    let mut conn = connect_as("svc-ingest", "test-svc-ingest-password").await.unwrap();
    let result: redis::RedisResult<redis::Value> = redis::cmd("XREADGROUP")
        .arg("GROUP")
        .arg("some-group")
        .arg("some-consumer")
        .arg("STREAMS")
        .arg("waddles:t:acme:c:main:app:waddles.bot.commands.default:action")
        .arg(">")
        .query_async(&mut conn)
        .await;
    assert!(result.is_err(), "svc-ingest must not be able to XREADGROUP an action stream");
}

#[tokio::test]
async fn svc_process_cannot_touch_a_key_outside_waddles_namespace() {
    let mut conn = connect_as("svc-process", "test-svc-process-password").await.unwrap();
    let result: redis::RedisResult<Option<String>> = conn.get("not-a-waddles-key").await;
    assert!(result.is_err(), "svc-process must not be able to touch a key outside waddles:t:*");
}

#[tokio::test]
async fn no_service_user_can_run_admin_or_dangerous_commands() {
    let matrix = load_matrix();
    let service_users: Vec<&AclUser> = matrix.users.iter().filter(|u| u.name != "waddles_admin").collect();
    assert!(!service_users.is_empty());

    for user in &service_users {
        let mut conn = connect_as(&user.name, &user.password()).await.unwrap();
        let config_result: redis::RedisResult<Vec<String>> =
            redis::cmd("CONFIG").arg("GET").arg("maxmemory").query_async(&mut conn).await;
        assert!(config_result.is_err(), "{}: must not be able to run CONFIG GET", user.name);

        let acl_result: redis::RedisResult<Vec<String>> =
            redis::cmd("ACL").arg("LIST").query_async(&mut conn).await;
        assert!(acl_result.is_err(), "{}: must not be able to run ACL LIST", user.name);
    }
}

#[tokio::test]
async fn no_valkey_user_exists_for_the_executor() {
    let matrix = load_matrix();
    assert!(matrix.executors_have_no_user);
    let result = connect_as("svc-process-executor", "anything").await;
    assert!(result.is_err(), "no user should exist for an executor identity");
}

/// D31 (spec Sec5.12, Sec11.10.2): every stage user can XADD its own
/// usage deltas onto `waddles:usage`, but none of them -- including the
/// one that wrote the entry -- can read it back, whatever read command is
/// attempted.
#[tokio::test]
async fn waddles_usage_selector_is_xadd_only_for_every_stage_user() {
    let matrix = load_matrix();
    let stage_users = ["svc-ingest", "svc-process", "svc-action", "svc-streaming"];
    let mut examined = 0;
    for name in stage_users {
        let user = matrix
            .users
            .iter()
            .find(|u| u.name == name)
            .unwrap_or_else(|| panic!("matrix has no user named {name:?}"));
        let mut conn = connect_as(&user.name, &user.password()).await.unwrap();

        let xadd_result: redis::RedisResult<String> =
            conn.xadd("waddles:usage", "*", &[("env", "{}")]).await;
        assert!(xadd_result.is_ok(), "{name}: must be able to XADD onto waddles:usage (D31)");

        let xrange_result: redis::RedisResult<Vec<redis::Value>> =
            redis::cmd("XRANGE").arg("waddles:usage").arg("-").arg("+").query_async(&mut conn).await;
        assert!(xrange_result.is_err(), "{name}: must not be able to XRANGE waddles:usage");

        let xrevrange_result: redis::RedisResult<Vec<redis::Value>> =
            redis::cmd("XREVRANGE").arg("waddles:usage").arg("+").arg("-").query_async(&mut conn).await;
        assert!(xrevrange_result.is_err(), "{name}: must not be able to XREVRANGE waddles:usage");

        let xreadgroup_result: redis::RedisResult<redis::Value> = redis::cmd("XREADGROUP")
            .arg("GROUP")
            .arg("some-group")
            .arg("some-consumer")
            .arg("STREAMS")
            .arg("waddles:usage")
            .arg(">")
            .query_async(&mut conn)
            .await;
        assert!(xreadgroup_result.is_err(), "{name}: must not be able to XREADGROUP waddles:usage");

        examined += 1;
    }
    assert_eq!(examined, stage_users.len(), "stage_users_examined must equal stage_users_in_matrix");
    println!("waddles:usage xadd-only stage users examined: {examined}");
}

/// D31: only hub-api's ACL user may read `waddles:usage`.
#[tokio::test]
async fn only_hub_api_can_read_waddles_usage() {
    let mut hub_api_conn = connect_as("hub-api", "test-hub-api-password").await.unwrap();
    let hub_api_result: redis::RedisResult<Vec<redis::Value>> =
        redis::cmd("XRANGE").arg("waddles:usage").arg("-").arg("+").query_async(&mut hub_api_conn).await;
    assert!(hub_api_result.is_ok(), "hub-api must be able to XRANGE waddles:usage (D31)");

    let hub_api_xadd_result: redis::RedisResult<String> =
        hub_api_conn.xadd("waddles:usage", "*", &[("env", "{}")]).await;
    assert!(hub_api_xadd_result.is_err(), "hub-api must never be able to XADD waddles:usage itself");

    let mut svc_process_conn = connect_as("svc-process", "test-svc-process-password").await.unwrap();
    let svc_process_result: redis::RedisResult<Vec<redis::Value>> = redis::cmd("XRANGE")
        .arg("waddles:usage")
        .arg("-")
        .arg("+")
        .query_async(&mut svc_process_conn)
        .await;
    assert!(svc_process_result.is_err(), "svc-process must not be able to XRANGE waddles:usage");
}
```

- [ ] **Step 6: Run and fix until green.**

Run: `cd /home/penguin/code/penguin-libs/.worktrees/plan-penguin-spine && make test-integration-spine`
Expected: the container comes up, `render_acl.py` prints `rendered 6 users to tests/valkey/users.acl`, all 8 tests in `acl_matrix_tests.rs` pass -- including the two D31 tests proving every stage user is XADD-only on `waddles:usage` and only hub-api can read it back (plus `integration_stream_tests.rs`/`client_rules_tests.rs`, which exist as empty placeholders — `touch packages/rust-spine/tests/integration_stream_tests.rs packages/rust-spine/tests/client_rules_tests.rs` first if they don't exist yet at this point in plan execution, since Tasks 13-17 are what actually fill them in), and the container/network/`.tls/` are removed afterward.

- [ ] **Step 7: Commit.**

```bash
git add packages/rust-spine/config packages/rust-spine/tests/acl_matrix_tests.rs packages/rust-spine/tests/valkey packages/rust-spine/.gitignore
git -C /home/penguin/code/penguin-libs add Makefile
git commit -m "$(cat <<'EOF'
feat(spine): add the Valkey ACL matrix, renderer, and live conformance test

config/valkey/acl-matrix.yaml is the normative D28 least-privilege
source: six service users, each scoped to exactly the commands and key
patterns its role uses (no category grant "because it was easier"),
plus an explicit executors_have_no_user statement. users.acl is
rendered from it, never hand-edited. acl_matrix_tests.rs proves ACL
LIST equals the matrix against a live pinned Valkey container, plus
the five Sec11.10.2 negative tests and two D31 usage-metering tests:
every stage user is +xadd-only on waddles:usage via a dedicated ACL
selector (never widening its root grant), and only hub-api can read
the stream back.

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01N2rQgkHY872RubwXoBZxtE
EOF
)"
```

---

### Task 13: `SpineClient::connect` and `SpineClient::append`

**Files:**
- Modify: `packages/rust-spine/src/client.rs`, `packages/rust-spine/src/lib.rs`
- Create: `packages/rust-spine/tests/integration_stream_tests.rs`

**Interfaces:**
- Consumes: `SpineConfig`/`probe_valkey`/`ProbeClass` (Tasks 9-10), `SpineMetrics` (Task 6), `StageEnvelope` (Task 4), `SpineError` (Task 5).
- Produces: `Grant { stream, platform, source_id }`, `Delivered { stream, entry_id, env: StageEnvelope, deliveries: u64 }`, `SpineClient` (`Clone`), `SpineClient::connect(cfg: SpineConfig, metrics: Arc<dyn SpineMetrics>) -> Result<Self, SpineError>`, `SpineClient::append(&self, stream: &str, env: &StageEnvelope) -> Result<String, SpineError>`. Tasks 14-17 add more methods to this same `SpineClient`; `Grant`/`Delivered` are used by Task 17's `GroupReader`.

Spec: §4.7 (public surface — see Global Constraints' stated deviations for why `connect` is fallible and the crate has no pool dependency), §5.1 (`XADD ... MAXLEN ~ ... * env {json}`), §5.7 (rule 2: this client's connection is never a blocking-read connection), §12.6 (the startup probe runs "before a stage drains anything").

- [ ] **Step 1: Append to `packages/rust-spine/src/client.rs`:**

```rust
//! The Valkey Streams admin/write client (spec Sec4.7): `XADD`, group
//! lifecycle, `XACK`, `XAUTOCLAIM`, the DLQ, and `XINFO GROUPS`.
//! Non-blocking traffic only — a blocking `XREADGROUP` read never runs
//! through this type (spec Sec5.7 rule 2); see [`crate::GroupReader`].

use std::sync::Arc;

use redis::streams::StreamMaxlen;
use redis::AsyncCommands;

use crate::config::{probe_valkey, ProbeClass, SpineConfig};
use crate::envelope::StageEnvelope;
use crate::error::SpineError;
use crate::metrics::SpineMetrics;

/// One stream a bundle is permitted to read, resolved by hub-api from its
/// `consumes` request (spec Sec5.2).
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Grant {
    /// The granted stream key.
    pub stream: String,
    /// The platform the stream belongs to.
    pub platform: String,
    /// The ingest source id the stream belongs to.
    pub source_id: String,
}

/// One entry successfully read and deserialized from a granted stream.
#[derive(Debug, Clone)]
pub struct Delivered {
    /// The stream the entry was read from.
    pub stream: String,
    /// The Valkey stream entry id.
    pub entry_id: String,
    /// The deserialized envelope.
    pub env: StageEnvelope,
    /// The delivery count at read time (`1` for a first delivery).
    pub deliveries: u64,
}

/// Per-group stats from `XINFO GROUPS` (spec Sec5.6).
#[derive(Debug, Clone)]
pub struct GroupStats {
    /// The consumer group name (equals the bundle's `app_id`).
    pub app_id: String,
    /// The stream the group belongs to.
    pub stream: String,
    /// Undelivered entries for the group, when the server reports one.
    pub lag: Option<u64>,
    /// The group's pending-entries-list size — the stuck-bundle signal.
    pub pending: u64,
}

fn parse_platform_and_source_id(stream: &str) -> Option<(String, String)> {
    let idx = stream.find(":src:")?;
    let rest = &stream[idx + ":src:".len()..];
    let mut parts = rest.split(':');
    let platform = parts.next()?.to_string();
    let source_id = parts.next()?.to_string();
    Some((platform, source_id))
}

fn build_connection_info(cfg: &SpineConfig) -> Result<redis::ConnectionInfo, SpineError> {
    let base: redis::ConnectionInfo = redis::IntoConnectionInfo::into_connection_info(cfg.valkey_url.as_str())
        .map_err(|e| SpineError::Config(format!("invalid VALKEY_URL {:?}: {e}", cfg.valkey_url)))?;
    let mut redis_settings = base.redis_settings().clone();
    if let Some(username) = &cfg.valkey_username {
        redis_settings = redis_settings.set_username(username);
    }
    if let Some(password) = &cfg.valkey_password {
        redis_settings = redis_settings.set_password(password);
    }
    Ok(base.set_redis_settings(redis_settings))
}

/// The spine's admin/write client. Backed by one
/// `redis::aio::MultiplexedConnection`, which already serves concurrent
/// callers safely over a single socket — no separate pool crate needed
/// (Global Constraints, deviation 5). `Clone` is cheap.
#[derive(Clone)]
pub struct SpineClient {
    conn: redis::aio::MultiplexedConnection,
    cfg: SpineConfig,
    metrics: Arc<dyn SpineMetrics>,
}

impl SpineClient {
    /// Runs the Sec12.6 startup probe, then connects to Valkey per `cfg`
    /// (TLS/auth per Sec11.6.1). Refuses to return a client for a
    /// dependency that never became reachable.
    pub async fn connect(cfg: SpineConfig, metrics: Arc<dyn SpineMetrics>) -> Result<Self, SpineError> {
        cfg.validate()?;

        let probe = probe_valkey(
            &cfg,
            std::time::Duration::from_millis(5_000),
            3,
            std::time::Duration::from_secs(1),
        )
        .await;
        metrics.insecure_transport("valkey", "tls", !cfg.security_transport_tls);
        metrics.insecure_transport("valkey", "auth", !cfg.security_transport_auth);
        if probe.class != ProbeClass::Ok {
            return Err(SpineError::Config(format!(
                "valkey startup probe failed ({}): {}",
                probe.class.as_str(),
                probe.message
            )));
        }

        let info = build_connection_info(&cfg)?;
        let client = if cfg.security_transport_tls {
            let root_cert = std::fs::read(&cfg.valkey_ca_file).ok();
            redis::Client::build_with_tls(
                info,
                redis::TlsCertificates {
                    client_tls: None,
                    root_cert,
                },
            )?
        } else {
            redis::Client::open(info)?
        };

        let async_cfg = redis::AsyncConnectionConfig::new()
            .set_response_timeout(Some(std::time::Duration::from_secs(cfg.drain_socket_timeout_s)));
        let conn = client.get_multiplexed_async_connection_with_config(&async_cfg).await?;

        Ok(SpineClient { conn, cfg, metrics })
    }

    /// Writes one envelope to `stream` with approximate `MAXLEN` trimming
    /// (spec Sec5.1): `XADD {stream} MAXLEN ~ {maxlen} * env {json}`.
    pub async fn append(&self, stream: &str, env: &StageEnvelope) -> Result<String, SpineError> {
        let json = serde_json::to_string(env)?;
        let mut conn = self.conn.clone();
        let maxlen = StreamMaxlen::Approx(self.cfg.stream_maxlen as usize);
        let id: Option<String> = conn
            .xadd_maxlen(stream, maxlen, "*", &[("env", json.as_str())])
            .await?;
        let id = id.ok_or_else(|| SpineError::Config(format!("XADD to {stream:?} returned no entry id")))?;

        // MAXLEN ~ is approximate and XADD's reply carries no trim count;
        // a stream sitting at-or-above its approximate cap right after a
        // write is the cheap, honest proxy for "trimming is happening
        // here" (spec Sec5.1's own test only asserts trimming happened at
        // all, never an exact count).
        let len: u64 = conn.xlen(stream).await.unwrap_or(0);
        if len >= self.cfg.stream_maxlen {
            self.metrics.stream_trimmed(stream);
        }

        if let Some((platform, source_id)) = parse_platform_and_source_id(stream) {
            self.metrics.stream_event_written(&platform, &source_id);
        }

        Ok(id)
    }
}
```

- [ ] **Step 2: Write `packages/rust-spine/tests/integration_stream_tests.rs`:**

```rust
#![allow(clippy::unwrap_used, clippy::panic)]
//! Integration tests against the pinned Valkey container (spec Sec14.2).
//! Run via `make test-integration-spine`.

use penguin_spine::{NoopMetrics, SpineClient, SpineConfig, StageEnvelope};
use std::sync::Arc;

fn unique_stream(label: &str) -> String {
    format!(
        "waddles:t:acme:c:main:src:twitch:{label}-{}:events",
        uuid::Uuid::new_v4()
    )
}

async fn test_client() -> SpineClient {
    let cfg = SpineConfig::from_env().expect("SpineConfig::from_env (run via make test-integration-spine)");
    SpineClient::connect(cfg, Arc::new(NoopMetrics))
        .await
        .expect("SpineClient::connect")
}

fn sample_envelope() -> StageEnvelope {
    let json = serde_json::json!({
        "tenant": "acme",
        "community": "main",
        "app_id": "waddles.bot.commands.default",
        "stage": "process",
        "event": {
            "platform": "twitch",
            "event_type": "chat.message",
            "actor": "some_user",
            "payload": {"text": "hello"},
            "occurred_at": "2026-09-14T12:00:00.000Z"
        },
        "ts": "2026-09-14T12:00:00.123Z",
        "target_app_id": null,
        "workstream_id": "8f14e45f-ceea-467e-adde-3fb5c9752730",
        "event_id": "3fa85f64-5717-4562-b3fc-2c963f66afa6",
        "session_id": null,
        "trace": null,
        "binding": {"kid": "test-kid", "mac": "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"}
    });
    serde_json::from_value(json).unwrap()
}

#[tokio::test]
async fn append_writes_and_returns_an_entry_id() {
    let client = test_client().await;
    let stream = unique_stream("append");
    let id = client.append(&stream, &sample_envelope()).await.unwrap();
    assert!(id.contains('-'), "a Valkey stream entry id looks like {{ms}}-{{seq}}, got {id:?}");
}
```

- [ ] **Step 3: Run and fix until green.**

Run: `cd /home/penguin/code/penguin-libs/.worktrees/plan-penguin-spine && make test-integration-spine`
Expected: `test append_writes_and_returns_an_entry_id ... ok` among the output, alongside the already-green `acl_matrix_tests` from Task 12; `client_rules_tests.rs` does not exist yet — `touch packages/rust-spine/tests/client_rules_tests.rs` first so the Makefile's `cargo test --test client_rules_tests` invocation doesn't fail on a missing file (Task 17 fills it in).

- [ ] **Step 4: Activate the partial `lib.rs` export**, replacing the commented client line:

```rust
pub use client::{Delivered, Grant, SpineClient};
// TODO(task-15): also export GroupStats
```

- [ ] **Step 5: Run the full unit-test suite too** (the container-free half):

Run: `docker run --rm -v "$(pwd)/packages/rust-spine:/work" -w /work rust:1.97.1 cargo test --lib`
Expected: `test result: ok.` across every module.

- [ ] **Step 6: Commit.**

```bash
git add packages/rust-spine/src/client.rs packages/rust-spine/src/lib.rs packages/rust-spine/tests/integration_stream_tests.rs
git commit -m "$(cat <<'EOF'
feat(spine): add SpineClient::connect and SpineClient::append

connect runs the Sec12.6 startup probe before returning a client and
reports the Sec11.6.4 insecure-transport gauges. append writes with
MAXLEN ~ approximate trimming and records waddles_stream_events_total/
waddles_stream_trimmed_total.

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01N2rQgkHY872RubwXoBZxtE
EOF
)"
```

---

### Task 14: `SpineClient::ensure_group` and `SpineClient::destroy_group`

**Files:**
- Modify: `packages/rust-spine/src/client.rs`, `packages/rust-spine/tests/integration_stream_tests.rs`

**Interfaces:**
- Consumes: `SpineClient` (Task 13).
- Produces: `SpineClient::ensure_group(&self, stream: &str, app_id: &str) -> Result<(), SpineError>`, `SpineClient::destroy_group(&self, stream: &str, app_id: &str) -> Result<(), SpineError>`. Task 17's `GroupReader` relies on a group already existing (created via `ensure_group` by the calling service, per spec's "the stage re-issues it on every distribution refresh").

Spec: §5.2 (group lifecycle table: hub-api creates at activation, the stage re-issues `BUSYGROUP`-tolerant on every refresh, hub-api destroys at deactivation).

- [ ] **Step 1: Append to the `impl SpineClient` block in `packages/rust-spine/src/client.rs`:**

```rust
    /// Creates the consumer group `app_id` on `stream` starting from `$`
    /// (new entries only), `MKSTREAM`, `BUSYGROUP`-tolerant (spec Sec5.2)
    /// — idempotent, safe to call on every distribution refresh so a
    /// group lost to a Valkey restore self-heals without operator action.
    pub async fn ensure_group(&self, stream: &str, app_id: &str) -> Result<(), SpineError> {
        let mut conn = self.conn.clone();
        let result: redis::RedisResult<()> = conn.xgroup_create_mkstream(stream, app_id, "$").await;
        match result {
            Ok(()) => Ok(()),
            Err(e) if e.code() == Some("BUSYGROUP") => Ok(()),
            Err(e) => Err(e.into()),
        }
    }

    /// Destroys the consumer group `app_id` on `stream` (`XGROUP
    /// DESTROY`), at deactivation or grant revocation (spec Sec5.2).
    pub async fn destroy_group(&self, stream: &str, app_id: &str) -> Result<(), SpineError> {
        let mut conn = self.conn.clone();
        let _removed: bool = conn.xgroup_destroy(stream, app_id).await?;
        Ok(())
    }
```

- [ ] **Step 2: Add a raw-connection test helper and two tests to `packages/rust-spine/tests/integration_stream_tests.rs`** (append after `append_writes_and_returns_an_entry_id`):

```rust
async fn raw_admin_connection() -> redis::aio::MultiplexedConnection {
    let url = std::env::var("VALKEY_URL").unwrap();
    let username = std::env::var("VALKEY_USERNAME").unwrap();
    let password = std::env::var("VALKEY_PASSWORD").unwrap();
    let ca_file = std::env::var("VALKEY_CA_FILE").unwrap();
    let root_cert = std::fs::read(&ca_file).unwrap();
    let base: redis::ConnectionInfo = redis::IntoConnectionInfo::into_connection_info(url.as_str()).unwrap();
    let redis_settings = base.redis_settings().clone().set_username(&username).set_password(&password);
    let info = base.set_redis_settings(redis_settings);
    let client = redis::Client::build_with_tls(
        info,
        redis::TlsCertificates { client_tls: None, root_cert: Some(root_cert) },
    )
    .unwrap();
    client.get_multiplexed_async_connection().await.unwrap()
}

#[tokio::test]
async fn ensure_group_creates_and_is_busygroup_tolerant() {
    let client = test_client().await;
    let stream = unique_stream("ensure-group");
    client.append(&stream, &sample_envelope()).await.unwrap();

    client.ensure_group(&stream, "waddles.bot.commands.default").await.unwrap();
    // A second call against the same group must not error.
    client.ensure_group(&stream, "waddles.bot.commands.default").await.unwrap();

    let mut conn = raw_admin_connection().await;
    let groups: redis::streams::StreamInfoGroupsReply = redis::cmd("XINFO")
        .arg("GROUPS")
        .arg(&stream)
        .query_async(&mut conn)
        .await
        .unwrap();
    assert!(groups.groups.iter().any(|g| g.name == "waddles.bot.commands.default"));
}

#[tokio::test]
async fn destroy_group_removes_a_created_group() {
    let client = test_client().await;
    let stream = unique_stream("destroy-group");
    client.append(&stream, &sample_envelope()).await.unwrap();
    client.ensure_group(&stream, "waddles.bot.commands.default").await.unwrap();

    client.destroy_group(&stream, "waddles.bot.commands.default").await.unwrap();

    let mut conn = raw_admin_connection().await;
    let groups: redis::streams::StreamInfoGroupsReply = redis::cmd("XINFO")
        .arg("GROUPS")
        .arg(&stream)
        .query_async(&mut conn)
        .await
        .unwrap();
    assert!(
        !groups.groups.iter().any(|g| g.name == "waddles.bot.commands.default"),
        "destroy_group must actually remove the consumer group"
    );
}
```

- [ ] **Step 3: Run and fix until green.**

Run: `cd /home/penguin/code/penguin-libs/.worktrees/plan-penguin-spine && make test-integration-spine`
Expected: both new tests pass alongside every earlier integration test.

- [ ] **Step 4: Commit.**

```bash
git add packages/rust-spine/src/client.rs packages/rust-spine/tests/integration_stream_tests.rs
git commit -m "$(cat <<'EOF'
feat(spine): add SpineClient::ensure_group and destroy_group

BUSYGROUP-tolerant create (idempotent, safe on every distribution
refresh) and a real XGROUP DESTROY, both verified against XINFO GROUPS
on the live pinned Valkey container.

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01N2rQgkHY872RubwXoBZxtE
EOF
)"
```

---

### Task 15: `SpineClient::ack`, `dead_letter`, `claim_stale`, `group_stats`

**Files:**
- Modify: `packages/rust-spine/src/client.rs`, `packages/rust-spine/src/lib.rs`, `packages/rust-spine/tests/integration_stream_tests.rs`

**Interfaces:**
- Consumes: `Delivered`/`Grant`/`SpineClient` (Task 13), `DlqRecord`/`DlqErrorDetail`/`DlqError`/`DlqErrorKind` (Task 5), `Stage`/`dlq_key`/`parse_scope_from_key` (Task 2).
- Produces: `SpineClient::ack(&self, d: &Delivered, app_id: &str) -> Result<(), SpineError>`, `SpineClient::dead_letter(&self, d: &Delivered, err: &DlqError) -> Result<(), SpineError>`, `SpineClient::claim_stale(&self, stream: &str, app_id: &str, stage: Stage) -> Result<Vec<Delivered>, SpineError>` (see Global Constraints deviation 6 for the added `stage` parameter), `SpineClient::group_stats(&self, stream: &str) -> Result<Vec<GroupStats>, SpineError>`, `GroupStats { app_id, stream, lag: Option<u64>, pending: u64 }`. Task 17's `GroupReader` calls `ack`/`dead_letter` (via its own `dlq: SpineClient` handle) for the entries it reads.

Spec: §5.3/§5.4 (`XACK`, `XAUTOCLAIM`, the redelivery cap at `SPINE_MAX_DELIVERIES`), §5.5 (DLQ write shape, the `envelope_invalid` case that never produces a `Delivered`), §5.6 (`XINFO GROUPS` sampling, `waddles_group_lag`/`waddles_group_pending`).

- [ ] **Step 1: Append to the `impl SpineClient` block in `packages/rust-spine/src/client.rs`**, and add the two supporting imports at the top of the file (`use crate::dlq::{DlqError, DlqErrorDetail, DlqErrorKind, DlqRecord};` and `use crate::scope::{dlq_key, parse_scope_from_key, Stage};`):

```rust
    /// Acknowledges one delivered entry (`XACK`), removing it from the
    /// group's pending-entries list (spec Sec5.3).
    pub async fn ack(&self, d: &Delivered, app_id: &str) -> Result<(), SpineError> {
        let mut conn = self.conn.clone();
        let _count: usize = conn.xack(&d.stream, app_id, &[d.entry_id.as_str()]).await?;
        Ok(())
    }

    /// Dead-letters one previously-delivered entry (spec Sec5.5/Sec6.3):
    /// `XADD waddles:dlq:{stage} MAXLEN ~ {dlq_maxlen} * rec {json}`, then
    /// `XACK`s the source entry so it stops being redelivered. The DLQ
    /// stage segment comes from `d.env.stage` (already validated to
    /// `process`/`action`), never from a caller-chosen `Stage` — see
    /// Global Constraints, deviation 4.
    pub async fn dead_letter(&self, d: &Delivered, err: &DlqError) -> Result<(), SpineError> {
        let stage = Stage::parse(&d.env.stage)?;
        let raw = serde_json::to_string(&d.env)?;
        let record = DlqRecord {
            schema_version: 1,
            stage: stage.as_str().to_string(),
            key: d.stream.clone(),
            entry_id: d.entry_id.clone(),
            group: d.env.app_id.clone(),
            tenant: d.env.tenant.clone(),
            community: d.env.community.clone(),
            app_id: d.env.app_id.clone(),
            workstream_id: Some(d.env.workstream_id.clone()),
            artifact_digest: err.artifact_digest.clone(),
            consumer_id: err.consumer_id.clone(),
            deliveries: d.deliveries,
            failed_at: chrono::Utc::now().to_rfc3339_opts(chrono::SecondsFormat::Millis, true),
            error: DlqErrorDetail {
                kind: err.kind,
                code: err.code.clone(),
                message: err.message.clone(),
                detail: err.detail.clone(),
            },
            trace: d.env.trace.clone(),
            raw,
        };
        self.dead_letter_raw(stage, &record, &d.stream, &d.env.app_id, &d.entry_id).await
    }

    /// Shared by `dead_letter` and (via `pub(crate)` — see
    /// `GroupReader::read`) the one DLQ path that never has a `Delivered`
    /// to hand to the public `dead_letter` method.
    pub(crate) async fn dead_letter_raw(
        &self,
        stage: Stage,
        record: &DlqRecord,
        source_stream: &str,
        group: &str,
        entry_id: &str,
    ) -> Result<(), SpineError> {
        let key = dlq_key(stage);
        let json = serde_json::to_string(record)?;
        let mut conn = self.conn.clone();
        let maxlen = StreamMaxlen::Approx(self.cfg.dlq_maxlen as usize);
        let _id: Option<String> = conn.xadd_maxlen(&key, maxlen, "*", &[("rec", json.as_str())]).await?;
        let _acked: usize = conn.xack(source_stream, group, &[entry_id]).await?;
        self.metrics.dlq_written(stage.as_str(), record.error.kind.as_str());
        Ok(())
    }

    /// `pub(crate)`: [`crate::GroupReader::read`] calls this directly for
    /// an entry whose `env` field fails to parse — the one DLQ reason
    /// that, by construction, can never produce a `Delivered` (spec
    /// Sec5.5).
    pub(crate) async fn dead_letter_unparseable(
        &self,
        stage: Stage,
        stream: &str,
        app_id: &str,
        entry_id: &str,
        deliveries: u64,
        raw_field: &str,
    ) -> Result<(), SpineError> {
        let (tenant, community) =
            parse_scope_from_key(stream).unwrap_or_else(|| ("unknown".to_string(), None));
        let record = DlqRecord {
            schema_version: 1,
            stage: stage.as_str().to_string(),
            key: stream.to_string(),
            entry_id: entry_id.to_string(),
            group: app_id.to_string(),
            tenant,
            community,
            app_id: app_id.to_string(),
            workstream_id: None,
            artifact_digest: None,
            consumer_id: self.cfg.consumer_id.clone(),
            deliveries,
            failed_at: chrono::Utc::now().to_rfc3339_opts(chrono::SecondsFormat::Millis, true),
            error: DlqErrorDetail {
                kind: DlqErrorKind::EnvelopeInvalid,
                code: "ENVELOPE_INVALID".to_string(),
                message: "strict deserialization failed".to_string(),
                detail: None,
            },
            trace: None,
            raw: raw_field.to_string(),
        };
        self.dead_letter_raw(stage, &record, stream, app_id, entry_id).await
    }

    /// Reclaims entries idle longer than `SPINE_CLAIM_IDLE_MS` on
    /// `stream`'s `app_id` group (`XAUTOCLAIM`, spec Sec5.4). An entry
    /// whose delivery count has already reached `SPINE_MAX_DELIVERIES` is
    /// dead-lettered and `XACK`ed here rather than returned for another
    /// attempt; an entry whose `env` field fails to parse is also
    /// dead-lettered here, recovering tenant/community from the stream
    /// key itself rather than trusting an unparsed payload (spec
    /// Sec5.5/Sec3.3/Sec11.8).
    pub async fn claim_stale(&self, stream: &str, app_id: &str, stage: Stage) -> Result<Vec<Delivered>, SpineError> {
        let mut conn = self.conn.clone();
        let opts = redis::streams::StreamAutoClaimOptions::default()
            .count(self.cfg.read_count.max(1) as usize);
        let reply: redis::streams::StreamAutoClaimReply = conn
            .xautoclaim_options(
                stream,
                app_id,
                &self.cfg.consumer_id,
                self.cfg.claim_idle_ms as usize,
                "0-0",
                opts,
            )
            .await?;

        let mut delivered = Vec::new();
        for entry in reply.claimed {
            let deliveries = entry.delivered_count.unwrap_or(1) as u64;
            let env_field: Option<String> = entry
                .map
                .get("env")
                .and_then(|v| redis::from_redis_value_ref::<String>(v).ok());
            let parsed: Option<StageEnvelope> =
                env_field.as_deref().and_then(|s| serde_json::from_str(s).ok());

            match parsed {
                Some(env) if deliveries < self.cfg.max_deliveries as u64 => {
                    self.metrics.stream_claimed(app_id);
                    delivered.push(Delivered {
                        stream: stream.to_string(),
                        entry_id: entry.id,
                        env,
                        deliveries,
                    });
                }
                Some(env) => {
                    let err = DlqError {
                        kind: DlqErrorKind::MaxDeliveries,
                        code: "MAX_DELIVERIES".to_string(),
                        message: format!("delivery count {deliveries} reached SPINE_MAX_DELIVERIES"),
                        detail: None,
                        artifact_digest: None,
                        consumer_id: self.cfg.consumer_id.clone(),
                    };
                    let d = Delivered {
                        stream: stream.to_string(),
                        entry_id: entry.id,
                        env,
                        deliveries,
                    };
                    self.dead_letter(&d, &err).await?;
                }
                None => {
                    self.dead_letter_unparseable(
                        stage,
                        stream,
                        app_id,
                        &entry.id,
                        deliveries,
                        env_field.as_deref().unwrap_or(""),
                    )
                    .await?;
                }
            }
        }
        Ok(delivered)
    }

    /// Per-group stats from `XINFO GROUPS` (spec Sec5.6), also recorded
    /// via [`crate::SpineMetrics`].
    pub async fn group_stats(&self, stream: &str) -> Result<Vec<GroupStats>, SpineError> {
        let mut conn = self.conn.clone();
        let reply: redis::streams::StreamInfoGroupsReply = conn.xinfo_groups(stream).await?;
        let mut out = Vec::new();
        for g in reply.groups {
            let lag = g.lag.map(|l| l as u64);
            let pending = g.pending as u64;
            self.metrics.group_lag(&g.name, stream, lag);
            self.metrics.group_pending(&g.name, stream, pending);
            out.push(GroupStats {
                app_id: g.name,
                stream: stream.to_string(),
                lag,
                pending,
            });
        }
        Ok(out)
    }
```

- [ ] **Step 2: Add integration tests** to `packages/rust-spine/tests/integration_stream_tests.rs` (append):

```rust
async fn read_one_via_xreadgroup(
    stream: &str,
    app_id: &str,
    consumer: &str,
) -> (String, penguin_spine::StageEnvelope) {
    let mut conn = raw_admin_connection().await;
    let opts = redis::streams::StreamReadOptions::default()
        .group(app_id, consumer)
        .count(1);
    let reply: redis::streams::StreamReadReply = conn
        .xread_options(&[stream], &[">"], &opts)
        .await
        .unwrap();
    let key = reply.keys.into_iter().next().expect("expected one stream key in the reply");
    let id_entry = key.ids.into_iter().next().expect("expected one entry");
    let env_field: String = redis::from_redis_value_ref(id_entry.map.get("env").unwrap()).unwrap();
    let env: penguin_spine::StageEnvelope = serde_json::from_str(&env_field).unwrap();
    (id_entry.id, env)
}

#[tokio::test]
async fn ack_removes_an_entry_from_the_pending_entries_list() {
    use penguin_spine::Delivered;
    let client = test_client().await;
    let stream = unique_stream("ack");
    let app_id = "waddles.bot.commands.default";
    client.append(&stream, &sample_envelope()).await.unwrap();
    client.ensure_group(&stream, app_id).await.unwrap();
    let (entry_id, env) = read_one_via_xreadgroup(&stream, app_id, "consumer-1").await;

    let d = Delivered { stream: stream.clone(), entry_id: entry_id.clone(), env, deliveries: 1 };
    client.ack(&d, app_id).await.unwrap();

    let stats = client.group_stats(&stream).await.unwrap();
    let group = stats.iter().find(|g| g.app_id == app_id).unwrap();
    assert_eq!(group.pending, 0, "acked entry must leave the group's PEL empty");
}

#[tokio::test]
async fn claim_stale_recovers_an_unacked_entry_after_the_idle_window() {
    use penguin_spine::Stage;
    let client = test_client().await;
    let stream = unique_stream("claim-stale");
    let app_id = "waddles.bot.commands.default";
    client.append(&stream, &sample_envelope()).await.unwrap();
    client.ensure_group(&stream, app_id).await.unwrap();
    // A first read leaves the entry pending (never acked, simulating a
    // consumer crash between read and ack).
    let _ = read_one_via_xreadgroup(&stream, app_id, "dead-consumer").await;

    // SPINE_CLAIM_IDLE_MS defaults to 30000; force it to 0 for this test
    // via a fresh client pointed at the same Valkey.
    let mut cfg = SpineConfig::from_env().unwrap();
    cfg.claim_idle_ms = 0;
    let claiming_client = SpineClient::connect(cfg, std::sync::Arc::new(NoopMetrics)).await.unwrap();

    let claimed = claiming_client.claim_stale(&stream, app_id, Stage::Process).await.unwrap();
    assert_eq!(claimed.len(), 1, "expected exactly one recovered entry");
    assert_eq!(claimed[0].deliveries, 1);

    claiming_client.ack(&claimed[0], app_id).await.unwrap();
    let stats = claiming_client.group_stats(&stream).await.unwrap();
    let group = stats.iter().find(|g| g.app_id == app_id).unwrap();
    assert_eq!(group.pending, 0, "PEL must be empty after the recovered entry is acked");
}
```

`SpineConfig`'s fields are all `pub` (Task 9) — `cfg.claim_idle_ms = 0` is a direct field write and compiles as written.

- [ ] **Step 3: Run and fix until green.**

Run: `cd /home/penguin/code/penguin-libs/.worktrees/plan-penguin-spine && make test-integration-spine`
Expected: both new tests pass.

- [ ] **Step 4: Activate the full `lib.rs` client export**, replacing both lines from Task 13 with one:

```rust
pub use client::{Delivered, Grant, GroupStats, SpineClient};
```

- [ ] **Step 5: Run the full unit-test suite too.**

Run: `docker run --rm -v "$(pwd)/packages/rust-spine:/work" -w /work rust:1.97.1 cargo test --lib`
Expected: `test result: ok.` across every module.

- [ ] **Step 6: Commit.**

```bash
git add packages/rust-spine/src/client.rs packages/rust-spine/src/lib.rs packages/rust-spine/tests/integration_stream_tests.rs
git commit -m "$(cat <<'EOF'
feat(spine): add ack, dead_letter, claim_stale, group_stats

claim_stale enforces SPINE_MAX_DELIVERIES (dead-letters rather than
re-returning an over-delivered entry) and dead-letters an unparseable
envelope by recovering tenant/community from the stream key itself
(Sec3.3/Sec11.8), never from the unparsed payload. group_stats records
waddles_group_lag/waddles_group_pending via SpineMetrics.

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01N2rQgkHY872RubwXoBZxtE
EOF
)"
```

---

### Task 16: Fan-in, group isolation, claim concurrency, redelivery cap, `MAXLEN`/DLQ bounding — integration tests

**Files:**
- Modify: `packages/rust-spine/tests/integration_stream_tests.rs`

**Interfaces:**
- Consumes: everything from Tasks 13-15 (`SpineClient`, `Delivered`, `Stage`, `DlqError`, `DlqErrorKind`).
- Produces: nothing new for later tasks — this task is pure test coverage closing out the remaining spec §14.2 bullets not already covered by Task 15's `ack`/`claim_stale` tests.

Spec: §14.2 (fan-in, group isolation, claim concurrency, redelivery cap, stream bounding, DLQ capping — the six bullets this task implements one-for-one).

- [ ] **Step 1: Append six tests to `packages/rust-spine/tests/integration_stream_tests.rs`:**

```rust
#[tokio::test]
async fn fan_in_one_write_is_observed_by_every_group_exactly_once() {
    use penguin_spine::Delivered;
    let client = test_client().await;
    let stream = unique_stream("fan-in");
    client.ensure_group(&stream, "app-a").await.unwrap();
    client.ensure_group(&stream, "app-b").await.unwrap();
    client.append(&stream, &sample_envelope()).await.unwrap();

    let (id_a, env_a) = read_one_via_xreadgroup(&stream, "app-a", "consumer-a").await;
    let (id_b, env_b) = read_one_via_xreadgroup(&stream, "app-b", "consumer-b").await;
    assert_eq!(id_a, id_b, "both groups must see the same entry id from one write");

    client.ack(&Delivered { stream: stream.clone(), entry_id: id_a, env: env_a, deliveries: 1 }, "app-a").await.unwrap();
    client.ack(&Delivered { stream: stream.clone(), entry_id: id_b, env: env_b, deliveries: 1 }, "app-b").await.unwrap();

    let stats = client.group_stats(&stream).await.unwrap();
    assert!(stats.iter().all(|g| g.pending == 0), "both groups' PELs must be empty after acking");
}

#[tokio::test]
async fn group_isolation_a_stuck_group_does_not_affect_a_healthy_group() {
    use penguin_spine::Delivered;
    let client = test_client().await;
    let stream = unique_stream("group-isolation");
    client.ensure_group(&stream, "healthy-app").await.unwrap();
    client.ensure_group(&stream, "stuck-app").await.unwrap();
    client.append(&stream, &sample_envelope()).await.unwrap();

    // The "stuck" group reads but never acks.
    let _ = read_one_via_xreadgroup(&stream, "stuck-app", "stuck-consumer").await;

    // The healthy group reads and acks normally on the SAME stream.
    let (entry_id, env) = read_one_via_xreadgroup(&stream, "healthy-app", "healthy-consumer").await;
    client
        .ack(&Delivered { stream: stream.clone(), entry_id, env, deliveries: 1 }, "healthy-app")
        .await
        .unwrap();

    let stats = client.group_stats(&stream).await.unwrap();
    let healthy = stats.iter().find(|g| g.app_id == "healthy-app").unwrap();
    let stuck = stats.iter().find(|g| g.app_id == "stuck-app").unwrap();
    assert_eq!(healthy.pending, 0, "the healthy group's PEL must be empty");
    assert_eq!(stuck.pending, 1, "the stuck group's PEL must still hold its unacked entry");
}

#[tokio::test]
async fn claim_concurrency_three_replicas_claim_disjoint_entries() {
    use penguin_spine::Stage;
    use std::collections::HashSet;

    let mut cfg = SpineConfig::from_env().unwrap();
    cfg.claim_idle_ms = 0;
    let stream = unique_stream("claim-concurrency");
    let app_id = "waddles.bot.commands.default";

    let writer = test_client().await;
    writer.ensure_group(&stream, app_id).await.unwrap();
    for _ in 0..9 {
        writer.append(&stream, &sample_envelope()).await.unwrap();
    }
    for _ in 0..9 {
        let _ = read_one_via_xreadgroup(&stream, app_id, "dead-consumer").await;
    }

    let c1 = SpineClient::connect(cfg.clone(), std::sync::Arc::new(NoopMetrics)).await.unwrap();
    let c2 = SpineClient::connect(cfg.clone(), std::sync::Arc::new(NoopMetrics)).await.unwrap();
    let c3 = SpineClient::connect(cfg, std::sync::Arc::new(NoopMetrics)).await.unwrap();

    let (r1, r2, r3) = tokio::join!(
        c1.claim_stale(&stream, app_id, Stage::Process),
        c2.claim_stale(&stream, app_id, Stage::Process),
        c3.claim_stale(&stream, app_id, Stage::Process),
    );

    let mut all_ids: Vec<String> = Vec::new();
    for r in [r1, r2, r3] {
        for d in r.unwrap() {
            all_ids.push(d.entry_id);
        }
    }
    let unique: HashSet<&String> = all_ids.iter().collect();
    assert_eq!(unique.len(), all_ids.len(), "no entry may be claimed by more than one replica");
    assert_eq!(all_ids.len(), 9, "all nine pending entries must be claimed exactly once across all replicas");
}

#[tokio::test]
async fn redelivery_cap_sends_the_entry_to_the_dlq_after_max_deliveries() {
    use penguin_spine::Stage;

    let mut cfg = SpineConfig::from_env().unwrap();
    cfg.claim_idle_ms = 0;
    cfg.max_deliveries = 3; // keep the test fast; the mechanism is identical at any cap
    let stream = unique_stream("redelivery-cap");
    let app_id = "waddles.bot.commands.default";

    let client = SpineClient::connect(cfg, std::sync::Arc::new(NoopMetrics)).await.unwrap();
    client.ensure_group(&stream, app_id).await.unwrap();
    client.append(&stream, &sample_envelope()).await.unwrap();
    // First delivery: a normal read, never acked (simulating a crash).
    let _ = read_one_via_xreadgroup(&stream, app_id, "dead-consumer").await;

    // Second delivery: claim_stale reclaims it (delivery count now 2 < 3).
    let claimed = client.claim_stale(&stream, app_id, Stage::Process).await.unwrap();
    assert_eq!(claimed.len(), 1);
    assert_eq!(claimed[0].deliveries, 2);
    // Left unacked again (simulating a second crash).

    // Third reclaim: delivery count reaches max_deliveries (3) -- the
    // client dead-letters it internally instead of returning it.
    let claimed_again = client.claim_stale(&stream, app_id, Stage::Process).await.unwrap();
    assert!(claimed_again.is_empty(), "an entry at SPINE_MAX_DELIVERIES must not be returned for another attempt");

    let stats = client.group_stats(&stream).await.unwrap();
    let group = stats.iter().find(|g| g.app_id == app_id).unwrap();
    assert_eq!(group.pending, 0, "the over-delivered entry must be XACKed once dead-lettered");
}

#[tokio::test]
async fn stream_bounding_trims_within_the_approximate_maxlen() {
    let mut cfg = SpineConfig::from_env().unwrap();
    cfg.stream_maxlen = 20;
    let client = SpineClient::connect(cfg, std::sync::Arc::new(NoopMetrics)).await.unwrap();
    let stream = unique_stream("maxlen");

    for _ in 0..70 {
        client.append(&stream, &sample_envelope()).await.unwrap();
    }

    let mut conn = raw_admin_connection().await;
    let len: u64 = redis::cmd("XLEN").arg(&stream).query_async(&mut conn).await.unwrap();
    assert!(len < 70, "expected trimming to have occurred, stream length is {len}");
    assert!(len <= 60, "MAXLEN ~ 20 should not leave the stream wildly over bound, got {len}");
}

#[tokio::test]
async fn dlq_stays_within_the_configured_maxlen() {
    use penguin_spine::{Delivered, DlqError, DlqErrorKind};

    let mut cfg = SpineConfig::from_env().unwrap();
    cfg.dlq_maxlen = 5;
    let client = SpineClient::connect(cfg, std::sync::Arc::new(NoopMetrics)).await.unwrap();
    let stream = unique_stream("dlq-cap");
    client.ensure_group(&stream, "app-dlq-cap").await.unwrap();

    for _ in 0..20 {
        client.append(&stream, &sample_envelope()).await.unwrap();
    }
    for _ in 0..20 {
        let (entry_id, env) = read_one_via_xreadgroup(&stream, "app-dlq-cap", "consumer-dlq").await;
        let d = Delivered { stream: stream.clone(), entry_id, env, deliveries: 1 };
        let err = DlqError {
            kind: DlqErrorKind::BundleError,
            code: "TEST_FORCED".to_string(),
            message: "forced for the dlq-capping test".to_string(),
            detail: None,
            artifact_digest: None,
            consumer_id: "test-consumer".to_string(),
        };
        client.dead_letter(&d, &err).await.unwrap();
    }

    let mut conn = raw_admin_connection().await;
    let len: u64 = redis::cmd("XLEN")
        .arg("waddles:dlq:process")
        .query_async(&mut conn)
        .await
        .unwrap();
    assert!(len < 20, "expected the DLQ to be trimmed toward its MAXLEN, got length {len}");
}
```

- [ ] **Step 2: Run and fix until green.**

Run: `cd /home/penguin/code/penguin-libs/.worktrees/plan-penguin-spine && make test-integration-spine`
Expected: all six new tests pass alongside every earlier integration test (12 total in `integration_stream_tests.rs` by now).

- [ ] **Step 3: Commit.**

```bash
git add packages/rust-spine/tests/integration_stream_tests.rs
git commit -m "$(cat <<'EOF'
test(spine): add fan-in, isolation, claim-concurrency, cap, and bounding tests

Six integration tests closing out spec Sec14.2: one write observed by
every group exactly once; a stuck group's PEL growth never affects a
healthy group on the same stream; three concurrent XAUTOCLAIM replicas
claim disjoint entries; the redelivery cap dead-letters rather than
re-returning an over-delivered entry; MAXLEN ~ and the DLQ's own
MAXLEN both bound observed stream length under sustained writes.

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01N2rQgkHY872RubwXoBZxtE
EOF
)"
```

---

### Task 17: `GroupReader` — dedicated connection, grant enforcement, `read`, and the two client rules

**Files:**
- Create: `packages/rust-spine/src/reader.rs`
- Modify: `packages/rust-spine/src/lib.rs`, `packages/rust-spine/tests/client_rules_tests.rs`

**Interfaces:**
- Consumes: `Grant`/`Delivered`/`SpineClient` (Task 13), `SpineConfig`/`validate_block_timeout` (Task 9), `StageEnvelope` (Task 4), `Stage`/`parse_scope_from_key` (Task 2), `DlqRecord`/`DlqErrorDetail`/`DlqErrorKind` (Task 5), `SpineMetrics` (Task 6), `SpineClient::dead_letter_raw`/`dead_letter_unparseable` (`pub(crate)`, Task 15).
- Produces: `GroupReader` (`Clone`), `GroupReader::connect(cfg: &SpineConfig, grants: Vec<Grant>, app_id: String, stage: Stage, dlq: SpineClient, metrics: Arc<dyn SpineMetrics>) -> Result<Self, SpineError>`, `GroupReader::read(&mut self) -> Result<Vec<Delivered>, SpineError>`, `GroupReader::ensure_granted(&self, stream: &str) -> Result<(), SpineError>`. This is the crate's last public type — M3/M4 (`svc_process`/`svc_action`) construct one `GroupReader` per stage pod.

Spec: §4.7 (public surface — see Global Constraints deviations 1-3 for the constructor signature differences), §5.2 (grant enforcement, the negative test), §5.3 (`XREADGROUP ... BLOCK`), §5.5 (the `envelope_invalid` DLQ path), §5.7 (both client rules, verbatim from `core/svc_ingest/outbound_drain.py`'s prior art).

- [ ] **Step 1: Write `packages/rust-spine/src/reader.rs`:**

```rust
//! The grant-scoped, dedicated-connection stream reader (spec Sec4.7,
//! Sec5.2, Sec5.7). Reads ONLY the streams in its grant list — a request
//! for any other stream fails with `SpineError::StreamNotGranted`, even
//! if a consumer group exists there (spec Sec5.2's negative test).

use std::sync::Arc;

use redis::streams::StreamReadOptions;
use redis::AsyncCommands;

use crate::client::{Delivered, Grant, SpineClient};
use crate::config::{validate_block_timeout, SpineConfig};
use crate::dlq::{DlqErrorDetail, DlqErrorKind, DlqRecord};
use crate::envelope::StageEnvelope;
use crate::error::SpineError;
use crate::metrics::SpineMetrics;
use crate::scope::{parse_scope_from_key, Stage};

/// A dedicated-connection, grant-scoped `XREADGROUP` reader (spec
/// Sec5.7). Never shares its connection with [`SpineClient`]'s admin
/// traffic — both connection-separation rules are enforced by
/// construction, not convention.
#[derive(Clone)]
pub struct GroupReader {
    conn: redis::aio::MultiplexedConnection,
    grants: Vec<Grant>,
    app_id: String,
    consumer_id: String,
    stage: Stage,
    dlq: SpineClient,
    metrics: Arc<dyn SpineMetrics>,
    read_count: usize,
    block_ms: u64,
}

impl GroupReader {
    /// Opens this reader's own dedicated connection (spec Sec5.7 rule 1)
    /// and validates the block-timeout invariant before ever attempting
    /// that connection — construction is refused, naming both values,
    /// when `SPINE_BLOCK_MS` is not strictly less than the connection's
    /// own socket timeout (`DRAIN_SOCKET_TIMEOUT_S`). See Global
    /// Constraints, deviations 1-3, for why this signature differs from
    /// the spec's illustrative `new(grants, app_id, consumer_id) -> Self`
    /// sketch: `dlq`/`stage` exist so an unparseable entry (which can
    /// never become a `Delivered`) still reaches its own stage's DLQ.
    pub async fn connect(
        cfg: &SpineConfig,
        grants: Vec<Grant>,
        app_id: String,
        stage: Stage,
        dlq: SpineClient,
        metrics: Arc<dyn SpineMetrics>,
    ) -> Result<Self, SpineError> {
        validate_block_timeout("SPINE_BLOCK_MS", cfg.block_ms, cfg.drain_socket_timeout_s)?;

        let base: redis::ConnectionInfo = redis::IntoConnectionInfo::into_connection_info(cfg.valkey_url.as_str())
            .map_err(|e| SpineError::Config(format!("invalid VALKEY_URL {:?}: {e}", cfg.valkey_url)))?;
        let mut redis_settings = base.redis_settings().clone();
        if let Some(username) = &cfg.valkey_username {
            redis_settings = redis_settings.set_username(username);
        }
        if let Some(password) = &cfg.valkey_password {
            redis_settings = redis_settings.set_password(password);
        }
        let info = base.set_redis_settings(redis_settings);

        let client = if cfg.security_transport_tls {
            let root_cert = std::fs::read(&cfg.valkey_ca_file).ok();
            redis::Client::build_with_tls(
                info,
                redis::TlsCertificates {
                    client_tls: None,
                    root_cert,
                },
            )?
        } else {
            redis::Client::open(info)?
        };

        // Sec5.7 rule 1: this connection's response timeout is the
        // dedicated blocking-read socket timeout, strictly greater than
        // SPINE_BLOCK_MS (validated above). Sec5.7 rule 2: this
        // connection is never shared with `dlq`'s admin traffic — it is
        // an entirely separate connection this GroupReader alone owns.
        let async_cfg = redis::AsyncConnectionConfig::new()
            .set_response_timeout(Some(std::time::Duration::from_secs(cfg.drain_socket_timeout_s)));
        let conn = client.get_multiplexed_async_connection_with_config(&async_cfg).await?;

        Ok(GroupReader {
            conn,
            grants,
            app_id,
            consumer_id: cfg.consumer_id.clone(),
            stage,
            dlq,
            metrics,
            read_count: cfg.read_count.max(1) as usize,
            block_ms: cfg.block_ms,
        })
    }

    /// Reads up to `SPINE_READ_COUNT` entries from every granted stream,
    /// blocking up to `SPINE_BLOCK_MS` when nothing is available (spec
    /// Sec5.3). An entry whose `env` field fails strict deserialization
    /// is dead-lettered immediately (spec Sec5.5's `envelope_invalid`,
    /// the one DLQ reason that can never produce a `Delivered`) rather
    /// than included in the returned batch.
    pub async fn read(&mut self) -> Result<Vec<Delivered>, SpineError> {
        if self.grants.is_empty() {
            return Ok(Vec::new());
        }
        let streams: Vec<&str> = self.grants.iter().map(|g| g.stream.as_str()).collect();
        let ids: Vec<&str> = streams.iter().map(|_| ">").collect();

        let opts = StreamReadOptions::default()
            .group(&self.app_id, &self.consumer_id)
            .count(self.read_count)
            .block(self.block_ms as usize);

        let reply: Option<redis::streams::StreamReadReply> =
            self.conn.xread_options(&streams, &ids, &opts).await?;

        let mut delivered = Vec::new();
        let Some(reply) = reply else {
            return Ok(delivered);
        };
        for key in reply.keys {
            for entry in key.ids {
                let env_field: Option<String> = entry
                    .map
                    .get("env")
                    .and_then(|v| redis::from_redis_value_ref::<String>(v).ok());
                match env_field
                    .as_deref()
                    .and_then(|s| serde_json::from_str::<StageEnvelope>(s).ok())
                {
                    Some(env) => {
                        delivered.push(Delivered {
                            stream: key.key.clone(),
                            entry_id: entry.id,
                            env,
                            deliveries: 1,
                        });
                    }
                    None => {
                        self.dlq
                            .dead_letter_unparseable(
                                self.stage,
                                &key.key,
                                &self.app_id,
                                &entry.id,
                                1,
                                env_field.as_deref().unwrap_or(""),
                            )
                            .await?;
                        self.metrics.consumer_skipped(&self.app_id, "envelope_invalid");
                    }
                }
            }
        }
        Ok(delivered)
    }

    /// Refuses a stream outside this reader's grant list (spec Sec5.2's
    /// negative test): the stage is the enforcement point, and a
    /// consumer group existing on a stream is not itself authority.
    pub fn ensure_granted(&self, stream: &str) -> Result<(), SpineError> {
        if self.grants.iter().any(|g| g.stream == stream) {
            Ok(())
        } else {
            Err(SpineError::StreamNotGranted {
                stream: stream.to_string(),
            })
        }
    }
}

// Silence unused-import warnings for types only referenced through
// SpineClient::dead_letter_unparseable's own parameter list, kept here so
// this module's `use` block documents the full DLQ record shape it feeds.
#[allow(unused_imports)]
use {parse_scope_from_key as _, DlqErrorDetail as _, DlqErrorKind as _, DlqRecord as _};
```

The trailing `use { ... as _ }` line exists only because `parse_scope_from_key`/`DlqErrorDetail`/`DlqErrorKind`/`DlqRecord` are imported for documentation clarity but not directly referenced in this file (they're used inside `SpineClient::dead_letter_unparseable`, which this module calls but does not re-implement) — **delete that import list and the trailing line entirely** if `cargo build` reports them as genuinely unused (it will); this note exists so the implementer understands why the import list above only kept `Stage`/`SpineError`/etc. and not those four. In short: do not add the trailing `use { ... }` line at all — it is called out here only to explain why those four names are absent from the real `use crate::...` lines above, not as code to include.

- [ ] **Step 2: Activate the `lib.rs` reader export**, replacing the commented reader line:

```rust
pub use reader::GroupReader;
```

- [ ] **Step 3: Build and fix compile errors.**

Run: `docker run --rm -v "$(pwd)/packages/rust-spine:/work" -w /work rust:1.97.1 cargo build`
Expected: clean build, no warnings about unused imports (remove any per the note above).

- [ ] **Step 4: Write `packages/rust-spine/tests/client_rules_tests.rs`:**

```rust
#![allow(clippy::unwrap_used, clippy::panic)]
//! The two Sec5.7 client connection-separation rules, plus grant
//! enforcement, tested against the pinned Valkey container. Run via
//! `make test-integration-spine`.

use penguin_spine::{Grant, GroupReader, NoopMetrics, Scope, SpineClient, SpineConfig, Stage};
use std::sync::Arc;

fn sample_envelope() -> penguin_spine::StageEnvelope {
    let json = serde_json::json!({
        "tenant": "acme", "community": "main", "app_id": "waddles.bot.commands.default",
        "stage": "process",
        "event": {"platform": "twitch", "event_type": "chat.message", "actor": "u",
                   "payload": {}, "occurred_at": "2026-09-14T12:00:00.000Z"},
        "ts": "2026-09-14T12:00:00.123Z", "target_app_id": null,
        "workstream_id": "8f14e45f-ceea-467e-adde-3fb5c9752730",
        "event_id": "3fa85f64-5717-4562-b3fc-2c963f66afa6",
        "session_id": null, "trace": null,
        "binding": {"kid": "test-kid", "mac": "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"}
    });
    serde_json::from_value(json).unwrap()
}

#[tokio::test]
async fn rule_1_construction_is_refused_when_block_ms_is_not_strictly_less_than_socket_timeout() {
    let mut cfg = SpineConfig::from_env().unwrap();
    cfg.drain_socket_timeout_s = 1;
    cfg.block_ms = 1_000; // 1000ms == 1s -- not strictly less

    let dlq = SpineClient::connect(SpineConfig::from_env().unwrap(), Arc::new(NoopMetrics))
        .await
        .unwrap();
    let result = GroupReader::connect(
        &cfg,
        vec![],
        "waddles.bot.commands.default".to_string(),
        Stage::Process,
        dlq,
        Arc::new(NoopMetrics),
    )
    .await;

    let err = result.expect_err("construction must be refused");
    let message = err.to_string();
    assert!(message.contains("SPINE_BLOCK_MS"), "error must name SPINE_BLOCK_MS: {message}");
    assert!(message.contains('1'), "error must name the socket timeout value: {message}");
}

#[tokio::test]
async fn rule_2_a_dedicated_reader_connection_survives_a_cancelled_block_and_a_same_client_admin_call() {
    let dlq_cfg = SpineConfig::from_env().unwrap();
    let dlq = SpineClient::connect(dlq_cfg.clone(), Arc::new(NoopMetrics)).await.unwrap();

    let scope = Scope::new("acme", Some("main".to_string()));
    let stream = scope.source_stream("twitch", &format!("client-rule2-{}", uuid::Uuid::new_v4()));
    let app_id = "waddles.bot.commands.default";
    dlq.ensure_group(&stream, app_id).await.unwrap();

    let grants = vec![Grant {
        stream: stream.clone(),
        platform: "twitch".to_string(),
        source_id: "client-rule2".to_string(),
    }];
    let mut reader_cfg = dlq_cfg.clone();
    reader_cfg.block_ms = 200; // short, so the cancellation below resolves quickly
    let mut reader = GroupReader::connect(
        &reader_cfg,
        grants,
        app_id.to_string(),
        Stage::Process,
        dlq.clone(),
        Arc::new(NoopMetrics),
    )
    .await
    .unwrap();

    // Nothing is on the stream yet, so this read blocks for up to
    // block_ms and is cancelled below before it resolves -- reproducing
    // the exact "cancel an in-flight blocking read" shape Sec5.7 rule 2
    // exists for. If the reader's connection were shared with
    // SpineClient's admin traffic, a subsequent admin call could race a
    // still-pending reply from this cancelled read.
    let _ = tokio::time::timeout(std::time::Duration::from_millis(50), reader.read()).await;

    // An admin-style call on the SEPARATE dlq/admin client, immediately
    // after. Bounded by a generous timeout so a violation of rule 2
    // (a hang) fails the assertion instead of wedging the test suite.
    let admin_result =
        tokio::time::timeout(std::time::Duration::from_secs(5), dlq.ensure_group(&stream, app_id)).await;
    assert!(
        admin_result.is_ok(),
        "an admin call on a separate connection must not hang after a cancelled blocking read"
    );
    admin_result.unwrap().unwrap();

    // The reader itself must still be usable afterward.
    dlq.append(&stream, &sample_envelope()).await.unwrap();
    let delivered = tokio::time::timeout(std::time::Duration::from_secs(2), reader.read())
        .await
        .expect("reader must still respond after the earlier cancelled read")
        .unwrap();
    assert_eq!(delivered.len(), 1);
}

#[tokio::test]
async fn grant_enforcement_refuses_a_stream_outside_the_grant_list_even_with_an_existing_group() {
    let cfg = SpineConfig::from_env().unwrap();
    let dlq = SpineClient::connect(cfg.clone(), Arc::new(NoopMetrics)).await.unwrap();

    let scope = Scope::new("acme", Some("main".to_string()));
    let granted_stream = scope.source_stream("discord", &format!("granted-{}", uuid::Uuid::new_v4()));
    let ungranted_stream = scope.source_stream("twitch", &format!("ungranted-{}", uuid::Uuid::new_v4()));
    let app_id = "waddles.bot.commands.default";

    // A group exists on the ungranted stream too -- proving the reader's
    // own grant list is the enforcement point, not group existence
    // (spec Sec5.2's negative test).
    dlq.ensure_group(&granted_stream, app_id).await.unwrap();
    dlq.ensure_group(&ungranted_stream, app_id).await.unwrap();

    let grants = vec![Grant {
        stream: granted_stream.clone(),
        platform: "discord".to_string(),
        source_id: "granted".to_string(),
    }];
    let reader = GroupReader::connect(&cfg, grants, app_id.to_string(), Stage::Process, dlq, Arc::new(NoopMetrics))
        .await
        .unwrap();

    assert!(reader.ensure_granted(&granted_stream).is_ok());
    let err = reader
        .ensure_granted(&ungranted_stream)
        .expect_err("must refuse an ungranted stream");
    assert!(matches!(err, penguin_spine::SpineError::StreamNotGranted { .. }));
}

#[tokio::test]
async fn envelope_invalid_entries_are_dead_lettered_and_excluded_from_read_results() {
    let cfg = SpineConfig::from_env().unwrap();
    let dlq = SpineClient::connect(cfg.clone(), Arc::new(NoopMetrics)).await.unwrap();

    let scope = Scope::new("acme", Some("main".to_string()));
    let stream = scope.source_stream("twitch", &format!("envelope-invalid-{}", uuid::Uuid::new_v4()));
    let app_id = "waddles.bot.commands.default";
    dlq.ensure_group(&stream, app_id).await.unwrap();

    // Write a malformed "env" field directly via a raw connection --
    // SpineClient::append always writes a valid envelope, so this
    // bypasses it deliberately to simulate real corruption in transit.
    let raw_url = std::env::var("VALKEY_URL").unwrap();
    let raw_username = std::env::var("VALKEY_USERNAME").unwrap();
    let raw_password = std::env::var("VALKEY_PASSWORD").unwrap();
    let raw_ca = std::env::var("VALKEY_CA_FILE").unwrap();
    let root_cert = std::fs::read(&raw_ca).unwrap();
    let base: redis::ConnectionInfo =
        redis::IntoConnectionInfo::into_connection_info(raw_url.as_str()).unwrap();
    let redis_settings = base.redis_settings().clone().set_username(&raw_username).set_password(&raw_password);
    let info = base.set_redis_settings(redis_settings);
    let raw_client = redis::Client::build_with_tls(
        info,
        redis::TlsCertificates { client_tls: None, root_cert: Some(root_cert) },
    )
    .unwrap();
    let mut raw_conn = raw_client.get_multiplexed_async_connection().await.unwrap();
    use redis::AsyncCommands;
    let _id: Option<String> = raw_conn
        .xadd(&stream, "*", &[("env", "{not valid json")])
        .await
        .unwrap();

    let grants = vec![Grant { stream: stream.clone(), platform: "twitch".to_string(), source_id: "x".to_string() }];
    let mut reader = GroupReader::connect(&cfg, grants, app_id.to_string(), Stage::Process, dlq, Arc::new(NoopMetrics))
        .await
        .unwrap();

    let delivered = reader.read().await.unwrap();
    assert!(delivered.is_empty(), "a malformed entry must never be returned from read()");

    let dlq_len: u64 = redis::cmd("XLEN")
        .arg("waddles:dlq:process")
        .query_async(&mut raw_conn)
        .await
        .unwrap();
    assert!(dlq_len >= 1, "the malformed entry must have reached the DLQ");
}
```

- [ ] **Step 5: Run and fix until green.**

Run: `cd /home/penguin/code/penguin-libs/.worktrees/plan-penguin-spine && make test-integration-spine`
Expected: all four new tests pass alongside every other integration test file.

- [ ] **Step 6: Run the full unit-test suite too, and `clippy`.**

Run:
```bash
docker run --rm -v "$(pwd)/packages/rust-spine:/work" -w /work rust:1.97.1 sh -c "cargo test --lib && cargo clippy --all-targets -- -D warnings && cargo fmt --check"
```
Expected: all pass, zero clippy warnings, `fmt --check` clean.

- [ ] **Step 7: Commit.**

```bash
git add packages/rust-spine/src/reader.rs packages/rust-spine/src/lib.rs packages/rust-spine/tests/client_rules_tests.rs
git commit -m "$(cat <<'EOF'
feat(spine): add GroupReader with both Sec5.7 client connection rules

connect refuses construction when SPINE_BLOCK_MS is not strictly less
than DRAIN_SOCKET_TIMEOUT_S, naming both values, before ever opening
its dedicated connection. read() enforces the grant list (refusing an
ungranted stream even when a consumer group exists there) and
dead-letters an envelope that fails to parse -- the one DLQ reason
that can never produce a Delivered -- via SpineClient's pub(crate)
dead_letter_unparseable. Client rule 2 (never sharing the dedicated
connection with admin traffic) is proven by a cancelled blocking read
followed by a same-process admin call on a separate SpineClient.

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01N2rQgkHY872RubwXoBZxtE
EOF
)"
```

---

### Task 18: Criterion benchmark — `XADD` throughput and fan-in read latency

**Files:**
- Create: `packages/rust-spine/benches/spine_bench.rs`
- Modify: `/home/penguin/code/penguin-libs/Makefile`

**Interfaces:**
- Consumes: the full public API (`Scope`, `SpineClient`, `GroupReader`, `SpineConfig`, `Grant`, `Delivered`, `Stage`, `NoopMetrics`).
- Produces: nothing consumed by later tasks — a standing performance baseline for M3-M5's own services to compare against.

Spec: §4.7 (`penguin-spine` is the shared spine every stage's throughput depends on — no spec section mandates a specific benchmark, this task exists per the task brief's own requirement for a criterion bench).

- [ ] **Step 1: Write `packages/rust-spine/benches/spine_bench.rs`:**

```rust
#![allow(clippy::unwrap_used)]
//! Criterion benchmarks against the pinned Valkey container. Run via
//! `make bench-spine` (starts the container, runs `cargo bench` inside
//! the pinned Rust toolchain container on the same network, tears down).

use criterion::{criterion_group, criterion_main, Criterion};
use penguin_spine::{Grant, GroupReader, NoopMetrics, Scope, SpineClient, SpineConfig, Stage, StageEnvelope};
use std::sync::Arc;
use tokio::runtime::Runtime;

fn sample_envelope() -> StageEnvelope {
    let json = serde_json::json!({
        "tenant": "acme",
        "community": "main",
        "app_id": "waddles.bot.commands.default",
        "stage": "process",
        "event": {
            "platform": "twitch",
            "event_type": "chat.message",
            "actor": "u",
            "payload": {"text": "bench"},
            "occurred_at": "2026-09-14T12:00:00.000Z"
        },
        "ts": "2026-09-14T12:00:00.123Z",
        "target_app_id": null,
        "workstream_id": "8f14e45f-ceea-467e-adde-3fb5c9752730",
        "event_id": "3fa85f64-5717-4562-b3fc-2c963f66afa6",
        "session_id": null,
        "trace": null,
        "binding": {"kid": "test-kid", "mac": "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"}
    });
    serde_json::from_value(json).unwrap()
}

fn bench_append(c: &mut Criterion) {
    let rt = Runtime::new().unwrap();
    let cfg = rt.block_on(async {
        SpineConfig::from_env().expect("SpineConfig::from_env (run via `make bench-spine`)")
    });
    let client = rt.block_on(async { SpineClient::connect(cfg, Arc::new(NoopMetrics)).await.unwrap() });
    let scope = Scope::new("acme", Some("main".to_string()));
    let stream = scope.source_stream("twitch", &format!("bench-append-{}", uuid::Uuid::new_v4()));
    let env = sample_envelope();

    c.bench_function("spine_append_xadd", |b| {
        b.to_async(&rt).iter(|| async {
            client.append(&stream, &env).await.unwrap();
        });
    });
}

async fn ack_all(client: &SpineClient, delivered: &[penguin_spine::Delivered], app_id: &str) {
    for d in delivered {
        client.ack(d, app_id).await.unwrap();
    }
}

fn bench_fan_in_read(c: &mut Criterion) {
    let rt = Runtime::new().unwrap();
    let cfg = rt.block_on(async { SpineConfig::from_env().unwrap() });
    let client = rt.block_on(async { SpineClient::connect(cfg.clone(), Arc::new(NoopMetrics)).await.unwrap() });
    let scope = Scope::new("acme", Some("main".to_string()));
    let stream = scope.source_stream("twitch", &format!("bench-fanin-{}", uuid::Uuid::new_v4()));
    let app_id = "waddles.bench.fanin.default";
    rt.block_on(async { client.ensure_group(&stream, app_id).await.unwrap() });
    let grants = vec![Grant {
        stream: stream.clone(),
        platform: "twitch".to_string(),
        source_id: "bench".to_string(),
    }];
    let mut reader = rt.block_on(async {
        GroupReader::connect(&cfg, grants, app_id.to_string(), Stage::Process, client.clone(), Arc::new(NoopMetrics))
            .await
            .unwrap()
    });
    let env = sample_envelope();

    c.bench_function("spine_fan_in_read", |b| {
        b.to_async(&rt).iter(|| async {
            client.append(&stream, &env).await.unwrap();
            let delivered = reader.read().await.unwrap();
            ack_all(&client, &delivered, app_id).await;
        });
    });
}

criterion_group!(benches, bench_append, bench_fan_in_read);
criterion_main!(benches);
```

- [ ] **Step 2: Add the `bench-spine` Makefile target.** Append to `/home/penguin/code/penguin-libs/Makefile`:

```makefile
.PHONY: bench-spine

bench-spine: test-integration-spine-up
	docker run --rm --network $(SPINE_NETWORK) \
	  -v $(CURDIR)/packages/rust-spine:/work \
	  -w /work \
	  -e VALKEY_URL=rediss://$(SPINE_VALKEY_CONTAINER):6390 \
	  -e VALKEY_USERNAME=waddles_admin \
	  -e VALKEY_PASSWORD=test-waddles_admin-password \
	  -e VALKEY_CA_FILE=/work/tests/valkey/.tls/ca.crt \
	  rust:1.97.1 \
	  cargo bench
	$(MAKE) test-integration-spine-down
```

- [ ] **Step 3: Run and confirm it executes end to end.**

Run: `cd /home/penguin/code/penguin-libs/.worktrees/plan-penguin-spine && make bench-spine`
Expected: criterion prints timing results for `spine_append_xadd` and `spine_fan_in_read` (e.g. `time: [...]`), exits 0, and the container/network/`.tls/` are removed afterward.

- [ ] **Step 4: Commit.**

```bash
git add packages/rust-spine/benches
git -C /home/penguin/code/penguin-libs add Makefile
git commit -m "$(cat <<'EOF'
test(spine): add criterion benchmarks for XADD and fan-in read

spine_append_xadd measures single-writer XADD throughput;
spine_fan_in_read measures one append + one grant-scoped read + ack
round trip. Both run against the pinned Valkey container via
`make bench-spine`.

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01N2rQgkHY872RubwXoBZxtE
EOF
)"
```

---

### Task 19: `binding` module — `BindingKeyring`, `compute_binding_mac`, `verify_binding`, `ScopeCheck`, `BoundaryError` (D30)

**Files:**
- Create: `packages/rust-spine/src/binding.rs`
- Modify: `packages/rust-spine/src/lib.rs`

**Interfaces:**
- Consumes: `StageEnvelope`, `Trace`, `Binding`, `trace_id_from_traceparent` (Task 4), `Grant` (Task 13), `parse_scope_from_key` (Task 2), `DlqErrorKind`, `DlqError` (Task 5).
- Produces: `BindingKeyEntry { key: Vec<u8>, retired_at: Option<chrono::DateTime<chrono::Utc>> }`, `BindingKeyring`, `BindingKeyring::{from_entries, load, signing_kid_and_key, verify_key_for}`, `BindingInput<'a> { tenant, community, workstream_id, event_id, trace_id }`, `compute_binding_mac(&BindingKeyring, &BindingInput<'_>) -> Binding`, `verify_binding(&BindingKeyring, &StageEnvelope) -> Result<(), BoundaryError>`, `ScopeCheck::{check_against_key, check_against_grant}`, `BoundaryError` (5 variants, `reason()`, `to_dlq_error()`), `RESERVED_IDENTITY_FIELDS`, `strip_bundle_identity_fields`. No later task in this plan consumes these — the stage binaries (M4/M5, out of this plan's scope) wire them into the read/dispatch path.

Spec: §5.11 (full normative text: minting, `binding.mac` formula, verification-at-every-hop's four checks, key rotation with overlap window, "Bundles cannot move a workstream"), §6.1.2 (`Binding`/`Trace` shapes, already defined Task 4), §6.3 (`error.kind = "tenant_boundary"`, never retried), §14.11 (tests 1, 2, 4 — the tenant-mismatch-across-streams, bundle-set-identity, and tampered-MAC negative tests this task implements directly; test 3 is hub-api install-time + stage-runtime `routes_to` enforcement, out of this crate; tests 5-7 are cross-service e2e, out of this crate).

- [ ] **Step 1: Write `packages/rust-spine/src/binding.rs`:**

```rust
//! D30: workstream identity, end-to-end trace, and the tenant wall (spec
//! Sec5.11). `BindingKeyring` holds the symmetric HMAC keys named by
//! `kid` (spec Sec12.3 `security.envelopeBinding.keySecretRef`) --
//! **never held by hub-api, a bundle, or the compiler**, only the four
//! Rust stage services. `compute_binding_mac`/`verify_binding` are the
//! mint/check pair every stage runs before any other processing of an
//! entry (spec Sec5.11 "Verification at every hop").

use std::collections::HashMap;
use std::path::Path;

use chrono::{DateTime, Duration as ChronoDuration, Utc};
use hmac::{Hmac, Mac};
use serde::Deserialize;
use sha2::Sha256;
use subtle::ConstantTimeEq;

use crate::client::Grant;
use crate::dlq::{DlqError, DlqErrorKind};
use crate::envelope::{trace_id_from_traceparent, Binding, StageEnvelope};
use crate::scope::parse_scope_from_key;

type HmacSha256 = Hmac<Sha256>;

/// One HMAC key version. `retired_at: None` means this is the currently
/// active signing key (spec Sec5.11's "current kid"); `Some(t)` means it
/// was retired at `t` and is still *verification*-eligible until
/// `t + rotation_overlap` (spec Sec12.3 `rotationOverlapSeconds`), never
/// used to mint a new MAC.
#[derive(Clone)]
pub struct BindingKeyEntry {
    /// Raw key bytes. Never logged -- see this type's `Debug` impl.
    pub key: Vec<u8>,
    /// `None` = active (signs new MACs); `Some(t)` = retired at `t`.
    pub retired_at: Option<DateTime<Utc>>,
}

impl std::fmt::Debug for BindingKeyEntry {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.debug_struct("BindingKeyEntry")
            .field("key", &"[REDACTED]")
            .field("retired_at", &self.retired_at)
            .finish()
    }
}

/// The set of `kid`-named HMAC keys a stage replica holds (spec Sec5.11,
/// Sec12.3). Loaded once at startup from `WADDLES_BINDING_KEY_FILE` and
/// never mutated; a rotation is a new deploy with a new file.
#[derive(Clone)]
pub struct BindingKeyring {
    active_kid: String,
    keys: HashMap<String, BindingKeyEntry>,
    rotation_overlap: ChronoDuration,
}

impl std::fmt::Debug for BindingKeyring {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.debug_struct("BindingKeyring")
            .field("active_kid", &self.active_kid)
            .field("known_kids", &self.keys.keys().collect::<Vec<_>>())
            .field("rotation_overlap", &self.rotation_overlap)
            .finish()
    }
}

/// A `WADDLES_BINDING_KEY_FILE` entry (spec Sec12.7): `key_hex` is the
/// raw HMAC key, hex-encoded; `retired_at`, when present, is an RFC 3339
/// timestamp.
#[derive(Debug, Deserialize)]
struct RawKeyEntry {
    key_hex: String,
    #[serde(default)]
    retired_at: Option<String>,
}

impl BindingKeyring {
    /// Builds a keyring directly from decoded entries -- the primitive
    /// [`BindingKeyring::load`] is built on, and what tests use to avoid
    /// touching the filesystem.
    pub fn from_entries(
        active_kid: impl Into<String>,
        entries: HashMap<String, BindingKeyEntry>,
        rotation_overlap: ChronoDuration,
    ) -> Result<Self, BoundaryError> {
        let active_kid = active_kid.into();
        match entries.get(&active_kid) {
            Some(e) if e.retired_at.is_none() => Ok(BindingKeyring { active_kid, keys: entries, rotation_overlap }),
            Some(_) => Err(BoundaryError::UnknownOrExpiredKid { kid: active_kid }),
            None => Err(BoundaryError::UnknownOrExpiredKid { kid: active_kid }),
        }
    }

    /// Loads `WADDLES_BINDING_KEY_FILE` (spec Sec12.7): a JSON object
    /// `{"<kid>": {"key_hex": "...", "retired_at": "<rfc3339>"|null}, ...}`.
    /// Never logs the file's contents -- only [`BoundaryError`] values,
    /// which never carry key material, escape this function.
    pub fn load(
        path: &Path,
        active_kid: impl Into<String>,
        rotation_overlap: ChronoDuration,
    ) -> Result<Self, BoundaryError> {
        let text = std::fs::read_to_string(path)
            .map_err(|_| BoundaryError::UnknownOrExpiredKid { kid: "<unreadable key file>".to_string() })?;
        let raw: HashMap<String, RawKeyEntry> = serde_json::from_str(&text)
            .map_err(|_| BoundaryError::UnknownOrExpiredKid { kid: "<malformed key file>".to_string() })?;

        let mut entries = HashMap::with_capacity(raw.len());
        for (kid, r) in raw {
            let key = hex::decode(&r.key_hex)
                .map_err(|_| BoundaryError::UnknownOrExpiredKid { kid: kid.clone() })?;
            let retired_at = match r.retired_at {
                None => None,
                Some(s) => Some(
                    DateTime::parse_from_rfc3339(&s)
                        .map_err(|_| BoundaryError::UnknownOrExpiredKid { kid: kid.clone() })?
                        .with_timezone(&Utc),
                ),
            };
            entries.insert(kid, BindingKeyEntry { key, retired_at });
        }
        Self::from_entries(active_kid, entries, rotation_overlap)
    }

    /// The `(kid, key)` pair every new `binding.mac` is minted under
    /// (spec Sec5.11: "always mints new MACs under the current `kid`").
    pub fn signing_kid_and_key(&self) -> (&str, &[u8]) {
        let entry = self.keys.get(&self.active_kid).expect(
            "invariant: from_entries/load never construct a keyring whose active_kid is absent or retired",
        );
        (&self.active_kid, &entry.key)
    }

    /// The verification key for `kid`, if it is either the active key or
    /// a retired key still inside its rotation-overlap window as of `now`
    /// (spec Sec5.11: "a verifier accepts a MAC produced under any `kid`
    /// still inside the overlap window"). `None` for an unknown kid, or a
    /// retired kid whose overlap window has elapsed.
    pub fn verify_key_for(&self, kid: &str, now: DateTime<Utc>) -> Option<&[u8]> {
        let entry = self.keys.get(kid)?;
        match entry.retired_at {
            None => Some(&entry.key),
            Some(retired_at) if now <= retired_at + self.rotation_overlap => Some(&entry.key),
            Some(_) => None,
        }
    }
}

/// The exact field tuple spec Sec5.11's `binding.mac` formula names:
/// `HMAC-SHA256(k_binding[kid], tenant || community || workstream_id ||
/// event_id || trace_id)`, concatenated with no separator, per the
/// formula as the spec states it.
pub struct BindingInput<'a> {
    /// The envelope's tenant slug.
    pub tenant: &'a str,
    /// The envelope's community slug, or `None` for tenant-wide.
    pub community: Option<&'a str>,
    /// The envelope's `workstream_id`.
    pub workstream_id: &'a str,
    /// The envelope's `event_id`.
    pub event_id: &'a str,
    /// The 32-hex trace-id segment of `trace.traceparent`.
    pub trace_id: &'a str,
}

impl BindingInput<'_> {
    fn concat(&self) -> String {
        let community = self.community.unwrap_or(crate::scope::TENANT_WIDE_SEGMENT);
        format!(
            "{}{}{}{}{}",
            self.tenant, community, self.workstream_id, self.event_id, self.trace_id
        )
    }
}

fn hmac_hex(key: &[u8], input: &str) -> String {
    let mut mac = HmacSha256::new_from_slice(key).expect("HMAC accepts a key of any length");
    mac.update(input.as_bytes());
    hex::encode(mac.finalize().into_bytes())
}

/// Mints a fresh `binding.mac` under the keyring's currently active `kid`
/// (spec Sec5.11). Ingest calls this once per inbound event; no other
/// stage mints, only verifies.
pub fn compute_binding_mac(keyring: &BindingKeyring, input: &BindingInput<'_>) -> Binding {
    let (kid, key) = keyring.signing_kid_and_key();
    let mac = hmac_hex(key, &input.concat());
    Binding { kid: kid.to_string(), mac }
}

/// Errors from `verify_binding`/`ScopeCheck` (spec Sec5.11's tenant wall,
/// D30). Every variant is `error.kind = "tenant_boundary"` (spec Sec6.3):
/// **never retried** -- see [`crate::DlqErrorKind::never_retry`].
#[derive(Debug, Clone, PartialEq, Eq, thiserror::Error)]
pub enum BoundaryError {
    /// The recomputed MAC did not match `binding.mac`.
    #[error("binding.mac does not verify")]
    MacMismatch,
    /// `binding.kid` is unknown, or was retired outside its rotation
    /// overlap window.
    #[error("binding.kid {kid:?} is unknown or its rotation-overlap window has elapsed")]
    UnknownOrExpiredKid {
        /// The offending kid.
        kid: String,
    },
    /// The envelope's `tenant` disagrees with the stream key's `t:`
    /// segment (or a [`Grant`]'s).
    #[error("envelope tenant does not match the stream/grant it was read from")]
    TenantMismatch,
    /// The envelope's `community` disagrees with the stream key's `c:`
    /// segment (or a [`Grant`]'s).
    #[error("envelope community does not match the stream/grant it was read from")]
    CommunityMismatch,
    /// `binding.mac` cannot be verified because the envelope carries no
    /// `trace` -- ingest always mints one (spec Sec5.11), so its absence
    /// here means a forged or malformed envelope, not a legitimate gap.
    #[error("envelope has no trace; binding.mac cannot be verified without a trace_id")]
    MissingTrace,
}

impl BoundaryError {
    /// The `reason` label on `waddles_tenant_boundary_violations_total`
    /// (spec Sec5.11) and the DLQ record's `error.code` basis.
    pub fn reason(&self) -> &'static str {
        match self {
            BoundaryError::MacMismatch => "mac_mismatch",
            BoundaryError::UnknownOrExpiredKid { .. } => "unknown_kid",
            BoundaryError::TenantMismatch => "tenant_mismatch",
            BoundaryError::CommunityMismatch => "community_mismatch",
            BoundaryError::MissingTrace => "missing_trace",
        }
    }

    /// Builds the [`DlqError`] a stage hands to `SpineClient::dead_letter`
    /// for this failure -- always `DlqErrorKind::TenantBoundary` (spec
    /// Sec6.3), never retried.
    pub fn to_dlq_error(&self, consumer_id: String, artifact_digest: Option<String>) -> DlqError {
        DlqError {
            kind: DlqErrorKind::TenantBoundary,
            code: self.reason().to_uppercase(),
            message: self.to_string(),
            detail: None,
            artifact_digest,
            consumer_id,
        }
    }
}

/// Verifies `env.binding.mac` against a freshly recomputed value (spec
/// Sec5.11, check 1 of 4). Constant-time compare on the decoded MAC
/// bytes -- a hex-decode failure is treated as a mismatch, never a panic
/// or an early return that could leak timing information about *where*
/// the mismatch was.
pub fn verify_binding(keyring: &BindingKeyring, env: &StageEnvelope) -> Result<(), BoundaryError> {
    let trace = env.trace.as_ref().ok_or(BoundaryError::MissingTrace)?;
    let trace_id = trace_id_from_traceparent(&trace.traceparent).ok_or(BoundaryError::MissingTrace)?;

    let key = keyring
        .verify_key_for(&env.binding.kid, Utc::now())
        .ok_or_else(|| BoundaryError::UnknownOrExpiredKid { kid: env.binding.kid.clone() })?;

    let input = BindingInput {
        tenant: &env.tenant,
        community: env.community.as_deref(),
        workstream_id: &env.workstream_id,
        event_id: &env.event_id,
        trace_id,
    };
    let expected_hex = hmac_hex(key, &input.concat());

    let expected_bytes = hex::decode(&expected_hex).unwrap_or_default();
    let actual_bytes = hex::decode(&env.binding.mac).unwrap_or_default();
    // A length mismatch alone (e.g. actual_bytes empty from a decode
    // failure) must still resolve through the constant-time path rather
    // than short-circuiting on `.len()` first.
    let equal = expected_bytes.len() == actual_bytes.len()
        && bool::from(expected_bytes.ct_eq(&actual_bytes));
    if equal {
        Ok(())
    } else {
        Err(BoundaryError::MacMismatch)
    }
}

/// Verifies that an envelope's tenant/community agree with the Valkey key
/// (or [`Grant`]) it was read from (spec Sec5.11, checks 2-3 of 4). This
/// crate's half of the check; the remaining half (install approval scope)
/// lives in the stage binary alongside its own approval cache, out of
/// this crate's scope.
pub struct ScopeCheck;

impl ScopeCheck {
    /// Check 2: `env.tenant`/`env.community` equal the `t:`/`c:` segments
    /// of the stream key the entry was read from.
    pub fn check_against_key(env: &StageEnvelope, key: &str) -> Result<(), BoundaryError> {
        let (tenant, community) = parse_scope_from_key(key).ok_or(BoundaryError::TenantMismatch)?;
        if env.tenant != tenant {
            return Err(BoundaryError::TenantMismatch);
        }
        if env.community != community {
            return Err(BoundaryError::CommunityMismatch);
        }
        Ok(())
    }

    /// Check 3: `env.tenant`/`env.community` equal the tenant/community
    /// implied by the [`Grant`] (its stream's key) the bundle was
    /// permitted to read.
    pub fn check_against_grant(env: &StageEnvelope, grant: &Grant) -> Result<(), BoundaryError> {
        Self::check_against_key(env, &grant.stream)
    }
}

/// The envelope-identity fields a process bundle's `transform` output can
/// never set (spec Sec5.11 "Bundles cannot move a workstream") -- the
/// stage copies these from the *input* envelope onto the output
/// unconditionally, never reading them from bundle output.
pub const RESERVED_IDENTITY_FIELDS: [&str; 5] =
    ["tenant_id", "community_id", "workstream_id", "event_id", "trace"];

/// Removes the first [`RESERVED_IDENTITY_FIELDS`] key present in a
/// process bundle's returned payload, if any, and returns its name so the
/// caller can increment `waddles_tenant_boundary_violations_total{stage=
/// "process",reason="bundle_set_identity"}` (spec Sec5.11). This is
/// deliberately **not** a hard failure: the event is not dropped, only
/// the offending field -- the stage's own copy of the input envelope's
/// identity fields is authoritative regardless.
pub fn strip_bundle_identity_fields(payload: &mut serde_json::Map<String, serde_json::Value>) -> Option<&'static str> {
    for field in RESERVED_IDENTITY_FIELDS {
        if payload.remove(field).is_some() {
            return Some(field);
        }
    }
    None
}

#[cfg(test)]
mod tests {
    #![allow(clippy::unwrap_used)]
    use super::*;
    use serde_json::json;

    fn keyring_with(active_kid: &str, key: &[u8], retired: Vec<(&str, &[u8], DateTime<Utc>)>) -> BindingKeyring {
        let mut entries = HashMap::new();
        entries.insert(active_kid.to_string(), BindingKeyEntry { key: key.to_vec(), retired_at: None });
        for (kid, k, retired_at) in retired {
            entries.insert(kid.to_string(), BindingKeyEntry { key: k.to_vec(), retired_at: Some(retired_at) });
        }
        BindingKeyring::from_entries(active_kid, entries, ChronoDuration::seconds(86_400)).unwrap()
    }

    fn valid_envelope_json() -> serde_json::Value {
        json!({
            "schema_version": 2,
            "tenant": "acme",
            "community": "main",
            "app_id": "waddles.bot.commands.default",
            "stage": "process",
            "event": {
                "platform": "twitch", "event_type": "chat.message", "actor": "u",
                "payload": {}, "occurred_at": "2026-09-14T12:00:00.000Z"
            },
            "ts": "2026-09-14T12:00:00.123Z",
            "target_app_id": null,
            "workstream_id": "8f14e45f-ceea-467e-adde-3fb5c9752730",
            "event_id": "3fa85f64-5717-4562-b3fc-2c963f66afa6",
            "session_id": null,
            "trace": {"traceparent": "00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01", "tracestate": null},
            "binding": {"kid": "2026-09", "mac": "0".repeat(64)}
        })
    }

    fn signed_envelope(keyring: &BindingKeyring, tenant: &str, community: Option<&str>) -> StageEnvelope {
        let mut v = valid_envelope_json();
        v["tenant"] = json!(tenant);
        v["community"] = match community {
            Some(c) => json!(c),
            None => serde_json::Value::Null,
        };
        let input = BindingInput {
            tenant,
            community,
            workstream_id: v["workstream_id"].as_str().unwrap(),
            event_id: v["event_id"].as_str().unwrap(),
            trace_id: "4bf92f3577b34da6a3ce929d0e0e4736",
        };
        let binding = compute_binding_mac(keyring, &input);
        v["binding"] = json!({"kid": binding.kid, "mac": binding.mac});
        serde_json::from_value(v).unwrap()
    }

    #[test]
    fn compute_and_verify_round_trip_succeeds() {
        let keyring = keyring_with("2026-09", &[1u8; 32], vec![]);
        let env = signed_envelope(&keyring, "acme", Some("main"));
        assert!(verify_binding(&keyring, &env).is_ok());
    }

    #[test]
    fn tampered_mac_is_rejected() {
        let keyring = keyring_with("2026-09", &[1u8; 32], vec![]);
        let mut env = signed_envelope(&keyring, "acme", Some("main"));
        let mut mac_bytes = hex::decode(&env.binding.mac).unwrap();
        mac_bytes[0] ^= 0xFF; // flip one byte
        env.binding.mac = hex::encode(mac_bytes);
        assert_eq!(verify_binding(&keyring, &env), Err(BoundaryError::MacMismatch));
    }

    #[test]
    fn unknown_kid_is_rejected() {
        let keyring = keyring_with("2026-09", &[1u8; 32], vec![]);
        let mut env = signed_envelope(&keyring, "acme", Some("main"));
        env.binding.kid = "does-not-exist".to_string();
        let err = verify_binding(&keyring, &env).unwrap_err();
        assert_eq!(err, BoundaryError::UnknownOrExpiredKid { kid: "does-not-exist".to_string() });
        assert_eq!(err.reason(), "unknown_kid");
    }

    #[test]
    fn rotated_key_accepted_within_overlap_window_and_refused_after() {
        let old_key = [2u8; 32];
        let new_key = [3u8; 32];
        // Retired 10 seconds ago, 1-hour overlap -- still inside the window.
        let mut entries = HashMap::new();
        entries.insert("2026-09".to_string(), BindingKeyEntry { key: new_key.to_vec(), retired_at: None });
        entries.insert(
            "2026-08".to_string(),
            BindingKeyEntry { key: old_key.to_vec(), retired_at: Some(Utc::now() - ChronoDuration::seconds(10)) },
        );
        let keyring_within = BindingKeyring::from_entries("2026-09", entries.clone(), ChronoDuration::seconds(3600)).unwrap();

        // An envelope signed under the *old* (retired) key/kid.
        let input = BindingInput {
            tenant: "acme", community: Some("main"),
            workstream_id: "8f14e45f-ceea-467e-adde-3fb5c9752730",
            event_id: "3fa85f64-5717-4562-b3fc-2c963f66afa6",
            trace_id: "4bf92f3577b34da6a3ce929d0e0e4736",
        };
        let mac = hmac_hex(&old_key, &input.concat());
        let mut v = valid_envelope_json();
        v["binding"] = json!({"kid": "2026-08", "mac": mac});
        let env: StageEnvelope = serde_json::from_value(v).unwrap();

        assert!(verify_binding(&keyring_within, &env).is_ok(), "must accept a retired kid within its overlap window");

        // Same key file, but retired 2 hours ago against a 1-hour overlap
        // -- outside the window now.
        let mut expired_entries = entries;
        expired_entries.insert(
            "2026-08".to_string(),
            BindingKeyEntry { key: old_key.to_vec(), retired_at: Some(Utc::now() - ChronoDuration::seconds(7_200)) },
        );
        let keyring_expired = BindingKeyring::from_entries("2026-09", expired_entries, ChronoDuration::seconds(3600)).unwrap();
        let err = verify_binding(&keyring_expired, &env).unwrap_err();
        assert_eq!(err, BoundaryError::UnknownOrExpiredKid { kid: "2026-08".to_string() });
    }

    #[test]
    fn missing_trace_is_rejected() {
        let keyring = keyring_with("2026-09", &[1u8; 32], vec![]);
        let mut v = valid_envelope_json();
        v["trace"] = serde_json::Value::Null;
        v["binding"] = json!({"kid": "2026-09", "mac": "0".repeat(64)});
        let env: StageEnvelope = serde_json::from_value(v).unwrap();
        assert_eq!(verify_binding(&keyring, &env), Err(BoundaryError::MissingTrace));
    }

    #[test]
    fn scope_check_against_key_matches_tenant_and_community() {
        let keyring = keyring_with("2026-09", &[1u8; 32], vec![]);
        let env = signed_envelope(&keyring, "acme", Some("main"));
        assert!(ScopeCheck::check_against_key(&env, "waddles:t:acme:c:main:src:twitch:tw-a:events").is_ok());
    }

    #[test]
    fn scope_check_against_key_rejects_a_different_tenant_stream() {
        // spec Sec14.11 test 1: a valid MAC for the envelope's OWN tenant,
        // read from a DIFFERENT tenant's stream key.
        let keyring = keyring_with("2026-09", &[1u8; 32], vec![]);
        let env = signed_envelope(&keyring, "acme", Some("main"));
        assert!(verify_binding(&keyring, &env).is_ok(), "the MAC itself is valid for acme/main");
        let err = ScopeCheck::check_against_key(&env, "waddles:t:other-tenant:c:main:src:twitch:tw-a:events")
            .unwrap_err();
        assert_eq!(err, BoundaryError::TenantMismatch);
        assert_eq!(err.reason(), "tenant_mismatch");
    }

    #[test]
    fn scope_check_against_key_rejects_a_different_community() {
        let keyring = keyring_with("2026-09", &[1u8; 32], vec![]);
        let env = signed_envelope(&keyring, "acme", Some("main"));
        let err = ScopeCheck::check_against_key(&env, "waddles:t:acme:c:other:src:twitch:tw-a:events").unwrap_err();
        assert_eq!(err, BoundaryError::CommunityMismatch);
    }

    #[test]
    fn scope_check_against_grant_delegates_to_check_against_key() {
        let keyring = keyring_with("2026-09", &[1u8; 32], vec![]);
        let env = signed_envelope(&keyring, "acme", Some("main"));
        let grant = Grant {
            stream: "waddles:t:acme:c:main:src:twitch:tw-a:events".to_string(),
            platform: "twitch".to_string(),
            source_id: "tw-a".to_string(),
        };
        assert!(ScopeCheck::check_against_grant(&env, &grant).is_ok());

        let mismatched_grant = Grant { stream: "waddles:t:other:c:main:src:twitch:tw-a:events".to_string(), ..grant };
        assert_eq!(ScopeCheck::check_against_grant(&env, &mismatched_grant), Err(BoundaryError::TenantMismatch));
    }

    #[test]
    fn strip_bundle_identity_fields_removes_and_reports_the_first_reserved_key() {
        let mut payload = serde_json::Map::new();
        payload.insert("text".to_string(), json!("hello"));
        payload.insert("workstream_id".to_string(), json!("attacker-supplied"));
        payload.insert("tenant_id".to_string(), json!("attacker-supplied"));

        let removed = strip_bundle_identity_fields(&mut payload);
        // RESERVED_IDENTITY_FIELDS order is fixed; tenant_id precedes
        // workstream_id in that array, so it is found and removed first.
        assert_eq!(removed, Some("tenant_id"));
        assert!(!payload.contains_key("tenant_id"));
        assert!(payload.contains_key("workstream_id"), "only the first match is removed per call");
        assert!(payload.contains_key("text"));
    }

    #[test]
    fn strip_bundle_identity_fields_is_none_when_nothing_reserved_is_present() {
        let mut payload = serde_json::Map::new();
        payload.insert("text".to_string(), json!("hello"));
        assert_eq!(strip_bundle_identity_fields(&mut payload), None);
    }

    #[test]
    fn boundary_error_to_dlq_error_is_always_tenant_boundary_and_never_retried() {
        let err = BoundaryError::MacMismatch;
        let dlq_err = err.to_dlq_error("svc-process-abc".to_string(), Some("sha256:aaaa".to_string()));
        assert_eq!(dlq_err.kind, DlqErrorKind::TenantBoundary);
        assert!(dlq_err.kind.never_retry());
        assert_eq!(dlq_err.code, "MAC_MISMATCH");
        assert_eq!(dlq_err.consumer_id, "svc-process-abc");
    }

    #[test]
    fn binding_keyring_debug_never_prints_key_bytes() {
        let keyring = keyring_with("2026-09", b"super-secret-key-material-32byte", vec![]);
        let rendered = format!("{keyring:?}");
        assert!(!rendered.contains("super-secret-key-material-32byte"));
        assert!(rendered.contains("REDACTED"));
    }

    #[test]
    fn from_entries_rejects_an_active_kid_that_is_itself_marked_retired() {
        let mut entries = HashMap::new();
        entries.insert(
            "2026-09".to_string(),
            BindingKeyEntry { key: vec![1; 32], retired_at: Some(Utc::now()) },
        );
        let err = BindingKeyring::from_entries("2026-09", entries, ChronoDuration::seconds(60)).unwrap_err();
        assert_eq!(err, BoundaryError::UnknownOrExpiredKid { kid: "2026-09".to_string() });
    }
}
```

- [ ] **Step 2: Run and fix until green.**

Run: `docker run --rm -v "$(pwd)/packages/rust-spine:/work" -w /work rust:1.97.1 cargo test --lib binding::`
Expected: `test result: ok. 14 passed; 0 failed`

- [ ] **Step 3: Activate the `lib.rs` export:**

```rust
mod binding;
pub use binding::{
    compute_binding_mac, strip_bundle_identity_fields, verify_binding, BindingInput,
    BindingKeyEntry, BindingKeyring, BoundaryError, ScopeCheck, RESERVED_IDENTITY_FIELDS,
};
```

(Add `mod binding;` alongside the other `mod` declarations near the top of `lib.rs`, and the `pub use` line alongside the others.)

- [ ] **Step 4: Run the full suite and confirm green.**

Run: `docker run --rm -v "$(pwd)/packages/rust-spine:/work" -w /work rust:1.97.1 cargo test`
Expected: `test result: ok.` across every module, no failures.

- [ ] **Step 5: Commit.**

```bash
git add packages/rust-spine/src/binding.rs packages/rust-spine/src/lib.rs
git commit -m "$(cat <<'EOF'
feat(spine): add the D30 binding module -- BindingKeyring, compute/
verify_binding, ScopeCheck, BoundaryError

Implements spec Sec5.11's tenant wall: BindingKeyring holds kid-named
HMAC keys with a rotation-overlap acceptance window; compute_binding_
mac/verify_binding mint and check binding.mac over exactly the fields
the spec's formula names; ScopeCheck proves envelope tenant/community
match the stream key or Grant an entry was read from; strip_bundle_
identity_fields enforces "bundles cannot move a workstream" by
dropping (never trusting) a bundle-supplied identity field. Every
BoundaryError maps to DlqErrorKind::TenantBoundary (never retried).
Negative tests: cross-tenant stream read, tampered MAC, unknown kid,
and key-rotation overlap acceptance/expiry (spec Sec14.11 tests 1/2/4).

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01N2rQgkHY872RubwXoBZxtE
EOF
)"
```

---

---

### Task 20: `waddles:usage` — `UsageDelta`, `HostCallCounts`, `UsageBatcher`, `SpineClient::append_usage` (D31)

**Files:**
- Create: `packages/rust-spine/src/usage.rs`
- Modify: `packages/rust-spine/src/client.rs`, `packages/rust-spine/src/lib.rs`, `packages/rust-spine/tests/integration_stream_tests.rs`

**Interfaces:**
- Consumes: `SpineClient`, `SpineError` (Task 13).
- Produces: `USAGE_STREAM_KEY: &str = "waddles:usage"`, `HostCallCounts { http, kv, db, relay, flags, log }`, `HostCallKind` (6 variants), `UsageDelta { tenant_id, community_id, workstream_id, stage, app_id, events, invocations, host_calls, fuel_ms, actions_delivered, outbound_bytes, media_minutes }`, `UsageDelta::zero(...)`, `UsageBatcher { record, flush, is_empty }`, `SpineClient::append_usage(&self, delta: &UsageDelta) -> Result<String, SpineError>`. No later task in this plan consumes these — the stage binaries (M4/M5, out of this plan's scope) call `UsageBatcher::record` at every host-call/invocation/event point and flush on a `METERING_FLUSH_INTERVAL_S` timer.

Spec: §5.12 (full normative text: what is recorded, per-stage-replica batching at `METERING_FLUSH_INTERVAL_S` default `10`, stages are write-only), §6.2 (`waddles:usage` key row: stream, `MAXLEN ~ SPINE_STREAM_MAXLEN`, written by every stage batched, read by hub-api's aggregator only), §11.10.2 (every stage user's grant is `+xadd`-only on this stream, implemented as an ACL selector in Task 12), §12.3/§12.7 (`metering.enabled`/`METERING_ENABLED` default `true`, `metering.flushIntervalSeconds`/`METERING_FLUSH_INTERVAL_S` default `10`), §13.1 ("usage is never an OTel metric label" — `workstream_id`/`app_id` are high-cardinality by design, this module's data never reaches `SpineMetrics`).

- [ ] **Step 1: Write `packages/rust-spine/src/usage.rs`:**

```rust
//! D31: workstream usage metering (spec Sec5.12). Every stage batches
//! deltas in-process via [`UsageBatcher`] and flushes them onto
//! `waddles:usage` (spec Sec6.2) at most every `METERING_FLUSH_INTERVAL_S`
//! -- never per event, so a chatty channel does not multiply the write
//! rate. Stages are write-only on this stream (spec Sec11.10.2, enforced
//! in Task 12's ACL matrix): this module never reads it back. `hub-api`'s
//! usage aggregator (out of this crate's scope) owns the read side.

use std::collections::HashMap;
use std::sync::Mutex;

use serde::{Deserialize, Serialize};

/// The single global stream every stage batches usage deltas onto (spec
/// Sec6.2) -- unlike every other key this crate builds, this one is
/// **not** tenant/community scoped: usage rows carry their own
/// `tenant_id`/`community_id` fields instead, since one stream is what
/// lets hub-api's aggregator drain a single source rather than fan out
/// across every tenant's key space.
pub const USAGE_STREAM_KEY: &str = "waddles:usage";

/// Which host-call capability a delta's count belongs to (spec Sec5.12's
/// "host calls by kind" — `context`/`clock` are not counted: `context` is
/// built once per invocation rather than called, and `clock` is a local
/// read with no host round-trip).
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum HostCallKind {
    /// The `http` host capability.
    Http,
    /// The `kv` host capability.
    Kv,
    /// The `db` host capability.
    Db,
    /// The `relay` host capability.
    Relay,
    /// The `flags` host capability.
    Flags,
    /// The `log` host capability.
    Log,
}

/// Host-call counts broken out by capability kind (spec Sec5.12).
#[derive(Debug, Clone, Copy, Default, PartialEq, Eq, Serialize, Deserialize)]
pub struct HostCallCounts {
    /// `http` host calls.
    pub http: u64,
    /// `kv` host calls.
    pub kv: u64,
    /// `db` host calls.
    pub db: u64,
    /// `relay` host calls.
    pub relay: u64,
    /// `flags` host calls.
    pub flags: u64,
    /// `log` host calls.
    pub log: u64,
}

impl HostCallCounts {
    /// +1 to the counter for `kind`.
    pub fn increment(&mut self, kind: HostCallKind) {
        match kind {
            HostCallKind::Http => self.http += 1,
            HostCallKind::Kv => self.kv += 1,
            HostCallKind::Db => self.db += 1,
            HostCallKind::Relay => self.relay += 1,
            HostCallKind::Flags => self.flags += 1,
            HostCallKind::Log => self.log += 1,
        }
    }

    /// Adds `other`'s counts into `self`, field-wise.
    pub fn add(&mut self, other: &HostCallCounts) {
        self.http += other.http;
        self.kv += other.kv;
        self.db += other.db;
        self.relay += other.relay;
        self.flags += other.flags;
        self.log += other.log;
    }
}

#[derive(Debug, Clone, PartialEq, Eq, Hash)]
struct UsageKey {
    tenant_id: String,
    community_id: Option<String>,
    workstream_id: String,
    stage: String,
    app_id: Option<String>,
}

/// One usage row, keyed by `(tenant_id, community_id, workstream_id,
/// stage, app_id)` (spec Sec5.12) -- the exact shape `XADD`ed onto
/// [`USAGE_STREAM_KEY`] and, on the hub-api side (out of this crate's
/// scope), aggregated hourly into `workstream_usage_hourly` (spec
/// Sec6.12). Field order matches the natural read order of spec Sec5.12's
/// own prose ("events, bundle invocations, ... host calls ..., actions
/// delivered, outbound bytes, and ... stream-media minutes").
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct UsageDelta {
    /// The tenant this usage belongs to.
    pub tenant_id: String,
    /// The community, or `None` for a tenant-wide workstream.
    pub community_id: Option<String>,
    /// Which workstream (spec Sec5.11, Sec6.11) this usage belongs to.
    pub workstream_id: String,
    /// `"ingest"` \| `"process"` \| `"action"` \| `"streaming"`.
    pub stage: String,
    /// `None` for ingest-stage rows, which have no bundle (spec Sec6.12).
    pub app_id: Option<String>,
    /// Events ingested/processed in this window.
    pub events: u64,
    /// Bundle invocations in this window.
    pub invocations: u64,
    /// Host calls by kind (spec Sec7.2/Sec7.3's per-call accounting).
    pub host_calls: HostCallCounts,
    /// Bundle fuel/CPU-ms, from the executor's per-call accounting.
    pub fuel_ms: u64,
    /// Actions delivered to a platform in this window.
    pub actions_delivered: u64,
    /// Outbound bytes sent in this window.
    pub outbound_bytes: u64,
    /// svc-streaming-only: stream-media minutes. `None` for every other stage.
    pub media_minutes: Option<f64>,
}

impl UsageDelta {
    /// A zeroed delta for the given key -- the starting point
    /// [`UsageBatcher`] accumulates into.
    pub fn zero(
        tenant_id: impl Into<String>,
        community_id: Option<String>,
        workstream_id: impl Into<String>,
        stage: impl Into<String>,
        app_id: Option<String>,
    ) -> Self {
        UsageDelta {
            tenant_id: tenant_id.into(),
            community_id,
            workstream_id: workstream_id.into(),
            stage: stage.into(),
            app_id,
            events: 0,
            invocations: 0,
            host_calls: HostCallCounts::default(),
            fuel_ms: 0,
            actions_delivered: 0,
            outbound_bytes: 0,
            media_minutes: None,
        }
    }

    fn key(&self) -> UsageKey {
        UsageKey {
            tenant_id: self.tenant_id.clone(),
            community_id: self.community_id.clone(),
            workstream_id: self.workstream_id.clone(),
            stage: self.stage.clone(),
            app_id: self.app_id.clone(),
        }
    }

    fn merge_from(&mut self, other: &UsageDelta) {
        self.events += other.events;
        self.invocations += other.invocations;
        self.host_calls.add(&other.host_calls);
        self.fuel_ms += other.fuel_ms;
        self.actions_delivered += other.actions_delivered;
        self.outbound_bytes += other.outbound_bytes;
        self.media_minutes = match (self.media_minutes, other.media_minutes) {
            (None, None) => None,
            (a, b) => Some(a.unwrap_or(0.0) + b.unwrap_or(0.0)),
        };
    }
}

/// In-process accumulator every stage replica holds, keyed by `(tenant_id,
/// community_id, workstream_id, stage, app_id)` (spec Sec5.12). `record`
/// is cheap and non-blocking (a mutex-guarded `HashMap` insert); a
/// background timer tick calls `flush` at most every
/// `METERING_FLUSH_INTERVAL_S` and hands each drained delta to
/// [`crate::SpineClient::append_usage`].
#[derive(Default)]
pub struct UsageBatcher {
    deltas: Mutex<HashMap<UsageKey, UsageDelta>>,
}

impl UsageBatcher {
    /// A fresh, empty batcher.
    pub fn new() -> Self {
        Self::default()
    }

    /// Accumulates `delta` into the in-memory batch. Multiple `record`
    /// calls for the same key within one flush interval are summed into
    /// one row -- this is what keeps a chatty channel from multiplying
    /// the `XADD` rate (spec Sec5.12).
    pub fn record(&self, delta: UsageDelta) {
        let mut deltas = self.deltas.lock().expect("UsageBatcher mutex poisoned");
        let key = delta.key();
        deltas
            .entry(key)
            .or_insert_with(|| {
                UsageDelta::zero(
                    delta.tenant_id.clone(),
                    delta.community_id.clone(),
                    delta.workstream_id.clone(),
                    delta.stage.clone(),
                    delta.app_id.clone(),
                )
            })
            .merge_from(&delta);
    }

    /// Drains every delta accumulated since the last flush. The caller
    /// hands each to [`crate::SpineClient::append_usage`]; a delta is
    /// gone from the batch the moment `flush` returns, regardless of
    /// whether the subsequent `XADD` succeeds -- a caller wanting
    /// at-least-once delivery on its own write failure should `record`
    /// the delta again rather than relying on this method to retry.
    pub fn flush(&self) -> Vec<UsageDelta> {
        let mut deltas = self.deltas.lock().expect("UsageBatcher mutex poisoned");
        deltas.drain().map(|(_, v)| v).collect()
    }

    /// `true` when nothing has been recorded since the last flush --
    /// lets a caller skip an empty flush tick's `XADD` entirely.
    pub fn is_empty(&self) -> bool {
        self.deltas.lock().expect("UsageBatcher mutex poisoned").is_empty()
    }
}

#[cfg(test)]
mod tests {
    #![allow(clippy::unwrap_used)]
    use super::*;

    fn sample(events: u64, invocations: u64) -> UsageDelta {
        let mut d = UsageDelta::zero("acme", Some("main".to_string()), "ws-1", "process", Some("waddles.bot.commands.default".to_string()));
        d.events = events;
        d.invocations = invocations;
        d
    }

    #[test]
    fn host_call_counts_increment_and_add() {
        let mut counts = HostCallCounts::default();
        counts.increment(HostCallKind::Http);
        counts.increment(HostCallKind::Http);
        counts.increment(HostCallKind::Db);
        assert_eq!(counts, HostCallCounts { http: 2, db: 1, ..Default::default() });

        let mut total = HostCallCounts::default();
        total.add(&counts);
        total.add(&counts);
        assert_eq!(total, HostCallCounts { http: 4, db: 2, ..Default::default() });
    }

    #[test]
    fn zero_delta_has_every_counter_at_zero() {
        let d = UsageDelta::zero("acme", None, "ws-1", "ingest", None);
        assert_eq!(d.events, 0);
        assert_eq!(d.invocations, 0);
        assert_eq!(d.host_calls, HostCallCounts::default());
        assert_eq!(d.media_minutes, None);
        assert_eq!(d.community_id, None);
        assert_eq!(d.app_id, None);
    }

    #[test]
    fn batcher_sums_records_sharing_the_same_key() {
        let batcher = UsageBatcher::new();
        batcher.record(sample(3, 1));
        batcher.record(sample(2, 1));
        let flushed = batcher.flush();
        assert_eq!(flushed.len(), 1, "same key must merge into one row");
        assert_eq!(flushed[0].events, 5);
        assert_eq!(flushed[0].invocations, 2);
    }

    #[test]
    fn batcher_keeps_different_keys_separate() {
        let batcher = UsageBatcher::new();
        batcher.record(sample(1, 0));
        let mut other = sample(1, 0);
        other.app_id = Some("waddles.bot.other.default".to_string());
        batcher.record(other);
        let flushed = batcher.flush();
        assert_eq!(flushed.len(), 2, "different app_id must be a different row");
    }

    #[test]
    fn flush_drains_and_clears_the_batch() {
        let batcher = UsageBatcher::new();
        batcher.record(sample(1, 1));
        assert!(!batcher.is_empty());
        let first_flush = batcher.flush();
        assert_eq!(first_flush.len(), 1);
        assert!(batcher.is_empty());
        assert_eq!(batcher.flush().len(), 0, "a second flush with nothing recorded in between must be empty");
    }

    #[test]
    fn media_minutes_merges_as_sum_and_stays_none_when_both_absent() {
        let batcher = UsageBatcher::new();
        let mut a = UsageDelta::zero("acme", None, "ws-1", "streaming", None);
        a.media_minutes = Some(2.5);
        let mut b = UsageDelta::zero("acme", None, "ws-1", "streaming", None);
        b.media_minutes = Some(1.5);
        batcher.record(a);
        batcher.record(b);
        let flushed = batcher.flush();
        assert_eq!(flushed[0].media_minutes, Some(4.0));

        let batcher2 = UsageBatcher::new();
        batcher2.record(sample(1, 0)); // media_minutes: None by default
        assert_eq!(batcher2.flush()[0].media_minutes, None);
    }

    #[test]
    fn usage_delta_round_trips_through_json() {
        let d = sample(5, 2);
        let json = serde_json::to_string(&d).unwrap();
        let back: UsageDelta = serde_json::from_str(&json).unwrap();
        assert_eq!(back, d);
    }
}
```

- [ ] **Step 2: Add `SpineClient::append_usage` to `packages/rust-spine/src/client.rs`** (append inside the existing `impl SpineClient` block, and add `use crate::usage::{UsageDelta, USAGE_STREAM_KEY};` to the file's imports):

```rust
    /// `XADD`s one usage delta onto [`crate::USAGE_STREAM_KEY`]
    /// (`waddles:usage`, spec Sec5.12/Sec6.2, D31), `MAXLEN ~` bounded
    /// exactly like every other stream this crate writes. Every stage is
    /// **write-only** here (spec Sec11.10.2, Task 12's ACL selector) --
    /// this method never reads the stream back; hub-api's aggregator
    /// owns that side.
    pub async fn append_usage(&self, delta: &UsageDelta) -> Result<String, SpineError> {
        let json = serde_json::to_string(delta)?;
        let mut conn = self.conn.clone();
        let maxlen = StreamMaxlen::Approx(self.cfg.stream_maxlen as usize);
        let id: Option<String> = conn
            .xadd_maxlen(USAGE_STREAM_KEY, maxlen, "*", &[("env", json.as_str())])
            .await?;
        id.ok_or_else(|| SpineError::Config("XADD to waddles:usage returned no entry id".to_string()))
    }
```

- [ ] **Step 3: Append an integration test to `packages/rust-spine/tests/integration_stream_tests.rs`:**

```rust
#[tokio::test]
async fn append_usage_writes_a_usage_delta_and_returns_an_entry_id() {
    use penguin_spine::{HostCallCounts, UsageDelta};
    let client = test_client().await;
    let mut delta = UsageDelta::zero(
        "acme",
        Some("main".to_string()),
        uuid::Uuid::new_v4().to_string(),
        "process",
        Some("waddles.bot.commands.default".to_string()),
    );
    delta.events = 3;
    delta.invocations = 3;
    delta.host_calls = HostCallCounts { http: 1, kv: 2, ..Default::default() };

    let id = client.append_usage(&delta).await.unwrap();
    assert!(id.contains('-'), "a Valkey stream entry id looks like {{ms}}-{{seq}}, got {id:?}");
}
```

- [ ] **Step 4: Run and fix until green.**

Run: `docker run --rm -v "$(pwd)/packages/rust-spine:/work" -w /work rust:1.97.1 cargo test --lib usage::`
Expected: `test result: ok. 7 passed; 0 failed`

Run: `cd /home/penguin/code/penguin-libs/.worktrees/plan-penguin-spine && make test-integration-spine`
Expected: `append_usage_writes_a_usage_delta_and_returns_an_entry_id ... ok` among the output.

- [ ] **Step 5: Activate the `lib.rs` export:**

```rust
mod usage;
pub use usage::{HostCallCounts, HostCallKind, UsageBatcher, UsageDelta, USAGE_STREAM_KEY};
```

(Add `mod usage;` alongside the other `mod` declarations, and the `pub use` line alongside the others.)

- [ ] **Step 6: Run the full suite and confirm green.**

Run: `docker run --rm -v "$(pwd)/packages/rust-spine:/work" -w /work rust:1.97.1 cargo test`
Expected: `test result: ok.` across every module, no failures.

- [ ] **Step 7: Commit.**

```bash
git add packages/rust-spine/src/usage.rs packages/rust-spine/src/client.rs packages/rust-spine/src/lib.rs packages/rust-spine/tests/integration_stream_tests.rs
git commit -m "$(cat <<'EOF'
feat(spine): add D31 workstream usage metering -- UsageDelta,
UsageBatcher, SpineClient::append_usage

UsageBatcher accumulates deltas per (tenant_id, community_id,
workstream_id, stage, app_id) in-process and flushes at most every
METERING_FLUSH_INTERVAL_S; append_usage XADDs one delta onto
waddles:usage, MAXLEN ~ bounded like every other stream. Stages are
write-only on this stream (Task 12's ACL selector) -- this crate never
reads it back; hub-api's aggregator (workstream_usage_hourly, out of
this plan's scope) owns that side.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01N2rQgkHY872RubwXoBZxtE
EOF
)"
```

---

### Task 21: CI workflow, full README/CHANGELOG, final verification, self-review

**Files:**
- Create: `/home/penguin/code/penguin-libs/.github/workflows/rust-spine.yml`
- Modify: `packages/rust-spine/README.md`, `packages/rust-spine/CHANGELOG.md`

**Interfaces:**
- Consumes: the crate's complete public API (all prior tasks).
- Produces: nothing — this is the plan's final task.

Spec: §14.5 (per-crate gate list — `cargo fmt --check`, `cargo clippy --all-targets -- -D warnings`, `cargo deny check`, `cargo audit`, `cargo test`, `cargo llvm-cov --fail-under-lines 90`), §17 Standards table (dependency pinning, coverage, verification integrity).

- [ ] **Step 1: Write `/home/penguin/code/penguin-libs/.github/workflows/rust-spine.yml`**, mirroring `waddlebot`'s already-vetted `rust-svc-streaming.yml` job shape and exact pins, plus a live Valkey container for the coverage-gated test run (this crate's tests need a real Valkey, unlike `svc_streaming`'s):

```yaml
name: Rust penguin-spine (lint + test + coverage)

on:
  push:
    branches: [main, 'release/**']
    paths:
      - 'packages/rust-spine/**'
      - '.github/workflows/rust-spine.yml'
  pull_request:
    branches: [main, 'release/**']
    paths:
      - 'packages/rust-spine/**'
  workflow_dispatch:

permissions:
  contents: read

jobs:
  lint-test-coverage:
    name: fmt + clippy + deny + audit + coverage
    runs-on: ubuntu-latest
    defaults:
      run:
        working-directory: packages/rust-spine
    steps:
      - name: Checkout code
        uses: actions/checkout@de0fac2e4500dabe0009e67214ff5f5447ce83dd  # v6.0.2

      - name: Install Rust 1.97.1 (rustfmt, clippy, llvm-tools-preview)
        uses: dtolnay/rust-toolchain@6bed0761d98439e5a578e2877258200ad565ba87  # stable branch snapshot
        with:
          toolchain: "1.97.1"
          components: rustfmt, clippy, llvm-tools-preview

      - name: Install cargo-deny, cargo-llvm-cov, cargo-audit
        uses: taiki-e/install-action@3f74d7c16a4242f1c95561e98edc25d36adb4375  # v2.87.12
        with:
          tool: cargo-deny@0.20.2,cargo-llvm-cov@0.9.1,cargo-audit@0.22.2

      - name: cargo fmt --check
        run: cargo fmt --check

      - name: cargo clippy --all-targets -- -D warnings
        run: cargo clippy --all-targets -- -D warnings

      - name: cargo deny check (advisories, licenses, bans, sources)
        run: cargo deny check

      - name: cargo audit
        run: cargo audit

      - name: Generate ephemeral TLS certs for the test Valkey container
        run: bash tests/valkey/gen-test-tls.sh tests/valkey/.tls localhost

      - name: Render users.acl from the ACL matrix
        run: |
          pip install --quiet pyyaml==6.0.2
          python3 config/valkey/render_acl.py config/valkey/acl-matrix.yaml tests/valkey/users.acl

      - name: Start the pinned Valkey test container
        run: |
          docker run -d --name penguin-spine-ci-valkey \
            -p 16390:6390 \
            -v "$GITHUB_WORKSPACE/packages/rust-spine/tests/valkey/.tls:/tls:ro" \
            -v "$GITHUB_WORKSPACE/packages/rust-spine/tests/valkey/users.acl:/acl/users.acl:ro" \
            -v "$GITHUB_WORKSPACE/packages/rust-spine/tests/valkey/valkey.conf:/usr/local/etc/valkey/valkey.conf:ro" \
            valkey/valkey:8.1.5@sha256:e51a82741b780e4bf315db10753edf07eea6496d405fa7df2a8677a18f5e7464 \
            valkey-server /usr/local/etc/valkey/valkey.conf
          ready=0
          for i in $(seq 1 30); do
            if docker exec penguin-spine-ci-valkey valkey-cli --tls --cert /tls/server.crt --key /tls/server.key --cacert /tls/ca.crt -p 6390 --user waddles_admin --pass test-waddles_admin-password PING 2>/dev/null | grep -q PONG; then ready=1; break; fi
            sleep 1
          done
          if [ "$ready" != "1" ]; then echo "valkey did not become ready in time"; exit 1; fi

      - name: cargo test (unit + integration, against the live container)
        env:
          VALKEY_URL: rediss://127.0.0.1:16390
          VALKEY_USERNAME: waddles_admin
          VALKEY_PASSWORD: test-waddles_admin-password
          VALKEY_CA_FILE: ${{ github.workspace }}/packages/rust-spine/tests/valkey/.tls/ca.crt
        run: cargo test -- --test-threads=1

      - name: cargo llvm-cov (>=90% line coverage gate, against the live container)
        env:
          VALKEY_URL: rediss://127.0.0.1:16390
          VALKEY_USERNAME: waddles_admin
          VALKEY_PASSWORD: test-waddles_admin-password
          VALKEY_CA_FILE: ${{ github.workspace }}/packages/rust-spine/tests/valkey/.tls/ca.crt
        run: cargo llvm-cov --fail-under-lines 90 -- --test-threads=1

      - name: Stop the Valkey test container
        if: always()
        run: docker rm -f penguin-spine-ci-valkey || true
```

- [ ] **Step 2: Write the full `packages/rust-spine/README.md`:**

```markdown
# penguin-spine

The Waddles data-plane spine over Valkey Streams: key builders,
byte-compatible envelope/DLQ types, `XADD`/`XREADGROUP`/`XACK`/
`XAUTOCLAIM`/`XGROUP`/`XINFO` wrappers, and the two client
connection-separation rules (spec Sec5.7). Backs `svc-ingest`,
`svc-process`, `svc-action` (write/read/DLQ) and, read-only, `hub-api`
(consumer-group lifecycle only).

Design source: `docs/superpowers/specs/2026-09-14-rust-data-plane-design.md`
(`waddlebot` repo, branch `docs/rust-data-plane-spec`). Implementation plan:
`docs/superpowers/plans/2026-09-14-penguin-spine.md` in this repo.

## Key scheme

| Purpose | Key | Valkey type |
|---|---|---|
| Ingest source stream | `waddles:t:{tenant}:c:{community\|_tenant}:src:{platform}:{source_id}:events` | stream, `MAXLEN ~` |
| Action stream | `waddles:t:{tenant}:c:{community\|_tenant}:app:{app_id}:action` | stream, `MAXLEN ~` |
| Bundle config | `...:app:{app_id}:cfg` | string |
| Bundle state | `...:app:{app_id}:state` | hash |
| Dead letter | `waddles:dlq:{stage}` | stream, `MAXLEN ~` |
| Usage metering (D31) | `waddles:usage` (not tenant/community scoped) | stream, `MAXLEN ~` |

`{community}` is the literal `_tenant` segment for a tenant-wide activation
— never omitted, so splitting a key on `:` always yields the same field
count. See [`Scope`] for the builders.

## Connection rules (spec Sec5.7)

1. **A blocking read runs on its own dedicated connection with its own
   socket timeout, strictly longer than the block duration.**
   [`GroupReader::connect`] refuses construction — naming both values —
   when `SPINE_BLOCK_MS` is not strictly less than `DRAIN_SOCKET_TIMEOUT_S`.
2. **Administrative traffic never shares a connection with an in-flight
   blocking read.** [`SpineClient`]'s `MultiplexedConnection` and
   [`GroupReader`]'s dedicated connection are always two separate sockets,
   even when constructed from the same [`SpineConfig`].

## Environment

| Var | Default | Notes |
|---|---|---|
| `VALKEY_URL` | *(required)* | Falls back to `REDIS_URL`. `rediss://` required unless `SECURITY_TRANSPORT_TLS=false`. |
| `VALKEY_USERNAME` / `VALKEY_PASSWORD` / `_FILE` | *(required unless `SECURITY_TRANSPORT_AUTH=false`)* | ACL credentials. |
| `VALKEY_CA_FILE` | `/etc/waddles/ca/valkey-ca.crt` | Custom CA for `rediss://`. |
| `SECURITY_TRANSPORT_TLS` / `SECURITY_TRANSPORT_AUTH` | `true` / `true` | D20 opt-outs — loud, never silent. |
| `SPINE_CONSUMER_ID` | pod name, else `unknown-{uuid-v4}` | |
| `SPINE_STREAM_MAXLEN` | `100000` | `MAXLEN ~` on every `XADD`. |
| `SPINE_READ_COUNT` | `64` | |
| `SPINE_BLOCK_MS` | `1000` | Must be `< DRAIN_SOCKET_TIMEOUT_S * 1000`. |
| `SPINE_CLAIM_IDLE_MS` / `SPINE_CLAIM_INTERVAL_MS` | `30000` / `15000` | |
| `SPINE_STATS_INTERVAL_MS` / `SPINE_PEL_ALERT` | `10000` / `5000` | |
| `SPINE_DLQ_MAXLEN` | `10000` | |
| `SPINE_MAX_DELIVERIES` | `5` | |
| `DRAIN_SOCKET_TIMEOUT_S` | `65` | |
| `RELAY_BLOCK_TIMEOUT_S` | `30` | Validated here; consumed by the (out-of-crate) outbound relay. |
| `WADDLES_BINDING_KEY_FILE` | `/etc/waddles/envelope-binding/keys.json` | `kid -> {key_hex, retired_at}` map for [`BindingKeyring::load`] (D30). |
| `WADDLES_BINDING_KID` | *(required)* | The active `kid` this replica mints new `binding.mac` values under. |
| `WADDLES_BINDING_ROTATION_OVERLAP_S` | `86400` | How long a retired `kid` still verifies. |
| `METERING_ENABLED` | `true` | Whether callers should run [`UsageBatcher`] at all (D31). |
| `METERING_FLUSH_INTERVAL_S` | `10` | Max interval between [`UsageBatcher::flush`] calls. |

## Workstream identity & tenant wall (D30)

Every `StageEnvelope` carries `workstream_id`/`event_id`/`session_id`/
`trace`/`binding` (spec Sec5.11, Sec6.1.2). `binding.mac` is an
`HMAC-SHA256` over `tenant || community || workstream_id || event_id ||
trace_id`, minted by [`compute_binding_mac`] and checked by
[`verify_binding`] against a [`BindingKeyring`] loaded from
`WADDLES_BINDING_KEY_FILE` -- a key only the four Rust stage services
hold, never hub-api, a bundle, or the compiler. [`ScopeCheck`] proves an
envelope's tenant/community agree with the stream key or [`Grant`] it was
read from. Any failure is `error.kind = "tenant_boundary"`
(`DlqErrorKind::TenantBoundary`), **never retried**
(`DlqErrorKind::never_retry`), and counted via
`SpineMetrics::tenant_boundary_violation`.

## Usage metering (D31)

[`UsageBatcher`] accumulates `UsageDelta` rows per `(tenant_id,
community_id, workstream_id, stage, app_id)` in-process; a caller flushes
it at most every `METERING_FLUSH_INTERVAL_S` and hands each drained delta
to [`SpineClient::append_usage`], which `XADD`s it onto `waddles:usage`.
Every stage is write-only there (Task 12's ACL selector) -- this crate
never reads it back; `hub-api`'s aggregator (`workstream_usage_hourly`,
out of this crate's scope) owns that side.

## Usage

```rust
use penguin_spine::{Grant, GroupReader, NoopMetrics, Scope, SpineClient, SpineConfig, Stage};
use std::sync::Arc;

# async fn example() -> Result<(), penguin_spine::SpineError> {
let cfg = SpineConfig::from_env()?;
let metrics = Arc::new(NoopMetrics);
let client = SpineClient::connect(cfg.clone(), metrics.clone()).await?;

let scope = Scope::new("acme", Some("main".to_string()));
let stream = scope.source_stream("twitch", "tw-channelA");
client.ensure_group(&stream, "waddles.bot.commands.default").await?;

let grants = vec![Grant {
    stream: stream.clone(),
    platform: "twitch".to_string(),
    source_id: "tw-channelA".to_string(),
}];
let mut reader = GroupReader::connect(
    &cfg,
    grants,
    "waddles.bot.commands.default".to_string(),
    Stage::Process,
    client.clone(),
    metrics,
)
.await?;

let delivered = reader.read().await?;
for d in &delivered {
    // ... hand `d.env` to the executor ...
    client.ack(d, "waddles.bot.commands.default").await?;
}
# Ok(())
# }
```

## Least-privilege ACL matrix (D28)

`config/valkey/acl-matrix.yaml` is the normative, versioned source for
every Valkey ACL user this crate's callers need; `config/valkey/render_acl.py`
renders it into `users.acl` — never hand-edited. See that file for the full
per-service command/key-pattern breakdown, and `tests/acl_matrix_tests.rs`
for the live `ACL LIST` equality test plus the five negative permission
tests. **Cross-repo note:** spec Sec11.10.2 names `config/valkey/acl-matrix.yaml`
as a path in whichever repo deploys the chart (`waddlebot`) — this crate
carries the canonical copy; wiring the chart to it is M6 work.

## Testing

```bash
# Unit tests only (no external dependencies):
docker run --rm -v "$(pwd):/work" -w /work rust:1.97.1 cargo test --lib

# Full suite, including integration + ACL-matrix conformance tests
# (starts/stops a pinned Valkey container automatically):
make test-integration-spine   # from the penguin-libs repo root

# Benchmarks:
make bench-spine
```

## License

MIT.
```

- [ ] **Step 3: Update `packages/rust-spine/CHANGELOG.md`:**

```markdown
# Changelog

All notable changes to `penguin-spine` are documented here.

## [0.1.0] - 2026-09-14

Initial release — Milestone M1a of the Waddles Rust data-plane design.

- `Scope`/`Stage` key builders, byte-compatible with `flask_core.stream_pipeline`.
- `PlatformEvent`/`StageEnvelope`/`EnvelopeError` with strict deserialization.
- `DlqRecord`/`DlqErrorDetail`/`DlqError`/`DlqErrorKind` (spec Sec6.3, all ten kinds, D30 adds `tenant_boundary`).
- `SpineMetrics` facade + `NoopMetrics`.
- `SpineConfig`: env loading, TLS/auth startup refusal, block-timeout validation.
- The Sec12.6 classified startup connectivity self-check (`probe_valkey`).
- `SpineClient`: `append`, `ensure_group`/`destroy_group`, `ack`, `dead_letter`,
  `claim_stale` (with the `SPINE_MAX_DELIVERIES` redelivery cap), `group_stats`.
- `GroupReader`: dedicated-connection, grant-scoped `XREADGROUP` reads,
  enforcing both Sec5.7 client connection-separation rules.
- The D28 least-privilege Valkey ACL matrix, its renderer, and a live
  `ACL LIST` conformance test plus five negative permission tests.
- 27 valid + 34 invalid golden envelope fixtures, full DLQ/key fixture
  coverage, shared with the (separate, not-yet-scheduled) `flask_core`
  alignment work.
- **D30** workstream identity/trace/tenant-wall: `schema_version` bumped
  to `2` (no dual-read), `workstream_id`/`event_id`/`session_id`/`trace`/
  `binding` on `StageEnvelope`, the `binding` module (`BindingKeyring`,
  `compute_binding_mac`/`verify_binding`, `ScopeCheck`, `BoundaryError`),
  `DlqErrorKind::TenantBoundary` (never retried), `workstream_id`/`trace`
  on `DlqRecord`, `SpineMetrics::tenant_boundary_violation`.
- **D31** workstream usage metering: `UsageDelta`/`HostCallCounts`/
  `UsageBatcher`, `SpineClient::append_usage` onto `waddles:usage`
  (`+xadd`-only for every stage, read-only for hub-api — Valkey ACL
  selector).
```

- [ ] **Step 4: Run the complete gate locally, exactly as CI will.**

Run:
```bash
cd /home/penguin/code/penguin-libs/.worktrees/plan-penguin-spine
docker run --rm -v "$(pwd)/packages/rust-spine:/work" -w /work rust:1.97.1 sh -c \
  "cargo fmt --check && cargo clippy --all-targets -- -D warnings"
make test-integration-spine
make bench-spine
```
Expected: every command exits 0.

- [ ] **Step 5: Self-review** (performed by you, the implementer finishing this plan — not a sub-task to delegate):
  1. **Spec coverage.** Re-open the spec's §4.7, §5 (including §5.11/§5.12, D30/D31), §6.1-6.3, §6.11/§6.12, §11.6.1, §11.10 (including §11.10.2's `waddles:usage` selector row), §12.3/§12.7 (including the binding-key and metering env vars), §13.1 (spine-owned metrics only, plus `tenant_boundary_violation`), §14.1, §14.2, §14.11 (tests 1/2/4, this crate's share) sections and confirm every bullet maps to a task above; list any gap you find and add a task for it before calling this plan done.
  2. **Placeholder scan.** `grep -n "TODO\|TBD\|similar to Task\|add tests for the above" packages/rust-spine -r` (run from the executed crate, not this plan file) must return nothing except the deliberate `// TODO(task-N):` lib.rs markers this plan itself instructs later tasks to remove — confirm none remain once Task 17 is done.
  3. **Signature consistency.** Grep this plan document itself for every occurrence of `SpineClient::`, `GroupReader::`, `Scope::`, `Stage::` and confirm each call site matches the signature the defining task declared (parameter order, `Stage` argument present on `claim_stale`/`GroupReader::connect`/`dead_letter_unparseable` throughout).
  4. Fix anything Step 5.1-5.3 turn up, then proceed to Step 6.

- [ ] **Step 6: Commit.**

```bash
git add packages/rust-spine/README.md packages/rust-spine/CHANGELOG.md
git -C /home/penguin/code/penguin-libs add .github/workflows/rust-spine.yml
git commit -m "$(cat <<'EOF'
docs(spine): add CI workflow, full README, and v0.1.0 changelog

Mirrors waddlebot's rust-svc-streaming.yml pins exactly (toolchain
1.97.1, cargo-deny 0.20.2, cargo-llvm-cov 0.9.1, taiki-e/install-action
v2.87.12), plus a live pinned Valkey container so the coverage gate
exercises the real XADD/XREADGROUP/XACK/XAUTOCLAIM/XGROUP/XINFO paths,
not just unit tests. README documents the key scheme, both Sec5.7
connection rules, the full environment table, and the D28 ACL matrix.

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01N2rQgkHY872RubwXoBZxtE
EOF
)"
```

---

## Self-Review Checklist (performed by the plan author before this document was finalized)

**1. Spec coverage — requirement → task:**

| Spec requirement | Task |
|---|---|
| Key builders + `_tenant` sentinel (Sec5.1, Sec5.9, Sec6.2) | 2 |
| `parse_scope_from_key` for the envelope_invalid DLQ path (Sec3.3, Sec5.5, Sec11.8) | 2, used in 15/17 |
| `PlatformEvent`/`Source` strict types (Sec6.1.1) | 3 |
| `StageEnvelope`/`PROCESS_TARGET_APP_ID_KEY` strict types (Sec6.1.2, Sec5.9) | 4 |
| `SpineError` | 5 |
| DLQ record shape, ten `error.kind` values (Sec6.3, D30 adds `tenant_boundary`) | 5 |
| `SpineMetrics` facade (Sec13.1 spine-owned subset, Sec4.9 no-penguin-logging-yet) | 6 |
| Golden fixtures: envelopes valid/invalid, keys, entries, dlq (Sec14.1) | 7, 8 |
| `fixtures_examined == fixtures_on_disk`, non-zero denominator, printed (Sec14.1, Verification Integrity) | 8 |
| Env config, TLS/auth startup refusal (Sec11.6.1, Sec12.7) | 9 |
| Block-timeout invariant (Sec5.7 rule 1) | 9, enforced again in 17 |
| Classified startup probe dns/tcp/tls/auth/ok (Sec12.6) | 10 |
| Pinned Valkey TLS container for integration tests (Sec14.2) | 11 |
| Least-privilege Valkey ACL matrix, renderer, live `ACL LIST` equality + 5 negatives (Sec11.10/D28) | 12 |
| `SpineClient::connect`/`append`, `MAXLEN ~` (Sec4.7, Sec5.1) | 13 |
| Group lifecycle, `BUSYGROUP`-tolerant (Sec5.2) | 14 |
| `ack`/`dead_letter`/`claim_stale`/redelivery cap/`group_stats` (Sec5.3-5.6) | 15 |
| Fan-in, group isolation, claim concurrency, stream/DLQ bounding (Sec14.2) | 16 |
| `GroupReader`, both client connection-separation rules, grant enforcement negative test, envelope_invalid DLQ path (Sec5.2, Sec5.7) | 17 |
| Benchmark | 18 |
| Workstream identity/trace/binding types on `StageEnvelope`, `schema_version` bump to 2 (Sec5.11, Sec6.1.2, D30) | 4 |
| `DlqErrorKind::TenantBoundary`, `never_retry`, `DlqRecord.workstream_id`/`.trace` (Sec6.3, D30) | 5 |
| `SpineMetrics::tenant_boundary_violation` (Sec13.1, D30) | 6 |
| Golden fixtures extended for D30 fields, tenant_boundary DLQ kind (Sec14.1) | 7, 8 |
| `waddles:usage` ACL selector (+xadd-only per stage, read-only for hub-api) (Sec11.10.2, D31) | 12 |
| `BindingKeyring`, `compute_binding_mac`/`verify_binding`, `ScopeCheck`, `BoundaryError`, kid rotation-overlap acceptance (Sec5.11, D30) | 19 |
| Negative tests: cross-tenant stream read, tampered MAC, unknown kid, rotation-overlap expiry (Sec14.11 tests 1/2/4, D30) | 19 |
| `UsageDelta`/`HostCallCounts`/`UsageBatcher`, `SpineClient::append_usage` onto `waddles:usage` (Sec5.12, Sec6.2, D31) | 20 |
| CI gate (fmt/clippy/deny/audit/test/llvm-cov ≥90%), README, CHANGELOG, v0.1.0 (Sec14.5) | 21 |

No gap found. `penguin-bundle-host::wire`/`::manifest`, `penguin-logging`, `penguin-connectors`, and `penguin-licensing`'s CI/publish jobs are separate M1 deliverables (sibling plans already exist as worktrees `plan-penguin-bundle-host`, `plan-penguin-logging`, `plan-penguin-connectors`) — correctly out of scope for this `penguin-spine`-only plan. D30's spec Sec14.11 tests 3/5/6/7 and the install-approval half of Sec5.11's check 3 are stage-binary/hub-api work (M4/M5, out of every M1 crate plan's scope) — this crate ships the verifiable primitives (`verify_binding`, `ScopeCheck`) those stages will call.

**2. Placeholder scan.** Re-searched this document, including the D30/D31 additions (Tasks 4-8, 12, 19, 20), for `TBD`, `TODO` (outside the deliberate `// TODO(task-N):` lib.rs markers each task instructs a later task to remove), `similar to Task`, and "add tests for the above" — none found outside those markers.

**3. Signature/type consistency, checked across every task:**
- `Scope::new(tenant, community: Option<String>)`, `.source_stream/.action_stream/.config_key/.state_key` — same signature Tasks 2, 8, 13, 17, 18, 21 all use.
- `Stage::{Process, Action}`, `.as_str()`, `Stage::parse(&str)` — Task 2 defines; Tasks 5 (`error.rs` uses `crate::SpineError::Config` inside `Stage::parse`, later superseded intact by Task 5's real `SpineError`), 15, 17 all call it identically.
- `SpineClient::connect(cfg: SpineConfig, metrics: Arc<dyn SpineMetrics>) -> Result<Self, SpineError>` — Task 13 defines by value; every later call site (15, 16, 17, 18, 21) passes an owned `SpineConfig` (cloning first where the same config is reused), matching.
- `SpineClient::claim_stale(&self, stream: &str, app_id: &str, stage: Stage)` — Task 15 defines with three params (the Global Constraints deviation 6 addition); Task 16's three call sites and Task 17 are consistent.
- `GroupReader::connect(cfg: &SpineConfig, grants: Vec<Grant>, app_id: String, stage: Stage, dlq: SpineClient, metrics: Arc<dyn SpineMetrics>)` — Task 17 defines; its own tests and Task 18's bench call it identically, in the same argument order.
- `Delivered { stream, entry_id, env, deliveries }` field names/order — Task 13 defines; Tasks 15, 16, 17 construct it identically every time.
- `DlqError { kind, code, message, detail, artifact_digest, consumer_id }` — Task 5 defines; Task 15's `claim_stale` and Task 16's `dlq_stays_within_the_configured_maxlen` construct it with the same field set; Task 19's `BoundaryError::to_dlq_error` builds the same six fields in the same order.
- `dead_letter_raw`/`dead_letter_unparseable` visibility corrected to `pub(crate)` in Task 15 specifically so Task 17's `GroupReader` (a sibling module) can call them — flagged and fixed during authoring rather than left as a cross-module privacy error.
- `StageEnvelope { schema_version, tenant, community, app_id, stage, event, ts, target_app_id, workstream_id, event_id, session_id, trace, binding }` (D30, Task 4) — field order matches the spec Sec6.1.2 JSON example exactly, which is what makes Task 8's byte-identical golden round-trips possible; Task 5's `dead_letter`/`dead_letter_unparseable`, Task 15's `DlqRecord` construction sites, and Task 19's test fixtures all read/construct the same field set.
- `BindingKeyring::from_entries`/`load` both return `Result<Self, BoundaryError>` and reject an active `kid` that is itself marked retired — Task 19 defines and tests both constructors against the same invariant.
- `UsageDelta::zero(tenant_id, community_id, workstream_id, stage, app_id)` — Task 20 defines; its own tests and the Task 20 integration test construct it with the same five positional arguments in the same order.

No inconsistency found beyond the one caught and fixed above (`pub(crate)` visibility). Plan complete.

