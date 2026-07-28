// Copyright 2026 Penguin Tech Inc
// SPDX-License-Identifier: Apache-2.0

package auth

import (
	"context"
	"fmt"
	"net/http"
	"net/http/httptest"
	"os"
	"strings"
	"testing"
	"time"

	"connectrpc.com/connect"
	gooidc "github.com/coreos/go-oidc/v3/oidc"

	"github.com/penguintechinc/penguin-libs/packages/go-aaa/audit"
	"github.com/penguintechinc/penguin-libs/packages/go-aaa/authn"
	"github.com/penguintechinc/penguin-libs/packages/go-aaa/authz"
	"github.com/penguintechinc/penguin-libs/packages/go-aaa/crypto"
	"github.com/penguintechinc/penguin-libs/packages/go-aaa/middleware"
	"github.com/penguintechinc/penguin-libs/packages/go-logging/logging"
	healthv1 "github.com/penguintechinc/penguin-libs/packages/go-rpc/gen/prpc/health/v1"
	"github.com/penguintechinc/penguin-libs/packages/go-rpc/gen/prpc/health/v1/healthv1connect"
)

// testFixture is populated once in TestMain and shared read-only across all
// tests in this file: it holds a genuine authn.OIDCRelyingParty constructed
// against a real (in-process, self-signed) OIDC provider.
//
// go-aaa's own middleware tests avoid constructing a real OIDCRelyingParty
// by faking the *interceptor logic* instead (see
// middleware/authn_test.go's buildFakeRPInterceptorWithOpts) — a seam that
// works there because their test replicates NewOIDCInterceptor's body
// against a validateFn callback. That seam is not available to this
// package: Config.OIDC is the concrete *authn.OIDCRelyingParty type, and
// NewOIDCRelyingParty always performs live discovery (crypto/keystore.go +
// oidc_provider.go have no mockable interface for it either). This file's
// "lowest-level seam" (per the Task 4 brief) is therefore to run the real
// discovery + JWKS + JWT-signing round trip against an httptest.Server —
// exercising the exact code path production wiring uses.
var testFixture *oidcFixture

type oidcFixture struct {
	rp       *authn.OIDCRelyingParty
	provider *authn.OIDCProvider
	audience string
}

// token signs and returns an ID token via the fixture's real OIDCProvider.
// sub is required; scope, roles, and tenant may be nil/empty per test case.
func (f *oidcFixture) token(t *testing.T, sub string, scope, roles []string, tenant string) string {
	t.Helper()
	now := time.Now()
	claims := &authn.Claims{
		// Sub/Iat/Exp must satisfy Claims.Validate() before IssueTokenSet
		// will sign anything. Iss/Aud here are validation placeholders only
		// — buildToken (oidc_provider.go) always stamps the issued token's
		// iss/aud from OIDCProviderConfig, never from the input Claims.
		Sub:    sub,
		Iss:    "ignored-by-issuer",
		Aud:    []string{"ignored-by-issuer"},
		Iat:    now,
		Exp:    now.Add(time.Hour),
		Scope:  scope,
		Roles:  roles,
		Tenant: tenant,
	}
	set, err := f.provider.IssueTokenSet(context.Background(), claims)
	if err != nil {
		t.Fatalf("IssueTokenSet: %v", err)
	}
	return set.IDToken
}

// newOIDCFixture stands up a self-signed httptest.Server serving a real
// OpenID discovery document and JWKS endpoint (backed by a
// crypto.MemoryKeyStore and authn.OIDCProvider), then constructs a genuine
// authn.OIDCRelyingParty against it via the same construction path
// production code uses. The trusting HTTP client only needs to be attached
// to the context used for construction/discovery: go-oidc's Provider caches
// the client passed at NewProvider time for all later remote-JWKS fetches
// (see Provider.remoteKeySet in oidc.go) — later ValidateToken calls at
// request time need no special context.
func newOIDCFixture() (fixture *oidcFixture, cleanup func(), err error) {
	ks, err := crypto.NewMemoryKeyStore(crypto.AlgorithmRS256)
	if err != nil {
		return nil, nil, fmt.Errorf("NewMemoryKeyStore: %w", err)
	}

	mux := http.NewServeMux()
	ts := httptest.NewTLSServer(mux)

	const clientID = "go-rpc-test-client"
	provider, err := authn.NewOIDCProvider(authn.OIDCProviderConfig{
		Issuer:    ts.URL,
		Audiences: []string{clientID},
	}, ks)
	if err != nil {
		ts.Close()
		return nil, nil, fmt.Errorf("NewOIDCProvider: %w", err)
	}

	mux.HandleFunc("/.well-known/openid-configuration", func(w http.ResponseWriter, _ *http.Request) {
		doc, docErr := provider.DiscoveryDocument()
		if docErr != nil {
			http.Error(w, docErr.Error(), http.StatusInternalServerError)
			return
		}
		w.Header().Set("Content-Type", "application/json")
		_, _ = w.Write(doc)
	})
	mux.HandleFunc("/.well-known/jwks.json", crypto.JWKSHandler(ks))

	ctx := gooidc.ClientContext(context.Background(), ts.Client())
	rp, err := authn.NewOIDCRelyingParty(ctx, authn.OIDCRPConfig{
		IssuerURL: ts.URL,
		ClientID:  clientID,
	})
	if err != nil {
		ts.Close()
		return nil, nil, fmt.Errorf("NewOIDCRelyingParty: %w", err)
	}

	return &oidcFixture{rp: rp, provider: provider, audience: clientID}, ts.Close, nil
}

func TestMain(m *testing.M) {
	fixture, cleanup, err := newOIDCFixture()
	if err != nil {
		fmt.Fprintf(os.Stderr, "auth_test: newOIDCFixture: %v\n", err)
		os.Exit(1)
	}
	testFixture = fixture

	code := m.Run()
	cleanup()
	os.Exit(code)
}

// newTestSPIFFEAuthenticator builds a real *authn.SPIFFEAuthenticator.
// NewSPIFFEAuthenticator only validates its config (no network I/O; the
// Workload API connection is a separate, explicit GetX509Source call), so
// this needs no fixture beyond a syntactically valid config.
func newTestSPIFFEAuthenticator(t *testing.T) *authn.SPIFFEAuthenticator {
	t.Helper()
	sa, err := authn.NewSPIFFEAuthenticator(authn.SPIFFEConfig{
		TrustDomain:    "example.org",
		WorkloadSocket: "unix:///tmp/go-rpc-test-nonexistent.sock",
		AllowedIDs:     []string{"spiffe://example.org/svc"},
	})
	if err != nil {
		t.Fatalf("NewSPIFFEAuthenticator: %v", err)
	}
	return sa
}

// successStub is the terminal handler used at the bottom of every composed
// chain in this file: reaching it means every interceptor granted access.
func successStub(_ context.Context, _ connect.AnyRequest) (connect.AnyResponse, error) {
	return connect.NewResponse(&struct{}{}), nil
}

// composeChain replicates connectrpc.com/connect's documented chain
// composition (newChain in interceptor.go): slice index 0 wraps outermost
// and therefore executes first on the request path. This lets tests invoke
// the exact slice Interceptors returns without spinning up a real
// connect.Handler/mux.
func composeChain(interceptors []connect.Interceptor, terminal connect.UnaryFunc) connect.UnaryFunc {
	next := terminal
	for i := len(interceptors) - 1; i >= 0; i-- {
		next = interceptors[i].WrapUnary(next)
	}
	return next
}

// --- Test 1: no credentials, non-public procedure -> CodeUnauthenticated ---

func TestInterceptors_NoCredentials_Unauthenticated(t *testing.T) {
	cfg := Config{
		Mode:     ModeOIDC,
		OIDC:     testFixture.rp,
		Enforcer: authz.NewRBACEnforcer(),
		Scopes:   middleware.ProcedureScopes{"": {"report:read"}},
	}
	interceptors, err := Interceptors(cfg)
	if err != nil {
		t.Fatalf("Interceptors: %v", err)
	}
	handler := composeChain(interceptors, successStub)

	req := connect.NewRequest(&struct{}{}) // no Authorization header
	_, err = handler(context.Background(), req)
	if err == nil {
		t.Fatal("expected error for missing credentials")
	}
	if connect.CodeOf(err) != connect.CodeUnauthenticated {
		t.Errorf("expected CodeUnauthenticated, got %v (%v)", connect.CodeOf(err), err)
	}
}

// --- Test 2: valid token, missing tenant claim -> denied before scope eval ---

func TestInterceptors_MissingTenant_DeniedBeforeScopeEvaluation(t *testing.T) {
	// The enforcer is unused by this scenario on the correct code path: the
	// token below already carries the exact scope the procedure requires
	// directly (no role resolution needed), so if authz ran before tenant
	// the request would succeed outright. go-aaa's authz.RBACEnforcer is a
	// concrete struct with no interface seam, so it cannot be replaced with
	// a call-counting stub (the pattern suggested as an example in the Task
	// 4 brief); asserting tenant.go's specific "missing tenant claim"
	// message — rather than just the PermissionDenied code, which authz
	// could also produce — is the achievable substitute: it can only appear
	// if the tenant interceptor actually ran and rejected the request
	// before authz was reached.
	enforcer := authz.NewRBACEnforcer()
	cfg := Config{
		Mode:     ModeOIDC,
		OIDC:     testFixture.rp,
		Enforcer: enforcer,
		Scopes:   middleware.ProcedureScopes{"": {"report:read"}},
	}
	interceptors, err := Interceptors(cfg)
	if err != nil {
		t.Fatalf("Interceptors: %v", err)
	}
	handler := composeChain(interceptors, successStub)

	tok := testFixture.token(t, "user-1", []string{"report:read"}, nil, "" /* no tenant */)
	req := connect.NewRequest(&struct{}{})
	req.Header().Set("Authorization", "Bearer "+tok)

	_, err = handler(context.Background(), req)
	if err == nil {
		t.Fatal("expected denial for missing tenant claim")
	}
	if connect.CodeOf(err) != connect.CodePermissionDenied {
		t.Errorf("expected CodePermissionDenied, got %v (%v)", connect.CodeOf(err), err)
	}
	if !strings.Contains(err.Error(), "missing tenant claim") {
		t.Errorf("expected tenant.go's denial message, got: %v", err)
	}
}

// --- Test 3: valid tenant, missing required scope -> CodePermissionDenied ---

func TestInterceptors_InsufficientScope_PermissionDenied(t *testing.T) {
	enforcer := authz.NewRBACEnforcer()
	cfg := Config{
		Mode:     ModeOIDC,
		OIDC:     testFixture.rp,
		Enforcer: enforcer,
		Scopes:   middleware.ProcedureScopes{"": {"report:write"}},
	}
	interceptors, err := Interceptors(cfg)
	if err != nil {
		t.Fatalf("Interceptors: %v", err)
	}
	handler := composeChain(interceptors, successStub)

	tok := testFixture.token(t, "user-1", []string{"report:read"}, nil, "tenant-a")
	req := connect.NewRequest(&struct{}{})
	req.Header().Set("Authorization", "Bearer "+tok)

	_, err = handler(context.Background(), req)
	if err == nil {
		t.Fatal("expected denial for insufficient scope")
	}
	if connect.CodeOf(err) != connect.CodePermissionDenied {
		t.Errorf("expected CodePermissionDenied, got %v (%v)", connect.CodeOf(err), err)
	}
}

// --- Test 4: procedure declared in neither Scopes nor Public -> denied ---
// --- even for a token with admin scopes                                ---

func TestInterceptors_UndeclaredProcedure_DeniedEvenWithAdminScopes(t *testing.T) {
	enforcer := authz.NewRBACEnforcer()
	cfg := Config{
		Mode:     ModeOIDC,
		OIDC:     testFixture.rp,
		Enforcer: enforcer,
		// "" (the procedure every connect.NewRequest test carries, since
		// Spec().Procedure has no exported setter) is deliberately absent
		// here — only a different procedure path is declared.
		Scopes: middleware.ProcedureScopes{"/some.Other/Procedure": {"admin:all"}},
		Public: nil,
	}
	interceptors, err := Interceptors(cfg)
	if err != nil {
		t.Fatalf("Interceptors: %v", err)
	}
	handler := composeChain(interceptors, successStub)

	tok := testFixture.token(t, "admin-1", []string{"admin:all", "report:read", "report:write"}, nil, "tenant-a")
	req := connect.NewRequest(&struct{}{})
	req.Header().Set("Authorization", "Bearer "+tok)

	_, err = handler(context.Background(), req)
	if err == nil {
		t.Fatal("expected denial for undeclared procedure")
	}
	if connect.CodeOf(err) != connect.CodePermissionDenied {
		t.Errorf("expected CodePermissionDenied, got %v (%v)", connect.CodeOf(err), err)
	}
	// The gate's denial message is intentionally generic ("permission
	// denied") rather than naming the undeclared procedure — see auth.go's
	// denyByDefaultGate.WrapUnary doc comment: this package has no logger to
	// record that detail server-side, so it is dropped rather than leaked to
	// the client.
	if err.Error() != "permission_denied: permission denied" {
		t.Errorf("expected the gate's generic denial message, got: %v", err)
	}
}

// --- Test 5: public procedure succeeds with zero credentials ---

func TestInterceptors_PublicProcedure_SucceedsWithZeroCredentials(t *testing.T) {
	cfg := Config{
		Mode:     ModeOIDC,
		OIDC:     testFixture.rp,
		Enforcer: authz.NewRBACEnforcer(),
		// Scoped AND public: Public must win so the procedure is reachable
		// with no credentials at all.
		Scopes: middleware.ProcedureScopes{"": {"report:read"}},
		Public: []string{""},
	}
	interceptors, err := Interceptors(cfg)
	if err != nil {
		t.Fatalf("Interceptors: %v", err)
	}
	handler := composeChain(interceptors, successStub)

	req := connect.NewRequest(&struct{}{}) // zero credentials: no header at all
	_, err = handler(context.Background(), req)
	if err != nil {
		t.Fatalf("expected success for public procedure with zero credentials, got: %v", err)
	}
}

// --- Test 6: roles claim alone (no scope) grants nothing ---

func TestInterceptors_RolesAloneGrantNothing(t *testing.T) {
	// The enforcer has no "admin" role registered, so resolveScopes
	// (authz.go) derives zero scopes from the roles claim. This demonstrates
	// spec §6's "roles is informational only": a roles claim is never
	// itself an authorization decision — it is only ever a lookup key into
	// the enforcer's own scope registry, and an unregistered role
	// contributes nothing.
	enforcer := authz.NewRBACEnforcer()
	cfg := Config{
		Mode:     ModeOIDC,
		OIDC:     testFixture.rp,
		Enforcer: enforcer,
		Scopes:   middleware.ProcedureScopes{"": {"report:read"}},
	}
	interceptors, err := Interceptors(cfg)
	if err != nil {
		t.Fatalf("Interceptors: %v", err)
	}
	handler := composeChain(interceptors, successStub)

	tok := testFixture.token(t, "user-1", nil, []string{"admin"}, "tenant-a")
	req := connect.NewRequest(&struct{}{})
	req.Header().Set("Authorization", "Bearer "+tok)

	_, err = handler(context.Background(), req)
	if err == nil {
		t.Fatal("expected denial: an unregistered role claim must not grant scopes")
	}
	if connect.CodeOf(err) != connect.CodePermissionDenied {
		t.Errorf("expected CodePermissionDenied, got %v (%v)", connect.CodeOf(err), err)
	}
}

// TestInterceptors_RoleGrantsScope_WhenRegisteredInEnforcer is the positive
// counterpart to TestInterceptors_RolesAloneGrantNothing: it confirms that
// scopes only ever flow through the enforcer's explicit role->scope
// registration, never from the roles claim value itself.
func TestInterceptors_RoleGrantsScope_WhenRegisteredInEnforcer(t *testing.T) {
	enforcer := authz.NewRBACEnforcer(authz.Role{Name: "admin", Scopes: []string{"report:read"}})
	cfg := Config{
		Mode:     ModeOIDC,
		OIDC:     testFixture.rp,
		Enforcer: enforcer,
		Scopes:   middleware.ProcedureScopes{"": {"report:read"}},
	}
	interceptors, err := Interceptors(cfg)
	if err != nil {
		t.Fatalf("Interceptors: %v", err)
	}
	handler := composeChain(interceptors, successStub)

	tok := testFixture.token(t, "user-1", nil, []string{"admin"}, "tenant-a")
	req := connect.NewRequest(&struct{}{})
	req.Header().Set("Authorization", "Bearer "+tok)

	_, err = handler(context.Background(), req)
	if err != nil {
		t.Fatalf("expected success: enforcer resolves 'admin' role to report:read, got: %v", err)
	}
}

// --- Test 7: constructor validation errors ---

func TestInterceptors_InvalidConfig(t *testing.T) {
	validEnforcer := authz.NewRBACEnforcer()
	sa := newTestSPIFFEAuthenticator(t)

	cases := []struct {
		name string
		cfg  Config
	}{
		{"unsupported mode", Config{Mode: "jwt", Enforcer: validEnforcer}},
		{"empty mode", Config{Mode: "", Enforcer: validEnforcer}},
		{"oidc mode with nil OIDC", Config{Mode: ModeOIDC, Enforcer: validEnforcer}},
		{"spiffe mode with nil SPIFFE", Config{Mode: ModeSPIFFE, Enforcer: validEnforcer}},
		{"both mode with nil OIDC", Config{Mode: ModeBoth, SPIFFE: sa, Enforcer: validEnforcer}},
		{"both mode with nil SPIFFE", Config{Mode: ModeBoth, OIDC: testFixture.rp, Enforcer: validEnforcer}},
		{"nil enforcer", Config{Mode: ModeOIDC, OIDC: testFixture.rp, Enforcer: nil}},
	}

	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			if _, err := Interceptors(tc.cfg); err == nil {
				t.Fatalf("expected a constructor error for case %q", tc.name)
			}
		})
	}
}

func TestInterceptors_ValidConfigsSucceed(t *testing.T) {
	validEnforcer := authz.NewRBACEnforcer()
	sa := newTestSPIFFEAuthenticator(t)

	cases := []struct {
		name string
		cfg  Config
	}{
		{"oidc mode", Config{Mode: ModeOIDC, OIDC: testFixture.rp, Enforcer: validEnforcer}},
		{"spiffe mode", Config{Mode: ModeSPIFFE, SPIFFE: sa, Enforcer: validEnforcer}},
		{"both mode", Config{Mode: ModeBoth, OIDC: testFixture.rp, SPIFFE: sa, Enforcer: validEnforcer}},
	}

	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			interceptors, err := Interceptors(tc.cfg)
			if err != nil {
				t.Fatalf("unexpected error: %v", err)
			}
			if len(interceptors) == 0 {
				t.Fatal("expected a non-empty interceptor chain")
			}
		})
	}
}

// --- Mode "both": dispatch behavior (new combinator logic, not go-aaa's) ---

func TestBothMode_DispatchesToOIDCWhenBearerPresent(t *testing.T) {
	sa := newTestSPIFFEAuthenticator(t)
	cfg := Config{
		Mode:     ModeBoth,
		OIDC:     testFixture.rp,
		SPIFFE:   sa,
		Enforcer: authz.NewRBACEnforcer(),
		Scopes:   middleware.ProcedureScopes{"": {"report:read"}},
	}
	interceptors, err := Interceptors(cfg)
	if err != nil {
		t.Fatalf("Interceptors: %v", err)
	}
	handler := composeChain(interceptors, successStub)

	tok := testFixture.token(t, "user-1", []string{"report:read"}, nil, "tenant-a")
	req := connect.NewRequest(&struct{}{})
	req.Header().Set("Authorization", "Bearer "+tok)

	_, err = handler(context.Background(), req)
	if err != nil {
		t.Fatalf("expected the OIDC branch to succeed with a valid bearer token, got: %v", err)
	}
}

func TestBothMode_DispatchesToSPIFFEWhenNoBearerToken(t *testing.T) {
	sa := newTestSPIFFEAuthenticator(t)
	cfg := Config{
		Mode:     ModeBoth,
		OIDC:     testFixture.rp,
		SPIFFE:   sa,
		Enforcer: authz.NewRBACEnforcer(),
		Scopes:   middleware.ProcedureScopes{"": {"report:read"}},
	}
	interceptors, err := Interceptors(cfg)
	if err != nil {
		t.Fatalf("Interceptors: %v", err)
	}
	handler := composeChain(interceptors, successStub)

	// No Authorization header: the combinator must route to the SPIFFE
	// interceptor rather than falling through to OIDC's own
	// "missing bearer token" branch. A real mTLS handshake can't be
	// exercised in a unit test, so this asserts on the SPIFFE-specific
	// error text (tlsPeerCertsFromContext in go-aaa's authn.go) — which can
	// only appear if the SPIFFE branch, not the OIDC one, actually ran.
	req := connect.NewRequest(&struct{}{})
	_, err = handler(context.Background(), req)
	if err == nil {
		t.Fatal("expected an error: no TLS peer certificate is available in this test")
	}
	if connect.CodeOf(err) != connect.CodeUnauthenticated {
		t.Errorf("expected CodeUnauthenticated, got %v (%v)", connect.CodeOf(err), err)
	}
	if !strings.Contains(err.Error(), "spiffe:") {
		t.Errorf("expected a spiffe-specific error proving the SPIFFE branch executed, got: %v", err)
	}
}

// --- hasBearerToken: unit coverage for the "both" mode dispatch predicate ---

func TestHasBearerToken(t *testing.T) {
	cases := []struct {
		name   string
		header string
		want   bool
	}{
		{"missing header", "", false},
		{"wrong scheme", "Basic dXNlcjpwYXNz", false},
		{"bearer with no token", "Bearer", false},
		{"valid bearer", "Bearer abc123", true},
	}

	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			req := connect.NewRequest(&struct{}{})
			if tc.header != "" {
				req.Header().Set("Authorization", tc.header)
			}
			if got := hasBearerToken(req); got != tc.want {
				t.Errorf("hasBearerToken(%q) = %v, want %v", tc.header, got, tc.want)
			}
		})
	}
}

// --- newDenyByDefaultInterceptor: focused, white-box gate coverage ---
//
// newDenyByDefaultInterceptor now returns *denyByDefaultGate, a full
// connect.Interceptor (see Finding 1 in auth.go/doc.go), so these tests call
// its WrapUnary method explicitly rather than invoking the value directly as
// a function — the old connect.UnaryInterceptorFunc return type supported
// direct invocation, the new struct type does not.

func TestDenyByDefaultInterceptor_DeclaredProcedurePassesThrough(t *testing.T) {
	interceptor := newDenyByDefaultInterceptor(middleware.ProcedureScopes{"": {"report:read"}}, nil)
	req := connect.NewRequest(&struct{}{})

	_, err := interceptor.WrapUnary(successStub)(context.Background(), req)
	if err != nil {
		t.Errorf("expected pass-through for a declared procedure, got: %v", err)
	}
}

func TestDenyByDefaultInterceptor_PresentKeyWithEmptyScopesStillCountsAsDeclared(t *testing.T) {
	// A key present with an empty scope slice means "declared, no scope
	// required" (matching go-aaa's own authz.go semantics for the same
	// case) — not "undeclared". Only a wholly absent key must be denied.
	interceptor := newDenyByDefaultInterceptor(middleware.ProcedureScopes{"": {}}, nil)
	req := connect.NewRequest(&struct{}{})

	_, err := interceptor.WrapUnary(successStub)(context.Background(), req)
	if err != nil {
		t.Errorf("expected pass-through for a declared (empty-scope) procedure, got: %v", err)
	}
}

func TestDenyByDefaultInterceptor_UndeclaredProcedureDenied(t *testing.T) {
	interceptor := newDenyByDefaultInterceptor(middleware.ProcedureScopes{}, nil)
	req := connect.NewRequest(&struct{}{})

	_, err := interceptor.WrapUnary(successStub)(context.Background(), req)
	if err == nil {
		t.Fatal("expected denial for an undeclared procedure")
	}
	if connect.CodeOf(err) != connect.CodePermissionDenied {
		t.Errorf("expected CodePermissionDenied, got %v (%v)", connect.CodeOf(err), err)
	}
}

func TestDenyByDefaultInterceptor_PublicProcedureBypassesEvenWhenUndeclared(t *testing.T) {
	interceptor := newDenyByDefaultInterceptor(middleware.ProcedureScopes{}, []string{""})
	req := connect.NewRequest(&struct{}{})

	_, err := interceptor.WrapUnary(successStub)(context.Background(), req)
	if err != nil {
		t.Errorf("expected pass-through for a public procedure, got: %v", err)
	}
}

// TestDenyByDefaultInterceptor_WrapStreamingClientPassesThrough covers the
// gate's client-side leg directly: the gate has no client-side enforcement
// role (see its doc comment in auth.go), so WrapStreamingClient must return
// exactly the StreamingClientFunc it was given, unmodified.
func TestDenyByDefaultInterceptor_WrapStreamingClientPassesThrough(t *testing.T) {
	interceptor := newDenyByDefaultInterceptor(middleware.ProcedureScopes{}, nil)
	called := false
	next := func(ctx context.Context, spec connect.Spec) connect.StreamingClientConn {
		called = true
		return nil
	}

	wrapped := interceptor.WrapStreamingClient(next)
	wrapped(context.Background(), connect.Spec{Procedure: "/x/Y"})

	if !called {
		t.Error("expected WrapStreamingClient to pass calls straight through to next")
	}
}

// --- Finding 1: streaming RPCs bypass the entire auth chain ---
//
// Every interceptor go-aaa's middleware package exports is a
// connect.UnaryInterceptorFunc, whose WrapStreamingHandler is a documented
// no-op (connectrpc.com/connect v1.20.0 interceptor.go:70-73). Before the
// fix, this package's own gate was built the same way, so a streaming
// procedure behind auth.Interceptors() reached the handler with zero
// interceptors having done anything — full bypass, regardless of
// credentials. These tests exercise the real generated
// healthv1connect.HealthServiceHandler (server-streaming Watch RPC) behind
// a real httptest.Server wired with connect.WithInterceptors(chain...) —
// the same wiring production servers use — because WrapUnary is never
// consulted for a streaming procedure, so nothing short of an actual
// streaming call proves the fix.
//
// RED/GREEN history (see the report for the literal `go test` output):
// TestStreamingWatch_NonPublic_DeniedWithZeroCredentials was written first
// asserting the fail-closed *expectation* (stream.Receive() returns false,
// stream.Err() is CodePermissionDenied). Run against the pre-fix
// denyByDefaultGate (a connect.UnaryInterceptorFunc, matching every other
// interceptor at the time), it FAILED: stream.Receive() returned true and
// stream.Msg() carried the stub handler's real response — proving the
// bypass Finding 1 describes, with no Authorization header at all. That
// failure is RED. Making denyByDefaultGate a full connect.Interceptor with
// a fail-closed WrapStreamingHandler (auth.go) turned the same assertion
// GREEN with no further change to this test.

// stubHealthServer implements healthv1connect.HealthServiceHandler. Watch
// sends exactly one response and returns nil; a client actually receiving
// that response is proof the call reached the handler — i.e. that
// everything in front of it, including this package's auth chain, let it
// through.
type stubHealthServer struct {
	healthv1connect.UnimplementedHealthServiceHandler
}

func (stubHealthServer) Watch(_ context.Context, _ *connect.Request[healthv1.CheckRequest], stream *connect.ServerStream[healthv1.CheckResponse]) error {
	return stream.Send(&healthv1.CheckResponse{Status: healthv1.ServingStatus_SERVING_STATUS_SERVING})
}

// newStreamingTestServer wires interceptors into a real
// healthv1connect.HealthServiceHandler behind an httptest.Server via
// connect.WithInterceptors — the same call production server wiring uses —
// and returns a real generated client. The Connect protocol supports
// server-streaming RPCs over plain HTTP/1.1 (chunked transfer encoding), so
// httptest.NewServer (HTTP/1.1) is sufficient; no TLS/h2c setup is needed.
func newStreamingTestServer(t *testing.T, interceptors []connect.Interceptor) healthv1connect.HealthServiceClient {
	t.Helper()
	mux := http.NewServeMux()
	path, handler := healthv1connect.NewHealthServiceHandler(stubHealthServer{}, connect.WithInterceptors(interceptors...))
	mux.Handle(path, handler)
	srv := httptest.NewServer(mux)
	t.Cleanup(srv.Close)
	return healthv1connect.NewHealthServiceClient(srv.Client(), srv.URL)
}

func TestStreamingWatch_NonPublic_DeniedWithZeroCredentials(t *testing.T) {
	enforcer := authz.NewRBACEnforcer()
	cfg := Config{
		Mode:     ModeOIDC,
		OIDC:     testFixture.rp,
		Enforcer: enforcer,
		Scopes:   middleware.ProcedureScopes{healthv1connect.HealthServiceWatchProcedure: {"health:watch"}},
	}
	interceptors, err := Interceptors(cfg)
	if err != nil {
		t.Fatalf("Interceptors: %v", err)
	}
	client := newStreamingTestServer(t, interceptors)

	stream, err := client.Watch(context.Background(), connect.NewRequest(&healthv1.CheckRequest{})) // zero credentials
	if err != nil {
		t.Fatalf("Watch: unexpected client-side error establishing the stream: %v", err)
	}
	if stream.Receive() {
		t.Fatalf("expected the streaming call to be denied before any message was sent, but received: %v — this is Finding 1's streaming auth bypass", stream.Msg())
	}
	if err := stream.Err(); err == nil {
		t.Fatal("expected a denial error from Receive/Err, got nil")
	} else if connect.CodeOf(err) != connect.CodePermissionDenied {
		t.Errorf("expected CodePermissionDenied, got %v (%v)", connect.CodeOf(err), err)
	}
}

func TestStreamingWatch_NonPublic_DeniedEvenWithValidCredentials(t *testing.T) {
	// Fail-closed means fail-closed regardless of credentials: go-aaa's
	// authn/tenant/authz interceptors are connect.UnaryInterceptorFunc and
	// therefore no-ops on the streaming path (see doc.go's "Streaming RPCs"
	// section), so a fully valid bearer token with the exact required scope
	// and a tenant claim changes nothing — the gate denies before the
	// request reaches any of those interceptors.
	enforcer := authz.NewRBACEnforcer()
	cfg := Config{
		Mode:     ModeOIDC,
		OIDC:     testFixture.rp,
		Enforcer: enforcer,
		Scopes:   middleware.ProcedureScopes{healthv1connect.HealthServiceWatchProcedure: {"health:watch"}},
	}
	interceptors, err := Interceptors(cfg)
	if err != nil {
		t.Fatalf("Interceptors: %v", err)
	}
	client := newStreamingTestServer(t, interceptors)

	tok := testFixture.token(t, "user-1", []string{"health:watch"}, nil, "tenant-a")
	req := connect.NewRequest(&healthv1.CheckRequest{})
	req.Header().Set("Authorization", "Bearer "+tok)

	stream, err := client.Watch(context.Background(), req)
	if err != nil {
		t.Fatalf("Watch: unexpected client-side error establishing the stream: %v", err)
	}
	if stream.Receive() {
		t.Fatalf("expected denial even with a fully valid token+scope+tenant, but received: %v — streaming authn/authz is not implemented, so it must fail closed rather than silently granting access", stream.Msg())
	}
	if connect.CodeOf(stream.Err()) != connect.CodePermissionDenied {
		t.Errorf("expected CodePermissionDenied, got %v (%v)", connect.CodeOf(stream.Err()), stream.Err())
	}
}

func TestStreamingWatch_PublicProcedure_PassesThrough(t *testing.T) {
	enforcer := authz.NewRBACEnforcer()
	cfg := Config{
		Mode:     ModeOIDC,
		OIDC:     testFixture.rp,
		Enforcer: enforcer,
		Scopes:   middleware.ProcedureScopes{healthv1connect.HealthServiceWatchProcedure: {"health:watch"}},
		Public:   []string{healthv1connect.HealthServiceWatchProcedure},
	}
	interceptors, err := Interceptors(cfg)
	if err != nil {
		t.Fatalf("Interceptors: %v", err)
	}
	client := newStreamingTestServer(t, interceptors)

	stream, err := client.Watch(context.Background(), connect.NewRequest(&healthv1.CheckRequest{})) // zero credentials
	if err != nil {
		t.Fatalf("Watch: unexpected client-side error establishing the stream: %v", err)
	}
	if !stream.Receive() {
		t.Fatalf("expected the public streaming procedure to pass through with zero credentials, got error: %v", stream.Err())
	}
	if stream.Msg().GetStatus() != healthv1.ServingStatus_SERVING_STATUS_SERVING {
		t.Errorf("unexpected response status: %v", stream.Msg().GetStatus())
	}
	if err := stream.Err(); err != nil {
		t.Errorf("unexpected stream error: %v", err)
	}
}

// --- Finding 2: ModeSPIFFE cannot authorize any non-public procedure ---
//
// See doc.go's "Known limitations" section for the full rationale,
// including why this test injects context claims rather than driving a real
// mTLS handshake: NewSPIFFEInterceptor's peer-certificate extraction
// requires a completed *tls.Conn handshake with no pure-computation seam
// available (unlike OIDC's JWT signing, which this file's testFixture
// already exercises for real). This test instead takes the real
// tenant/gate/authz sub-slice of the chain that
// Interceptors(Config{Mode: ModeSPIFFE, ...}) constructs — everything after
// the authn interceptor, at index 0 — and injects context claims shaped
// exactly like go-aaa's NewSPIFFEInterceptor synthesis
// (middleware/authn.go: &authn.Claims{Sub: spiffeID, Iss: "spiffe"}, no
// Tenant field), i.e. exactly the context state a successful SPIFFE
// handshake would have produced. Scopes intentionally requires no scope for
// the test procedure (a present key with an empty slice, matching
// TestDenyByDefaultInterceptor_PresentKeyWithEmptyScopesStillCountsAsDeclared's
// documented semantics) so that if a future go-aaa change ever populated
// Tenant for SPIFFE identities, authz would trivially grant access —
// isolating the tenant check as the sole thing this test can be denied by
// today.
func TestSPIFFEMode_SynthesizedClaimsHaveNoTenant_DeniedByTenantInterceptor(t *testing.T) {
	sa := newTestSPIFFEAuthenticator(t)
	cfg := Config{
		Mode:     ModeSPIFFE,
		SPIFFE:   sa,
		Enforcer: authz.NewRBACEnforcer(),
		Scopes:   middleware.ProcedureScopes{"": {}},
	}
	interceptors, err := Interceptors(cfg)
	if err != nil {
		t.Fatalf("Interceptors: %v", err)
	}
	if len(interceptors) < 2 {
		t.Fatalf("expected at least [authn, tenant, gate, authz] in the chain, got %d interceptors", len(interceptors))
	}
	// Skip index 0 (authn): exercise the real tenant -> gate -> authz
	// sub-slice this package's own Interceptors() constructed for
	// Mode: ModeSPIFFE.
	handler := composeChain(interceptors[1:], successStub)

	// Mirrors go-aaa's NewSPIFFEInterceptor claims synthesis exactly
	// (middleware/authn.go) — the state left in context by a *successful*
	// SPIFFE mTLS peer validation.
	claims := &authn.Claims{Sub: "spiffe://example.org/svc", Iss: "spiffe"}
	ctx := authz.ContextWithClaims(context.Background(), claims)

	req := connect.NewRequest(&struct{}{})
	_, err = handler(ctx, req)
	if err == nil {
		t.Fatal("expected denial: SPIFFE-synthesized claims carry no tenant, so the tenant interceptor must reject")
	}
	if connect.CodeOf(err) != connect.CodePermissionDenied {
		t.Errorf("expected CodePermissionDenied, got %v (%v)", connect.CodeOf(err), err)
	}
	if !strings.Contains(err.Error(), "missing tenant claim") {
		t.Errorf("expected tenant.go's denial message (proving the tenant interceptor, not the gate or authz, was the one that denied), got: %v", err)
	}
}

// --- Finding 3: audit is outermost, so it always attributes to "anonymous" ---
//
// See doc.go's "Interceptor order" section (the "Trade-off, disclosed
// rather than hidden" paragraph) for the full rationale. This test wires a
// real audit.Emitter (audit.NewEmitter) backed by a real
// logging.CallbackSink — the same package-level constructors go-aaa's own
// emitter_test.go uses — into the full chain via Config.Audit, then drives
// a completely valid, successful, authenticated request (valid token,
// correct tenant, correct scope) through it. The audit event fires and is
// classified EventAuthzGranted/OutcomeSuccess as expected, but its subject
// is asserted to be "anonymous" — NOT the token's real "sub" claim
// ("user-1") — because go-aaa's NewAuditInterceptor (audit.go) resolves the
// subject from context before calling next, and audit sits outermost, so it
// never sees the context authn produces. That assertion documents the
// CURRENT limitation; it is not the desired end state. If this assertion
// ever starts failing because events[0]["subject"] is "user-1", it means
// go-aaa gained post-next subject resolution — update doc.go's
// "Trade-off, disclosed rather than hidden" paragraph and this test/comment
// together rather than treating the failure as a regression to revert.
func TestAuditInterceptor_EmitsEvent_ButAttributesToAnonymous(t *testing.T) {
	var events []map[string]interface{}
	sink := logging.NewCallbackSink(func(event map[string]interface{}) {
		events = append(events, event)
	})
	emitter := audit.NewEmitter(sink)

	enforcer := authz.NewRBACEnforcer()
	cfg := Config{
		Mode:     ModeOIDC,
		OIDC:     testFixture.rp,
		Enforcer: enforcer,
		Scopes:   middleware.ProcedureScopes{"": {"report:read"}},
		Audit:    emitter,
	}
	interceptors, err := Interceptors(cfg)
	if err != nil {
		t.Fatalf("Interceptors: %v", err)
	}
	handler := composeChain(interceptors, successStub)

	tok := testFixture.token(t, "user-1", []string{"report:read"}, nil, "tenant-a")
	req := connect.NewRequest(&struct{}{})
	req.Header().Set("Authorization", "Bearer "+tok)

	if _, err := handler(context.Background(), req); err != nil {
		t.Fatalf("expected a fully authorized request to succeed, got: %v", err)
	}

	if len(events) != 1 {
		t.Fatalf("expected exactly 1 audit event to be emitted, got %d", len(events))
	}
	if events[0]["type"] != string(audit.EventAuthzGranted) {
		t.Errorf("expected event type %q, got %v", audit.EventAuthzGranted, events[0]["type"])
	}
	if events[0]["outcome"] != string(audit.OutcomeSuccess) {
		t.Errorf("expected outcome %q, got %v", audit.OutcomeSuccess, events[0]["outcome"])
	}
	// DOCUMENTED LIMITATION, not the desired end state — see the comment
	// above this test and doc.go's "Interceptor order" trade-off paragraph.
	if events[0]["subject"] != "anonymous" {
		t.Errorf("expected subject %q (documented attribution limitation), got %v", "anonymous", events[0]["subject"])
	}
}
