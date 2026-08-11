# penguin-rpc (pRPC) Phase 1 — Go Reference Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn `packages/go-rpc` from a scaffold into the working pRPC reference implementation: Connect RPC served over dual HTTP/3+HTTP/2 with spec-mandated hardening, zero-trust interceptor chain, protovalidate enforcement, health + conformance services, MCP/A2A mounting, and a multi-lane fallback client — validated by an integration matrix in CI.

**Architecture:** Salvage the proven transport core from `packages/go-h3` (dual-listener server, fallback client, observability interceptors, health checker) into go-rpc's packages, upgraded to the pRPC spec (spec/SPEC.md): TLS 1.3-only, 0-RTT off, 4 MiB caps, default deadlines, X-Correlation-Id. New code: deny-by-default auth chain wiring go-aaa, protovalidate interceptor, generated-stub services (health, conformance), MCP/A2A mount helpers, multi-lane DialStrategy.

**Tech Stack:** Go 1.25, connect-go v1.20.0, quic-go (≥v0.57.0), protovalidate-go, go-aaa (local replace), MCP go-sdk v1.x, a2a-go v2.x, zap, buf codegen.

## Global Constraints

- Worktree `/home/penguin/code/penguin-libs/.worktrees/penguin-rpc`, branch `feature/penguin-rpc`. Commit per task; never push; never touch main. Do NOT modify `packages/go-h3/` (salvage = copy+adapt, Phase 5 retires it).
- Every new `.go` file starts with `// Copyright 2026 Penguin Tech Inc` + `// SPDX-License-Identifier: Apache-2.0` + **blank line** before `package` (godoc rule from Phase 0).
- Package doc comments: only `doc.go` carries the package comment (2–3 line docstring per org rules on every exported type/func).
- go.mod stays `go 1.25.0` (local toolchain is go1.26.4 — never let it bump the directive; `GOTOOLCHAIN=local go mod tidy` if needed). All deps pinned exact versions — resolve latest stable with `go list -m -versions <mod>` and record; NEVER `@latest`.
- TDD per task: failing test observed before implementation; `go test -race ./...` green + `go vet` + `gofmt -l` empty before each commit.
- Spec values (normative, from spec/SPEC.md): TLS 1.3 only; 0-RTT disabled; 4 MiB default max message; default unary deadline when caller provides none; correlation header `X-Correlation-Id`; deny-by-default auth (procedures opt INTO public); tenant check before scope check; MCP at `/mcp`; agent card at `/.well-known/agent-card.json`; sanitized logging (no tokens/PII; masked `tok_****1234`).
- Generated code lives in `packages/go-rpc/gen/` — never hand-edited; excluded from coverage metrics and lint scope (`.golangci.yml` skip-dirs if needed).
- Salvage sources (read, copy, adapt — cite in report): `packages/go-h3/server/{server.go,options.go,tls.go,middleware.go}`, `packages/go-h3/client/{client.go,options.go,retry.go}`, `packages/go-h3/health/health.go` + their `_test.go` files. go-aaa interceptors: `packages/go-aaa/middleware/{tenant.go,authn.go,authz.go,audit.go}`.

---

### Task 1: Codegen wiring + generated stubs

**Files:**
- Modify: `proto/buf.gen.yaml` (add go-rpc outputs), `Makefile` (new `prpc-generate` target), `packages/go-rpc/go.mod`
- Create: `packages/go-rpc/gen/` (generated), `packages/go-rpc/gen/README.md` (one line: generated, do not edit, regen via `make prpc-generate`)

**Interfaces:**
- Produces: importable stubs `github.com/penguintechinc/penguin-libs/packages/go-rpc/gen/prpc/health/v1` (+ `/healthv1connect`) and `.../gen/prpc/conformance/v1` (+ `/conformancev1connect`); `make prpc-generate` (regen) and regen-and-diff check used by Task 10.

- [ ] Add to `proto/buf.gen.yaml` two plugin entries scoped to go-rpc: `buf.build/protocolbuffers/go` and `buf.build/connectrpc/go`, both `out: ../packages/go-rpc/gen`, `opt: paths=source_relative`, with `inputs`/module-level `--path prpc` filtering if v2 supports it — otherwise generate all and `git clean` non-prpc dirs from `packages/go-rpc/gen/` in the make target (document choice). Existing plugin entries untouched.
- [ ] `Makefile`: add `prpc-generate:` target — `cd proto && buf generate --path prpc` then `cd packages/go-rpc && go mod tidy`. Add `prpc-generate-check:` — regen + `git diff --exit-code packages/go-rpc/gen/` (used in CI).
- [ ] Run it; add `option go_package` lines to BOTH prpc protos (`.../packages/go-rpc/gen/prpc/health/v1;healthv1` and `.../gen/prpc/conformance/v1;conformancev1`) — REQUIRED for correct import paths; verify `buf lint`/`buf format --diff`/`buf breaking --against main` still pass (go_package additions are non-breaking).
- [ ] go.mod: add exact-pinned `connectrpc.com/connect v1.20.0`, `google.golang.org/protobuf` (latest stable), `buf.build/gen/go/bufbuild/protovalidate/protocolbuffers/go` (protovalidate proto deps for the conformance stub) — resolve exact versions, no @latest.
- [ ] Verify: `cd packages/go-rpc && go build ./... && go vet ./...` compiles the generated packages.
- [ ] Commit: `feat(go-rpc): buf codegen wiring + generated prpc health/conformance stubs`

### Task 2: Server core (salvaged, spec-hardened)

**Files:**
- Create: `packages/go-rpc/server/{server.go,options.go,tls.go,doc.go}` + `_test.go` for each

**Interfaces:**
- Produces: `server.Config{H2Addr, H3Addr, H2Enabled, H3Enabled bool, TLSConfig *tls.Config, GracePeriod time.Duration, MaxMessageBytes int (default 4<<20), DefaultUnaryTimeout time.Duration (default 30s), Interceptors []connect.Interceptor}`; `DefaultConfig()`; `ConfigFromEnv()` (env: `H2_PORT,H3_PORT,H2_ENABLED,H3_ENABLED,TLS_CERT_PATH,TLS_KEY_PATH,HTTP3_ENABLED` — HTTP3_ENABLED=false is the operator kill-switch, default true); `New(cfg Config, logger *zap.Logger) (*Server, error)`; `(*Server).Mux() *http.ServeMux`; `(*Server).Start(ctx) error` (graceful); `(*Server).ListenAddr(protocol string) string`; `NewTLSConfig(certPath, keyPath string) (*tls.Config, error)`; `SelfSignedTLSConfig() (*tls.Config, error)` (tests/examples only).

- [ ] Salvage from go-h3 server package; adapt with spec hardening, each enforced IN CODE and ASSERTED IN TESTS: `tls.Config.MinVersion = tls.VersionTLS13` forced in New() regardless of input; http3.Server QUIC config `Allow0RTT: false` (assert the constructed config); h2 http.Server timeouts (ReadHeaderTimeout etc.); MaxMessageBytes wired to connect handler options via a `HandlerOptions()` helper the service tasks use (`connect.WithReadMaxBytes(cfg.MaxMessageBytes)`); DefaultUnaryTimeout exposed for the interceptor chain (Task 3 wires it).
- [ ] TDD: port go-h3's server tests; add new tests: TLS12 config in → server still negotiates TLS13-only; 0-RTT disabled; dual listeners serve the same mux (loopback with SelfSignedTLSConfig); HTTP3_ENABLED=false → only H2 listener.
- [ ] Commit: `feat(go-rpc): dual H2+H3 server core with pRPC transport hardening (salvaged from go-h3)`

### Task 3: Observability interceptors (salvaged) + deadline interceptor

**Files:**
- Create: `packages/go-rpc/server/middleware.go` + `middleware_test.go`

**Interfaces:**
- Produces: `NewLoggingInterceptor(*zap.Logger)`, `NewMetricsInterceptor()` (Prometheus: request count/duration/errors by procedure), `NewCorrelationInterceptor()` (+ `CorrelationIDFromContext(ctx) string`; header exactly `X-Correlation-Id`), `NewRecoveryInterceptor(*zap.Logger)`, `NewDeadlineInterceptor(d time.Duration)` (applies default ctx timeout to unary calls lacking one), `DefaultInterceptors(logger, cfg) []connect.Interceptor` (canonical order: recovery → correlation → deadline → logging → metrics).
- Consumes: server.Config.DefaultUnaryTimeout (Task 2).

- [ ] Salvage go-h3 `server/middleware.go` + tests; rename header to `X-Correlation-Id` per spec; add the deadline interceptor (new — test: handler observes ctx deadline when client sent none; existing client deadline NOT overridden).
- [ ] Logging sanitization test: authorization/cookie header values never appear in log output (zap observer core).
- [ ] Commit: `feat(go-rpc): observability interceptor suite + default-deadline enforcement`

### Task 4: Zero-trust auth package

**Files:**
- Create: `packages/go-rpc/auth/{auth.go,doc.go,auth_test.go}`
- Modify: `packages/go-rpc/go.mod` (+ go-aaa require + `replace => ../go-aaa`, matching go-aaa's own replace pattern for go-common)

**Interfaces:**
- Produces: `auth.Config{Mode string ("oidc"|"spiffe"|"both"), OIDC *authn.OIDCRelyingParty, SPIFFE *authn.SPIFFEAuthenticator, Enforcer *authz.RBACEnforcer, Scopes middleware.ProcedureScopes, Public []string, Audit *audit.Emitter (optional)}`; `auth.Interceptors(cfg Config) ([]connect.Interceptor, error)` returning the spec-ordered chain: tenant → authn (OIDC/SPIFFE) → authz → audit(optional). Deny-by-default: a procedure absent from BOTH cfg.Scopes and cfg.Public is rejected `CodePermissionDenied` before reaching the handler; Public procedures skip authn/authz entirely but still get tenant-if-present passthrough.
- Consumes: go-aaa `middleware.NewTenantInterceptor`, `NewOIDCInterceptor`, `NewSPIFFEInterceptor`, `NewAuthzInterceptor(enforcer, procedures, opts...)`, `NewAuditInterceptor` (read those files first; reuse — do NOT reimplement claim validation).

- [ ] Read go-aaa middleware to determine how Public/skip lists are expressed (its `InterceptorOption`s); wrap rather than fork. The deny-by-default gate is go-rpc's own thin interceptor placed first-after-tenant if go-aaa's authz doesn't already deny unknown procedures (verify by reading `authz.go`; document which case applied).
- [ ] TDD (in-memory tokens/identities, table-driven): no credentials → CodeUnauthenticated; valid token missing tenant claim → denied BEFORE scope evaluation (assert error ordering); valid tenant + missing scope → CodePermissionDenied; procedure not declared anywhere → CodePermissionDenied even with valid admin token; Public procedure → 200 with zero credentials; roles claim alone (no scope) grants nothing.
- [ ] Commit: `feat(go-rpc): deny-by-default zero-trust auth chain wiring go-aaa (tenant→authn→authz)`

### Task 5: Protovalidate interceptor

**Files:**
- Create: `packages/go-rpc/server/validate.go` + `validate_test.go`
- Modify: `packages/go-rpc/go.mod` (+ `buf.build/go/protovalidate` latest stable, exact pin)

**Interfaces:**
- Produces: `NewValidationInterceptor() (connect.Interceptor, error)` — validates every request message (unary + each client-stream message) against embedded protovalidate constraints; violations → `connect.NewError(connect.CodeInvalidArgument, err)` with the violation detail; handler never invoked on invalid input.

- [ ] TDD against the generated conformance stubs (Task 1): `EchoRequest{message: ""}` → InvalidArgument (min_len 1); 4097-byte message → InvalidArgument (max_len 4096); `repeat: 101` → InvalidArgument (lte 100); valid request passes through untouched; message types WITHOUT constraints skip cleanly (health.CheckRequest).
- [ ] Commit: `feat(go-rpc): protovalidate server interceptor — contract constraints enforced at runtime`

### Task 6: Multi-lane client (salvaged + DialStrategy)

**Files:**
- Create: `packages/go-rpc/client/{client.go,options.go,retry.go,lanes.go,doc.go}` + `_test.go` each

**Interfaces:**
- Produces: `client.Config{BaseURL string, Lanes []Lane (default [LaneH3, LaneH2]), TLSConfig *tls.Config, DialTimeout, IdleTimeout time.Duration, AltSvcUpgrade bool (default true)}`; `Lane` type (`LaneH3`, `LaneH2`; `LaneZiti` reserved const, returns ErrLaneUnavailable in Phase 1 — Phase 4 fills it); `New(cfg Config, logger *zap.Logger) (*Client, error)`; `(*Client).HTTPClient() *http.Client` (feeds generated Connect client constructors — its RoundTripper does lane selection/failover per request); `(*Client).Protocol() string` ("h3"/"h2" — last successful lane); `(*Client).MarkLaneFailed(Lane)` / `(*Client).MaybeRetryLane(Lane)` (generalize go-h3's MarkH3Failed/MaybeRetryH3 cooldown logic); `RetryConfig` + `DoWithRetry[T]` (salvage verbatim semantics: exponential backoff, no retry on 4xx-class codes); Alt-Svc: on H2 responses carrying an `alt-svc: h3=...` hint and AltSvcUpgrade, promote H3 lane for NEW requests (in-flight unaffected — RoundTripper decides per request).
- Consumes: `server` package (tests spin real loopback servers via Task 2).

- [ ] Salvage go-h3 client + retry (+tests); refactor h3/h2 special-casing into the ordered-lane engine; TLS 1.3 min forced client-side too.
- [ ] TDD: H3-up → Protocol()=="h3"; H3 listener down → transparent H2 fallback, Protocol()=="h2", no error surfaced; failed lane cooldown then MaybeRetryLane restores; Alt-Svc hint on H2 response flips subsequent requests to H3 (loopback server toggling H3 on); DoWithRetry: 3 attempts on CodeUnavailable then success; zero retries on CodeInvalidArgument/CodePermissionDenied.
- [ ] Commit: `feat(go-rpc): multi-lane client with H3→H2 fallback, Alt-Svc upgrade, retry (salvaged from go-h3)`

### Task 7: Health service

**Files:**
- Create: `packages/go-rpc/health/{health.go,doc.go,health_test.go}`

**Interfaces:**
- Produces: `health.NewChecker()` (salvage go-h3 Checker: `SetStatus(service string, s Status)`, `GetStatus`), `health.NewService(c *Checker) healthv1connect.HealthServiceHandler` (implements `Check` + streaming `Watch` — Watch sends current status immediately then pushes on change; test via channel-driven status flips), `health.Register(mux *http.ServeMux, c *Checker, opts ...connect.HandlerOption)` (mounts the Connect handler AND plain `GET /healthz` returning 200/503 JSON `{"status":"SERVING"}`).
- Consumes: generated `healthv1`/`healthv1connect` (Task 1), `server.HandlerOptions()` (Task 2).

- [ ] TDD: Check unknown service → SERVING_STATUS_UNSPECIFIED behavior decision: empty-string service = whole process (spec §8); Watch streams the transition NOT_SERVING→SERVING; /healthz flips 200↔503 with checker state.
- [ ] Commit: `feat(go-rpc): prpc.health.v1 service (Check/Watch) + /healthz endpoint`

### Task 8: Conformance service

**Files:**
- Create: `packages/go-rpc/conformance/{conformance.go,doc.go,conformance_test.go}`

**Interfaces:**
- Produces: `conformance.NewService() conformancev1connect.ConformanceServiceHandler` + `conformance.Register(mux, opts ...connect.HandlerOption)`. Semantics: `Unary` echoes message (repeat co-determines response: message repeated `repeat` times joined by ""? NO — keep simple + spec-aligned: response.message = request.message; `repeat` only drives ServerStream count); `ServerStream` sends `repeat` (default 1) responses; `ClientStream` concatenates received messages (bounded by 4 MiB cap) and returns one response; `BidiStream` echoes each received message as it arrives (full-duplex). Every response sets `protocol` = "h3" when `req.Peer().Protocol`/HTTP major version is 3, else "h2" (determine the reliable connect-go mechanism — `req.HTTPMethod()`/header `:protocol` or an http middleware stamping a context key from `r.ProtoMajor`; document choice).
- Consumes: generated conformance stubs, server.HandlerOptions().

- [ ] TDD: all four patterns over an in-process server (H2 loopback); protocol field correctness verified over BOTH lanes in Task 10's integration (unit test asserts the context-stamping mechanism).
- [ ] Commit: `feat(go-rpc): prpc.conformance.v1 service — all four Connect call patterns`

### Task 9: MCP + A2A mount helpers

**Files:**
- Create: `packages/go-rpc/mcp/{mcp.go,doc.go,mcp_test.go}`, `packages/go-rpc/a2a/{a2a.go,doc.go,a2a_test.go}`
- Modify: `packages/go-rpc/go.mod` (+ `github.com/modelcontextprotocol/go-sdk` latest v1.x exact; + a2a-go official module latest v2.x exact — resolve real module paths; if a2a-go's v2 module cannot be added cleanly under Go 1.25 constraints, STOP and report options rather than forcing)

**Interfaces:**
- Produces: `mcp.Mount(mux *http.ServeMux, server *mcpsdk.Server) error` — mounts Streamable HTTP handler at exactly `/mcp` (spec §7) inheriting the server's TLS/auth-by-middleware; `a2a.Mount(mux *http.ServeMux, card []byte (or the SDK's card type), handler http.Handler) error` — serves the agent card at `/.well-known/agent-card.json` (unauthenticated discovery per spec) and mounts the SDK's JSON-RPC handler at the path SPEC.md §7 names. Both helpers reject nil mux/server with errors, never panic.
- Consumes: spec §7 exact paths.

- [ ] TDD with the OFFICIAL SDK clients where feasible (mcp go-sdk client over httptest → initialize handshake succeeds; a2a: GET agent card returns the JSON + JSON-RPC endpoint answers a well-formed request). If an SDK's test surface is too heavy for unit scope, test the mounting contract (paths, content-types, 405s) and defer full SDK round-trip to Task 10 integration — state which.
- [ ] Commit: `feat(go-rpc): MCP and A2A mount helpers on the pRPC server (official SDKs)`

### Task 10: Integration matrix + CI/coverage gates + examples

**Files:**
- Create: `packages/go-rpc/integration/integration_test.go` (build tag `integration`), `packages/go-rpc/examples/echo-server/main.go`, `packages/go-rpc/examples/echo-client/main.go`
- Modify: `.github/workflows/prpc-packages.yml` (integration job + regen-and-diff step), `Makefile` (`prpc-integration` target)

**Interfaces:**
- Consumes: everything above. Produces: the Phase 1 verification gate.

- [ ] Integration test (real sockets, SelfSignedTLSConfig, full stack: server + DefaultInterceptors + validation + auth(with a permissive test config exercising one denied case) + health + conformance): matrix {H3 lane, H2 lane} × {Unary, ServerStream, ClientStream, BidiStream} asserting `EchoResponse.protocol` matches the lane; plus: H3-down fallback mid-suite; auth deny (missing tenant) over both lanes; oversized message rejected (ReadMaxBytes); protovalidate violation over the wire → InvalidArgument.
- [ ] Examples: echo-server (serves conformance+health with self-signed TLS, both lanes) and echo-client (calls Unary over H3, prints protocol) — compile in CI (`go build ./examples/...`), runnable per README.
- [ ] prpc-packages.yml: replace the Phase-1 placeholder comment with `integration-go` job (needs build-matrix leg? — `needs: [proto-lint]` and runs `go test -race -tags=integration ./integration/...` in packages/go-rpc) + a `codegen-check` job running `make prpc-generate-check` (SHA-pinned buf-setup as existing jobs). Coverage gate: in ci.yml build-go-rpc Test step, switch to `go test -race -coverprofile=cover.out $(go list ./... | grep -v /gen/ | grep -v /examples/)` + fail below 90% total via `go tool cover -func` awk check.
- [ ] Commit: `feat(go-rpc): cross-lane integration matrix, codegen drift gate, 90% coverage gate, examples`

### Task 11: Docs

**Files:**
- Modify: `packages/go-rpc/README.md` (real quickstart replacing scaffold status), `docs/penguin-rpc/README.md` (go-rpc status → "Phase 1 complete: reference implementation"; roadmap tick), `docs/penguin-rpc/CHANGELOG.md` ([Unreleased] Phase 1 section)

- [ ] README quickstart: 20-line server (Config + auth + health + conformance + Start) and 10-line client (New + generated conformance client + Unary call) — code that actually compiles against the shipped API (verify by `go vet` on a temp example or make it a `//go:build ignore` doc file); document env vars incl. HTTP3_ENABLED kill-switch; MCP/A2A mounting snippet; link spec sections.
- [ ] Verify: `make prpc-proto && make prpc-generate-check` green; `git status` clean post-commit.
- [ ] Commit: `docs(go-rpc): Phase 1 quickstart, package docs, changelog`

---

## Verification (phase gate)

- `cd packages/go-rpc && go test -race ./...` — all green, coverage ≥90% (non-gen, non-examples).
- `go test -race -tags=integration ./integration/...` — full matrix green locally.
- `make prpc-proto`, `make prpc-generate-check`, `make lint` (go-rpc lines), `go vet`, `gofmt -l` empty.
- Spec cross-check: every MUST in SPEC.md §3 (transport), §5 (contract runtime), §6 (zero-trust), §8 (operational) traceable to a test named in Tasks 2–10.

## Self-review notes (authoring)

- Task order = dependency order (stubs → server → interceptors → auth/validate → client → services → mounts → integration). Auth (T4) and validation (T5) independent after T2/T1 but sequenced to keep single-writer on go.mod.
- The `refs/tags/v` publish exclusion from Phase 0 stays; nothing here publishes.
- a2a-go module-path uncertainty is explicitly a STOP-and-report gate in T9, not a guess.
- Coverage gate excludes gen/ + examples/ — spec'd in T10 verbatim to avoid drift between local and CI commands.
