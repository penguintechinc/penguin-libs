# penguin-rpc (pRPC) Phase 0 — Foundations Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Land the pRPC spec draft, protobuf contracts with an enforced `buf breaking` gate, three compiling package scaffolds (Go/Python/Rust), and full CI/publish wiring — the foundation Phases 1–3 build on.

**Architecture:** pRPC = an Apache-2.0 profile spec (Connect protocol over HTTP/3 with H2 fallback, zero-trust, MCP/A2A conventions) + three framework packages. Phase 0 creates the spec documents, `proto/prpc/*` contracts, minimal-but-real package skeletons, and the CI gates that enforce contracts from day one.

**Tech Stack:** Buf v2, proto3 + protovalidate, Go 1.25, Python ≥3.11 (setuptools src-layout), Rust 1.97 edition 2024 (Cargo workspace), GitHub Actions.

## Global Constraints

- Work happens in worktree `/home/penguin/code/penguin-libs/.worktrees/penguin-rpc` on branch `feature/penguin-rpc`. All `git`/build commands run from this worktree root unless a `cd` is shown. Never touch `main`.
- Commits: conventional-commit style on the feature branch only (approved as part of this plan). Never push.
- License: every new package gets `LICENSE` (Apache-2.0 full text from https://www.apache.org/licenses/LICENSE-2.0.txt) + `NOTICE` (exact content in Task 3). Source files start with the 2-line header shown in Task 3.
- Do NOT modify `packages/go-h3/`, `packages/python-libs/src/penguin_libs/h3/`, or `.github/workflows/h3-packages.yml` — retirement is Phase 5.
- Versions: all new packages `0.1.0`. Go `1.25.0`. Rust workspace `rust-version = "1.97"`, `edition = "2021"`. Python `requires-python = ">=3.11"`.
- Dependency pinning: exact versions only (`==` pip, `=` cargo). New GitHub Actions steps pin to full commit SHA resolved at execution time via `gh api repos/<owner>/<repo>/git/ref/tags/<tag> --jq .object.sha` (existing workflows use floating tags — pre-existing violation, flagged, out of scope).
- Existing files to modify are listed per task; match surrounding style exactly.

---

### Task 1: Spec documents

**Files:**
- Create: `spec/SPEC.md`, `spec/TRADEMARKS.md`

**Interfaces:**
- Produces: profile names cited by later phases: `transport`, `rpc`, `contract`, `zero-trust`, `ai`, `operational`, `ziti-binding`, `transport-upgrade`.

- [ ] **Step 1: Write `spec/SPEC.md`** with this structure and content (expand each bullet into normative prose using RFC-2119 keywords; the design doc `docs/superpowers/specs/2026-07-14-penguin-rpc-design.md` §"Spec profiles" is the source of truth — every numbered profile there becomes a §):

```markdown
# pRPC Specification — prpc/1.0-draft
Status: DRAFT · License: Apache-2.0 · Governance: Penguin Tech Inc

## 1. Overview            — what pRPC is; relationship to Connect protocol (wire-compatible profile)
## 2. Terminology         — RFC 2119; lane, posture (`dark-only`|`hybrid`|`direct`), procedure, contract
## 3. Transport Profile   — H3 primary (ALPN h3) + H2 fallback on a port pair; TLS 1.3 ONLY; 0-RTT MUST be disabled; connection migration MAY be used; default max message 4 MiB; mandatory deadlines
## 4. RPC Profile         — Connect protocol (unary, server/client/bidi streaming); protobuf + JSON codecs; Connect error model
## 5. Contract Profile    — proto3 only; versioned packages `<product>.<service>.v1`; generated stubs are the only supported API; `buf breaking` MUST gate merges; protovalidate constraints MUST be enforced server-side
## 6. Zero-Trust Profile  — identity on every request (SPIFFE mTLS or OIDC JWT with claims sub,iss,aud,iat,exp,scope,tenant,teams,roles); tenant check precedes scope check; deny-by-default (procedures opt INTO `public`); sanitized logging
## 7. AI Conventions      — MCP Streamable HTTP mounted at `/mcp`; A2A agent card at `/.well-known/agent-card.json` + JSON-RPC endpoint; both inherit server TLS/auth; no anonymous tool calls
## 8. Operational Conventions — `/healthz` + `prpc.health.v1.HealthService`; Prometheus metrics; correlation-ID header `X-Correlation-Id`
## 9. Ziti Binding Profile — bind/dial app-embedded OpenZiti; H2 semantics on overlay streams; pooled connections for HoL mitigation
## 10. Transport Upgrade Profile — secure-first dial order; Alt-Svc-style advertisement; posture rules; default posture `direct` (H3 primary, automatic H2 fallback); in-flight requests complete on original lane
## 11. Conformance        — implementations MUST pass `prpc.conformance.v1.ConformanceService` matrix (3 clients × 3 servers × {h3,h2} × 4 patterns)
```

- [ ] **Step 2: Write `spec/TRADEMARKS.md`**: "pRPC", "penguin-rpc", and the pRPC logo are trademarks of Penguin Tech Inc. Apache-2.0 §6 does not grant trademark rights. Permitted: unmodified builds, factual references, compatibility claims ("implements prpc/1.0"). Not permitted without written permission: modified builds under the name, implying endorsement.

- [ ] **Step 3: Verify** — `test -s spec/SPEC.md && test -s spec/TRADEMARKS.md && grep -c "MUST" spec/SPEC.md` → count ≥ 10.

- [ ] **Step 4: Commit** — `git add spec/ && git commit -m "docs(prpc): add pRPC 1.0-draft specification and trademark policy"`

---

### Task 2: Protobuf contracts + buf breaking gate

**Files:**
- Create: `proto/prpc/health/v1/health.proto`, `proto/prpc/conformance/v1/conformance.proto`
- Modify: `proto/buf.yaml` (add protovalidate dep + breaking config)

**Interfaces:**
- Produces: `prpc.health.v1.HealthService/{Check,Watch}`, `prpc.conformance.v1.ConformanceService/{Unary,ServerStream,ClientStream,BidiStream}` — Phases 1–4 implement/test against exactly these.

- [ ] **Step 1: Add to `proto/buf.yaml`** (Buf v2 syntax, merge into existing keys):

```yaml
deps:
  - buf.build/bufbuild/protovalidate
breaking:
  use:
    - FILE
```

- [ ] **Step 2: Write `proto/prpc/health/v1/health.proto`**:

```protobuf
syntax = "proto3";
package prpc.health.v1;

// HealthService reports serving status per pRPC §8 (Operational Conventions).
service HealthService {
  rpc Check(CheckRequest) returns (CheckResponse) {}
  rpc Watch(CheckRequest) returns (stream CheckResponse) {}
}
message CheckRequest {
  string service = 1; // empty = whole-process health
}
message CheckResponse {
  ServingStatus status = 1;
}
enum ServingStatus {
  SERVING_STATUS_UNSPECIFIED = 0;
  SERVING_STATUS_SERVING = 1;
  SERVING_STATUS_NOT_SERVING = 2;
}
```

- [ ] **Step 3: Write `proto/prpc/conformance/v1/conformance.proto`** (protovalidate showcase — the reference for the Contract Profile):

```protobuf
syntax = "proto3";
package prpc.conformance.v1;

import "buf/validate/validate.proto";

// ConformanceService exercises all four Connect RPC patterns plus
// contract-level validation, per pRPC §11.
service ConformanceService {
  rpc Unary(EchoRequest) returns (EchoResponse) {}
  rpc ServerStream(EchoRequest) returns (stream EchoResponse) {}
  rpc ClientStream(stream EchoRequest) returns (EchoResponse) {}
  rpc BidiStream(stream EchoRequest) returns (stream EchoResponse) {}
}
message EchoRequest {
  string message = 1 [(buf.validate.field).string = {min_len: 1, max_len: 4096}];
  uint32 repeat = 2 [(buf.validate.field).uint32 = {lte: 100}];
}
message EchoResponse {
  string message = 1;
  string protocol = 2; // "h3" | "h2" — which lane served the request
}
```

- [ ] **Step 4: Verify lint + deps** — `cd proto && buf dep update && buf lint` → exit 0 (run `buf dep update` once to write `buf.lock` with the protovalidate dep).

- [ ] **Step 5: Prove the breaking gate fails on a break** — temporarily rename field `message` → `msg` in `health.proto`… actually use conformance: change `string message = 1` to `string msg = 1`, then run `cd proto && buf breaking --against '../.git#branch=feature/penguin-rpc,subdir=proto'` → expect **no failure yet** (files are new, not on the baseline); instead verify the gate mechanism against main: `buf breaking --against '../.git#branch=main,subdir=proto'` → exit 0 for new files; then simulate a break on an EXISTING contract: change `string message = 1` to `string message = 2` in `proto/examples/echo/v1/echo.proto`, rerun → expect FAIL with `FIELD_SAME_NUMBER`/wire-break error. **Revert the simulated break** (`git checkout -- proto/examples/echo/v1/echo.proto`).

- [ ] **Step 6: Commit** — `git add proto/ && git commit -m "feat(prpc): add health + conformance contracts with protovalidate; enable buf breaking"`

---

### Task 3: `packages/go-rpc` scaffold

**Files:**
- Create: `packages/go-rpc/{go.mod,doc.go,version.go,version_test.go,.golangci.yml,LICENSE,NOTICE,README.md}`

**Interfaces:**
- Produces: module `github.com/penguintechinc/penguin-libs/packages/go-rpc`, package `gorpc`, `gorpc.Version` const. Phase 1 adds `server/`, `client/`, `auth/`, `mcp/`, `a2a/`, `health/`, `ziti/` under this module.

Every new `.go` source file starts with:

```go
// Copyright 2026 Penguin Tech Inc
// SPDX-License-Identifier: Apache-2.0
```

`NOTICE` (identical file for all three packages):

```
Penguin RPC (pRPC)
Copyright 2026 Penguin Tech Inc

This product includes software developed at
Penguin Tech Inc (https://www.penguintech.io).
```

- [ ] **Step 1: Write the failing test** `packages/go-rpc/version_test.go`:

```go
// Copyright 2026 Penguin Tech Inc
// SPDX-License-Identifier: Apache-2.0
package gorpc

import "testing"

func TestVersion(t *testing.T) {
	if Version != "0.1.0" {
		t.Fatalf("Version = %q, want 0.1.0", Version)
	}
}
```

- [ ] **Step 2: Create `go.mod`** (`module github.com/penguintechinc/penguin-libs/packages/go-rpc`, `go 1.25.0`), then run `cd packages/go-rpc && go test ./...` → expect FAIL: `undefined: Version`.

- [ ] **Step 3: Implement** — `doc.go` (`// Package gorpc is the Go implementation of the pRPC specification (spec/SPEC.md): Connect RPC over HTTP/3 with HTTP/2 fallback, zero-trust interceptors, and MCP/A2A mounting.` + `package gorpc`) and `version.go` (`const Version = "0.1.0"`), both with the copyright header.

- [ ] **Step 4: Verify** — `cd packages/go-rpc && go test ./... && go vet ./...` → PASS. Copy `.golangci.yml` from `packages/go-aaa/.golangci.yml` unchanged; run `golangci-lint run ./...` if installed (else CI covers it).

- [ ] **Step 5: Add LICENSE (Apache-2.0 full text), NOTICE (above), README.md** (name, one-paragraph purpose, "Status: Phase 0 scaffold — APIs land in Phase 1", install line `go get github.com/penguintechinc/penguin-libs/packages/go-rpc@go-rpc-v0.1.0`, license/trademark pointers).

- [ ] **Step 6: Commit** — `git add packages/go-rpc && git commit -m "feat(go-rpc): scaffold pRPC Go module (Apache-2.0)"`

---

### Task 4: `packages/python-rpc` scaffold

**Files:**
- Create: `packages/python-rpc/{pyproject.toml,LICENSE,NOTICE,README.md,src/penguin_rpc/{__init__.py,py.typed},tests/test_version.py}`

**Interfaces:**
- Produces: PyPI dist `penguin-rpc`, import `penguin_rpc`, `penguin_rpc.__version__`. Phase 2 adds `config.py`, `app.py`, `client.py`, `auth.py` etc. Extras reserved now: `h3`, `mcp`, `a2a`, `ziti`, `all`, `dev`.

- [ ] **Step 1: Write the failing test** `packages/python-rpc/tests/test_version.py`:

```python
"""Version metadata tests for penguin-rpc."""
from penguin_rpc import __version__


def test_version() -> None:
    assert __version__ == "0.1.0"
```

- [ ] **Step 2: Write `pyproject.toml`** — mirror `packages/python-aaa/pyproject.toml` structure exactly (setuptools build-backend, src layout, ruff select `["E","F","I","N","W","UP"]` line-length 100, `[tool.mypy] strict = true`, pytest `testpaths=["tests"]`, bandit block) with:

```toml
[project]
name = "penguin-rpc"
version = "0.1.0"
description = "pRPC: Connect RPC over HTTP/3/QUIC with zero-trust defaults and MCP/A2A mounting"
license = {text = "Apache-2.0"}
requires-python = ">=3.11"
dependencies = []

[project.optional-dependencies]
h3 = []      # populated in Phase 2 (hypercorn[h3], aioquic)
mcp = []     # populated in Phase 2 (mcp)
a2a = []     # populated in Phase 2 (a2a-sdk[http-server])
ziti = []    # populated in Phase 4 (openziti)
all = ["penguin-rpc[h3,mcp,a2a,ziti]"]
dev = ["pytest==8.4.1", "pytest-cov==6.2.1", "mypy==1.16.1", "ruff==0.12.3", "bandit==1.8.5"]
```

(Confirm the five dev-tool pins against the versions already pinned in `packages/python-aaa/pyproject.toml` and reuse those exact pins if they differ.)

- [ ] **Step 3: Run test to verify it fails** — `cd packages/python-rpc && python3 -m venv .venv && .venv/bin/pip install -e ".[dev]" && .venv/bin/pytest -v` → FAIL: `ImportError` (module exists but empty / missing `__version__`).

- [ ] **Step 4: Implement `src/penguin_rpc/__init__.py`**:

```python
# Copyright 2026 Penguin Tech Inc
# SPDX-License-Identifier: Apache-2.0
"""penguin-rpc (pRPC): Connect RPC over HTTP/3/QUIC.

Python implementation of the pRPC specification (spec/SPEC.md) —
zero-trust defaults, HTTP/2 fallback, MCP/A2A mounting. Phase 0 scaffold.
"""

__version__ = "0.1.0"
```

Create empty `src/penguin_rpc/py.typed`.

- [ ] **Step 5: Verify** — `.venv/bin/pytest -v --cov=penguin_rpc` → PASS (100% cov); `.venv/bin/ruff check src tests && .venv/bin/ruff format --check src tests && .venv/bin/mypy src` → clean.

- [ ] **Step 6: LICENSE, NOTICE (Task 3 content), README.md** ("Status: Phase 0 scaffold — APIs land in Phase 2", `pip install penguin-rpc`).

- [ ] **Step 7: Commit** — `git add packages/python-rpc && git commit -m "feat(python-rpc): scaffold penguin-rpc package (Apache-2.0)"` (ensure `.venv` is NOT added; add `packages/python-rpc/.venv/` to root `.gitignore` if `git status` shows it).

---

### Task 5: `packages/rust-rpc` Cargo workspace scaffold

**Files:**
- Create: `packages/rust-rpc/{Cargo.toml,deny.toml,rustfmt.toml,LICENSE,NOTICE,README.md}`
- Create: `packages/rust-rpc/crates/penguin-rpc/{Cargo.toml,src/lib.rs}`
- Create: `packages/rust-rpc/crates/penguin-h3-tower/{Cargo.toml,src/lib.rs}`

**Interfaces:**
- Produces: crates `penguin-rpc` and `penguin-h3-tower` (both 0.1.0), each exposing `pub const VERSION: &str`. Phase 3 fills in the h3→Tower bridge and the framework crate.

- [ ] **Step 1: Workspace `packages/rust-rpc/Cargo.toml`**:

```toml
[workspace]
resolver = "2"
members = ["crates/penguin-rpc", "crates/penguin-h3-tower"]

[workspace.package]
version = "0.1.0"
edition = "2021"
rust-version = "1.97"
license = "Apache-2.0"
repository = "https://github.com/penguintechinc/penguin-libs"
authors = ["Penguin Tech Inc <dev@penguintech.io>"]
```

- [ ] **Step 2: Member Cargo.tomls** — `crates/penguin-rpc/Cargo.toml`:

```toml
[package]
name = "penguin-rpc"
description = "pRPC: Connect RPC over HTTP/3/QUIC with zero-trust defaults (Rust implementation)"
version.workspace = true
edition.workspace = true
rust-version.workspace = true
license.workspace = true
repository.workspace = true
authors.workspace = true

[dependencies]
```

`crates/penguin-h3-tower/Cargo.toml` identical except `name = "penguin-h3-tower"` and `description = "Serve tower services over HTTP/3 (hyperium h3 + quinn bridge)"`.

- [ ] **Step 3: `src/lib.rs` for BOTH crates** (test-first is folded in — the test ships in the same file):

```rust
// Copyright 2026 Penguin Tech Inc
// SPDX-License-Identifier: Apache-2.0

//! Phase 0 scaffold — implementation lands in Phase 3. See spec/SPEC.md.

#![forbid(unsafe_code)]
#![deny(missing_docs)]

/// Crate version, sourced from Cargo.toml.
pub const VERSION: &str = env!("CARGO_PKG_VERSION");

#[cfg(test)]
mod tests {
    #[test]
    fn version_matches_workspace() {
        assert_eq!(super::VERSION, "0.1.0");
    }
}
```

(Adjust the first doc line per crate: penguin-h3-tower says "h3→Tower bridge lands in Phase 3".)

- [ ] **Step 4: `deny.toml`** (license allow-list + advisories):

```toml
[licenses]
allow = ["Apache-2.0", "MIT", "BSD-2-Clause", "BSD-3-Clause", "ISC", "Unicode-3.0", "Zlib"]

[advisories]
yanked = "deny"
```

`rustfmt.toml`: `max_width = 100`.

- [ ] **Step 5: Verify** — `cd packages/rust-rpc && cargo test --workspace && cargo clippy --workspace --all-targets -- -D warnings && cargo fmt --all --check` → all PASS. If `cargo` is missing on this machine, run inside Docker: `docker run --rm -v "$PWD":/w -w /w rust:1.97-slim-bookworm sh -c 'cargo test --workspace && cargo clippy --workspace --all-targets -- -D warnings'` (resolve and record the image digest with `docker inspect --format='{{index .RepoDigests 0}}' rust:1.97-slim-bookworm` for Task 8). `cargo deny check` if cargo-deny installed (else CI covers it).

- [ ] **Step 6: LICENSE, NOTICE (Task 3 content), README.md** at workspace root ("Status: Phase 0 scaffold — bridge + framework land in Phase 3").

- [ ] **Step 7: Commit** — `git add packages/rust-rpc && git commit -m "feat(rust-rpc): scaffold penguin-rpc + penguin-h3-tower crates (Apache-2.0)"` (ensure `target/` not added — root `.gitignore` must contain `packages/rust-rpc/target/`; add if missing).

---

### Task 6: Makefile wiring

**Files:**
- Modify: `Makefile` (root)

**Interfaces:**
- Produces: `make prpc-proto`, and go-rpc/python-rpc/rust-rpc folded into existing `build`, `lint`, `test`, `security` targets.

- [ ] **Step 1: Read `Makefile`** and append, matching its existing per-package recipe style, additions to each aggregate target:
  - `build`: `cd packages/go-rpc && go build ./...` · `python3 -m py_compile packages/python-rpc/src/penguin_rpc/__init__.py` · `cd packages/rust-rpc && cargo build --workspace`
  - `lint`: golangci-lint for go-rpc · `ruff check` + `ruff format --check` for python-rpc · `cargo clippy --workspace --all-targets -- -D warnings` + `cargo fmt --all --check` for rust-rpc
  - `test`: `go test -race -v ./...` (go-rpc) · `pytest tests/ -v --tb=short` (python-rpc) · `cargo test --workspace` (rust-rpc)
  - `security`: `govulncheck ./...` + `gosec -quiet ./...` (go-rpc) · `bandit -r src/ -c pyproject.toml` (python-rpc) · `cargo audit` + `cargo deny check` (rust-rpc)
  - New target `prpc-proto`: `cd proto && buf lint && buf breaking --against '../.git#branch=main,subdir=proto' && buf format --diff --exit-code`

- [ ] **Step 2: Verify** — `make prpc-proto` → exit 0; `make build` → exit 0 (existing packages must still build — if a pre-existing package fails, STOP and report; do not paper over).

- [ ] **Step 3: Commit** — `git add Makefile && git commit -m "chore(prpc): wire go-rpc/python-rpc/rust-rpc into make targets; add prpc-proto"`

---

### Task 7: CI jobs in `ci.yml`

**Files:**
- Modify: `.github/workflows/ci.yml` (append three jobs; do not touch existing jobs)

**Interfaces:**
- Consumes: package layouts from Tasks 3–5. Produces: jobs `build-go-rpc`, `build-python-rpc`, `build-rust-rpc`.

- [ ] **Step 1: Resolve action SHAs** (execution time): for `actions/checkout@v4`, `actions/setup-python@v5`, `actions/setup-go@v5`, `dtolnay/rust-toolchain` — `gh api repos/actions/checkout/git/ref/tags/v4.2.2 --jq .object.sha` (repeat per action, latest stable tag). Use `<sha> # vX.Y.Z` comment style.

- [ ] **Step 2: Append jobs** modeled on the existing `build-python-aaa` / `build-go-aaa` jobs (same triggers), SHA-pinned:
  - `build-go-rpc`: setup-go 1.25 → `go build ./... && go test -race -v ./...` + golangci-lint, govulncheck, gosec in `packages/go-rpc`
  - `build-python-rpc`: setup-python 3.13 → `pip install -e ".[dev]"` → `ruff check`, `ruff format --check`, `mypy src/`, `bandit -r src/ -c pyproject.toml`, `pytest --cov=penguin_rpc` in `packages/python-rpc`
  - `build-rust-rpc`: rust-toolchain 1.97.0 (components clippy,rustfmt) → `cargo fmt --all --check && cargo clippy --workspace --all-targets -- -D warnings && cargo test --workspace` + `cargo install cargo-deny --version 0.18.3 --locked && cargo deny check` in `packages/rust-rpc`

- [ ] **Step 3: Verify** — `actionlint .github/workflows/ci.yml` if available, else `python3 -c "import yaml,sys; yaml.safe_load(open('.github/workflows/ci.yml'))"` → exit 0.

- [ ] **Step 4: Commit** — `git add .github/workflows/ci.yml && git commit -m "ci(prpc): add build jobs for go-rpc, python-rpc, rust-rpc"`

---

### Task 8: `prpc-packages.yml` cross-cutting workflow

**Files:**
- Create: `.github/workflows/prpc-packages.yml`

**Interfaces:**
- Consumes: `make prpc-proto` equivalent steps; conformance contracts from Task 2. Produces: the PR gate that enforces the Contract Profile.

- [ ] **Step 1: Write the workflow** — triggers: `pull_request` + `push` to `main` with paths `['packages/go-rpc/**','packages/python-rpc/**','packages/rust-rpc/**','proto/**','spec/**']`. Jobs (all SHA-pinned, modeled on `h3-packages.yml` which stays untouched):
  - `proto-lint`: `bufbuild/buf-action` pinned → `buf lint` + `buf format --diff --exit-code` (workdir `proto/`)
  - `proto-breaking`: `buf breaking --against 'https://github.com/penguintechinc/penguin-libs.git#branch=main,subdir=proto'`
  - `build-matrix`: needs `[proto-lint]`; the three package builds (reuse Task 7 step lists). Cross-language integration job is added in Phase 1 when the first server exists — note this as a YAML comment in the file, not a placeholder job.

- [ ] **Step 2: Verify** — YAML parses (same check as Task 7 Step 3).

- [ ] **Step 3: Commit** — `git add .github/workflows/prpc-packages.yml && git commit -m "ci(prpc): add prpc-packages workflow with buf breaking merge gate"`

---

### Task 9: Publish wiring in `publish.yml`

**Files:**
- Modify: `.github/workflows/publish.yml`

**Interfaces:**
- Produces: tag-driven publishing — `penguin-rpc-v*` (PyPI via OIDC trusted publishing, env `pypi-rpc`), `rust-rpc-v*` (crates.io via `rust-lang/crates-io-auth-action`, both crates, `penguin-h3-tower` first), `go-rpc-v*` (validate-only job).

- [ ] **Step 1: Add tag triggers** `penguin-rpc-v*`, `rust-rpc-v*`, `go-rpc-v*` to `on.push.tags` and to the `workflow_dispatch` package options list, matching existing list style.

- [ ] **Step 2: Add `publish-python-rpc` job** — copy the `publish` job pattern used by python-aaa (environment `pypi-aaa` → new environment name `pypi-rpc`; `if: startsWith(github.ref, 'refs/tags/penguin-rpc-v')`; `packages-dir: packages/python-rpc/dist/`).

- [ ] **Step 3: Add `validate-go-rpc` job** — copy `validate-go-aaa` (go build + test on tag).

- [ ] **Step 4: Add `publish-rust-rpc` job** — `if: startsWith(github.ref, 'refs/tags/rust-rpc-v')`; steps: checkout, rust-toolchain 1.97.0, `rust-lang/crates-io-auth-action` (SHA-pinned; produces `CARGO_REGISTRY_TOKEN`), then `cargo publish -p penguin-h3-tower && cargo publish -p penguin-rpc` from `packages/rust-rpc` (order matters once penguin-rpc depends on the bridge; harmless now). Add `id-token: write` permission on the job.

- [ ] **Step 5: Verify** — YAML parses; `git diff .github/workflows/publish.yml` shows no edits to existing jobs.

- [ ] **Step 6: Commit** — `git add .github/workflows/publish.yml && git commit -m "ci(prpc): tag-driven publish jobs for penguin-rpc (PyPI), rust crates (crates.io), go validate"`

- [ ] **Step 7: Record manual follow-ups** in `docs/penguin-rpc/README.md` "Maintainers" section (Task 10): create PyPI trusted publisher + `pypi-rpc` GitHub environment; create crates.io trusted-publishing config for both crates. These are console actions the user must perform — list them, do not attempt them.

---

### Task 10: Documentation + status tables

**Files:**
- Create: `docs/penguin-rpc/README.md`, `docs/penguin-rpc/CHANGELOG.md`
- Modify: root `README.md`, `docs/PUBLISHING.md`, `PACKAGE_PUBLISHING_STATUS.md`

**Interfaces:**
- Consumes: everything above. Produces: the package's public documentation entry points.

- [ ] **Step 1: `docs/penguin-rpc/README.md`** — sections: What is pRPC (3 sentences + spec link), Packages table (go-rpc / penguin-rpc PyPI / penguin-rpc + penguin-h3-tower crates, all 0.1.0, status "Phase 0 scaffold"), Roadmap (Phases 1–5, one line each from the design doc), Maintainers (the manual publishing follow-ups from Task 9 Step 7, plus "org rules `backend.md` still references go-h3/penguin-h3 — update after Phase 5").

- [ ] **Step 2: `docs/penguin-rpc/CHANGELOG.md`** — `## [Unreleased]` with the Phase 0 additions listed (spec draft, contracts + breaking gate, three scaffolds, CI/publish wiring).

- [ ] **Step 3: Root `README.md`** — add the three packages to the appropriate per-language tables, matching existing row format (note Apache-2.0 license where the table has a license column; do not restyle existing rows). Add a one-line "Rust" section if none exists.

- [ ] **Step 4: `docs/PUBLISHING.md` + `PACKAGE_PUBLISHING_STATUS.md`** — add rows: penguin-rpc (PyPI, tag `penguin-rpc-v*`), go-rpc (tag `go-rpc-v*`, GOPROXY), penguin-rpc + penguin-h3-tower (crates.io, tag `rust-rpc-v*`), each "not yet published".

- [ ] **Step 5: Verify** — `make prpc-proto && make lint` → exit 0 (full-repo sanity), `git status` clean after commit.

- [ ] **Step 6: Commit** — `git add docs/ README.md PACKAGE_PUBLISHING_STATUS.md && git commit -m "docs(prpc): package docs, changelog, publishing status for penguin-rpc"`

---

## Self-review notes (done at authoring)

- Spec coverage: design §Phases item 0 fully covered (spec ✓ T1, licensing ✓ T3–T5, scaffolding ✓ T3–T5, proto+breaking ✓ T2, CI ✓ T7–T8, publish ✓ T9, Makefile ✓ T6, docs ✓ T10). Echo protovalidate constraints moved to conformance.proto (Phase 0) to avoid touching go-h3's generated deps before Phase 1 — echo.proto gains constraints in Phase 1 alongside regen.
- Deliberate-break verification of `buf breaking` is T2 Step 5 (local, reverted) — the "deliberate-break test PR" from the design is satisfied by this plus the always-on CI gate from T8.
- Type consistency: `gorpc.Version` / `penguin_rpc.__version__` / `VERSION` consts all `0.1.0`; service names `prpc.health.v1.HealthService`, `prpc.conformance.v1.ConformanceService` used identically in T2/T8 and the spec §8/§11.
- Rust edition: `2021` chosen (broadest tool compatibility at rust-version 1.97); revisit edition 2024 in Phase 3 if all toolchain stages support it.
