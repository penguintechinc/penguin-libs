// Copyright 2026 Penguin Tech Inc
// SPDX-License-Identifier: Apache-2.0

package auth

import (
	"context"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"

	"github.com/penguintechinc/penguin-libs/packages/go-aaa/audit"
	"github.com/penguintechinc/penguin-libs/packages/go-aaa/authn"
	"github.com/penguintechinc/penguin-libs/packages/go-aaa/authz"
	"github.com/penguintechinc/penguin-libs/packages/go-logging/logging"
)

// This file proves and pins the fix for the Critical spec-compliance defect
// described in the Task 9 brief: mcp.Mount and a2a.Mount register raw
// http.Handlers directly on a *http.ServeMux, entirely outside the Connect
// interceptor chain auth.Interceptors builds. Connect interceptors can only
// wrap a generated connect.Handler (via connect.WithInterceptors); they have
// no effect whatsoever on a raw http.Handler mounted next to one on the same
// mux. HTTPMiddleware is the missing net/http-level primitive that actually
// lets an operator secure those endpoints — this file exercises it, reusing
// this package's existing OIDC/SPIFFE fixtures (testFixture,
// newTestSPIFFEAuthenticator) from auth_test.go rather than re-deriving JWKS
// setup.

// --- constructor validation ---

func TestHTTPMiddleware_InvalidConfig(t *testing.T) {
	sa := newTestSPIFFEAuthenticator(t)

	cases := []struct {
		name string
		cfg  HTTPConfig
	}{
		{"unsupported mode", HTTPConfig{Mode: "jwt"}},
		{"empty mode", HTTPConfig{Mode: ""}},
		{"oidc mode with nil OIDC", HTTPConfig{Mode: ModeOIDC}},
		{"spiffe mode with nil SPIFFE", HTTPConfig{Mode: ModeSPIFFE}},
		{"both mode with nil OIDC", HTTPConfig{Mode: ModeBoth, SPIFFE: sa}},
		{"both mode with nil SPIFFE", HTTPConfig{Mode: ModeBoth, OIDC: testFixture.rp}},
	}

	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			if _, err := HTTPMiddleware(tc.cfg); err == nil {
				t.Fatalf("expected a constructor error for case %q", tc.name)
			}
		})
	}
}

func TestHTTPMiddleware_ValidConfigsSucceed(t *testing.T) {
	sa := newTestSPIFFEAuthenticator(t)

	cases := []struct {
		name string
		cfg  HTTPConfig
	}{
		{"oidc mode", HTTPConfig{Mode: ModeOIDC, OIDC: testFixture.rp}},
		{"spiffe mode", HTTPConfig{Mode: ModeSPIFFE, SPIFFE: sa}},
		{"both mode", HTTPConfig{Mode: ModeBoth, OIDC: testFixture.rp, SPIFFE: sa}},
	}

	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			mw, err := HTTPMiddleware(tc.cfg)
			if err != nil {
				t.Fatalf("unexpected error: %v", err)
			}
			if mw == nil {
				t.Fatal("expected a non-nil middleware constructor function")
			}
		})
	}
}

// --- core fail-closed behavior ---

func TestHTTPMiddleware_Anonymous_Unauthorized(t *testing.T) {
	mw, err := HTTPMiddleware(HTTPConfig{Mode: ModeOIDC, OIDC: testFixture.rp})
	if err != nil {
		t.Fatalf("HTTPMiddleware: %v", err)
	}

	called := false
	next := http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		called = true
		w.WriteHeader(http.StatusOK)
	})

	req := httptest.NewRequestWithContext(context.Background(), http.MethodGet, "/x", nil) // no Authorization header at all
	rec := httptest.NewRecorder()
	mw(next).ServeHTTP(rec, req)

	if rec.Code != http.StatusUnauthorized {
		t.Errorf("expected 401 for an anonymous request, got %d", rec.Code)
	}
	if called {
		t.Error("expected next to NOT be called for an anonymous request")
	}
}

func TestHTTPMiddleware_ValidTokenValidTenant_Success(t *testing.T) {
	mw, err := HTTPMiddleware(HTTPConfig{Mode: ModeOIDC, OIDC: testFixture.rp})
	if err != nil {
		t.Fatalf("HTTPMiddleware: %v", err)
	}

	var gotClaims *authn.Claims
	called := false
	next := http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		called = true
		gotClaims = authz.ClaimsFromContext(r.Context())
		w.WriteHeader(http.StatusOK)
	})

	tok := testFixture.token(t, "user-1", []string{"report:read"}, nil, "tenant-a")
	req := httptest.NewRequestWithContext(context.Background(), http.MethodGet, "/x", nil)
	req.Header.Set("Authorization", "Bearer "+tok)
	rec := httptest.NewRecorder()
	mw(next).ServeHTTP(rec, req)

	if rec.Code != http.StatusOK {
		t.Fatalf("expected 200, got %d", rec.Code)
	}
	if !called {
		t.Fatal("expected next to be called for a valid, tenant-scoped request")
	}
	if gotClaims == nil {
		t.Fatal("expected authz.ClaimsFromContext to return the validated claims inside the handler")
	}
	if gotClaims.Sub != "user-1" {
		t.Errorf("expected claims.Sub %q, got %q", "user-1", gotClaims.Sub)
	}
	if gotClaims.Tenant != "tenant-a" {
		t.Errorf("expected claims.Tenant %q, got %q", "tenant-a", gotClaims.Tenant)
	}
}

func TestHTTPMiddleware_MissingTenant_Forbidden(t *testing.T) {
	mw, err := HTTPMiddleware(HTTPConfig{Mode: ModeOIDC, OIDC: testFixture.rp})
	if err != nil {
		t.Fatalf("HTTPMiddleware: %v", err)
	}

	called := false
	next := http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		called = true
		w.WriteHeader(http.StatusOK)
	})

	tok := testFixture.token(t, "user-1", []string{"report:read"}, nil, "" /* no tenant */)
	req := httptest.NewRequestWithContext(context.Background(), http.MethodGet, "/x", nil)
	req.Header.Set("Authorization", "Bearer "+tok)
	rec := httptest.NewRecorder()
	mw(next).ServeHTTP(rec, req)

	if rec.Code != http.StatusForbidden {
		t.Errorf("expected 403 for a token with no tenant claim, got %d", rec.Code)
	}
	if called {
		t.Error("expected next to NOT be called when the tenant claim is missing")
	}
}

func TestHTTPMiddleware_InvalidToken_Unauthorized(t *testing.T) {
	mw, err := HTTPMiddleware(HTTPConfig{Mode: ModeOIDC, OIDC: testFixture.rp})
	if err != nil {
		t.Fatalf("HTTPMiddleware: %v", err)
	}

	called := false
	next := http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		called = true
		w.WriteHeader(http.StatusOK)
	})

	req := httptest.NewRequestWithContext(context.Background(), http.MethodGet, "/x", nil)
	req.Header.Set("Authorization", "Bearer this.is.not-a-valid-jwt")
	rec := httptest.NewRecorder()
	mw(next).ServeHTTP(rec, req)

	if rec.Code != http.StatusUnauthorized {
		t.Errorf("expected 401 for a garbage token, got %d", rec.Code)
	}
	if called {
		t.Error("expected next to NOT be called for an invalid token")
	}
}

// --- RequiredScopes ---

func TestHTTPMiddleware_RequiredScopes_MissingScope_Forbidden(t *testing.T) {
	mw, err := HTTPMiddleware(HTTPConfig{
		Mode:           ModeOIDC,
		OIDC:           testFixture.rp,
		RequiredScopes: []string{"report:write"},
	})
	if err != nil {
		t.Fatalf("HTTPMiddleware: %v", err)
	}

	called := false
	next := http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		called = true
		w.WriteHeader(http.StatusOK)
	})

	tok := testFixture.token(t, "user-1", []string{"report:read"}, nil, "tenant-a")
	req := httptest.NewRequestWithContext(context.Background(), http.MethodGet, "/x", nil)
	req.Header.Set("Authorization", "Bearer "+tok)
	rec := httptest.NewRecorder()
	mw(next).ServeHTTP(rec, req)

	if rec.Code != http.StatusForbidden {
		t.Errorf("expected 403 for a token missing a required scope, got %d", rec.Code)
	}
	if called {
		t.Error("expected next to NOT be called when a required scope is missing")
	}
}

func TestHTTPMiddleware_RequiredScopes_AllPresent_Success(t *testing.T) {
	mw, err := HTTPMiddleware(HTTPConfig{
		Mode:           ModeOIDC,
		OIDC:           testFixture.rp,
		RequiredScopes: []string{"report:read", "report:write"},
	})
	if err != nil {
		t.Fatalf("HTTPMiddleware: %v", err)
	}

	called := false
	next := http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		called = true
		w.WriteHeader(http.StatusOK)
	})

	tok := testFixture.token(t, "user-1", []string{"report:read", "report:write", "extra:scope"}, nil, "tenant-a")
	req := httptest.NewRequestWithContext(context.Background(), http.MethodGet, "/x", nil)
	req.Header.Set("Authorization", "Bearer "+tok)
	rec := httptest.NewRecorder()
	mw(next).ServeHTTP(rec, req)

	if rec.Code != http.StatusOK {
		t.Errorf("expected 200 for a token carrying every required scope, got %d", rec.Code)
	}
	if !called {
		t.Error("expected next to be called once every required scope is present")
	}
}

// --- SPIFFE / Both mode dispatch ---

func TestHTTPMiddleware_SPIFFEMode_NoPeerCertificate_Unauthorized(t *testing.T) {
	sa := newTestSPIFFEAuthenticator(t)
	mw, err := HTTPMiddleware(HTTPConfig{Mode: ModeSPIFFE, SPIFFE: sa})
	if err != nil {
		t.Fatalf("HTTPMiddleware: %v", err)
	}

	called := false
	next := http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		called = true
		w.WriteHeader(http.StatusOK)
	})

	req := httptest.NewRequestWithContext(context.Background(), http.MethodGet, "/x", nil) // no r.TLS at all
	rec := httptest.NewRecorder()
	mw(next).ServeHTTP(rec, req)

	if rec.Code != http.StatusUnauthorized {
		t.Errorf("expected 401 with no TLS peer certificate, got %d", rec.Code)
	}
	if called {
		t.Error("expected next to NOT be called with no TLS peer certificate")
	}
}

func TestHTTPMiddleware_BothMode_DispatchesToOIDCWhenBearerPresent(t *testing.T) {
	sa := newTestSPIFFEAuthenticator(t)
	mw, err := HTTPMiddleware(HTTPConfig{Mode: ModeBoth, OIDC: testFixture.rp, SPIFFE: sa})
	if err != nil {
		t.Fatalf("HTTPMiddleware: %v", err)
	}

	called := false
	next := http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		called = true
		w.WriteHeader(http.StatusOK)
	})

	// A valid bearer token but zero TLS state: if this were mis-dispatched to
	// the SPIFFE branch it would fail (no peer certificate); success here
	// proves the OIDC branch, not SPIFFE, handled it.
	tok := testFixture.token(t, "user-1", nil, nil, "tenant-a")
	req := httptest.NewRequestWithContext(context.Background(), http.MethodGet, "/x", nil)
	req.Header.Set("Authorization", "Bearer "+tok)
	rec := httptest.NewRecorder()
	mw(next).ServeHTTP(rec, req)

	if rec.Code != http.StatusOK {
		t.Errorf("expected the OIDC branch to succeed with a valid bearer token, got %d", rec.Code)
	}
	if !called {
		t.Error("expected next to be called")
	}
}

func TestHTTPMiddleware_BothMode_DispatchesToSPIFFEWhenNoBearerToken(t *testing.T) {
	sa := newTestSPIFFEAuthenticator(t)
	mw, err := HTTPMiddleware(HTTPConfig{Mode: ModeBoth, OIDC: testFixture.rp, SPIFFE: sa})
	if err != nil {
		t.Fatalf("HTTPMiddleware: %v", err)
	}

	called := false
	next := http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		called = true
		w.WriteHeader(http.StatusOK)
	})

	// No Authorization header and no TLS state: the combinator must route to
	// the SPIFFE branch (which then fails closed on the missing peer cert)
	// rather than falling through to OIDC's own "missing bearer" branch. Both
	// branches reject here, so this alone isn't proof of dispatch — paired
	// with TestHTTPMiddleware_BothMode_DispatchesToOIDCWhenBearerPresent and
	// TestHTTPMiddleware_SPIFFEMode_NoPeerCertificate_Unauthorized above, it
	// pins that the fail-closed outcome holds for the "both, no bearer" case
	// specifically, not just the has-bearer case.
	req := httptest.NewRequestWithContext(context.Background(), http.MethodGet, "/x", nil)
	rec := httptest.NewRecorder()
	mw(next).ServeHTTP(rec, req)

	if rec.Code != http.StatusUnauthorized {
		t.Errorf("expected 401, got %d", rec.Code)
	}
	if called {
		t.Error("expected next to NOT be called")
	}
}

// --- optional audit emission ---

func TestHTTPMiddleware_AuditEmitsEventOnSuccess(t *testing.T) {
	var events []map[string]interface{}
	sink := logging.NewCallbackSink(func(event map[string]interface{}) {
		events = append(events, event)
	})
	emitter := audit.NewEmitter(sink)

	mw, err := HTTPMiddleware(HTTPConfig{Mode: ModeOIDC, OIDC: testFixture.rp, Audit: emitter})
	if err != nil {
		t.Fatalf("HTTPMiddleware: %v", err)
	}

	next := http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		w.WriteHeader(http.StatusOK)
	})

	tok := testFixture.token(t, "user-1", nil, nil, "tenant-a")
	req := httptest.NewRequestWithContext(context.Background(), http.MethodGet, "/mcp", nil)
	req.Header.Set("Authorization", "Bearer "+tok)
	rec := httptest.NewRecorder()
	mw(next).ServeHTTP(rec, req)

	if rec.Code != http.StatusOK {
		t.Fatalf("expected 200, got %d", rec.Code)
	}
	if len(events) != 1 {
		t.Fatalf("expected exactly 1 audit event, got %d", len(events))
	}
	if events[0]["outcome"] != string(audit.OutcomeSuccess) {
		t.Errorf("expected outcome %q, got %v", audit.OutcomeSuccess, events[0]["outcome"])
	}
	// Unlike the Connect audit interceptor (outermost in the chain built by
	// Interceptors, so it always attributes to "anonymous" — see
	// doc.go's "Interceptor order" trade-off), this middleware resolves the
	// subject after authentication succeeds, so a successful request is
	// correctly attributed to the caller's sub claim.
	if events[0]["subject"] != "user-1" {
		t.Errorf("expected subject %q, got %v", "user-1", events[0]["subject"])
	}
}

func TestHTTPMiddleware_AuditEmitsEventOnRejection(t *testing.T) {
	var events []map[string]interface{}
	sink := logging.NewCallbackSink(func(event map[string]interface{}) {
		events = append(events, event)
	})
	emitter := audit.NewEmitter(sink)

	mw, err := HTTPMiddleware(HTTPConfig{Mode: ModeOIDC, OIDC: testFixture.rp, Audit: emitter})
	if err != nil {
		t.Fatalf("HTTPMiddleware: %v", err)
	}

	next := http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		w.WriteHeader(http.StatusOK)
	})

	req := httptest.NewRequestWithContext(context.Background(), http.MethodGet, "/mcp", nil) // anonymous
	rec := httptest.NewRecorder()
	mw(next).ServeHTTP(rec, req)

	if rec.Code != http.StatusUnauthorized {
		t.Fatalf("expected 401, got %d", rec.Code)
	}
	if len(events) != 1 {
		t.Fatalf("expected exactly 1 audit event, got %d", len(events))
	}
	if events[0]["outcome"] != string(audit.OutcomeFailure) {
		t.Errorf("expected outcome %q, got %v", audit.OutcomeFailure, events[0]["outcome"])
	}
	if events[0]["subject"] != "anonymous" {
		t.Errorf("expected subject %q, got %v", "anonymous", events[0]["subject"])
	}
}

// --- sanitized error bodies: no token/claim echo ---

func TestHTTPMiddleware_ErrorBodyDoesNotEchoToken(t *testing.T) {
	mw, err := HTTPMiddleware(HTTPConfig{Mode: ModeOIDC, OIDC: testFixture.rp})
	if err != nil {
		t.Fatalf("HTTPMiddleware: %v", err)
	}

	next := http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		w.WriteHeader(http.StatusOK)
	})

	const secretLookingToken = "Bearer eyJhbGciOiJSUzI1NiJ9.super-secret-payload.sig" //nolint:gosec // TEST ONLY: dummy test token, not a real credential
	req := httptest.NewRequestWithContext(context.Background(), http.MethodGet, "/x", nil)
	req.Header.Set("Authorization", secretLookingToken)
	rec := httptest.NewRecorder()
	mw(next).ServeHTTP(rec, req)

	if rec.Code != http.StatusUnauthorized {
		t.Fatalf("expected 401, got %d", rec.Code)
	}
	body := rec.Body.String()
	if strings.Contains(body, "super-secret-payload") {
		t.Errorf("error body must not echo any part of the rejected token, got: %s", body)
	}
}

// --- end-to-end composition test: proves the Task 9 gap is closed ---
//
// This is the test the Task 9 brief calls for specifically: a bare
// *http.ServeMux with a dummy handler registered at "/mcp" — standing in for
// exactly what mcp.Mount registers, without importing the mcp package (kept
// here so it reuses this package's OIDC fixture instead of duplicating JWKS
// setup) — wrapped by HTTPMiddleware. An anonymous GET must be rejected
// before the handler runs; an authenticated GET must reach it. This is the
// concrete, executable proof that any handler mounted behind the wrapper —
// including mcp.Mount's and a2a.Mount's — no longer serves anonymously.
func TestHTTPMiddleware_ComposedWithServeMux_AnonymousMCPRejected(t *testing.T) {
	mw, err := HTTPMiddleware(HTTPConfig{Mode: ModeOIDC, OIDC: testFixture.rp})
	if err != nil {
		t.Fatalf("HTTPMiddleware: %v", err)
	}

	mux := http.NewServeMux()
	mux.Handle("/mcp", http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		w.WriteHeader(http.StatusOK)
	}))
	wrapped := mw(mux)

	anonReq := httptest.NewRequestWithContext(context.Background(), http.MethodGet, "/mcp", nil) // no Authorization header
	anonRec := httptest.NewRecorder()
	wrapped.ServeHTTP(anonRec, anonReq)
	if anonRec.Code != http.StatusUnauthorized {
		t.Fatalf("anonymous GET /mcp: expected 401, got %d — this is the exact defect Task 9 fixes: a raw handler mounted on the bare mux must never be reachable anonymously", anonRec.Code)
	}

	tok := testFixture.token(t, "user-1", nil, nil, "tenant-a")
	authReq := httptest.NewRequestWithContext(context.Background(), http.MethodGet, "/mcp", nil)
	authReq.Header.Set("Authorization", "Bearer "+tok)
	authRec := httptest.NewRecorder()
	wrapped.ServeHTTP(authRec, authReq)
	if authRec.Code != http.StatusOK {
		t.Fatalf("authenticated GET /mcp: expected 200, got %d", authRec.Code)
	}
}
