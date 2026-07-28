// Copyright 2026 Penguin Tech Inc
// SPDX-License-Identifier: Apache-2.0

//go:build integration

// Package integration is the Phase 1 cross-lane verification gate for
// go-rpc (Task 10): it wires one real server — both H2 and H3 listeners,
// SelfSignedTLSConfig, the full production interceptor chain (recovery,
// correlation, deadline, logging, metrics, protovalidate, zero-trust auth),
// conformance + health services, and MCP + A2A mounts guarded by
// auth.HTTPMiddleware — and drives it end-to-end over real sockets with
// real generated Connect clients. Nothing here is mocked: TLS handshakes,
// QUIC/UDP and TCP dials, JWT signing/verification, and protovalidate CEL
// evaluation all run for real, exercising exactly the surface a production
// deployment uses.
//
// # Streaming procedures are declared Public
//
// go-aaa cannot yet authorize streaming RPCs (auth/auth.go's
// denyByDefaultGate.WrapStreamingHandler fails closed unconditionally for
// any non-public streaming procedure, regardless of credentials — see
// auth/doc.go's "Streaming RPCs" section, the T4 follow-up). To let the
// streaming legs of the matrix below actually run against the real auth
// chain, ConformanceService's ServerStream/ClientStream/BidiStream
// procedures are declared in auth.Config.Public here rather than Scopes.
// Only Unary is scope-gated ("conformance:invoke"), which is what the
// auth-deny scenario below exercises.
package integration

import (
	"context"
	"crypto/tls"
	"crypto/x509"
	"encoding/json"
	"fmt"
	"net"
	"net/http"
	"net/http/httptest"
	"os"
	"strings"
	"testing"
	"time"

	"connectrpc.com/connect"
	gooidc "github.com/coreos/go-oidc/v3/oidc"
	"go.uber.org/zap"

	a2asdk "github.com/a2aproject/a2a-go/v2/a2a"
	mcpsdk "github.com/modelcontextprotocol/go-sdk/mcp"

	"github.com/penguintechinc/penguin-libs/packages/go-aaa/authn"
	"github.com/penguintechinc/penguin-libs/packages/go-aaa/authz"
	"github.com/penguintechinc/penguin-libs/packages/go-aaa/crypto"
	"github.com/penguintechinc/penguin-libs/packages/go-aaa/middleware"

	"github.com/penguintechinc/penguin-libs/packages/go-rpc/a2a"
	"github.com/penguintechinc/penguin-libs/packages/go-rpc/auth"
	"github.com/penguintechinc/penguin-libs/packages/go-rpc/client"
	"github.com/penguintechinc/penguin-libs/packages/go-rpc/conformance"
	conformancev1 "github.com/penguintechinc/penguin-libs/packages/go-rpc/gen/prpc/conformance/v1"
	"github.com/penguintechinc/penguin-libs/packages/go-rpc/gen/prpc/conformance/v1/conformancev1connect"
	healthv1 "github.com/penguintechinc/penguin-libs/packages/go-rpc/gen/prpc/health/v1"
	"github.com/penguintechinc/penguin-libs/packages/go-rpc/gen/prpc/health/v1/healthv1connect"
	"github.com/penguintechinc/penguin-libs/packages/go-rpc/health"
	"github.com/penguintechinc/penguin-libs/packages/go-rpc/mcp"
	"github.com/penguintechinc/penguin-libs/packages/go-rpc/server"
)

// --- OIDC test fixture -----------------------------------------------------
//
// This mirrors auth/auth_test.go's newOIDCFixture exactly (same package
// family, same rationale documented there): Config.OIDC is the concrete
// *authn.OIDCRelyingParty type with no mockable seam, so the lowest-level
// fixture available is a real discovery + JWKS + JWT-signing round trip
// against an httptest.Server, exercising the exact code path production
// wiring uses.

type oidcFixture struct {
	rp       *authn.OIDCRelyingParty
	provider *authn.OIDCProvider
	audience string
}

// token signs and returns a JWT via the fixture's real OIDCProvider. sub is
// required; scope and tenant may be empty/nil per scenario.
func (f *oidcFixture) token(t *testing.T, sub string, scope []string, tenant string) string {
	t.Helper()
	now := time.Now()
	claims := &authn.Claims{
		Sub:    sub,
		Iss:    "ignored-by-issuer",
		Aud:    []string{"ignored-by-issuer"},
		Iat:    now,
		Exp:    now.Add(time.Hour),
		Scope:  scope,
		Tenant: tenant,
	}
	set, err := f.provider.IssueTokenSet(context.Background(), claims)
	if err != nil {
		t.Fatalf("IssueTokenSet: %v", err)
	}
	return set.IDToken
}

// newOIDCFixture stands up a self-signed httptest.Server serving a real
// OpenID discovery document and JWKS endpoint, then constructs a genuine
// authn.OIDCRelyingParty against it via the same construction path
// production code uses.
func newOIDCFixture() (fixture *oidcFixture, cleanup func(), err error) {
	ks, err := crypto.NewMemoryKeyStore(crypto.AlgorithmRS256)
	if err != nil {
		return nil, nil, fmt.Errorf("NewMemoryKeyStore: %w", err)
	}

	mux := http.NewServeMux()
	ts := httptest.NewTLSServer(mux)

	const clientID = "go-rpc-integration-test-client"
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

var testFixture *oidcFixture

func TestMain(m *testing.M) {
	fixture, cleanup, err := newOIDCFixture()
	if err != nil {
		fmt.Fprintf(os.Stderr, "integration: newOIDCFixture: %v\n", err)
		os.Exit(1)
	}
	testFixture = fixture

	code := m.Run()
	cleanup()
	os.Exit(code)
}

// --- server/env setup --------------------------------------------------

// testEnv holds everything a subtest needs against the one full-stack
// server started for this test binary.
type testEnv struct {
	pool *x509.CertPool

	h2Addr string
	h3Addr string

	h3Conformance conformancev1connect.ConformanceServiceClient
	h2Conformance conformancev1connect.ConformanceServiceClient

	rawHTTPClient *http.Client // plain TLS-trusting client for MCP/A2A HTTP-level checks

	goodToken      string // valid tenant + "conformance:invoke" scope
	noTenantToken  string // valid scope, no tenant claim
	tlsCfgForLanes *tls.Config
}

func waitForAddr(t *testing.T, srv *server.Server, protocol string) string {
	t.Helper()
	deadline := time.Now().Add(2 * time.Second)
	for time.Now().Before(deadline) {
		if addr := srv.ListenAddr(protocol); addr != "" {
			return addr
		}
		time.Sleep(5 * time.Millisecond)
	}
	t.Fatalf("timed out waiting for %s listener address", protocol)
	return ""
}

func certPoolFromTLSConfig(t *testing.T, cfg *tls.Config) *x509.CertPool {
	t.Helper()
	if len(cfg.Certificates) == 0 || len(cfg.Certificates[0].Certificate) == 0 {
		t.Fatal("tls.Config has no certificates")
	}
	cert, err := x509.ParseCertificate(cfg.Certificates[0].Certificate[0])
	if err != nil {
		t.Fatalf("parsing certificate: %v", err)
	}
	pool := x509.NewCertPool()
	pool.AddCert(cert)
	return pool
}

// setupEnv builds the single full-stack server this whole test file drives:
// SelfSignedTLSConfig, both lanes on distinct 127.0.0.1 ports,
// MaxMessageBytes = 4<<20, and the canonical interceptor chain —
// DefaultInterceptors + the protovalidate validation interceptor +
// auth.Interceptors — applied via HandlerOptions() to every registered
// service, exactly as production wiring is documented to do.
func setupEnv(t *testing.T) *testEnv {
	t.Helper()

	tlsCfg, err := server.SelfSignedTLSConfig()
	if err != nil {
		t.Fatalf("SelfSignedTLSConfig: %v", err)
	}
	pool := certPoolFromTLSConfig(t, tlsCfg)

	logger := zap.NewNop()

	cfg := server.Config{
		H2Addr:          "127.0.0.1:0",
		H3Addr:          "127.0.0.1:0",
		H2Enabled:       true,
		H3Enabled:       true,
		TLSConfig:       tlsCfg,
		GracePeriod:     2 * time.Second,
		MaxMessageBytes: 4 << 20,
	}

	validationInterceptor, err := server.NewValidationInterceptor()
	if err != nil {
		t.Fatalf("NewValidationInterceptor: %v", err)
	}

	enforcer := authz.NewRBACEnforcer()
	authCfg := auth.Config{
		Mode:     auth.ModeOIDC,
		OIDC:     testFixture.rp,
		Enforcer: enforcer,
		// Only Unary is scope-gated; a token needs "conformance:invoke" plus
		// a tenant claim to call it.
		Scopes: middleware.ProcedureScopes{
			conformancev1connect.ConformanceServiceUnaryProcedure: {"conformance:invoke"},
		},
		// ServerStream/ClientStream/BidiStream are Public because the deny-
		// by-default gate fails closed on every non-public streaming
		// procedure unconditionally (go-aaa cannot authorize streaming yet —
		// T4 follow-up, see auth/doc.go's "Streaming RPCs" section). Health
		// is Public too: a liveness/readiness endpoint that itself requires
		// auth to determine service health is a common anti-pattern.
		Public: []string{
			conformancev1connect.ConformanceServiceServerStreamProcedure,
			conformancev1connect.ConformanceServiceClientStreamProcedure,
			conformancev1connect.ConformanceServiceBidiStreamProcedure,
			healthv1connect.HealthServiceCheckProcedure,
			healthv1connect.HealthServiceWatchProcedure,
		},
	}
	authInterceptors, err := auth.Interceptors(authCfg)
	if err != nil {
		t.Fatalf("auth.Interceptors: %v", err)
	}

	interceptors := append([]connect.Interceptor{}, server.DefaultInterceptors(logger, cfg)...)
	interceptors = append(interceptors, validationInterceptor)
	interceptors = append(interceptors, authInterceptors...)
	cfg.Interceptors = interceptors

	srv, err := server.New(cfg, logger)
	if err != nil {
		t.Fatalf("server.New: %v", err)
	}

	mux := srv.Mux()
	conformance.Register(mux, srv.HandlerOptions()...)
	checker := health.NewChecker()
	health.Register(mux, checker, srv.HandlerOptions()...)

	// --- MCP: sub-mux + auth.HTTPMiddleware wrap, registered on the main
	// mux at mcp.Path. mcp.Mount only accepts a *http.ServeMux and installs
	// its own handler directly on it, so there is no raw-handler accessor
	// to wrap individually — mounting on a dedicated sub-mux first and then
	// wrapping THAT (registered on the main mux at the identical path) is
	// the documented workaround (see mcp/doc.go's usage sketch) and
	// requires no API change.
	mcpServer := mcpsdk.NewServer(&mcpsdk.Implementation{Name: "go-rpc-integration-test", Version: "v0.0.1"}, nil)
	mcpSubMux := http.NewServeMux()
	if err := mcp.Mount(mcpSubMux, mcpServer); err != nil {
		t.Fatalf("mcp.Mount: %v", err)
	}
	mcpAuthMW, err := auth.HTTPMiddleware(auth.HTTPConfig{Mode: auth.ModeOIDC, OIDC: testFixture.rp})
	if err != nil {
		t.Fatalf("auth.HTTPMiddleware (mcp): %v", err)
	}
	mux.Handle(mcp.Path, mcpAuthMW(mcpSubMux))

	// --- A2A: agent card stays public (Mount registers it directly,
	// unwrapped); the JSON-RPC handler is pre-wrapped with
	// auth.HTTPMiddleware before being handed to Mount, per a2a/doc.go's
	// usage sketch and progress.md's T9 note ("MountAgent has no wrappable
	// seam — use Mount + pre-wrapped handler for auth").
	cardBytes, err := json.Marshal(&a2asdk.AgentCard{Name: "go-rpc-integration-test-agent"})
	if err != nil {
		t.Fatalf("marshal agent card: %v", err)
	}
	a2aAuthMW, err := auth.HTTPMiddleware(auth.HTTPConfig{Mode: auth.ModeOIDC, OIDC: testFixture.rp})
	if err != nil {
		t.Fatalf("auth.HTTPMiddleware (a2a): %v", err)
	}
	a2aStub := http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		w.WriteHeader(http.StatusOK)
	})
	if err := a2a.Mount(mux, cardBytes, a2aAuthMW(a2aStub)); err != nil {
		t.Fatalf("a2a.Mount: %v", err)
	}

	ctx, cancel := context.WithCancel(context.Background())
	startDone := make(chan error, 1)
	go func() { startDone <- srv.Start(ctx) }()
	t.Cleanup(func() {
		cancel()
		select {
		case err := <-startDone:
			if err != nil {
				t.Errorf("server Start returned error: %v", err)
			}
		case <-time.After(5 * time.Second):
			t.Error("server did not shut down in time")
		}
	})

	h2Addr := waitForAddr(t, srv, "h2")
	h3Addr := waitForAddr(t, srv, "h3")

	// Distinct ports are required for the H3-down fallback scenario below,
	// which relies on the H2 address having no UDP/QUIC listener bound at
	// its port number. net.Listen("tcp", "127.0.0.1:0") and
	// net.ListenPacket("udp", "127.0.0.1:0") are independent ephemeral-port
	// allocations, so a numeric collision is possible in principle though
	// vanishingly unlikely in practice (mirroring client_integration_test's
	// own accepted-TOCTOU-race tolerance for test-only port allocation);
	// fail fast with a clear message rather than silently passing a
	// scenario that didn't actually test what it claims to.
	_, h2Port, err := net.SplitHostPort(h2Addr)
	if err != nil {
		t.Fatalf("splitting h2Addr %q: %v", h2Addr, err)
	}
	_, h3Port, err := net.SplitHostPort(h3Addr)
	if err != nil {
		t.Fatalf("splitting h3Addr %q: %v", h3Addr, err)
	}
	if h2Port == h3Port {
		t.Fatalf("h2Addr and h3Addr coincidentally share port %s; H3-down fallback scenario requires distinct ports", h2Port)
	}

	tlsClientCfg := &tls.Config{RootCAs: pool}

	h3Client, err := client.New(client.Config{
		BaseURL:   "https://" + h3Addr,
		TLSConfig: tlsClientCfg.Clone(),
		Lanes:     []client.Lane{client.LaneH3},
	}, zap.NewNop())
	if err != nil {
		t.Fatalf("client.New (h3): %v", err)
	}
	t.Cleanup(func() { _ = h3Client.Close() })

	h2Client, err := client.New(client.Config{
		BaseURL:   "https://" + h2Addr,
		TLSConfig: tlsClientCfg.Clone(),
		Lanes:     []client.Lane{client.LaneH2},
	}, zap.NewNop())
	if err != nil {
		t.Fatalf("client.New (h2): %v", err)
	}
	t.Cleanup(func() { _ = h2Client.Close() })

	rawHTTPClient := &http.Client{
		Transport: &http.Transport{TLSClientConfig: tlsClientCfg.Clone()},
		Timeout:   10 * time.Second,
	}

	return &testEnv{
		pool:           pool,
		h2Addr:         h2Addr,
		h3Addr:         h3Addr,
		h3Conformance:  conformancev1connect.NewConformanceServiceClient(h3Client.HTTPClient(), "https://"+h3Addr),
		h2Conformance:  conformancev1connect.NewConformanceServiceClient(h2Client.HTTPClient(), "https://"+h2Addr),
		rawHTTPClient:  rawHTTPClient,
		goodToken:      testFixture.token(t, "user-1", []string{"conformance:invoke"}, "tenant-a"),
		noTenantToken:  testFixture.token(t, "user-1", []string{"conformance:invoke"}, ""),
		tlsCfgForLanes: tlsClientCfg,
	}
}

// --- laneCase: shared table for the matrix + auth-deny subtests --------

type laneCase struct {
	name         string
	rpcClient    conformancev1connect.ConformanceServiceClient
	wantProtocol string
}

func (env *testEnv) laneCases() []laneCase {
	return []laneCase{
		{name: "h3", rpcClient: env.h3Conformance, wantProtocol: "h3"},
		{name: "h2", rpcClient: env.h2Conformance, wantProtocol: "h2"},
	}
}

// --- TestIntegration: the whole matrix + scenario suite -----------------

func TestIntegration(t *testing.T) {
	env := setupEnv(t)

	// --- 1. Matrix: {H3, H2} x {Unary, ServerStream, ClientStream,
	// BidiStream} against conformance; EchoResponse.protocol must match the
	// lane that actually served the request. Unary is scope-gated, so it
	// carries the valid, properly-scoped, tenanted token. The three
	// streaming patterns are Public (see setupEnv's auth.Config comment),
	// so they are deliberately called with ZERO credentials — this proves,
	// over real sockets and both real transports, that the Public
	// declaration actually bypasses the chain end-to-end, not just in the
	// httptest-based unit coverage auth/auth_test.go already has.
	for _, lc := range env.laneCases() {
		t.Run("Matrix/"+lc.name+"/Unary", func(t *testing.T) {
			req := connect.NewRequest(&conformancev1.EchoRequest{Message: "hello"})
			req.Header().Set("Authorization", "Bearer "+env.goodToken)
			resp, err := lc.rpcClient.Unary(context.Background(), req)
			if err != nil {
				t.Fatalf("Unary: %v", err)
			}
			if resp.Msg.GetMessage() != "hello" {
				t.Errorf("Message = %q, want %q", resp.Msg.GetMessage(), "hello")
			}
			if resp.Msg.GetProtocol() != lc.wantProtocol {
				t.Errorf("Protocol = %q, want %q", resp.Msg.GetProtocol(), lc.wantProtocol)
			}
		})

		t.Run("Matrix/"+lc.name+"/ServerStream", func(t *testing.T) {
			req := connect.NewRequest(&conformancev1.EchoRequest{Message: "ss", Repeat: 3})
			stream, err := lc.rpcClient.ServerStream(context.Background(), req)
			if err != nil {
				t.Fatalf("ServerStream: %v", err)
			}
			count := 0
			for stream.Receive() {
				count++
				if stream.Msg().GetMessage() != "ss" {
					t.Errorf("message #%d = %q, want %q", count, stream.Msg().GetMessage(), "ss")
				}
				if stream.Msg().GetProtocol() != lc.wantProtocol {
					t.Errorf("message #%d protocol = %q, want %q", count, stream.Msg().GetProtocol(), lc.wantProtocol)
				}
			}
			if err := stream.Err(); err != nil {
				t.Fatalf("stream.Err(): %v", err)
			}
			if count != 3 {
				t.Errorf("received %d messages, want 3", count)
			}
		})

		t.Run("Matrix/"+lc.name+"/ClientStream", func(t *testing.T) {
			stream := lc.rpcClient.ClientStream(context.Background())
			if err := stream.Send(&conformancev1.EchoRequest{Message: "a"}); err != nil {
				t.Fatalf("Send(a): %v", err)
			}
			if err := stream.Send(&conformancev1.EchoRequest{Message: "b"}); err != nil {
				t.Fatalf("Send(b): %v", err)
			}
			resp, err := stream.CloseAndReceive()
			if err != nil {
				t.Fatalf("CloseAndReceive: %v", err)
			}
			if resp.Msg.GetMessage() != "ab" {
				t.Errorf("Message = %q, want %q", resp.Msg.GetMessage(), "ab")
			}
			if resp.Msg.GetProtocol() != lc.wantProtocol {
				t.Errorf("Protocol = %q, want %q", resp.Msg.GetProtocol(), lc.wantProtocol)
			}
		})

		t.Run("Matrix/"+lc.name+"/BidiStream", func(t *testing.T) {
			stream := lc.rpcClient.BidiStream(context.Background())
			sendErrs := make(chan error, 1)
			go func() {
				defer close(sendErrs)
				if err := stream.Send(&conformancev1.EchoRequest{Message: "x"}); err != nil {
					sendErrs <- err
					return
				}
				if err := stream.Send(&conformancev1.EchoRequest{Message: "y"}); err != nil {
					sendErrs <- err
					return
				}
				sendErrs <- stream.CloseRequest()
			}()

			var got []string
			for i := 0; i < 2; i++ {
				resp, err := stream.Receive()
				if err != nil {
					t.Fatalf("Receive #%d: %v", i, err)
				}
				got = append(got, resp.GetMessage())
				if resp.GetProtocol() != lc.wantProtocol {
					t.Errorf("message #%d protocol = %q, want %q", i, resp.GetProtocol(), lc.wantProtocol)
				}
			}
			_ = stream.CloseResponse()
			if err := <-sendErrs; err != nil {
				t.Fatalf("send goroutine: %v", err)
			}
			if got[0] != "x" || got[1] != "y" {
				t.Errorf("got %v, want [x y]", got)
			}
		})
	}

	// --- 2. Auth deny (missing tenant) over BOTH lanes, plus the positive
	// control. This is the concrete, real-socket proof that the interceptor
	// chain built by auth.Interceptors is actually threaded through
	// HandlerOptions() into the real server (closing the T2 "HandlerOptions
	// threading" deferral) and that the deny path is reachable on a real
	// request, not just in the httptest-composed chain auth/auth_test.go
	// already covers (closing the T4 "integration deny-on-real-path"
	// deferral).
	for _, lc := range env.laneCases() {
		t.Run("AuthDeny/MissingTenant/"+lc.name, func(t *testing.T) {
			req := connect.NewRequest(&conformancev1.EchoRequest{Message: "denied"})
			req.Header().Set("Authorization", "Bearer "+env.noTenantToken)
			_, err := lc.rpcClient.Unary(context.Background(), req)
			if err == nil {
				t.Fatal("expected denial for a token with no tenant claim")
			}
			if connect.CodeOf(err) != connect.CodePermissionDenied {
				t.Errorf("code = %v, want CodePermissionDenied (err: %v)", connect.CodeOf(err), err)
			}
			if !strings.Contains(err.Error(), "missing tenant claim") {
				t.Errorf("expected the tenant interceptor's denial message, got: %v", err)
			}
		})

		t.Run("AuthDeny/PositiveControl/"+lc.name, func(t *testing.T) {
			req := connect.NewRequest(&conformancev1.EchoRequest{Message: "ok"})
			req.Header().Set("Authorization", "Bearer "+env.goodToken)
			resp, err := lc.rpcClient.Unary(context.Background(), req)
			if err != nil {
				t.Fatalf("expected success for a properly-scoped, tenanted token, got: %v", err)
			}
			if resp.Msg.GetProtocol() != lc.wantProtocol {
				t.Errorf("Protocol = %q, want %q", resp.Msg.GetProtocol(), lc.wantProtocol)
			}
		})
	}

	// --- 3. Oversized message rejected (ReadMaxBytes / MaxMessageBytes).
	// connect-go enforces ReadMaxBytes while unmarshaling the request body,
	// inside NewUnaryHandler's `implementation` closure, BEFORE the
	// interceptor chain (including auth) is ever invoked — verified by
	// reading connectrpc.com/connect@v1.20.0 handler.go and
	// compression.go/envelope.go, whose read-limit violation path returns
	// connect.CodeResourceExhausted ("message size %d is larger than
	// configured max %d"). A 5 MiB message exceeds MaxMessageBytes (4 MiB)
	// by construction; requests are sent uncompressed by default (per the
	// generated client's own doc comment), so the wire size is not
	// shrunk by compression before the limit check runs.
	t.Run("OversizedMessage_Rejected", func(t *testing.T) {
		big := strings.Repeat("A", 5*1024*1024)
		req := connect.NewRequest(&conformancev1.EchoRequest{Message: big})
		req.Header().Set("Authorization", "Bearer "+env.goodToken)
		_, err := env.h2Conformance.Unary(context.Background(), req)
		if err == nil {
			t.Fatal("expected rejection for a message exceeding MaxMessageBytes")
		}
		if connect.CodeOf(err) != connect.CodeResourceExhausted {
			t.Errorf("code = %v, want CodeResourceExhausted (err: %v)", connect.CodeOf(err), err)
		}
	})

	// --- 4. protovalidate violation over the wire. EchoRequest.message has
	// a buf.validate `min_len: 1` constraint (proto/prpc/conformance/v1/
	// conformance.proto); an empty message violates it. The validation
	// interceptor sits outside (before) the auth chain in the configured
	// order (DefaultInterceptors + validate + auth.Interceptors), and the
	// request carries a fully valid, correctly-scoped, tenanted token, so a
	// CodeInvalidArgument result can only originate from the validation
	// interceptor — never from auth, which would grant this exact token.
	t.Run("ProtovalidateViolation_InvalidArgument", func(t *testing.T) {
		req := connect.NewRequest(&conformancev1.EchoRequest{Message: ""})
		req.Header().Set("Authorization", "Bearer "+env.goodToken)
		_, err := env.h2Conformance.Unary(context.Background(), req)
		if err == nil {
			t.Fatal("expected a protovalidate violation for an empty message")
		}
		if connect.CodeOf(err) != connect.CodeInvalidArgument {
			t.Errorf("code = %v, want CodeInvalidArgument (err: %v)", connect.CodeOf(err), err)
		}
	})

	// --- 5. MCP/A2A: auth.HTTPMiddleware actually protects a real mount
	// site (T9's ⚠️ HARD T10 REQ). Anonymous requests to /mcp and /a2a's
	// JSON-RPC endpoint must be rejected before either handler runs; a
	// valid bearer token must reach them. The agent card stays public
	// discovery regardless.
	t.Run("MCP_A2A_HTTPMiddleware_Wiring", func(t *testing.T) {
		base := "https://" + env.h2Addr

		t.Run("MCP/Anonymous_401", func(t *testing.T) {
			resp := doMCPRequest(t, env, base, "")
			defer resp.Body.Close()
			t.Logf("anonymous POST %s -> %d", mcp.Path, resp.StatusCode)
			if resp.StatusCode != http.StatusUnauthorized {
				t.Errorf("anonymous POST %s = %d, want 401", mcp.Path, resp.StatusCode)
			}
		})

		t.Run("MCP/Authenticated_ReachesHandler", func(t *testing.T) {
			resp := doMCPRequest(t, env, base, env.goodToken)
			defer resp.Body.Close()
			t.Logf("authenticated POST %s -> %d", mcp.Path, resp.StatusCode)
			if resp.StatusCode == http.StatusUnauthorized {
				t.Errorf("authenticated POST %s = 401, want any non-401 status (proof the request reached the MCP handler, not auth.HTTPMiddleware's rejection)", mcp.Path)
			}
		})

		t.Run("A2A/AgentCard_PublicWithZeroCredentials", func(t *testing.T) {
			resp, err := env.rawHTTPClient.Get(base + a2a.WellKnownAgentCardPath)
			if err != nil {
				t.Fatalf("GET agent card: %v", err)
			}
			defer resp.Body.Close()
			if resp.StatusCode != http.StatusOK {
				t.Errorf("GET %s = %d, want 200 (agent card must stay public discovery)", a2a.WellKnownAgentCardPath, resp.StatusCode)
			}
		})

		t.Run("A2A/JSONRPC_Anonymous_401", func(t *testing.T) {
			resp, err := env.rawHTTPClient.Post(base+a2a.JSONRPCPath, "application/json", strings.NewReader(`{}`))
			if err != nil {
				t.Fatalf("POST %s: %v", a2a.JSONRPCPath, err)
			}
			defer resp.Body.Close()
			if resp.StatusCode != http.StatusUnauthorized {
				t.Errorf("anonymous POST %s = %d, want 401", a2a.JSONRPCPath, resp.StatusCode)
			}
		})

		t.Run("A2A/JSONRPC_Authenticated_ReachesHandler", func(t *testing.T) {
			req, err := http.NewRequest(http.MethodPost, base+a2a.JSONRPCPath, strings.NewReader(`{}`))
			if err != nil {
				t.Fatalf("building request: %v", err)
			}
			req.Header.Set("Content-Type", "application/json")
			req.Header.Set("Authorization", "Bearer "+env.goodToken)
			resp, err := env.rawHTTPClient.Do(req)
			if err != nil {
				t.Fatalf("POST %s: %v", a2a.JSONRPCPath, err)
			}
			defer resp.Body.Close()
			if resp.StatusCode != http.StatusOK {
				t.Errorf("authenticated POST %s = %d, want 200 (the stub handler behind auth.HTTPMiddleware)", a2a.JSONRPCPath, resp.StatusCode)
			}
		})
	})

	// --- 6. H3-down fallback. Config.BaseURL supplies ONE authority shared
	// by every lane absent an Alt-Svc-driven override (client/options.go's
	// Config.Lanes doc), and this server never advertises Alt-Svc, so a
	// client pointed at env.h2Addr with the default H3-then-H2 preference
	// has its H3 (QUIC/UDP) dial attempt land on a port with no UDP
	// listener bound — the real H3 listener is at the DIFFERENT h3Addr
	// port. That dial fails exactly like a genuinely "down" H3 listener
	// would (satisfying the brief's own "(or point H3 at a dead UDP port)"
	// alternative to physically tearing down a listener, which the Server
	// API has no way to do independently of the other lane anyway), and
	// laneRouter transparently fails over to H2 within the same call.
	t.Run("H3Down_FallsBackToH2", func(t *testing.T) {
		fallbackClient, err := client.New(client.Config{
			BaseURL:     "https://" + env.h2Addr,
			TLSConfig:   env.tlsCfgForLanes.Clone(),
			Lanes:       []client.Lane{client.LaneH3, client.LaneH2},
			DialTimeout: time.Second, // bound the doomed H3/QUIC dial attempt
		}, zap.NewNop())
		if err != nil {
			t.Fatalf("client.New (fallback): %v", err)
		}
		defer func() { _ = fallbackClient.Close() }()

		fallbackConformance := conformancev1connect.NewConformanceServiceClient(fallbackClient.HTTPClient(), "https://"+env.h2Addr)

		req := connect.NewRequest(&conformancev1.EchoRequest{Message: "fallback"})
		req.Header().Set("Authorization", "Bearer "+env.goodToken)
		resp, err := fallbackConformance.Unary(context.Background(), req)
		if err != nil {
			t.Fatalf("expected transparent fallback to H2, got error: %v", err)
		}
		if resp.Msg.GetProtocol() != "h2" {
			t.Errorf("Protocol = %q, want %q (H3 unreachable at this address, must fall back to H2)", resp.Msg.GetProtocol(), "h2")
		}
		if fallbackClient.Protocol() != "h2" {
			t.Errorf("Client.Protocol() = %q, want %q", fallbackClient.Protocol(), "h2")
		}
	})

	// --- Bonus: health is registered and reachable with zero credentials
	// (Public), confirming the full-stack wiring registered a second real
	// service correctly, not just conformance.
	t.Run("HealthCheck_PublicSmokeTest", func(t *testing.T) {
		healthClient := healthv1connect.NewHealthServiceClient(env.rawHTTPClient, "https://"+env.h2Addr)
		resp, err := healthClient.Check(context.Background(), connect.NewRequest(&healthv1.CheckRequest{}))
		if err != nil {
			t.Fatalf("Check (zero credentials, public procedure): %v", err)
		}
		if resp.Msg.GetStatus() != healthv1.ServingStatus_SERVING_STATUS_SERVING {
			t.Errorf("Status = %v, want SERVING_STATUS_SERVING", resp.Msg.GetStatus())
		}
	})
}

// doMCPRequest issues a POST to the mounted /mcp endpoint with an
// initialize-shaped JSON-RPC body and the correct Streamable HTTP headers,
// optionally carrying an Authorization bearer header when token is
// non-empty. The MCP go-sdk's own ServeHTTP (streamable.go) never writes
// StatusUnauthorized/StatusForbidden itself for a server-side request (those
// codes only appear in its OAuth CLIENT code path) — so any non-401 result
// here is conclusive proof the request passed auth.HTTPMiddleware and
// reached the SDK handler.
func doMCPRequest(t *testing.T, env *testEnv, base, token string) *http.Response {
	t.Helper()
	body := `{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-06-18","capabilities":{},"clientInfo":{"name":"integration-test","version":"1.0"}}}`
	req, err := http.NewRequest(http.MethodPost, base+mcp.Path, strings.NewReader(body))
	if err != nil {
		t.Fatalf("building MCP request: %v", err)
	}
	req.Header.Set("Content-Type", "application/json")
	req.Header.Set("Accept", "application/json, text/event-stream")
	if token != "" {
		req.Header.Set("Authorization", "Bearer "+token)
	}
	resp, err := env.rawHTTPClient.Do(req)
	if err != nil {
		t.Fatalf("POST %s: %v", mcp.Path, err)
	}
	return resp
}
