// Copyright 2026 Penguin Tech Inc
// SPDX-License-Identifier: Apache-2.0

package auth

import (
	"fmt"
	"net/http"

	"github.com/penguintechinc/penguin-libs/packages/go-aaa/audit"
	"github.com/penguintechinc/penguin-libs/packages/go-aaa/authn"
	"github.com/penguintechinc/penguin-libs/packages/go-aaa/authz"
)

// HTTPConfig configures HTTPMiddleware. Mode selects the authn strategy
// exactly as Config does (ModeOIDC, ModeSPIFFE, or ModeBoth); the matching
// authenticator field(s) are required for that mode. Unlike Config,
// HTTPConfig has no Enforcer/Scopes/Public: a raw http.Handler wrapped by
// HTTPMiddleware (such as mcp.Mount's or a2a.Mount's target) has no
// per-procedure scope table to enforce against, so authorization here is
// limited to the optional, flat RequiredScopes check below.
type HTTPConfig struct {
	// Mode selects the authentication strategy: ModeOIDC, ModeSPIFFE, or ModeBoth.
	Mode string
	// OIDC validates bearer tokens. Required when Mode is ModeOIDC or ModeBoth.
	OIDC *authn.OIDCRelyingParty
	// SPIFFE validates mTLS peer identities. Required when Mode is ModeSPIFFE or ModeBoth.
	SPIFFE *authn.SPIFFEAuthenticator
	// RequiredScopes, when non-empty, requires every listed scope to be
	// present in the validated Claims.Scope before a request is let through.
	// No role expansion is performed — there is no Enforcer at this layer,
	// so only literal scopes carried by the token itself are checked.
	RequiredScopes []string
	// Audit, when non-nil, emits an audit event for every accept/reject outcome.
	Audit *audit.Emitter
}

// HTTPMiddleware returns net/http middleware that authenticates every
// request per cfg.Mode using go-aaa's OIDC/SPIFFE validators — the same
// validation logic the Connect interceptor chain built by Interceptors
// uses — requires a non-empty tenant claim, optionally enforces
// cfg.RequiredScopes, and stores the validated Claims in the request
// context via authz.ContextWithClaims before calling next.
//
// It exists because Connect interceptors (what Interceptors returns) only
// wrap a generated connect.Handler via connect.WithInterceptors; they have
// no effect on a raw http.Handler mounted directly on a *http.ServeMux, as
// mcp.Mount and a2a.Mount both do (see mcp/doc.go and a2a/doc.go). This is
// the primitive that actually lets an operator secure those endpoints.
//
// It fails closed: any request that is unauthenticated, carries no tenant
// claim, or is missing a required scope is rejected — with a sanitized,
// generic error body that never echoes the token or any claim value —
// before next is ever invoked. Constructor validation returns an error,
// rather than panicking, for the same invalid-configuration cases as
// Interceptors: an unsupported Mode, or a nil authenticator required by the
// selected Mode. HTTPConfig has no Enforcer/Scopes, so — unlike
// Interceptors — those are never required here.
func HTTPMiddleware(cfg HTTPConfig) (func(http.Handler) http.Handler, error) {
	if err := validateHTTPConfig(cfg); err != nil {
		return nil, err
	}

	return func(next http.Handler) http.Handler {
		return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
			claims, err := authenticateHTTP(cfg, r)
			if err != nil {
				emitHTTPAuditEvent(cfg, r, nil, audit.EventAuthFailure, audit.OutcomeFailure)
				writeHTTPError(w, http.StatusUnauthorized, "unauthenticated")
				return
			}

			ctx := authz.ContextWithClaims(r.Context(), claims)

			if authz.TenantFromContext(ctx) == "" {
				emitHTTPAuditEvent(cfg, r, claims, audit.EventAuthzDenied, audit.OutcomeFailure)
				writeHTTPError(w, http.StatusForbidden, "missing tenant claim")
				return
			}

			if !hasAllScopes(claims.Scope, cfg.RequiredScopes) {
				emitHTTPAuditEvent(cfg, r, claims, audit.EventAuthzDenied, audit.OutcomeFailure)
				writeHTTPError(w, http.StatusForbidden, "insufficient scope")
				return
			}

			emitHTTPAuditEvent(cfg, r, claims, audit.EventAuthzGranted, audit.OutcomeSuccess)
			next.ServeHTTP(w, r.WithContext(ctx))
		})
	}, nil
}

// validateHTTPConfig checks that cfg.Mode is supported and that the
// authenticator(s) required by that mode are present. It mirrors
// validateConfig's mode/authenticator checks exactly, but — unlike
// validateConfig — never requires an Enforcer; HTTPConfig has none.
func validateHTTPConfig(cfg HTTPConfig) error {
	switch cfg.Mode {
	case ModeOIDC:
		if cfg.OIDC == nil {
			return fmt.Errorf("auth: mode %q requires a non-nil OIDC relying party", cfg.Mode)
		}
	case ModeSPIFFE:
		if cfg.SPIFFE == nil {
			return fmt.Errorf("auth: mode %q requires a non-nil SPIFFE authenticator", cfg.Mode)
		}
	case ModeBoth:
		if cfg.OIDC == nil || cfg.SPIFFE == nil {
			return fmt.Errorf("auth: mode %q requires both a non-nil OIDC relying party and a non-nil SPIFFE authenticator", cfg.Mode)
		}
	default:
		return fmt.Errorf("auth: unsupported mode %q; must be one of %q, %q, %q", cfg.Mode, ModeOIDC, ModeSPIFFE, ModeBoth)
	}
	return nil
}

// authenticateHTTP dispatches to the OIDC or SPIFFE validator per cfg.Mode,
// mirroring newAuthnInterceptor/newDualAuthnInterceptor's dispatch exactly:
// ModeBoth routes to OIDC when the request carries an "Authorization:
// Bearer " header and to SPIFFE otherwise.
func authenticateHTTP(cfg HTTPConfig, r *http.Request) (*authn.Claims, error) {
	switch cfg.Mode {
	case ModeOIDC:
		return authenticateOIDCHTTP(cfg.OIDC, r)
	case ModeSPIFFE:
		return authenticateSPIFFEHTTP(cfg.SPIFFE, r)
	case ModeBoth:
		if hasBearerTokenHTTP(r) {
			return authenticateOIDCHTTP(cfg.OIDC, r)
		}
		return authenticateSPIFFEHTTP(cfg.SPIFFE, r)
	default:
		// Unreachable: cfg has already passed validateHTTPConfig by the time
		// HTTPMiddleware's returned handler runs. Kept total rather than
		// panicking, matching newAuthnInterceptor's own default branch.
		return nil, fmt.Errorf("auth: unsupported mode %q", cfg.Mode)
	}
}

// authenticateOIDCHTTP validates the request's Authorization bearer token
// against rp, mirroring go-aaa's NewOIDCInterceptor bearer-token check and
// ValidateToken call exactly (middleware/authn.go).
func authenticateOIDCHTTP(rp *authn.OIDCRelyingParty, r *http.Request) (*authn.Claims, error) {
	auth := r.Header.Get("Authorization")
	if len(auth) < 8 || auth[:7] != "Bearer " {
		return nil, fmt.Errorf("missing bearer token")
	}

	claims, err := rp.ValidateToken(r.Context(), auth[7:])
	if err != nil {
		return nil, fmt.Errorf("invalid token: %w", err)
	}
	return claims, nil
}

// authenticateSPIFFEHTTP validates the request's TLS peer certificate chain
// against sa, mirroring go-aaa's NewSPIFFEInterceptor claims synthesis
// exactly: &authn.Claims{Sub: spiffeID, Iss: "spiffe"}, with no Tenant field
// set — see auth/doc.go's "Known limitations" section for why a request
// authenticated this way still fails HTTPMiddleware's tenant check
// downstream, the same documented limitation ModeSPIFFE already has in the
// Connect interceptor chain. Unlike NewSPIFFEInterceptor, which reads the
// peer certificate chain out of a net.Conn stashed in context via
// middleware.ConnContextKey (a Connect-specific seam required because
// connect.AnyRequest has no direct TLS accessor), this reads
// r.TLS.PeerCertificates directly — the standard net/http surface for an
// already-completed mTLS handshake.
func authenticateSPIFFEHTTP(sa *authn.SPIFFEAuthenticator, r *http.Request) (*authn.Claims, error) {
	if r.TLS == nil || len(r.TLS.PeerCertificates) == 0 {
		return nil, fmt.Errorf("spiffe: no peer certificates in TLS connection state")
	}

	spiffeID, err := sa.ValidatePeerCertificate(r.TLS.PeerCertificates)
	if err != nil {
		return nil, fmt.Errorf("spiffe: peer validation failed: %w", err)
	}

	return &authn.Claims{Sub: spiffeID, Iss: "spiffe"}, nil
}

// hasBearerTokenHTTP reports whether r carries an "Authorization: Bearer "
// header, mirroring hasBearerToken's connect.AnyRequest check (auth.go) for
// the net/http surface.
func hasBearerTokenHTTP(r *http.Request) bool {
	auth := r.Header.Get("Authorization")
	return len(auth) >= 8 && auth[:7] == "Bearer "
}

// hasAllScopes reports whether every scope in required is present in
// granted. An empty required slice is trivially satisfied — RequiredScopes
// is opt-in.
func hasAllScopes(granted, required []string) bool {
	if len(required) == 0 {
		return true
	}
	grantedSet := make(map[string]bool, len(granted))
	for _, s := range granted {
		grantedSet[s] = true
	}
	for _, s := range required {
		if !grantedSet[s] {
			return false
		}
	}
	return true
}

// emitHTTPAuditEvent emits an audit event for a single HTTP-layer authn/authz
// outcome when cfg.Audit is configured; it is a no-op otherwise. subject
// falls back to "anonymous" when claims is nil or carries no Sub, mirroring
// go-aaa's own subjectFromContext fallback (middleware/audit.go). Unlike the
// Connect chain's audit interceptor — which sits outermost in the slice
// Interceptors returns and therefore always attributes events to
// "anonymous", even on a successful request (see doc.go's "Interceptor
// order" trade-off) — this call happens after authentication has already
// resolved claims for the current request, so a successful or
// tenant/scope-denied event is correctly attributed to the caller's Sub
// claim; only a fully unauthenticated request (claims == nil) falls back to
// "anonymous".
func emitHTTPAuditEvent(cfg HTTPConfig, r *http.Request, claims *authn.Claims, eventType audit.EventType, outcome audit.Outcome) {
	if cfg.Audit == nil {
		return
	}
	subject := "anonymous"
	if claims != nil && claims.Sub != "" {
		subject = claims.Sub
	}
	event := audit.NewAuditEvent(eventType, subject, "http", r.URL.Path, outcome)
	_ = cfg.Audit.Emit(event)
}

// writeHTTPError writes a fixed, generic JSON error body and status code.
// It never includes the underlying validation error, a token, or any claim
// value — only the fixed message string the caller passes in — so a
// rejected request cannot leak token or claim material back to the caller.
func writeHTTPError(w http.ResponseWriter, status int, message string) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(status)
	_, _ = fmt.Fprintf(w, `{"error":%q}`, message)
}
