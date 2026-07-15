// Copyright 2026 Penguin Tech Inc
// SPDX-License-Identifier: Apache-2.0

// Package auth assembles the zero-trust interceptor chain required by
// spec/SPEC.md §6: every non-public procedure must present a verifiable
// identity, that identity's tenant claim is checked before any scope is
// evaluated, and a procedure that opts into neither an explicit scope
// requirement nor the public list is denied by default. It is a thin
// composition layer over github.com/penguintechinc/penguin-libs/packages/
// go-aaa/middleware — claim validation, tenant enforcement, and scope
// checking are all reused verbatim from go-aaa; this package never
// reimplements them.
//
// # Deny-by-default gate
//
// go-aaa's authz.go (middleware.NewAuthzInterceptor) allows procedures that
// are absent from its ProcedureScopes map: "required, ok :=
// procedures[procedure]; if !ok || len(required) == 0 { return next(ctx,
// req) }" grants unconditional access rather than denying. That is the
// "allows-unknown" case described in the Task 4 brief, so this package adds
// its own thin gate interceptor (newDenyByDefaultInterceptor in auth.go)
// that rejects, with CodePermissionDenied, any procedure present in neither
// cfg.Scopes nor cfg.Public — closing the gap before the request ever
// reaches go-aaa's authz interceptor.
//
// # Interceptor order
//
// Interceptors returns, outermost to innermost (matching
// connect.WithInterceptors / connect's chain composition, where slice index
// 0 executes first on the request path and last on the response path):
//
//	audit (if cfg.Audit != nil) -> authn (OIDC/SPIFFE per cfg.Mode) -> tenant -> deny-by-default gate -> authz
//
// This deliberately differs from the Task 4 brief's literal phrasing
// ("tenant → authn → authz → audit"), for two concrete, code-verified
// reasons:
//
//  1. Audit must be outermost, not innermost. go-aaa's
//     middleware.NewAuditInterceptor classifies its downstream error via
//     connect.CodeOf(err) into EventAuthFailure (CodeUnauthenticated) or
//     EventAuthzDenied (CodePermissionDenied) — see audit.go's
//     classifyResult and audit_test.go's
//     TestAuditInterceptor_UnauthenticatedEmitsAuthFailure /
//     TestAuditInterceptor_PermissionDeniedEmitsAuthzDenied. Under connect's
//     chain semantics an interceptor only observes errors returned by
//     interceptors *inside* it (i.e. later in the slice); placed last, audit
//     would never see a rejection from authn/tenant/authz — its failure
//     branches would be unreachable dead code. Placed first, it wraps and
//     records every outcome, matching what it was built to do.
//
//     Trade-off, disclosed rather than hidden: outermost placement buys
//     outcome coverage at the cost of attribution accuracy. go-aaa's
//     NewAuditInterceptor (audit.go) computes its event's subject via
//     subjectFromContext(ctx) *before* calling next — using the ctx the
//     audit interceptor itself received, not the ctx authn produces after a
//     successful validation (authz.ContextWithClaims is only called inside
//     the authn interceptor, which is *inside* audit in this chain). So
//     subjectFromContext always sees a context with no Claims and falls
//     back to "anonymous" — for every event, including EventAuthzGranted on
//     a fully authenticated, successful request. auth_test.go's
//     TestAuditInterceptor_EmitsEvent_ButAttributesToAnonymous pins this: it
//     drives a real, successful, authenticated request through the full
//     chain with a real audit.Emitter and asserts the emitted event's
//     subject is "anonymous" despite the caller having presented a valid
//     token. This package keeps audit outermost anyway (outcome coverage —
//     seeing every rejection — was judged more valuable than attribution),
//     but the accuracy cost is real and unresolved: fixing it requires
//     go-aaa to add post-next subject resolution to NewAuditInterceptor
//     (e.g. re-reading Claims from the post-next ctx, or accepting a
//     subject-resolution hook), which is out of scope for this package —
//     this package only composes go-aaa's interceptors, it does not
//     reimplement or patch them.
//
//  2. Tenant must run after authn, not before. middleware.NewTenantInterceptor
//     reads the tenant claim via authz.TenantFromContext(ctx), which reads
//     Claims stashed in ctx by authz.ContextWithClaims — and that call is
//     made by NewOIDCInterceptor/NewSPIFFEInterceptor only on a
//     successfully validated identity. Running tenant before authn would
//     mean TenantFromContext always sees an empty context, so the tenant
//     check would reject unconditionally regardless of the token's actual
//     claims. The spec constraint actually being enforced (§6: "The tenant
//     check MUST precede the scope check") is about tenant preceding authz,
//     which this order satisfies exactly — tenant still runs strictly
//     before the deny-by-default gate and before authz, so a missing-tenant
//     token is rejected before any scope (or gate) evaluation occurs.
//
// # Public procedures
//
// cfg.Public is passed as middleware.WithPublicProcedures(cfg.Public...) to
// every one of the wrapped go-aaa interceptors (authn, tenant, authz) and
// is also honored directly by the deny-by-default gate. Reading tenant.go
// confirms NewTenantInterceptor checks the public set first and returns
// next(ctx, req) immediately when the procedure is public — it does not
// hard-fail without a token for public procedures, so a public procedure
// bypasses tenant, authn, and authz entirely and can be called with zero
// credentials.
//
// # Mode "both"
//
// cfg.Mode == "both" accepts either an OIDC bearer token or a SPIFFE mTLS
// peer identity on a per-request basis (spec §6: "SPIFFE mTLS for
// service-to-service traffic, or an OIDC JWT for client/agent-to-service
// traffic" — an inclusive-or, not a requirement that both be present
// simultaneously). Chaining go-aaa's two authn interceptors directly would
// produce AND semantics (both must succeed, since each unconditionally
// requires its own credential), so this package supplies a small combinator
// that dispatches to NewOIDCInterceptor when an "Authorization: Bearer "
// header is present and to NewSPIFFEInterceptor otherwise — reusing both
// go-aaa constructors as opaque building blocks, never reimplementing their
// validation logic.
//
// # Streaming RPCs
//
// connect.WithInterceptors composes each connect.Interceptor's WrapUnary,
// WrapStreamingClient, and WrapStreamingHandler independently — a streaming
// RPC never goes through WrapUnary at all (connect-go's chain.WrapStreamingHandler,
// interceptor.go). Every interceptor go-aaa's middleware package exports
// (NewOIDCInterceptor, NewSPIFFEInterceptor, NewTenantInterceptor,
// NewAuthzInterceptor, NewAuditInterceptor) is built from
// connect.UnaryInterceptorFunc, whose WrapStreamingClient and
// WrapStreamingHandler are both documented no-ops that return next
// unmodified (connectrpc.com/connect v1.20.0, interceptor.go lines 65-73).
// Before this package's fix, its own gate (newDenyByDefaultInterceptor) was
// also built from connect.UnaryInterceptorFunc — so a streaming procedure
// behind auth.Interceptors() reached the handler with none of authn,
// tenant, the gate, or authz having done anything at all: zero
// authentication, zero authorization, for any streaming procedure,
// regardless of credentials. auth_test.go's
// TestStreamingWatch_NonPublic_DeniedWithZeroCredentials is the pinned
// regression proof for this (see its comment for the RED/GREEN history).
//
// The fix: denyByDefaultGate (auth.go) is implemented as a full
// connect.Interceptor rather than a connect.UnaryInterceptorFunc, so its
// WrapStreamingHandler runs on every streaming call. It fails closed —
// any streaming procedure not listed in cfg.Public is rejected with
// CodePermissionDenied before the handler ever runs, unconditionally, with
// or without credentials. A streaming procedure listed in cfg.Public passes
// straight through with no enforcement at all, exactly like a public unary
// procedure.
//
// This is a stopgap, not real streaming authentication/authorization: a
// non-public streaming procedure cannot be reached through this chain at
// all today, even with a perfectly valid token/SPIFFE identity/tenant/scope
// — there is no code path here that validates a streaming caller's identity
// or claims. Real per-message or per-stream authn/tenant/authz for
// streaming RPCs requires go-aaa's middleware package to grow
// connect.Interceptor implementations (not connect.UnaryInterceptorFunc)
// for authn/tenant/authz, so this package would have something to actually
// invoke inside WrapStreamingHandler. That is out-of-scope go-aaa work; a
// non-public streaming procedure remains unreachable through this chain
// until it lands. One additional consequence worth flagging for operators:
// because NewAuditInterceptor is also a connect.UnaryInterceptorFunc, audit
// (when cfg.Audit is configured) does not observe streaming calls either —
// not even the denials this gate now produces — for the same structural
// reason.
//
// # Known limitations
//
// ModeSPIFFE cannot authorize any non-public procedure today, and this is
// intentional fail-closed behavior rather than a bug this package works
// around. go-aaa's NewSPIFFEInterceptor (middleware/authn.go) synthesizes
// claims on a successful mTLS peer validation as
// &authn.Claims{Sub: spiffeID, Iss: "spiffe"} — no Tenant field is set,
// because go-aaa has no trust-domain-to-tenant mapping today. This
// package's chain always runs NewTenantInterceptor immediately after authn
// (see "Interceptor order" above), and NewTenantInterceptor
// (middleware/tenant.go) rejects with CodePermissionDenied
// ("missing tenant claim") whenever authz.TenantFromContext(ctx) is empty.
// So every non-public procedure called under ModeSPIFFE is denied at the
// tenant check, unconditionally — the caller's SPIFFE ID validated
// correctly, but the request never gets far enough to reach the
// deny-by-default gate or authz at all.
//
// auth_test.go's TestSPIFFEMode_SynthesizedClaimsHaveNoTenant_DeniedByTenantInterceptor
// pins this behavior. It does not drive a full request through
// NewSPIFFEInterceptor itself: doing so needs a real, completed mTLS
// handshake (tlsPeerCertsFromContext in go-aaa's authn.go reads
// (*tls.Conn).ConnectionState().PeerCertificates, which is only populated
// after an actual handshake — unlike this package's OIDC test fixture,
// there is no pure-computation path, such as JWT signing, that can stand in
// for it). Instead the test takes the real tenant/gate/authz sub-slice of
// the chain that auth.Interceptors(Config{Mode: ModeSPIFFE, ...}) actually
// returns, and injects context claims shaped exactly like
// NewSPIFFEInterceptor's synthesis (same Sub/Iss, no Tenant) — the state a
// successful SPIFFE handshake would have produced. This exercises the real
// downstream composition this package owns (tenant -> gate -> authz) against
// exactly the claims shape go-aaa's SPIFFE path is documented to produce,
// without reimplementing an mTLS handshake harness whose correctness would
// really be pinning go-aaa's code, not this package's.
//
// The real fix is go-aaa adding a trust-domain-to-tenant mapping so
// NewSPIFFEInterceptor (or a wrapping configuration) can populate Tenant
// from the validated SPIFFE ID's trust domain — that is out of scope for
// this package, which only composes go-aaa's interceptors. Flagged here for
// go-aaa maintainer follow-up.
package auth
