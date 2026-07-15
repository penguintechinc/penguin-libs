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
package auth
