# penguin-tools — Generic WASM Tools Interface (Design Spec)

**Status:** DRAFT r2 — scope cut to penguin-libs, connectors layer added · **Date:** 2026-11-10 · **Owner:** penguin-libs
**Scope rule:** every deliverable lives in penguin-libs. Nothing in waddles, penguind, waddleai, gough or tobogganing is changed by this work; consumer adoption is recorded as handoff notes (§6) only.
**Consumers (target):** waddles, penguind, waddleai, gough, tobogganing
**Reference implementation:** waddles (`core/bundle_executor`, `wit/waddle-bundle`, unmerged `tool.wit` on `feature/tool-invoke-actor-scope`)

---

## 1. Problem

Five products each define "tools" differently; two already host wasmtime, independently:

| Product | Today | Runtime | Schema | Identity in call | Sandbox |
|---|---|---|---|---|---|
| **waddles** | WIT component bundles (`stage`, `connector`), `tool.wit` (unmerged: `tool.invoke` + `tool-provider.call`) | wasmtime **49.0.4**, component model, WASI p2, pooling, out-of-process executor over `penguin-bundle-host` wire | WIT types; JSON-in-string payloads, no per-tool JSON Schema | tenant/community/app (host-built `InvokeScope`); actor only on unmerged branch | fuel + epoch + 64 MiB + WASI sockets denied |
| **penguind** | `penguin-wasm-host` (**untracked, uncommitted**) — 11 declared tools, 4 implemented | wasmtime **50.0.1**, **core-module** ptr/len ABI (`penguin.call_tool`), in-process, no WASI | JSON Schema per tool (`tool_definitions.json`), validated in + out | none | fuel + epoch + 16 MiB + 256 calls/run, deny-all allowlist |
| **waddleai** | FastMCP tools (`shared/mcp/tools.py`), CLI agent `BaseTool`, MCP gateway | Python, no wasm | type hints → JSON Schema (MCP `inputSchema`) | `ToolContext` from ASGI request (never from args) | subprocess / k8s pods |
| **gough** | Infra drivers (cloud ABCs, Redfish/IPMI, LXD) | Python, no wasm | ABC + dataclass + pydantic | roles decorators | none |
| **tobogganing** | `ModuleContract` registry + scheduler job handlers; Rust node-agent | Python + Rust, no wasm | dataclasses, string `job_type` | `require_scope` + `require_tenant` | subprocess timeouts only |

Shared library state: `penguin-bundle-host` 0.5.0 (`release/rust-bundle-host/v0.2.x`, untagged, not on `main`) is **wire + manifest only** — `ExportKind::ToolCall` exists but no executor, no WIT files, no signing, no limit enforcement, untyped `payload: serde_json::Value`, closed `CapabilityKind` enum (every new capability = crate release, see PR #132).

**Goal:** one Rust library family in penguin-libs that defines *what a tool is*, *how a sandboxed wasm tool is loaded, verified, granted, invoked and observed*, so each product keeps only its product-specific capabilities and grant policy. It **stacks on `penguin-connectors`**: platform connectors (Twitch, Discord, Slack, YouTube, Kick) become first-class host capabilities and inbound event sources, so a wasm tool can reply on a chat platform without ever holding a credential (§5.8).

## 2. Goals / Non-goals

**Goals**
- G1. One WIT package `penguin:tools` defining tool descriptors, provider export, invoker import, and a generic capability set.
- G2. One Rust host crate (`penguin-tools-host`) owning engine config, loading, verification, registry, dispatch, limits, telemetry — usable **in-process** (penguind, tobogganing node-agent) or as an **out-of-process executor** over the existing `penguin-bundle-host` wire (waddles, Python products).
- G3. Typed tool contract: name, version, JSON Schema (2020-12) for input **and** output, side-effect class, required capabilities — validated host-side on every call.
- G4. Host-built invocation scope (tenant/team/actor UUIDs, trace) — guests can never name scope. PII-free (UUIDs only).
- G5. Open capability registry: products register capabilities by namespaced string ID (`penguin:http`, `waddle:reputation`) instead of extending a closed enum.
- G6. Direct MCP mapping — a tool descriptor is a valid MCP tool definition, so waddleai's `/mcp` surface can expose wasm tools unchanged.
- G8. Connectors stack: a common `Connector` trait in `penguin-connectors`, and an adapter layer that exposes any connector as a grant-checked capability (`penguin:connector.<platform>`) and as an inbound trigger for tool invocations.
- G7. Security floor shared by all: mandatory signature verification, deny-all grants, fuel + epoch + memory caps, no ambient WASI network/fs.

**Non-goals**
- Rewriting native side-effect drivers into wasm (gough BMC/IPMI/cloud SDKs, tobogganing rtnetlink/WireGuard, subprocess scanners, interactive shells). These stay **host-side** and are exposed to wasm tools as *capabilities* where useful.
- Replacing product grant policy (waddles `bundle_capability_gate`, tobogganing entitlements). Products plug in via a trait.
- LLM agent loops (waddleai `agentic_loop`) — they become *callers* of the interface.
- Editing any repository other than penguin-libs (consumer adoption is a handoff, §6).
- Re-implementing platform wire protocols — those stay in the `penguin-connector-*` crates; tools-host only adapts them.
- A build toolchain for guests beyond SDK helpers (waddles `bundle_compiler` remains product-side in v1).

## 3. Architecture

```
                      ┌─────────────── product (waddles / penguind / waddleai / gough / tobogganing) ───────────────┐
 caller (LLM loop,    │  GrantResolver impl   CapabilityProvider impls   FlagGate impl   ScopeBuilder (from JWT/SVID) │
 MCP, REST, scheduler)│         │                     │                        │                 │                  │
        │             └─────────┼─────────────────────┼────────────────────────┼─────────────────┼──────────────────┘
        ▼                       ▼                     ▼                        ▼                 ▼
 ┌──────────────────────────────── penguin-tools-host (Rust) ────────────────────────────────────────────┐
 │ ToolHost::invoke(scope, ToolRef, args, opts)                                                          │
 │   1 flag/kill-switch → 2 resolve ToolRef→Module(digest) → 3 grant check → 4 input schema validate      │
 │   → 5 instantiate (pooled, fresh Store, fuel+epoch+mem) → 6 call `provider.call` under deadline       │
 │   → 7 host capability calls routed via CapabilityRegistry (each re-checks grant + scope)               │
 │   → 8 output schema validate → 9 telemetry (OTel span/metrics/log) → ToolResult                        │
 │ Loader: fetch → sha256 digest → ed25519 sidecar verify (mandatory) → compile (precompile cache) → Registry│
 └───────────────▲──────────────────────────────────────────────────────────────▲────────────────────────┘
                 │ in-process (Rust consumers)                                    │ executor mode
                 │                                                     penguin-bundle-host wire (length-prefixed JSON)
                 │                                                                │
          penguind / node-agents                            waddles svc_*  ·  penguin-tools Python client (waddleai, gough, tobogganing)
```

### 3.1 Crates / packages (all in penguin-libs, MIT)

| Package | Lang | Purpose |
|---|---|---|
| `wit/penguin-tools/` (`penguin:tools@0.1.0`) | WIT | Canonical interfaces + worlds (§4). Vendored by guests/products via `wit-deps`. |
| `packages/rust-tools-host` (`penguin-tools-host`) | Rust | Engine, loader, verifier, registry, dispatcher, capability registry, limits, telemetry. Feature flags: `executor` (wire server), `in-process`. |
| `packages/rust-bundle-host` (`penguin-bundle-host`) | Rust | **Kept** as the wire protocol. Additive: `ToolInvoke`/`ToolResult` bodies carrying `ToolRef`, typed scope, idempotency key; capability becomes `String` id (with `CapabilityKind` kept as constants for compat). |
| `packages/rust-tools-sdk` (`penguin-tools-sdk`) | Rust | Guest helpers: `#[tool]` macro → descriptor + JSON Schema (schemars), wit-bindgen glue. |
| `packages/rust-connectors/crates/penguin-connector-core` | Rust | **New, in the existing connectors workspace.** The shared `Connector` / `Receiver` / `Sender` / `SignatureVerifier` traits and normalized `ChatEvent`, `SendOutcome`, `ConnectorError` types (§5.8). Existing platform crates implement it; no behaviour change. |
| `packages/rust-tools-connectors` (`penguin-tools-connectors`) | Rust | Adapter crate: `ConnectorCapability<C: Connector>` (a `CapabilityProvider`), `ConnectorRegistry`, and the inbound `EventTrigger` that routes normalized events to tool invocations. Depends on `penguin-tools-host` + `penguin-connector-core` only — never on a concrete platform crate. |
| `packages/rust-tools-client` (`penguin-tools-client`) | Rust | Async wire **client** for the executor (framing, correlation, deadlines, scope from validated JWT/SVID), MCP descriptor mapping. **All clients are Rust (D5)** — no Python client or Python guest SDK. |

### 3.2 Hosting modes

| Mode | Used by | Why |
|---|---|---|
| **In-process** (`ToolHost` in the caller's tokio runtime) | penguind, Rust agents | Single binary; client-side; low latency. |
| **Executor** (separate sandboxed process/pod speaking `penguin-bundle-host` wire) | waddles (already), waddleai, gough, tobogganing hub | Blast-radius isolation from the API process. Callers use the Rust `penguin-tools-client`; Python tool/caller code in those products is **ported to Rust** (D5), not bridged. |

Both modes run the **same** dispatcher; the executor is a thin wire adapter around `ToolHost`.

## 4. WIT contract (`penguin:tools@0.1.0`)

```wit
package penguin:tools@0.1.0;

interface types {
  /// Side-effect class drives idempotency + approval policy.
  enum effect { read, write, destructive }

  record tool-descriptor {
    name: string,            // `[a-z][a-z0-9_.-]{0,63}`, unique within module
    version: string,         // semver of the tool contract
    description: string,
    input-schema: string,    // JSON Schema 2020-12 (canonical JSON)
    output-schema: string,   // JSON Schema 2020-12
    effect: effect,
    capabilities: list<string>,  // required capability ids, e.g. "penguin:http"
  }

  variant tool-error {
    not-granted,
    forbidden,
    invalid-args(string),        // schema violation / malformed
    timeout,
    depth-exceeded,
    pool-exhausted,
    target-unavailable,
    capability-failed(string),   // capability id
    failed(string),              // tool-defined failure, ≤512 B, no secrets
  }
}

/// Guest export — every tool module implements this.
interface provider {
  use types.{tool-descriptor, tool-error};
  describe: func() -> list<tool-descriptor>;
  /// args/result: canonical JSON bytes, validated by the host against the schemas.
  call: func(name: string, args: list<u8>) -> result<list<u8>, tool-error>;
}

/// Host import — call another tool. Host is sole authority on scope; callee runs under ITS OWN grants.
interface invoker {
  use types.{tool-error};
  invoke: func(target: string, tool: string, args: list<u8>, idempotency-key: option<string>)
    -> result<list<u8>, tool-error>;
}

/// Read-only view of the host-built scope (UUIDs only, no PII).
interface context {
  record scope { tenant: string, team: option<string>, actor: option<string>, module: string, trace-id: string }
  current: func() -> scope;
}

/// Generic capabilities every product may grant.
interface http  { /* request(req) -> result<response, http-error>; host-side egress guard */ }
interface kv    { /* get/set/delete, scope-partitioned by host */ }
interface log   { /* emit(level, message, fields-json) → penguin logging + OTel */ }
interface clock { /* now, monotonic */ }
interface feature-flags { /* enabled(key) -> bool — fail CLOSED on backend error */ }

world tool-module {
  import context; import log; import clock;            // always linked
  import http; import kv; import feature-flags; import invoker; import connector; // linked, but every call grant-checked
  export provider;
}
```

- Product worlds **extend** `tool-module` with their own interfaces (e.g. `waddle:bundle/reputation`, `penguind:net/doh`) — never edit `penguin:tools`.
- `describe()` is called once at load; descriptors are cached with the digest and must match the signed manifest (§5.2) — mismatch = load failure.
- waddles' `tool.wit` maps 1:1 (`tool.invoke` → `invoker.invoke`, `tool-provider.call` → `provider.call`); adds `describe` + schemas.

## 5. Host behaviour

### 5.1 Engine (single pinned config)
- wasmtime: **one pinned version across all consumers** (proposal: `=50.0.x`, waddles moves up from 49.0.4). Features: component-model, async, cranelift, pooling-allocator. WASI p2 with **no** sockets, no ip-name-lookup, empty env/args, optional read-only scratch preopen only.
- Fuel **and** epoch interruption (epoch tick 10–50 ms, one shared ticker per `Engine`, not per runtime).
- Defaults (overridable per module within host maxima): deadline 2 s (max 10 s), memory 64 MiB (max 256), fuel 500M, nested-invoke depth 4, ≤256 capability calls per invocation, args/result ≤ 1 MiB (wire frame cap).
- Fresh `Store` per invocation; pooled instances; precompiled `.cwasm` cache keyed by (digest, engine fingerprint).

### 5.2 Loading & verification (fail-closed)
1. Fetch bytes (bucket / OCI / https) — https-only, no redirects, resolved-IP pinning (penguind `fetcher.rs` pattern).
2. `sha256` must equal the requested digest.
3. **Ed25519 sidecar signature is mandatory** over `penguin-tools/v1\nid=..\nversion=..\nsha256=..\nmanifest_sha256=..`. Key set supports rotation (waddles `signing.rs`). No "skip when no key configured" path — missing keys = host refuses to start (§9 fixes waddles `invoke.rs:758`).
4. Signed **tool manifest** (YAML/JSON) lists tools + required capabilities; must equal `describe()` output. This implements penguind's promised "signed manifest allowlist".
5. Registry keyed by digest; refcounted per scope; single-flight compile.

### 5.3 Dispatch order (from penguind `registry.rs`, extended)
`flag kill-switch → resolve ToolRef → module loaded & digest pinned → GrantResolver.authorize(scope, module, tool) → input schema → [idempotency check for write/destructive] → call under deadline → output schema → telemetry`. Every capability call re-enters `GrantResolver` with `(scope, module, capability, op, resource)`.

### 5.4 Product extension points (traits)
```rust
pub trait GrantResolver: Send + Sync {      // waddles: bundle_capability_gate; tobogganing: entitlements
    async fn authorize_tool(&self, s: &InvocationScope, m: &ModuleId, t: &ToolName) -> Result<(), Denial>;
    async fn authorize_capability(&self, s: &InvocationScope, m: &ModuleId, cap: &CapabilityId, op: &str) -> Result<(), Denial>;
}
pub trait CapabilityProvider: Send + Sync { // one per capability id; product-owned
    fn id(&self) -> CapabilityId;            // "penguin:http", "waddle:reputation", "gough:bmc.power"
    fn link(&self, linker: &mut Linker<HostState>) -> anyhow::Result<()>;
}
pub trait FlagGate: Send + Sync { async fn enabled(&self, key: &str, s: &InvocationScope) -> bool; } // fail closed
pub struct InvocationScope { tenant: Uuid, team: Option<Uuid>, actor: Option<Uuid>, tier: Tier, trace: TraceContext, depth: u8, deadline: Instant }
```
- `InvocationScope` is built only by host code from a validated JWT / SPIFFE SVID; there is no constructor from guest data.
- Connector-backed providers come from `penguin-tools-connectors` (§5.8), not the host crate.
- Built-in providers shipped by the crate: `penguin:log`, `penguin:clock`, `penguin:context`, `penguin:http` (port of waddles `EgressGuard`: SSRF guard, DNS pinning, redirect recheck, host-side secret-ref injection), `penguin:kv` (backend trait), `penguin:flags`.

### 5.5 Telemetry (mandatory)
- Spans: `tool.invoke` (attrs: module digest, tool name, effect, outcome — never args/results).
- Metrics: `penguin_tools_invocations_total{tool,outcome}`, `penguin_tools_invocation_seconds` (histogram), `penguin_tools_fuel_used` (histogram), `penguin_tools_capability_calls_total{capability,outcome}`. Unbounded labels (guest-supplied names) collapse to `unresolved`.
- **All telemetry via `penguin-logging` (`packages/rust-logging`, OTel-based: `tracing` + `tracing-opentelemetry` + `opentelemetry-otlp` 0.32)** — hard dependency of `penguin-tools-host`, executor and client; `init(ServiceConfig::from_env(..))` at startup; no hand-rolled logging/`println!`, no direct OTel SDK setup. The guest `log` capability forwards into the same pipeline. OTLP from `OTEL_*` env only; dead exporter never fails a call. Smoke tests use the `testing` feature (`init_test_telemetry`, `TelemetryCounts`) to assert logs/metrics/histograms/spans ≥1.
- Consumers migrate their existing logging to `penguin-logging` as part of adoption (waddles executor `telemetry.rs` + prometheus/metrics crates, penguind `tools/metrics.rs` prometheus registry).

### 5.6 Feature flags & licensing
- Per product: `{product}.wasm-tools` (default OFF) + kill-switch semantics checked **per invocation**, not only at run start (penguind gap).
- Licensing is product policy via `GrantResolver`/`FlagGate`; crate ships no tier logic.

### 5.7 MCP / caller mapping
`ToolDescriptor` → MCP `{name, description, inputSchema, outputSchema, annotations.destructiveHint = effect==destructive}`. waddleai's MCP mount can list and call executor-hosted tools; results tagged with provenance (`trust_tier`) as the gateway already does.

### 5.8 Connectors layer
**Common trait** (`penguin-connector-core`, designed from the shapes the two implemented connectors already have):
```rust
pub trait Connector: Send + Sync {
    fn platform(&self) -> Platform;                        // Twitch | Discord | Slack | YouTube | Kick
    fn sender(&self) -> Option<&dyn Sender>;               // None = receive-only
    fn verifier(&self) -> Option<&dyn SignatureVerifier>;  // None where the platform has none (e.g. Slack Socket Mode)
}
#[async_trait] pub trait Sender: Send + Sync {
    /// `target` = channel/room id; connectors whose target is fixed in config (Twitch IRC) ignore None.
    async fn send(&self, target: Option<&str>, text: &str) -> Result<SendOutcome, ConnectorError>;
}
pub trait SignatureVerifier: Send + Sync { fn verify(&self, headers: &HeaderMap, body: &[u8]) -> bool; } // constant-time
#[async_trait] pub trait Receiver: Send {
    async fn recv(&mut self) -> Result<Option<ChatEvent>, ConnectorError>;   // None = clean close
}
pub struct ChatEvent { platform, id, channel, author_id, author_name, text, received_at, raw: Option<Value> }
```
- `ConnectorError` is a closed, secret-free enum (`Auth`, `RateLimited{retry_after}`, `Unavailable`, `Protocol`, `Rejected`); platform errors map into it and never carry tokens.
- Platform crates gain `impl Connector` behind their existing API; their public functions are untouched. Scaffolded crates (slack, youtube, kick) implement it returning `ConnectorError::Unavailable("not implemented")` — **no silent success**.

**As capability** (outbound): `ConnectorCapability` registers `penguin:connector.<platform>` with WIT ops `send(target, text) -> send-outcome`. Credentials live in the host-side connector instance, are resolved by the product through a `CredentialResolver` trait (secret refs, same pattern as `penguin:http` secret-ref injection) and are never visible to the guest. Every call re-enters `GrantResolver` with `(scope, module, "penguin:connector.twitch", "send", target)`; `target` is the resource, so grants can be per-channel. Outbound text is length-capped and rate-limited per (tenant, platform, target) by the adapter.

**As trigger** (inbound): `EventTrigger` consumes a `Receiver` (or a verified webhook body) and, per `TriggerBinding {platform, filter, tool, scope_source}`, calls `ToolHost::invoke` with a **host-built** `InvocationScope` — the scope comes from the binding's tenant, never from event content. Event text is passed as data in `args`, never interpreted by the host. Bindings are product-owned config; the library ships no default bindings. Backpressure: bounded queue per binding, drop-oldest with a counter metric (`penguin_tools_trigger_dropped_total`), never unbounded.

**Security notes:** webhook bodies pass `SignatureVerifier` before any parsing; replay protection stays in the platform crate (Twitch `ReplayGuard`); a tool's `send` capability cannot target a platform other than its granted capability id; connector tokens are redacted in `Debug` (already true in the platform crates — adapter must not regress it).

## 6. Consumer handoff (out of scope — penguin-libs only)
No changes are made to consumer repos. The table records what each product would do later, for the owners of those repos.

| Product | Later change (NOT done here) | Effort | Keeps |
|---|---|---|---|
| **waddles** | Executor swaps its engine/loader/registry for `penguin-tools-host`; `stage-tools` world extends `penguin:tools/tool-module`; gate becomes `GrantResolver`; merge actor-scope work. Frozen `stage*` worlds untouched (transform/dispatch stay as product exports). | M | `bundle_capability_gate`, compiler, product WIT |
| **penguind** | **Commit the untracked work first.** Replace core-module `call_tool` ABI with `tool-module` world; `tool_definitions.json` → descriptors; minisign → ed25519 sidecar (or support both during transition); keep `ModuleLimits`/allowlist as `GrantResolver`. | M | executors as `CapabilityProvider`s (`doh_query`, `config_read`, …) |
| **waddleai** | Port MCP tools (`shared/mcp/tools.py` user + admin sets) and the CLI agent tools to Rust — wasm guests where sandboxable, Rust host capabilities otherwise; Rust MCP surface lists/calls executor tools via `penguin-tools-client`. | L | external MCP gateway semantics, provenance tagging |
| **gough** | Port cloud/BMC/LXD drivers to Rust `gough:*` capabilities (cert pinning, cipher-0 refusal, audit preserved); plan-step validators as wasm tools. Fix SPIFFE chain validation (`app/grpc_auth.py:55`) first. | XL | driver behaviour + audit trail |
| **tobogganing** | Port `ModuleContract` job handlers + entitlement gate to Rust (`GrantResolver`); scanners (trivy/govulncheck) become a host capability; node-agent (already Rust) embeds the in-process host. | L | module API surface |
| **waddles** (Python guest SDK) | `sdk/waddle-sdk` (componentize-py) bundles ported to Rust guests via `penguin-tools-sdk`. | M | — |

## 7. Security requirements (acceptance gates)
1. No unsigned module ever instantiates (test: unsigned/tampered/rotated-out key → `LoadFailed`).
2. Deny-all default: a module with no grants can call `log`/`clock`/`context` only.
3. Guest cannot set or alter scope; nested invoke runs under callee grants; depth cap enforced.
4. Schema validation in **and** out; oversized args/results rejected before allocation.
5. `hang_forever`, `memory_hog`, `fuel_burner`, `invoke_recursion` fixtures each terminate with the right typed error within deadline + 1 tick.
6. No secret/PII in spans, metric labels, logs, error strings (redaction tests).
7. `cargo deny`/`cargo audit` clean; coverage ≥90 % lines+branches.

## 8. Decisions needed from reviewer

| # | Question | Decision |
|---|---|---|
| D1 | New crate `penguin-tools-host` vs grow `penguin-bundle-host`? | ✅ **ACCEPTED 2026-11-09** — new crate; bundle-host stays the wire. |
| D2 | Component model vs penguind core-module ABI? | ✅ **ACCEPTED** — component model; core ABI dropped after penguind migrates. |
| D3 | Signing format? | ✅ **ACCEPTED** — ed25519 sidecar with rotation; minisign read-only during penguind transition. |
| D4 | wasmtime pin? | ✅ **ACCEPTED** — `=50.0.x` everywhere. |
| D5 | Python hosting? | ✅ **DECIDED (revised)** — every client (non-CLI) is **Rust**; no Python client, no Python guest SDK. Python tool code in waddleai/gough/tobogganing and waddles' Python guest SDK is **ported to Rust** (§6). |
| D6 | Capability IDs? | ✅ **ACCEPTED** — namespaced strings (`ns:name`), validated at load. |
| D7 | Where do tool manifests live? | ✅ **ACCEPTED** — signed sidecar next to the component is authoritative; products may embed copies. |
| D8 | Release line | ✅ **ACCEPTED** — `release/rust-tools-host/v0.1.x`, `publish = false` until 0.2 (git-rev pinning). |
| D9 | Go components | ✅ **DECIDED 2026-11-09** — all Go is ported to Rust: tobogganing Go engines (testserver), gough `discovery-agent`, and penguin-libs `go-*` packages. No Go in any part of this interface. penguin-libs Go modules are **deprecated, never removed** (existing versions stay installable); they keep receiving security patches (priority 1) until consumers migrate. |
| D11 | Connectors integration | ✅ **DECIDED 2026-11-10** — shared `Connector` trait in `penguin-connectors` (new `penguin-connector-core`); tools-host adapts connectors as capabilities (`penguin:connector.<platform>`) via the new `penguin-tools-connectors` crate. |
| D12 | Scope | ✅ **DECIDED 2026-11-10** — penguin-libs only. No edits to waddles/penguind/waddleai/gough/tobogganing; adoption is handoff notes (§6). |
| D13 | Inbound events | ✅ **DECIDED 2026-11-10** — connector events can trigger tools through host-scoped `TriggerBinding`s (§5.8). Scope never derives from event content. |
| D14 | Cross-package deps | ⏳ **OPEN** — `penguin-logging`, `penguin-bundle-host`, `penguin-connectors` live only on their `release/*` branches, not `main`. Proposal: git-rev pins (D8) until each is on `main`. |
| D10 | Logging/telemetry | ✅ **DECIDED** — `penguin-logging` (OTel) everywhere (§5.5). |

## 9. Pre-existing issues found during review (fix independently)
*Only the penguin-libs items are in scope. The rest are listed for their repo owners and are not touched by this work.*

- waddles `core/bundle_executor/src/invoke.rs:758` — signature check skipped when no platform keys configured.
- waddles — two different enums named `CapabilityKind` (wire vs gate); duplicate drifting manifests (`bundle.yaml` vs `hub-manifest.yaml`); host `flags.enabled`/tier **fail open** (`host/imports.rs ~551`).
- penguind — entire wasm host **untracked/uncommitted**; docs claim "None = all declared" but code is deny-all; flag checked only at run start; 7/11 tools `NotImplemented`.
- penguin-bundle-host — plan doc out of sync (says no manifest parsing; crate ships 31 rules); 0.5.0 untagged; PR #132 based on 0.1.0.
- gough — `app/grpc_auth.py:55-58` SPIFFE helper does no chain validation.
