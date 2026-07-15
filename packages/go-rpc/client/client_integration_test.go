// Copyright 2026 Penguin Tech Inc
// SPDX-License-Identifier: Apache-2.0

package client

import (
	"context"
	"crypto/tls"
	"crypto/x509"
	"fmt"
	"io"
	"net"
	"net/http"
	"testing"
	"time"

	"go.uber.org/goleak"
	"go.uber.org/zap"

	"github.com/penguintechinc/penguin-libs/packages/go-rpc/server"
)

// --- test helpers: real loopback H2+H3 servers via the go-rpc server
// package (Task 2), mirroring server_test.go's own helpers since those are
// unexported and this is a different package. ---

func mustSelfSignedTLSConfig(t *testing.T) *tls.Config {
	t.Helper()
	cfg, err := server.SelfSignedTLSConfig()
	if err != nil {
		t.Fatalf("SelfSignedTLSConfig: %v", err)
	}
	return cfg
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

// freeTCPPort allocates and immediately releases a TCP port, for tests that
// need H2 (TCP) and H3 (UDP) bound to the identical port number — the
// common real-world Alt-Svc-free deployment shape ("h3 lives on the same
// port number as h2, just a different socket family"). There's an
// inherent, accepted TOCTOU race between release and rebind.
func freeTCPPort(t *testing.T) int {
	t.Helper()
	ln, err := net.Listen("tcp", "127.0.0.1:0")
	if err != nil {
		t.Fatalf("allocating a free port: %v", err)
	}
	defer func() { _ = ln.Close() }()
	return ln.Addr().(*net.TCPAddr).Port
}

// startServer starts srv in a background goroutine and registers a cleanup
// that cancels it and waits for a clean shutdown.
func startServer(t *testing.T, cfg server.Config) *server.Server {
	t.Helper()
	srv, err := server.New(cfg, zap.NewNop())
	if err != nil {
		t.Fatalf("server.New: %v", err)
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
	return srv
}

func doGet(t *testing.T, c *Client, url string) (status int, body string) {
	t.Helper()
	req, err := http.NewRequestWithContext(context.Background(), http.MethodGet, url, nil)
	if err != nil {
		t.Fatalf("building request for %s: %v", url, err)
	}
	resp, err := c.HTTPClient().Do(req)
	if err != nil {
		t.Fatalf("request to %s failed (expected transparent lane failover, not a surfaced error): %v", url, err)
	}
	defer func() { _ = resp.Body.Close() }()
	data, err := io.ReadAll(resp.Body)
	if err != nil {
		t.Fatalf("reading response body from %s: %v", url, err)
	}
	return resp.StatusCode, string(data)
}

// --- TDD scenario 1: both lanes up -> H3 preferred. ---

func TestClient_BothLanesUp_PrefersH3(t *testing.T) {
	port := freeTCPPort(t)
	addr := fmt.Sprintf("127.0.0.1:%d", port)
	tlsCfg := mustSelfSignedTLSConfig(t)

	srv := startServer(t, server.Config{
		H2Addr: addr, H3Addr: addr, H2Enabled: true, H3Enabled: true,
		TLSConfig: tlsCfg, GracePeriod: 2 * time.Second,
	})
	srv.Mux().HandleFunc("/ping", func(w http.ResponseWriter, _ *http.Request) {
		_, _ = w.Write([]byte("pong"))
	})
	waitForAddr(t, srv, "h2")
	waitForAddr(t, srv, "h3")

	pool := certPoolFromTLSConfig(t, tlsCfg)
	c, err := New(Config{BaseURL: "https://" + addr, TLSConfig: &tls.Config{RootCAs: pool}}, zap.NewNop())
	if err != nil {
		t.Fatalf("New: %v", err)
	}
	defer func() { _ = c.Close() }()

	status, body := doGet(t, c, "https://"+addr+"/ping")
	if status != http.StatusOK || body != "pong" {
		t.Fatalf("status=%d body=%q, want 200/pong", status, body)
	}
	if c.Protocol() != "h3" {
		t.Errorf("Protocol() = %q, want h3", c.Protocol())
	}
}

// --- TDD scenario 2: H3 listener absent -> transparent H2 fallback. ---

func TestClient_H3ListenerAbsent_FallsBackToH2(t *testing.T) {
	tlsCfg := mustSelfSignedTLSConfig(t)
	srv := startServer(t, server.Config{
		H2Addr: "127.0.0.1:0", H2Enabled: true, H3Enabled: false,
		TLSConfig: tlsCfg, GracePeriod: 2 * time.Second,
	})
	srv.Mux().HandleFunc("/ping", func(w http.ResponseWriter, _ *http.Request) {
		_, _ = w.Write([]byte("pong"))
	})
	h2Addr := waitForAddr(t, srv, "h2")

	pool := certPoolFromTLSConfig(t, tlsCfg)
	c, err := New(Config{
		BaseURL:     "https://" + h2Addr,
		TLSConfig:   &tls.Config{RootCAs: pool},
		DialTimeout: time.Second, // bound the doomed H3 dial attempt
	}, zap.NewNop())
	if err != nil {
		t.Fatalf("New: %v", err)
	}
	defer func() { _ = c.Close() }()

	status, body := doGet(t, c, "https://"+h2Addr+"/ping")
	if status != http.StatusOK || body != "pong" {
		t.Fatalf("status=%d body=%q, want 200/pong (transparent fallback)", status, body)
	}
	if c.Protocol() != "h2" {
		t.Errorf("Protocol() = %q, want h2", c.Protocol())
	}
}

// --- TDD scenario 4: Alt-Svc hint on an H2 response promotes H3 for the
// NEXT request; the request that carried the hint is unaffected. ---

func TestClient_AltSvcUpgrade_PromotesH3ForFutureRequests(t *testing.T) {
	tlsCfg := mustSelfSignedTLSConfig(t)
	srv := startServer(t, server.Config{
		H2Addr: "127.0.0.1:0", H3Addr: "127.0.0.1:0", H2Enabled: true, H3Enabled: true,
		TLSConfig: tlsCfg, GracePeriod: 2 * time.Second,
	})
	h2Addr := waitForAddr(t, srv, "h2")
	h3Addr := waitForAddr(t, srv, "h3")
	_, h3Port, err := net.SplitHostPort(h3Addr)
	if err != nil {
		t.Fatalf("splitting h3 addr %q: %v", h3Addr, err)
	}
	srv.Mux().HandleFunc("/ping", func(w http.ResponseWriter, _ *http.Request) {
		w.Header().Set("Alt-Svc", fmt.Sprintf(`h3=":%s"; ma=3600`, h3Port))
		_, _ = w.Write([]byte("pong"))
	})

	pool := certPoolFromTLSConfig(t, tlsCfg)
	// Client only knows about the H2 lane up front — mirrors the brief's
	// "client on [LaneH2] order" TDD variant.
	c, err := New(Config{
		BaseURL:       "https://" + h2Addr,
		TLSConfig:     &tls.Config{RootCAs: pool},
		Lanes:         []Lane{LaneH2},
		AltSvcUpgrade: true,
	}, zap.NewNop())
	if err != nil {
		t.Fatalf("New: %v", err)
	}
	defer func() { _ = c.Close() }()

	status, body := doGet(t, c, "https://"+h2Addr+"/ping")
	if status != http.StatusOK || body != "pong" {
		t.Fatalf("first request: status=%d body=%q, want 200/pong", status, body)
	}
	if c.Protocol() != "h2" {
		t.Fatalf("Protocol() after first request = %q, want h2 (Alt-Svc upgrades future requests, not the one that carried it)", c.Protocol())
	}

	status, body = doGet(t, c, "https://"+h2Addr+"/ping")
	if status != http.StatusOK || body != "pong" {
		t.Fatalf("second request: status=%d body=%q, want 200/pong", status, body)
	}
	if c.Protocol() != "h3" {
		t.Errorf("Protocol() after second request = %q, want h3 (Alt-Svc must have promoted it)", c.Protocol())
	}
}

// --- TDD scenario 6: a caller-supplied TLS12 config still results in a
// working TLS13 connection against the server (which itself only accepts
// TLS13, per Task 2's server.New()). ---

func TestClient_ForcesTLS13_HandshakeSucceedsAgainstTLS13OnlyServer(t *testing.T) {
	tlsCfg := mustSelfSignedTLSConfig(t)
	srv := startServer(t, server.Config{
		H2Addr: "127.0.0.1:0", H2Enabled: true, H3Enabled: false,
		TLSConfig: tlsCfg, GracePeriod: 2 * time.Second,
	})
	srv.Mux().HandleFunc("/ping", func(w http.ResponseWriter, _ *http.Request) {
		_, _ = w.Write([]byte("pong"))
	})
	h2Addr := waitForAddr(t, srv, "h2")

	pool := certPoolFromTLSConfig(t, tlsCfg)
	clientTLSCfg := &tls.Config{RootCAs: pool, MinVersion: tls.VersionTLS12} // caller mistake
	c, err := New(Config{BaseURL: "https://" + h2Addr, TLSConfig: clientTLSCfg, Lanes: []Lane{LaneH2}}, zap.NewNop())
	if err != nil {
		t.Fatalf("New: %v", err)
	}
	defer func() { _ = c.Close() }()

	if clientTLSCfg.MinVersion != tls.VersionTLS13 {
		t.Fatalf("MinVersion = %d, want tls.VersionTLS13 (New must force it before dialing)", clientTLSCfg.MinVersion)
	}

	status, body := doGet(t, c, "https://"+h2Addr+"/ping")
	if status != http.StatusOK || body != "pong" {
		t.Fatalf("status=%d body=%q, want 200/pong (TLS13 handshake must still succeed)", status, body)
	}
}

// --- TDD scenario 7: Close() releases both lanes' transports without
// leaking goroutines. ---
//
// The server itself lazily spawns its own QUIC-transport goroutines
// (runSendQueue, baseServer.run, etc.) the moment it handles the first real
// H3 connection, and those persist for the server's lifetime independent of
// anything the client does. A disposable warm-up client/request forces that
// lazy initialization to happen BEFORE the goleak snapshot, so the
// snapshot/verify pair below isolates goroutines caused by the client under
// test's own New -> use -> Close lifecycle.
func TestClient_Close_NoGoroutineLeak(t *testing.T) {
	port := freeTCPPort(t)
	addr := fmt.Sprintf("127.0.0.1:%d", port)
	tlsCfg := mustSelfSignedTLSConfig(t)
	srv := startServer(t, server.Config{
		H2Addr: addr, H3Addr: addr, H2Enabled: true, H3Enabled: true,
		TLSConfig: tlsCfg, GracePeriod: 2 * time.Second,
	})
	srv.Mux().HandleFunc("/ping", func(w http.ResponseWriter, _ *http.Request) {
		_, _ = w.Write([]byte("pong"))
	})
	waitForAddr(t, srv, "h2")
	waitForAddr(t, srv, "h3")

	pool := certPoolFromTLSConfig(t, tlsCfg)

	warmup, err := New(Config{BaseURL: "https://" + addr, TLSConfig: &tls.Config{RootCAs: pool}}, zap.NewNop())
	if err != nil {
		t.Fatalf("New (warmup): %v", err)
	}
	if status, _ := doGet(t, warmup, "https://"+addr+"/ping"); status != http.StatusOK {
		t.Fatalf("warmup request: status=%d, want 200", status)
	}
	if err := warmup.Close(); err != nil {
		t.Fatalf("warmup Close: %v", err)
	}

	snapshot := goleak.IgnoreCurrent()

	c, err := New(Config{BaseURL: "https://" + addr, TLSConfig: &tls.Config{RootCAs: pool}}, zap.NewNop())
	if err != nil {
		t.Fatalf("New: %v", err)
	}

	if status, _ := doGet(t, c, "https://"+addr+"/ping"); status != http.StatusOK {
		t.Fatalf("h3 request: status=%d, want 200", status)
	}
	if c.Protocol() != "h3" {
		t.Fatalf("Protocol() = %q, want h3", c.Protocol())
	}
	c.MarkLaneFailed(LaneH3)
	if status, _ := doGet(t, c, "https://"+addr+"/ping"); status != http.StatusOK {
		t.Fatalf("h2 request: status=%d, want 200", status)
	}
	if c.Protocol() != "h2" {
		t.Fatalf("Protocol() = %q, want h2", c.Protocol())
	}

	if err := c.Close(); err != nil {
		t.Fatalf("Close: %v", err)
	}

	goleak.VerifyNone(t, snapshot)
}
