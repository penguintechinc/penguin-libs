# penguin-rpc (pRPC) — Design

**Date:** 2026-07-14 · **Status:** Approved · **License:** Apache-2.0 (code + spec)

## Problem & Goal

PenguinTech needs a service-communication framework that succeeds gRPC internally and is designed for **external adoption**: gRPC-style typed RPC carried over HTTP/3/QUIC, serving both Service↔Service and Client/Agent→Service traffic, AI-agent protocols (MCP, A2A) built in, zero-trust security by default. Prior art in-repo (`packages/go-h3`, experimental `penguin_libs.h3`) is superseded: its internals are salvaged, both are retired in the same release pRPC ships.

## Decisions

| Decision | Choice |
|---|---|
| Wire protocol | Connect protocol over HTTP/3 (QUIC primary, HTTP/2 fallback); protobuf + JSON codecs |
| Contracts | proto3 schema-first, **enforced**: generated stubs only, `buf breaking` CI gate, protovalidate runtime constraints |
| Traffic classes | Service↔Service (SPIFFE mTLS / machine JWTs) and Client/Agent→Service (OIDC JWTs) |
| AI protocols | MCP + A2A compliance by **hosting official SDKs** on our transport (mounting, not reimplementing) |
| Security | Zero-trust: identity on every request, deny-by-default per-procedure scopes, tenant-first checks, TLS 1.3 only, 0-RTT disabled |
| OpenZiti | Pluggable Dialer/Listener transport abstraction; optional Ziti overlay adapter (dark services, Connect-over-H2 on Ziti streams) |
| Transport default | `direct` posture: **HTTP/3 primary, automatic HTTP/2 fallback**; Ziti lanes opt-in; "secure-first, then fast" upgrade profile via Alt-Svc-style hints |
| Name / brand | penguin-rpc ("pRPC"); credit via Apache NOTICE + copyright headers + trademark on the name |
| Architecture | **Spec + curated stack**: an open profile spec + three batteries-included packages assembling best-in-class parts |

## Architecture

```
              pRPC SPEC (spec/SPEC.md, prpc/1.0-draft)
  transport │ rpc │ contract │ zero-trust │ AI │ ops │ ziti │ upgrade profiles
┌───────────────────┬────────────────────┬─────────────────────┐
│ packages/rust-rpc │ packages/go-rpc    │ packages/python-rpc │
│ crates: penguin-  │ Go module          │ PyPI: penguin-rpc   │
│ rpc, penguin-h3-  │ (…/packages/go-rpc)│ import: penguin_rpc │
│ tower             │                    │                     │
├───────────────────┼────────────────────┼─────────────────────┤
│ connectrpc (rs)   │ connect-go (GA)    │ connect-python      │ RPC
│ quinn + h3 +      │ quic-go/http3      │ hypercorn[h3] +     │ QUIC
│  our Tower bridge │  (from go-h3)      │  aioquic            │
│ rmcp mount        │ mcp go-sdk mount   │ mcp python-sdk mount│ MCP
│ a2a: deferred     │ a2a-go mount       │ a2a-sdk mount       │ A2A
│ ziti: stub        │ sdk-golang adapter │ openziti adapter    │ Ziti
└───────────────────┴────────────────────┴─────────────────────┘
        + proto/prpc (Buf v2) + cross-language conformance matrix in CI
```

Key novel components we own: the Rust **h3→Tower bridge** (`penguin-h3-tower` — hyper/axum cannot serve H3), the zero-trust interceptor suites, the multi-lane client `DialStrategy` (H3 → H2 → Ziti ordering with Alt-Svc upgrade hints), and the spec itself.

## Spec profiles (summary)

1. **Transport**: ALPN `h3` primary + H2 fallback on a port pair; TLS 1.3 only; 0-RTT disabled; connection migration allowed; size/timeout caps.
2. **RPC**: Connect protocol, all four streaming patterns, deadlines, cancellation, error model.
3. **Contract**: proto3 only, versioned packages (`<product>.<service>.v1`), `buf breaking` gating, protovalidate CEL constraints enforced server-side, JSON codec = same schema.
4. **Zero-trust**: mandatory identity (SPIFFE mTLS or OIDC JWT with `sub,iss,aud,iat,exp,scope,tenant,teams,roles`); tenant check → scope check; deny-by-default; procedures opt into `public`, never out of auth; sanitized logging.
5. **AI conventions**: MCP at `/mcp` (Streamable HTTP), A2A agent card at `/.well-known/agent-card.json` + JSON-RPC endpoint; same TLS/auth/observability; no anonymous tool calls.
6. **Operational**: `/healthz` + Connect health service, Prometheus metrics, correlation-ID propagation.
7. **Ziti binding**: bind/dial app-embedded OpenZiti; H2 semantics on overlay streams (QUIC/UDP does not traverse them); pooled connections mitigate HoL.
8. **Transport upgrade** ("secure-first, then fast"): postures `dark-only` / `hybrid` / `direct` (default `direct`); servers MAY advertise direct-H3 endpoints; clients migrate new requests, in-flight requests finish on their lane.

## Testing & verification

- ≥90% coverage per package; mypy --strict / clippy -D warnings / golangci-lint.
- Cross-language CI matrix: 3 clients × 3 servers × {H3, H2-fallback} × 4 streaming patterns.
- Connect conformance harness against all three servers.
- Security tests: unauthenticated deny, tenant-before-scope, oversized-payload reject, 0-RTT/TLS assertions.
- Contract tests: deliberate-break PR proves `buf breaking` gate; protovalidate violation tests; regen-and-diff on generated stubs.
- MCP/A2A end-to-end with official SDK clients over H3 and H2.

## Phases

0. Foundations: spec draft, licensing (LICENSE/NOTICE/TRADEMARKS), scaffolding, CI/publish wiring (`prpc-packages.yml` supersedes `h3-packages.yml`; tags `penguin-rpc-v*`, `go-rpc-v*`, `rust-rpc-v*`).
1. Go reference implementation (salvages go-h3).
2. Python implementation.
3. Rust implementation (`penguin-h3-tower` first).
4. Ziti adapters + conformance matrix + published benchmarks.
5. Retirement (delete go-h3 with `go-h3-final` tag; remove `penguin_libs.h3`) + v0.1.0 releases + docs.

## Risks

- connect-python beta / h3 crate pre-GA / hypercorn H3 experimental → H3 stays default-ON, protected by automatic H2 fallback + `HTTP3_ENABLED=false` kill-switch.
- Rust A2A deferred (official SDK unpublished/incomplete); Rust protovalidate community-maintained (fallback: prost type safety, documented CEL gap).
- Community `connectrpc` Rust crate → pin exact; fallback is contributing/vendoring atop our bridge.
- Org rules (`backend.md`) still name go-h3/penguin-h3 — admin-repo update needed after ship.

## Ecosystem facts (2026-07 research)

connect-go v1.20 GA · connect-python v0.9 beta (ASGI/WSGI, 4 patterns) · Rust `connectrpc` v0.8.1 community · quinn 0.11 prod-grade · hyperium h3 0.0.8 pre-GA · MCP SDKs mountable: rmcp v2.2 (tower), go-sdk v1.6 (`http.Handler`), python-sdk v1.28 (ASGI) · A2A spec v1.0 (LF): a2a-python v1.1, a2a-go v2.3 mountable, a2a-rs incomplete · Python H3: hypercorn[h3]+aioquic experimental; niquests = best H3 client; httpx none.
