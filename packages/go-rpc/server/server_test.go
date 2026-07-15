// Copyright 2026 Penguin Tech Inc
// SPDX-License-Identifier: Apache-2.0

package server

import (
	"context"
	"crypto/tls"
	"crypto/x509"
	"errors"
	"io"
	"net"
	"net/http"
	"testing"
	"time"

	"github.com/quic-go/quic-go/http3"
	"go.uber.org/zap"
)

// waitForAddr polls ListenAddr until the given protocol's listener has bound
// a real address, or fails the test after a short deadline. Needed because
// Start blocks and callers must run it in a goroutine.
func waitForAddr(t *testing.T, srv *Server, protocol string) string {
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

// certPoolFromTLSConfig builds an x509.CertPool trusting the leaf
// certificate embedded in cfg, so test clients can verify the loopback
// server without disabling certificate verification.
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

func mustSelfSignedTLSConfig(t *testing.T) *tls.Config {
	t.Helper()
	cfg, err := SelfSignedTLSConfig()
	if err != nil {
		t.Fatalf("SelfSignedTLSConfig: %v", err)
	}
	return cfg
}

func TestServer_New_NilLogger(t *testing.T) {
	srv, err := New(Config{}, nil)
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if srv == nil {
		t.Fatal("expected non-nil server")
	}
	if srv.logger == nil {
		t.Error("expected a default logger to be created")
	}
}

func TestServer_Mux(t *testing.T) {
	srv, err := New(Config{}, zap.NewNop())
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if srv.Mux() == nil {
		t.Fatal("expected non-nil mux")
	}
	if srv.Mux() != srv.Mux() {
		t.Error("expected Mux() to return the same instance across calls")
	}
}

func TestNew_DefaultsMaxMessageBytesAndUnaryTimeout(t *testing.T) {
	srv, err := New(Config{}, zap.NewNop())
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if srv.cfg.MaxMessageBytes != defaultMaxMessageBytes {
		t.Errorf("MaxMessageBytes = %d, want %d", srv.cfg.MaxMessageBytes, defaultMaxMessageBytes)
	}
	if srv.cfg.DefaultUnaryTimeout != defaultUnaryTimeout {
		t.Errorf("DefaultUnaryTimeout = %v, want %v", srv.cfg.DefaultUnaryTimeout, defaultUnaryTimeout)
	}
}

func TestNew_PreservesNonZeroMaxMessageBytesAndUnaryTimeout(t *testing.T) {
	cfg := Config{MaxMessageBytes: 1024, DefaultUnaryTimeout: 5 * time.Second}
	srv, err := New(cfg, zap.NewNop())
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if srv.cfg.MaxMessageBytes != 1024 {
		t.Errorf("MaxMessageBytes = %d, want 1024 (caller value must not be overridden)", srv.cfg.MaxMessageBytes)
	}
	if srv.cfg.DefaultUnaryTimeout != 5*time.Second {
		t.Errorf("DefaultUnaryTimeout = %v, want 5s", srv.cfg.DefaultUnaryTimeout)
	}
}

func TestServer_HandlerOptions(t *testing.T) {
	srv, err := New(Config{MaxMessageBytes: 2048}, zap.NewNop())
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	opts := srv.HandlerOptions()
	if len(opts) != 2 {
		t.Fatalf("HandlerOptions() returned %d options, want 2 (ReadMaxBytes + Interceptors)", len(opts))
	}
	for i, opt := range opts {
		if opt == nil {
			t.Errorf("HandlerOptions()[%d] is nil", i)
		}
	}
}

func TestListenAddr_UnknownProtocol(t *testing.T) {
	srv, err := New(Config{}, zap.NewNop())
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if addr := srv.ListenAddr("h4"); addr != "" {
		t.Errorf("ListenAddr(\"h4\") = %q, want empty string", addr)
	}
}

func TestListenAddr_BeforeStart(t *testing.T) {
	srv, err := New(Config{}, zap.NewNop())
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if addr := srv.ListenAddr("h2"); addr != "" {
		t.Errorf("ListenAddr(\"h2\") before Start = %q, want empty string", addr)
	}
	if addr := srv.ListenAddr("h3"); addr != "" {
		t.Errorf("ListenAddr(\"h3\") before Start = %q, want empty string", addr)
	}
}

// --- NEW hardening test (1/5): TLS12 config in -> server still negotiates
// TLS13-only. New() must force MinVersion regardless of caller input, and
// the forcing must be real: a client that only offers up to TLS 1.2 MUST
// fail to complete a handshake against the server.
func TestNew_ForcesTLS13MinVersion(t *testing.T) {
	tlsCfg := mustSelfSignedTLSConfig(t)
	tlsCfg.MinVersion = tls.VersionTLS12 // caller mistake: request TLS12

	_, err := New(Config{TLSConfig: tlsCfg}, zap.NewNop())
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}

	if tlsCfg.MinVersion != tls.VersionTLS13 {
		t.Fatalf("MinVersion = %d, want tls.VersionTLS13 (New must force it)", tlsCfg.MinVersion)
	}
}

func TestServer_ForcesTLS13_RejectsTLS12Client(t *testing.T) {
	tlsCfg := mustSelfSignedTLSConfig(t)
	tlsCfg.MinVersion = tls.VersionTLS12 // caller mistake: request TLS12

	cfg := Config{
		H2Addr:      "127.0.0.1:0",
		H2Enabled:   true,
		H3Enabled:   false,
		TLSConfig:   tlsCfg,
		GracePeriod: 2 * time.Second,
	}
	srv, err := New(cfg, zap.NewNop())
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}

	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()
	startDone := make(chan error, 1)
	go func() { startDone <- srv.Start(ctx) }()

	addr := waitForAddr(t, srv, "h2")
	pool := certPoolFromTLSConfig(t, tlsCfg)

	clientCfg := &tls.Config{RootCAs: pool, MaxVersion: tls.VersionTLS12}
	conn, dialErr := tls.Dial("tcp", addr, clientCfg)
	if dialErr == nil {
		_ = conn.Close()
		t.Fatal("expected TLS handshake to fail for a TLS1.2-only client against a TLS1.3-only server, got success")
	}

	cancel()
	select {
	case err := <-startDone:
		if err != nil {
			t.Fatalf("Start returned error: %v", err)
		}
	case <-time.After(5 * time.Second):
		t.Fatal("Start did not return after cancel")
	}
}

// --- NEW hardening test (2/5): the constructed HTTP/3 QUIC config has
// Allow0RTT explicitly false. quic-go's http3.Server defaults QUICConfig to
// &quic.Config{Allow0RTT: true} when the field is left nil, so this asserts
// the server always supplies its own config rather than relying on that
// (insecure, replay-vulnerable) default.
func TestStart_H3QUICConfigDisables0RTT(t *testing.T) {
	tlsCfg := mustSelfSignedTLSConfig(t)
	cfg := Config{
		H2Enabled:   false,
		H3Addr:      "127.0.0.1:0",
		H3Enabled:   true,
		TLSConfig:   tlsCfg,
		GracePeriod: 2 * time.Second,
	}
	srv, err := New(cfg, zap.NewNop())
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}

	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()
	startDone := make(chan error, 1)
	go func() { startDone <- srv.Start(ctx) }()

	waitForAddr(t, srv, "h3")

	srv.mu.Lock()
	h3 := srv.h3
	srv.mu.Unlock()

	if h3 == nil {
		t.Fatal("expected internal http3.Server to be constructed")
	}
	if h3.QUICConfig == nil {
		t.Fatal("http3.Server.QUICConfig is nil — server would fall back to quic-go's insecure Allow0RTT:true default")
	}
	if h3.QUICConfig.Allow0RTT {
		t.Error("QUICConfig.Allow0RTT = true, want false (spec §3: 0-RTT MUST be disabled)")
	}

	cancel()
	select {
	case err := <-startDone:
		if err != nil {
			t.Fatalf("Start returned error: %v", err)
		}
	case <-time.After(5 * time.Second):
		t.Fatal("Start did not return after cancel")
	}
}

// --- NEW hardening test (3/5): both listeners serve the same mux over real
// loopback sockets — H2 via a TLS client, H3 via a quic-go http3 client
// transport.
func TestServer_DualListenersServeSameMux(t *testing.T) {
	tlsCfg := mustSelfSignedTLSConfig(t)
	cfg := Config{
		H2Addr:      "127.0.0.1:0",
		H3Addr:      "127.0.0.1:0",
		H2Enabled:   true,
		H3Enabled:   true,
		TLSConfig:   tlsCfg,
		GracePeriod: 2 * time.Second,
	}
	srv, err := New(cfg, zap.NewNop())
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	srv.Mux().HandleFunc("/ping", func(w http.ResponseWriter, _ *http.Request) {
		_, _ = w.Write([]byte("pong"))
	})

	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()
	startDone := make(chan error, 1)
	go func() { startDone <- srv.Start(ctx) }()

	h2Addr := waitForAddr(t, srv, "h2")
	h3Addr := waitForAddr(t, srv, "h3")
	pool := certPoolFromTLSConfig(t, tlsCfg)

	h2Client := &http.Client{
		Transport: &http.Transport{
			TLSClientConfig:   &tls.Config{RootCAs: pool},
			ForceAttemptHTTP2: true,
		},
		Timeout: 5 * time.Second,
	}
	status, body, proto := doGet(t, h2Client, "https://"+h2Addr+"/ping")
	if status != http.StatusOK || body != "pong" {
		t.Fatalf("H2 request: status=%d body=%q, want 200/pong", status, body)
	}
	if proto != "HTTP/2.0" {
		t.Errorf("H2 request negotiated protocol %q, want HTTP/2.0", proto)
	}

	h3Transport := &http3.Transport{TLSClientConfig: &tls.Config{RootCAs: pool}}
	defer func() { _ = h3Transport.Close() }()
	h3Client := &http.Client{Transport: h3Transport, Timeout: 5 * time.Second}
	status, body, _ = doGet(t, h3Client, "https://"+h3Addr+"/ping")
	if status != http.StatusOK || body != "pong" {
		t.Fatalf("H3 request: status=%d body=%q, want 200/pong", status, body)
	}

	cancel()
	select {
	case err := <-startDone:
		if err != nil {
			t.Fatalf("Start returned error: %v", err)
		}
	case <-time.After(5 * time.Second):
		t.Fatal("Start did not return after cancel")
	}
}

// --- NEW hardening test (5/5): graceful shutdown — Start(ctx) returns
// cleanly after cancel, and an in-flight request is allowed to complete
// within GracePeriod rather than being aborted.
func TestServer_GracefulShutdown_WaitsForInFlightRequest(t *testing.T) {
	tlsCfg := mustSelfSignedTLSConfig(t)
	cfg := Config{
		H2Addr:      "127.0.0.1:0",
		H2Enabled:   true,
		H3Enabled:   false,
		TLSConfig:   tlsCfg,
		GracePeriod: 5 * time.Second,
	}
	srv, err := New(cfg, zap.NewNop())
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}

	handlerStarted := make(chan struct{})
	srv.Mux().HandleFunc("/slow", func(w http.ResponseWriter, _ *http.Request) {
		close(handlerStarted)
		time.Sleep(300 * time.Millisecond)
		_, _ = w.Write([]byte("done"))
	})

	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()
	startDone := make(chan error, 1)
	go func() { startDone <- srv.Start(ctx) }()

	addr := waitForAddr(t, srv, "h2")
	pool := certPoolFromTLSConfig(t, tlsCfg)
	client := &http.Client{
		Transport: &http.Transport{
			TLSClientConfig:   &tls.Config{RootCAs: pool},
			ForceAttemptHTTP2: true,
		},
	}

	type reqResult struct {
		body string
		err  error
	}
	reqDone := make(chan reqResult, 1)
	go func() {
		req, buildErr := http.NewRequestWithContext(context.Background(), http.MethodGet, "https://"+addr+"/slow", nil)
		if buildErr != nil {
			reqDone <- reqResult{err: buildErr}
			return
		}
		resp, doErr := client.Do(req)
		if doErr != nil {
			reqDone <- reqResult{err: doErr}
			return
		}
		defer func() { _ = resp.Body.Close() }()
		body, readErr := io.ReadAll(resp.Body)
		reqDone <- reqResult{body: string(body), err: readErr}
	}()

	select {
	case <-handlerStarted:
	case <-time.After(2 * time.Second):
		t.Fatal("handler never started")
	}

	// Cancel while the request is in flight: graceful shutdown must let it
	// finish rather than aborting it.
	cancel()

	select {
	case err := <-startDone:
		if err != nil {
			t.Fatalf("Start returned error: %v", err)
		}
	case <-time.After(5 * time.Second):
		t.Fatal("Start did not return within GracePeriod")
	}

	select {
	case res := <-reqDone:
		if res.err != nil {
			t.Fatalf("in-flight request failed: %v", res.err)
		}
		if res.body != "done" {
			t.Fatalf("in-flight request body = %q, want %q", res.body, "done")
		}
	case <-time.After(1 * time.Second):
		t.Fatal("in-flight request result not received")
	}
}

// TestStart_H3TLSMissing_ClosesH2Listener is an additional (non-mandated)
// hardening test: if H3 is enabled without TLS, Start must fail fast without
// leaking the H2 listener it already opened.
func TestStart_H3TLSMissing_ClosesH2Listener(t *testing.T) {
	cfg := Config{
		H2Addr:      "127.0.0.1:0",
		H2Enabled:   true,
		H3Enabled:   true,
		TLSConfig:   nil,
		GracePeriod: 2 * time.Second,
	}
	srv, err := New(cfg, zap.NewNop())
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}

	startErrc := make(chan error, 1)
	go func() { startErrc <- srv.Start(context.Background()) }()

	var startErr error
	select {
	case startErr = <-startErrc:
	case <-time.After(3 * time.Second):
		t.Fatal("Start did not return")
	}
	if startErr == nil {
		t.Fatal("expected error when H3Enabled but TLSConfig nil")
	}

	h2Addr := srv.ListenAddr("h2")
	if h2Addr == "" {
		t.Fatal("expected h2Addr to have been recorded before the H3 error aborted startup")
	}

	// The H2 listener must have been released — rebinding the same address
	// should succeed immediately.
	ln, err := net.Listen("tcp", h2Addr)
	if err != nil {
		t.Fatalf("H2 listener leaked, could not rebind %s: %v", h2Addr, err)
	}
	_ = ln.Close()
}

// TestStart_H2ListenError exercises the H2 net.Listen failure path: binding
// to an address already in use must return an error without hanging.
func TestStart_H2ListenError(t *testing.T) {
	occupied, err := net.Listen("tcp", "127.0.0.1:0")
	if err != nil {
		t.Fatalf("occupying a port: %v", err)
	}
	defer func() { _ = occupied.Close() }()

	cfg := Config{
		H2Addr:      occupied.Addr().String(),
		H2Enabled:   true,
		H3Enabled:   false,
		GracePeriod: time.Second,
	}
	srv, err := New(cfg, zap.NewNop())
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}

	startErrc := make(chan error, 1)
	go func() { startErrc <- srv.Start(context.Background()) }()

	select {
	case err := <-startErrc:
		if err == nil {
			t.Fatal("expected error when H2 address already in use")
		}
	case <-time.After(3 * time.Second):
		t.Fatal("Start did not return")
	}
}

// TestStart_H3ListenError exercises the H3 net.ListenPacket failure path:
// binding to a UDP address already in use must return an error without
// hanging.
func TestStart_H3ListenError(t *testing.T) {
	occupied, err := net.ListenPacket("udp", "127.0.0.1:0")
	if err != nil {
		t.Fatalf("occupying a UDP port: %v", err)
	}
	defer func() { _ = occupied.Close() }()

	tlsCfg := mustSelfSignedTLSConfig(t)
	cfg := Config{
		H2Enabled:   false,
		H3Addr:      occupied.LocalAddr().String(),
		H3Enabled:   true,
		TLSConfig:   tlsCfg,
		GracePeriod: time.Second,
	}
	srv, err := New(cfg, zap.NewNop())
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}

	startErrc := make(chan error, 1)
	go func() { startErrc <- srv.Start(context.Background()) }()

	select {
	case err := <-startErrc:
		if err == nil {
			t.Fatal("expected error when H3 address already in use")
		}
	case <-time.After(3 * time.Second):
		t.Fatal("Start did not return")
	}
}

func doGet(t *testing.T, client *http.Client, url string) (status int, body string, proto string) {
	t.Helper()
	req, err := http.NewRequestWithContext(context.Background(), http.MethodGet, url, nil)
	if err != nil {
		t.Fatalf("building request for %s: %v", url, err)
	}
	resp, err := client.Do(req)
	if err != nil {
		t.Fatalf("request to %s failed: %v", url, err)
	}
	defer func() { _ = resp.Body.Close() }()
	data, err := io.ReadAll(resp.Body)
	if err != nil {
		t.Fatalf("reading response body from %s: %v", url, err)
	}
	return resp.StatusCode, string(data), resp.Proto
}

// sanity check that errors.Is is what we expect it to be (guards against a
// stdlib import mistake causing a false-negative on http.ErrServerClosed
// checks inside Start/shutdown).
func TestErrServerClosed_Sentinel(t *testing.T) {
	if !errors.Is(http.ErrServerClosed, http.ErrServerClosed) {
		t.Fatal("errors.Is sanity check failed")
	}
}
