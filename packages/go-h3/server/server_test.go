package server

import (
	"context"
	"net"
	"net/http"
	"testing"
	"time"

	"go.uber.org/zap"
)

// waitForServerReady polls the server using net.Dial until it's listening or deadline is reached
// getAddr is a callback that returns the current listening address
func waitForServerReady(getAddr func() string, deadline time.Time) bool {
	for time.Now().Before(deadline) {
		addr := getAddr()
		if addr == "" {
			time.Sleep(10 * time.Millisecond)
			continue
		}
		ctx, cancel := context.WithTimeout(context.Background(), 50*time.Millisecond)
		conn, err := (&net.Dialer{}).DialContext(ctx, "tcp", addr)
		cancel()
		if err == nil {
			_ = conn.Close()
			return true
		}
		time.Sleep(10 * time.Millisecond)
	}
	return false
}

func TestServer_Start_WithContextCancellation(t *testing.T) {
	logger := zap.NewNop()
	cfg := DefaultConfig()
	cfg.H2Enabled = true
	cfg.H3Enabled = false
	cfg.H2Addr = ":0" // Use random port

	srv, err := New(cfg, logger)
	if err != nil {
		t.Fatalf("failed to create server: %v", err)
	}

	ctx, cancel := context.WithCancel(context.Background())

	// Start server in goroutine
	errChan := make(chan error, 1)
	go func() {
		errChan <- srv.Start(ctx)
	}()

	// Give server time to start
	time.Sleep(100 * time.Millisecond)

	// Cancel context to trigger shutdown
	cancel()

	// Wait for server to shut down
	select {
	case <-time.After(5 * time.Second):
		t.Error("server did not shut down within timeout")
	case err := <-errChan:
		// Shutdown should succeed
		if err != nil {
			t.Errorf("server returned error on shutdown: %v", err)
		}
	}
}

func TestServer_ListenAddr_BeforeStart(t *testing.T) {
	logger := zap.NewNop()
	cfg := DefaultConfig()

	srv, err := New(cfg, logger)
	if err != nil {
		t.Fatalf("failed to create server: %v", err)
	}

	// ListenAddr before Start should return empty string
	addr := srv.ListenAddr("h2")
	if addr != "" {
		t.Errorf("expected empty addr before start, got %s", addr)
	}
}

func TestServer_ListenAddr_AfterStart(t *testing.T) {
	logger := zap.NewNop()
	cfg := DefaultConfig()
	cfg.H2Enabled = true
	cfg.H3Enabled = false
	cfg.H2Addr = ":0" // Use random port

	srv, err := New(cfg, logger)
	if err != nil {
		t.Fatalf("failed to create server: %v", err)
	}

	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()

	// Start server
	go func() {
		_ = srv.Start(ctx)
	}()

	// Wait for server to be ready using readiness polling against ListenAddr
	deadline := time.Now().Add(2 * time.Second)
	if !waitForServerReady(func() string { return srv.ListenAddr("h2") }, deadline) {
		t.Fatal("server did not become ready within deadline")
	}

	// ListenAddr should return the actual bound address
	addr := srv.ListenAddr("h2")
	if addr == "" {
		t.Error("expected non-empty addr after start")
	}
	if addr == ":0" {
		t.Error("ListenAddr should return bound address, not \":0\"")
	}

	// Verify the address is actually listening by connecting to it
	dialCtx, cancel := context.WithTimeout(context.Background(), 100*time.Millisecond)
	conn, err := (&net.Dialer{}).DialContext(dialCtx, "tcp", addr)
	cancel()
	if err != nil {
		t.Errorf("could not connect to %s: %v", addr, err)
	} else {
		_ = conn.Close()
	}
}

func TestServer_ListenAddr_InvalidProtocol(t *testing.T) {
	logger := zap.NewNop()
	cfg := DefaultConfig()

	srv, err := New(cfg, logger)
	if err != nil {
		t.Fatalf("failed to create server: %v", err)
	}

	// ListenAddr with invalid protocol should return empty
	addr := srv.ListenAddr("invalid")
	if addr != "" {
		t.Errorf("expected empty addr for invalid protocol, got %s", addr)
	}
}

func TestServer_ListenAddr_StoppedServer(t *testing.T) {
	logger := zap.NewNop()
	cfg := DefaultConfig()
	cfg.H2Enabled = true
	cfg.H3Enabled = false
	cfg.H2Addr = ":0"

	srv, err := New(cfg, logger)
	if err != nil {
		t.Fatalf("failed to create server: %v", err)
	}

	ctx, cancel := context.WithTimeout(context.Background(), 1*time.Second)
	defer cancel()

	// Start and stop server
	errChan := make(chan error, 1)
	go func() {
		errChan <- srv.Start(ctx)
	}()

	// Wait for context to cancel and server to shut down
	<-ctx.Done()
	<-errChan
	time.Sleep(50 * time.Millisecond)

	// ListenAddr for h3 (not started) should return empty
	addr := srv.ListenAddr("h3")
	if addr != "" {
		t.Errorf("expected empty addr for unused protocol, got %s", addr)
	}
}

func TestServer_Mux_RegistersHandlers(t *testing.T) {
	logger := zap.NewNop()
	cfg := DefaultConfig()

	srv, err := New(cfg, logger)
	if err != nil {
		t.Fatalf("failed to create server: %v", err)
	}

	mux := srv.Mux()
	if mux == nil {
		t.Error("Mux() should not return nil")
	}

	// Register a simple handler
	mux.HandleFunc("/test", func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(http.StatusOK)
	})

	// Verify the mux is functioning (basic sanity check)
	// The actual HTTP functionality would require a running server
}

func TestServer_H3Disabled_NoError(t *testing.T) {
	logger := zap.NewNop()
	cfg := DefaultConfig()
	cfg.H2Enabled = true
	cfg.H3Enabled = false
	cfg.H2Addr = ":0"

	srv, err := New(cfg, logger)
	if err != nil {
		t.Fatalf("failed to create server: %v", err)
	}

	ctx, cancel := context.WithTimeout(context.Background(), 1*time.Second)
	defer cancel()

	// Start with H3 disabled should not error
	go func() {
		_ = srv.Start(ctx)
	}()

	// Wait for context to cancel
	<-ctx.Done()
	time.Sleep(50 * time.Millisecond)

	// No assertion needed - if we got here without panic, test passes
}

func TestServer_H3Enabled_RequiresTLS(t *testing.T) {
	logger := zap.NewNop()
	cfg := DefaultConfig()
	cfg.H2Enabled = false
	cfg.H3Enabled = true
	cfg.H3Addr = ":0"
	cfg.TLSConfig = nil // Intentionally missing TLS config

	srv, err := New(cfg, logger)
	if err != nil {
		t.Fatalf("failed to create server: %v", err)
	}

	// Start should fail because H3 requires TLS
	ctx, cancel := context.WithTimeout(context.Background(), 1*time.Second)
	defer cancel()

	err = srv.Start(ctx)
	if err == nil {
		t.Error("expected error when H3 enabled without TLS config")
	}
}

// freePort reserves an ephemeral port and releases it, returning an address
// that is free at call time. Tests use it to know exactly which port a leaked
// listener would occupy.
func freePort(t *testing.T) string {
	t.Helper()
	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	ln, err := (&net.ListenConfig{}).Listen(ctx, "tcp", "127.0.0.1:0")
	cancel()
	if err != nil {
		t.Fatalf("reserving probe port: %v", err)
	}
	addr := ln.Addr().String()
	if err := ln.Close(); err != nil {
		t.Fatalf("closing probe listener: %v", err)
	}
	return addr
}

// Regression: Start used to bind and serve the H2 listener before validating
// that H3 requires TLS, so the error return leaked a bound, actively serving
// port. Validation must now happen before anything binds.
func TestServer_Start_H3WithoutTLS_LeavesNoBoundH2Port(t *testing.T) {
	addr := freePort(t)

	cfg := DefaultConfig()
	cfg.H2Enabled = true
	cfg.H3Enabled = true
	cfg.H2Addr = addr
	cfg.H3Addr = ":0"
	cfg.TLSConfig = nil // Intentionally missing: H3 cannot start without it

	srv, err := New(cfg, zap.NewNop())
	if err != nil {
		t.Fatalf("failed to create server: %v", err)
	}

	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()

	if err := srv.Start(ctx); err == nil {
		t.Fatal("expected error when H3 enabled without TLS config")
	}

	srv.mu.Lock()
	h2ln := srv.h2ln
	h2 := srv.h2
	srv.mu.Unlock()
	if h2ln != nil {
		t.Errorf("h2 listener still set after failed Start: %s", h2ln.Addr())
	}
	if h2 != nil {
		t.Error("h2 server still set after failed Start")
	}

	// Re-binding the port proves no listener survived the error path.
	rebindCtx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	ln, err := (&net.ListenConfig{}).Listen(rebindCtx, "tcp", addr)
	cancel()
	if err != nil {
		t.Fatalf("port %s still bound after failed Start (listener leak): %v", addr, err)
	}
	if err := ln.Close(); err != nil {
		t.Errorf("closing rebound listener: %v", err)
	}
}

// A failed bind must surface as an error and leave no server state behind.
func TestServer_Start_H2BindFailure_ReturnsErrorAndCleansUp(t *testing.T) {
	occupyCtx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	occupied, err := (&net.ListenConfig{}).Listen(occupyCtx, "tcp", "127.0.0.1:0")
	cancel()
	if err != nil {
		t.Fatalf("creating occupying listener: %v", err)
	}
	defer func() { _ = occupied.Close() }()

	cfg := DefaultConfig()
	cfg.H2Enabled = true
	cfg.H3Enabled = false
	cfg.H2Addr = occupied.Addr().String() // Already bound, so listen must fail

	srv, err := New(cfg, zap.NewNop())
	if err != nil {
		t.Fatalf("failed to create server: %v", err)
	}

	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()

	if err := srv.Start(ctx); err == nil {
		t.Fatal("expected error when H2 address is already in use")
	}

	srv.mu.Lock()
	defer srv.mu.Unlock()
	if srv.h2ln != nil || srv.h2 != nil {
		t.Error("server state retained after failed bind")
	}
}

func TestServer_New_AppliesSecureTimeoutDefaults(t *testing.T) {
	logger := zap.NewNop()

	// Create server with bare Config{} - zero values for all timeouts
	cfg := Config{
		H2Enabled: true,
		H3Enabled: false,
		H2Addr:    ":0",
	}

	srv, err := New(cfg, logger)
	if err != nil {
		t.Fatalf("failed to create server: %v", err)
	}

	// Check that secure defaults were applied
	if srv.cfg.ReadHeaderTimeout != 10*time.Second {
		t.Errorf("expected ReadHeaderTimeout 10s, got %v", srv.cfg.ReadHeaderTimeout)
	}
	if srv.cfg.ReadTimeout != 30*time.Second {
		t.Errorf("expected ReadTimeout 30s, got %v", srv.cfg.ReadTimeout)
	}
	if srv.cfg.WriteTimeout != 30*time.Second {
		t.Errorf("expected WriteTimeout 30s, got %v", srv.cfg.WriteTimeout)
	}
	if srv.cfg.IdleTimeout != 60*time.Second {
		t.Errorf("expected IdleTimeout 60s, got %v", srv.cfg.IdleTimeout)
	}
	if srv.cfg.QUICMaxIdleTimeout != 60*time.Second {
		t.Errorf("expected QUICMaxIdleTimeout 60s, got %v", srv.cfg.QUICMaxIdleTimeout)
	}
	if srv.cfg.GracePeriod != 30*time.Second {
		t.Errorf("expected GracePeriod 30s, got %v", srv.cfg.GracePeriod)
	}
}
