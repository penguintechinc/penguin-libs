# penguin-tools — Implementation Plan

**Spec:** `docs/superpowers/specs/2026-11-09-penguin-tools-design.md` · **Status:** DRAFT r2 — D1–D13 decided, D14 open
**Scope:** penguin-libs only. No consumer repo is modified.
**Release line:** `release/rust-tools-host/v0.1.x` (new) · `release/rust-bundle-host/v0.2.x` (wire additions)
**Model routing:** code/tests → Sonnet developer dispatch; ops (worktrees, pushes, PRs) → Haiku / github-ops; plan review → architect; security gate → security persona.

## Phase 0 — Unblock (penguin-libs only)
| # | Task | Exit criteria |
|---|---|---|
| 0.1 | Resolve D14: dependency strategy for `penguin-logging` / `penguin-bundle-host` / `penguin-connectors` (git-rev pins vs landing on `main`) | decision recorded in spec §8 |
| 0.2 | Tag `penguin-bundle-host` 0.5.0; rebase PR #132 onto it | tag exists; #132 mergeable |
| 0.3 | Create `release/rust-tools-host/v0.1.x` | branch exists; feature PRs target it |
| — | *(removed)* penguind commit, waddles actor-scope merge: other repos, out of scope — see spec §6 handoff | — |

## Phase 1 — Contract (`penguin:tools@0.1.0`)
| # | Task | Tests (written first) |
|---|---|---|
| 1.1 | `wit/penguin-tools/{types,provider,invoker,context,http,kv,log,clock,flags}.wit` + `world tool-module` | `wasm-tools component wit` parses; golden WIT snapshot |
| 1.2 | `packages/rust-tools-sdk`: `#[tool]` macro → descriptor + schemars JSON Schema; wit-bindgen glue | macro expansion tests; schema golden files |
| 1.3 | Fixture guests (Rust): `echo`, `hang_forever`, `memory_hog`, `fuel_burner`, `invoke_recursion`, `bad_schema_output`, `undeclared_capability` | built in container, digests pinned in `tests/fixtures/digests.toml` |
| 1.4 | ~~Python guest helper~~ — dropped (D5: Rust only) | — |

## Phase 2 — Host core (`packages/rust-tools-host`)
| # | Task | Tests |
|---|---|---|
| 2.1 | `Engine` builder: wasmtime pin, pooling, fuel+epoch (shared ticker), WASI p2 minus sockets | config snapshot; socket import denied |
| 2.2 | `Loader`: fetch trait, sha256, **mandatory** ed25519 sidecar w/ rotation (port waddles `signing.rs`), signed manifest == `describe()` | unsigned / tampered / wrong-key / manifest-mismatch → `LoadFailed`; rotated key accepted |
| 2.3 | `Registry`: digest-keyed, refcount per scope, single-flight compile, `.cwasm` cache keyed by (digest, engine fingerprint) | concurrent load = 1 compile; cache invalidates on engine change |
| 2.4 | `InvocationScope` (host-only ctor from validated JWT claims / SVID), `GrantResolver`, `FlagGate`, `CapabilityProvider` traits | scope cannot be built from guest data (compile-fail test) |
| 2.5 | `Dispatcher` in spec §5.3 order; schema validation in/out (jsonschema, compiled at load); idempotency-key required for write/destructive | one test per rejection branch; order asserted |
| 2.6 | Limits: deadline, memory, fuel, depth, capability-call budget, 1 MiB args/results | fixtures from 1.3 terminate with typed errors ≤ deadline + 1 tick |
| 2.7 | Built-in capabilities: `log`, `clock`, `context`, `flags` (fail closed), `kv` (backend trait + in-mem impl) | deny-all default: only log/clock/context reachable |
| 2.8 | `penguin:http` provider — port waddles `EgressGuard` (SSRF, DNS pinning, redirect recheck, secret-ref injection) | SSRF matrix (RFC1918, link-local, metadata IPs, DNS rebinding) |
| 2.9 | Telemetry: spans/metrics/logs per spec §5.5; label-cardinality guard; dead exporter tolerance | OTLP test sink: logs ≥1, metrics ≥1, histograms ≥1, spans ≥1 |

## Phase 2C — Connectors stack
| # | Task | Tests (written first) |
|---|---|---|
| 2C.1 | `penguin-connector-core` crate in `packages/rust-connectors`: `Connector`/`Sender`/`Receiver`/`SignatureVerifier` traits, `ChatEvent`, `SendOutcome`, secret-free `ConnectorError` | trait-object safety test; error Display/Debug never contains a token |
| 2C.2 | `impl Connector` for Twitch + Discord over existing public API (no behaviour change) | existing suites unchanged and green; new conformance suite run against both |
| 2C.3 | `impl Connector` for slack/youtube/kick returning `Unavailable("not implemented")` | conformance asserts error, never `Ok` (no silent success) |
| 2C.4 | `penguin-tools-connectors`: `ConnectorCapability`, `ConnectorRegistry`, `CredentialResolver` trait; per-(tenant,platform,target) rate limit + length cap | grant re-check per call; guest cannot read credential; wrong-platform target denied |
| 2C.5 | `EventTrigger` + `TriggerBinding`: host-built scope, bounded queue, drop-oldest metric | scope never from event content; overflow drops + counts; webhook with bad signature never reaches a tool |
| 2C.6 | WIT `penguin:tools/connector` interface + `connector-send` capability fixture guest | fixture guest sends via mock connector; ungranted fixture is denied |

## Phase 3 — Executor mode
| # | Task | Tests |
|---|---|---|
| 3.1 | `penguin-bundle-host`: additive `ToolInvoke`/`ToolResult`/`ToolDescribe` bodies (ToolRef, typed scope, idempotency key), capability as string id with `CapabilityKind` constants for compat | wire codec round-trip; old frames still decode |
| 3.2 | `penguin-tools-host --features executor`: wire server wrapping `ToolHost` (hello handshake reports limits + sandbox) | e2e over unix socket with fixtures |
| 3.3 | Container image (rootless, distroless, read-only FS) + Helm values snippet | trivy/hadolint clean; smoke test |
| 3.4 | `packages/rust-tools-client`: async Rust wire client (framing, correlation, deadlines, host-built scope), MCP descriptor mapping | integration tests against real executor container; ≥90 % cov |

## Phase 4 — Consumer adoption: OUT OF SCOPE
Not performed by this work. The per-product migration notes (penguind pilot, waddles executor swap, waddleai/tobogganing/gough Rust ports, waddles Python guest SDK) are retained in spec §6 as handoff for the owners of those repos. penguin-libs's deliverable is complete when the crates, WIT, executor image and docs ship.

## Phase 5 — Hardening & release
- security persona audit of `rust-tools-host`, `penguin-tools-connectors` + executor (sandbox escape, grant bypass, scope forgery, trigger flooding) (sandbox escape, grant bypass, scope forgery, DoS)
- fuzz: wire decoder, schema validator inputs, manifest parser (cargo-fuzz, 10 min CI budget)
- `cargo deny`, `cargo audit`, coverage ≥90 % lines+branches, docs (`docs/tools/`), tag `rust-tools-host-v0.1.0`

## Sequencing & parallelism
```
P0 ──► P1.1 ──┬─► P1.2/1.3/1.4 (parallel)
              └─► P2.1 ─► P2.2 ─► P2.3 ─┬─► P2.5 ─► P2.6
                         P2.4 ──────────┘   P2.7/2.8/2.9 (parallel after 2.4)
P2.4 done ─► P2C.1 ─► P2C.2/2C.3 (parallel) ─► P2C.4 ─► P2C.5 ─► P2C.6
P2 done ─► P3.1 ─► P3.2 ─► P3.3 / P3.4 (parallel)
```
Estimated: P1–P2 ≈ 2–3 weeks of Sonnet dispatches; P2C ≈ 1 week; P3 ≈ 1 week.

## Risks
| Risk | Mitigation |
|---|---|
| wasmtime version skew across products | single pin in workspace; Renovate-off, manual bump PR across consumers |
| waddles frozen `stage*` worlds | tools live in a separate world; transform/dispatch untouched |
| Python teams bypass executor with native tools | allowed — interface is opt-in per tool; MCP surface unifies listing |
| Capability string-ID typos | validated at load against registered providers; unknown id = `LoadFailed` |
| Schema validation cost | compile validators once per digest at load |
