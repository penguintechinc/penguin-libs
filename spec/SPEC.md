# pRPC Specification — prpc/1.0-draft
Status: DRAFT · License: Apache-2.0 · Governance: Penguin Tech Inc

## 1. Overview

pRPC (`prpc/1.0-draft`) is an open, Apache-2.0-licensed RPC protocol specification. It layers a transport profile (HTTP/3 over QUIC primary, HTTP/2 fallback), a contract profile (proto3, versioned, enforced), a zero-trust security profile, and built-in AI-agent protocol support (MCP, A2A) on top of the Connect protocol wire format. pRPC is designed to succeed gRPC for both service-to-service and client/agent-to-service communication.

pRPC's RPC profile (§4) is the Connect protocol, unmodified: any conforming Connect client MUST be able to call a conforming pRPC server without protocol translation. What distinguishes "pRPC" from a bare Connect deployment is the additional transport, contract, zero-trust, AI, operational, Ziti, and transport-upgrade profiles this document defines — a Connect service that does not implement those profiles MUST NOT claim pRPC conformance (see §11).

This document defines the wire-level and behavioral requirements a conforming implementation MUST satisfy. It does not define package distribution, CI wiring, or language-specific SDK ergonomics; those live in per-implementation documentation.

## 2. Terminology

The key words "MUST", "MUST NOT", "REQUIRED", "SHOULD", "SHOULD NOT", "MAY", and "OPTIONAL" in this document are to be interpreted as described in RFC 2119.

- **lane**: a transport path a client uses to reach a server for a given call — H3 (QUIC), H2 (fallback), or a Ziti overlay lane (§9) where configured.
- **posture**: the deployment stance governing which lane(s) a server exposes and a client may use — `dark-only`, `hybrid`, or `direct` (default `direct`; see §10).
- **procedure**: a single RPC method (unary or one of the three streaming patterns) defined on a proto3 service, addressed by its fully qualified Connect procedure path.
- **contract**: the versioned proto3 package plus its generated stubs that together define a service's wire-level API surface (§5).

## 3. Transport Profile

Servers MUST offer HTTP/3 via ALPN `h3` as the primary transport and MUST also offer HTTP/2 as a fallback, advertised together on a single port pair (UDP for H3, TCP for H2). TLS 1.3 MUST be used exclusively on both transports; TLS 1.2 and earlier MUST NOT be negotiated. 0-RTT MUST be disabled on every pRPC endpoint, since 0-RTT data is replayable and pRPC procedures are not guaranteed idempotent. Connection migration MAY be used when the underlying QUIC implementation supports it. Servers MUST enforce a default maximum message size of 4 MiB per message (implementations MAY make this configurable) and MUST reject messages exceeding the configured limit. Every RPC MUST support a caller-supplied deadline; servers MUST enforce deadlines and MUST cancel in-flight work when a deadline is exceeded.

## 4. RPC Profile

pRPC uses the Connect protocol unmodified as its RPC framing. Conforming servers MUST support all four Connect call patterns: unary, server-streaming, client-streaming, and bidirectional-streaming. Both the protobuf and JSON codecs MUST be supported on unary and streaming calls; protobuf MUST be the default codec when a client does not negotiate otherwise. Errors MUST use the Connect error model (code, message, structured details) — implementations MUST NOT define a custom error envelope. Streaming calls MUST propagate client-initiated cancellation to the server and MUST support mid-stream error termination per the Connect streaming envelope. Deadlines (§3) apply uniformly across all four call patterns.

## 5. Contract Profile

Contracts MUST be defined in proto3 only; proto2 MUST NOT be used for new or updated pRPC contracts. Packages MUST be versioned as `<product>.<service>.v1` (incrementing to `v2`, etc. on breaking change); unversioned proto packages MUST NOT be published as pRPC contracts. Generated stubs are the only supported client API: hand-written HTTP or Connect client code targeting a pRPC service MUST NOT be used in place of generated stubs. `buf breaking` MUST gate merges to a proto package's default branch — a detected break MUST fail CI and MUST block merge. protovalidate CEL constraints declared on a message MUST be enforced server-side on every request; client-side validation alone MUST NOT be treated as sufficient. The JSON codec (§4) MUST reflect exactly the same schema as the protobuf encoding — JSON-only fields MUST NOT exist.

## 6. Zero-Trust Profile

Every request MUST carry a verifiable identity: SPIFFE mTLS for service-to-service traffic, or an OIDC JWT for client/agent-to-service traffic. An OIDC JWT MUST carry, at minimum, the claims `sub`, `iss`, `aud`, `iat`, `exp`, `scope`, `tenant`, `teams`, and `roles`. Requests lacking a valid identity MUST be rejected before any procedure-specific logic executes. The tenant check MUST precede the scope check: a `tenant` claim mismatch MUST short-circuit to a rejection before scopes are evaluated. Procedures MUST deny by default — a procedure is unauthenticated/unauthorized unless it explicitly opts into the `public` designation; procedures MUST NOT opt out of authentication on a per-call basis once implemented as non-public. All logging touching request or identity data MUST be sanitized: raw tokens, full claim values, and other secrets MUST NOT appear in logs.

## 7. AI Conventions

A server exposing MCP tools MUST mount an MCP Streamable HTTP endpoint at `/mcp`, implemented by hosting an official MCP SDK rather than a reimplementation of the MCP wire protocol. A server exposing A2A agents MUST publish an agent card at `/.well-known/agent-card.json` and MUST expose the corresponding A2A JSON-RPC endpoint. Both the `/mcp` endpoint and the A2A endpoints MUST inherit the server's standard transport profile (§3) and zero-trust identity/auth profile (§6) unchanged — MCP and A2A traffic MUST NOT be exempted from either. Anonymous tool or task invocations MUST NOT be permitted: every MCP tool call and every A2A task request MUST satisfy the same identity requirements as any other pRPC procedure.

## 8. Operational Conventions

Servers MUST expose a `/healthz` endpoint and MUST additionally implement `prpc.health.v1.HealthService` for programmatic health checks over Connect. Servers MUST expose Prometheus-format metrics for request/response and error observability. Every request MUST carry a correlation ID in the `X-Correlation-Id` header; a server MUST propagate an inbound `X-Correlation-Id` unchanged to downstream calls and to its own log lines, and MUST generate a new correlation ID when the header is absent from an inbound request.

## 9. Ziti Binding Profile

Implementations MAY provide an OpenZiti overlay adapter that binds and dials app-embedded Ziti identities as an additional, opt-in transport lane. Because QUIC/UDP does not traverse Ziti overlay streams, Connect-over-H2 semantics MUST be used on any Ziti lane — H3 MUST NOT be attempted over a Ziti stream. Clients using a Ziti lane MUST pool connections to mitigate the head-of-line blocking inherent to a single-stream H2 constraint on the overlay. The Ziti binding is opt-in: a server or client that has not configured a Ziti identity MUST NOT be required to establish one, and MUST continue operating over the direct H3/H2 lanes (§3) unaffected.

## 10. Transport Upgrade Profile

A deployment MUST select exactly one posture: `dark-only` (Ziti overlay only, no direct H3/H2 lane exposed), `hybrid` (both Ziti and direct lanes available), or `direct` (H3 primary with automatic H2 fallback, no Ziti lane). The default posture MUST be `direct`. Clients MUST dial secure-first: for the configured posture, a client MUST attempt the most secure available lane before falling back to a less-preferred lane. Servers MAY advertise direct-H3 endpoints using Alt-Svc-style hints so that a client currently on an H2 lane can upgrade subsequent new requests to H3. When a client migrates to a new lane, requests already in flight on the original lane MUST be allowed to complete on that lane — implementations MUST NOT abort or silently re-issue in-flight requests across lanes.

## 11. Conformance

An implementation claiming pRPC conformance MUST pass the `prpc.conformance.v1.ConformanceService` matrix across 3 clients × 3 servers × {h3, h2} × 4 streaming patterns. Any combination of client, server, transport, or pattern that is skipped MUST be reported as such — an implementation MUST NOT claim full `prpc/1.0-draft` conformance while omitting any cell of the matrix, and partial results MUST be reported per-combination rather than aggregated into a single pass/fail. Conformance results MUST be reproducible by re-running the published conformance harness without modification to the implementation under test.
