// Copyright 2026 Penguin Tech Inc
// SPDX-License-Identifier: Apache-2.0

// Command echo-server is a runnable demo of the go-rpc server stack: it
// mirrors the non-auth wiring integration/integration_test.go establishes —
// SelfSignedTLSConfig, both the H2 and H3 listeners, server.DefaultInterceptors
// plus the protovalidate validation interceptor, and the ConformanceService +
// HealthService registered on the shared mux. It deliberately omits
// auth/MCP/A2A to keep the example small and anonymous-friendly; see
// packages/go-rpc/integration/integration_test.go for the full-stack,
// authenticated wiring this trims down from.
package main

import (
	"context"
	"crypto/tls"
	"encoding/pem"
	"flag"
	"fmt"
	"os"
	"os/signal"
	"path/filepath"
	"syscall"
	"time"

	"connectrpc.com/connect"
	"go.uber.org/zap"

	"github.com/penguintechinc/penguin-libs/packages/go-rpc/conformance"
	"github.com/penguintechinc/penguin-libs/packages/go-rpc/health"
	"github.com/penguintechinc/penguin-libs/packages/go-rpc/server"
)

// main parses listen addresses from flags/env, builds the demo server, and
// blocks until SIGINT/SIGTERM triggers a graceful shutdown. Setup errors and
// a failed Start both result in a non-zero exit; see run for the wiring.
func main() {
	if err := run(); err != nil {
		fmt.Fprintln(os.Stderr, "echo-server:", err)
		os.Exit(1)
	}
}

// run builds and starts the full-stack demo server, then waits for Start to
// return — either because ctx was cancelled by a shutdown signal (clean
// return) or because a listener failed fatally (wrapped error return).
func run() error {
	h2Addr := flag.String("h2-addr", envDefault("H2_ADDR", "127.0.0.1:8080"), "HTTP/2 listen address")
	h3Addr := flag.String("h3-addr", envDefault("H3_ADDR", "127.0.0.1:8443"), "HTTP/3 (QUIC/UDP) listen address")
	certPath := flag.String("cert-file", envDefault("PRPC_ECHO_CERT_FILE", defaultCertPath()),
		"path to write the server's self-signed certificate (PEM) so echo-client can trust it")
	flag.Parse()

	logger, err := zap.NewDevelopment()
	if err != nil {
		return fmt.Errorf("creating logger: %w", err)
	}
	defer func() { _ = logger.Sync() }()

	// DEMO ONLY: SelfSignedTLSConfig mints an ephemeral, in-memory
	// certificate for "localhost"/loopback — never use it in production.
	// See its doc comment in server/tls.go.
	tlsCfg, err := server.SelfSignedTLSConfig()
	if err != nil {
		return fmt.Errorf("SelfSignedTLSConfig: %w", err)
	}

	// Export the certificate to disk (real verification, not a skipped
	// check) so echo-client — a separate process with no access to this
	// in-memory tls.Config — can build a CA pool that actually trusts it.
	// This mirrors integration_test.go's certPoolFromTLSConfig, adapted for
	// two independently-launched binaries instead of one shared process.
	if err := writeCertPEM(*certPath, tlsCfg); err != nil {
		return fmt.Errorf("writing certificate PEM to %s: %w", *certPath, err)
	}
	defer func() { _ = os.Remove(*certPath) }()

	cfg := server.Config{
		H2Addr:          *h2Addr,
		H3Addr:          *h3Addr,
		H2Enabled:       true,
		H3Enabled:       true,
		TLSConfig:       tlsCfg,
		GracePeriod:     5 * time.Second,
		MaxMessageBytes: 4 << 20,
	}

	validationInterceptor, err := server.NewValidationInterceptor()
	if err != nil {
		return fmt.Errorf("NewValidationInterceptor: %w", err)
	}

	interceptors := append([]connect.Interceptor{}, server.DefaultInterceptors(logger, cfg)...)
	cfg.Interceptors = append(interceptors, validationInterceptor)

	srv, err := server.New(cfg, logger)
	if err != nil {
		return fmt.Errorf("server.New: %w", err)
	}

	mux := srv.Mux()
	conformance.Register(mux, srv.HandlerOptions()...)
	checker := health.NewChecker()
	health.Register(mux, checker, srv.HandlerOptions()...)

	ctx, stop := signal.NotifyContext(context.Background(), os.Interrupt, syscall.SIGTERM)
	defer stop()

	startErrCh := make(chan error, 1)
	go func() { startErrCh <- srv.Start(ctx) }()

	logger.Info("echo-server listening",
		zap.String("h2_addr", waitForAddr(srv, "h2")),
		zap.String("h3_addr", waitForAddr(srv, "h3")),
		zap.String("cert_file", *certPath),
	)
	logger.Info("press Ctrl+C to stop")

	if err := <-startErrCh; err != nil {
		return fmt.Errorf("server.Start: %w", err)
	}
	logger.Info("echo-server shut down cleanly")
	return nil
}

// waitForAddr polls Server.ListenAddr for protocol ("h2" or "h3") until it
// reports a bound address or a short deadline elapses, so startup logging
// shows the actual resolved address (relevant when a flag/env value uses
// port 0). It never fails the caller — an empty result just means the
// listener had not bound yet when the deadline passed.
func waitForAddr(srv *server.Server, protocol string) string {
	deadline := time.Now().Add(2 * time.Second)
	for time.Now().Before(deadline) {
		if addr := srv.ListenAddr(protocol); addr != "" {
			return addr
		}
		time.Sleep(5 * time.Millisecond)
	}
	return srv.ListenAddr(protocol)
}

// writeCertPEM PEM-encodes the leaf certificate held in tlsCfg and writes it
// to path with 0600 permissions, so only the local user can read it. It
// returns an error if tlsCfg carries no certificate — which would indicate a
// bug in SelfSignedTLSConfig, not caller misuse.
func writeCertPEM(path string, tlsCfg *tls.Config) error {
	if len(tlsCfg.Certificates) == 0 || len(tlsCfg.Certificates[0].Certificate) == 0 {
		return fmt.Errorf("tls config has no certificate to export")
	}
	block := &pem.Block{Type: "CERTIFICATE", Bytes: tlsCfg.Certificates[0].Certificate[0]}
	return os.WriteFile(path, pem.EncodeToMemory(block), 0o600) //nolint:gosec // operator-controlled demo path, not user input from a request
}

// defaultCertPath returns the OS temp directory path echo-server writes its
// self-signed certificate to by default, and echo-client reads from by
// default — keeping the two binaries' defaults in sync without either
// hardcoding the other's flag value.
func defaultCertPath() string {
	return filepath.Join(os.TempDir(), "prpc-echo-server-cert.pem")
}

// envDefault returns the named environment variable's value, or fallback if
// it is unset or empty — used to seed flag.String defaults so addresses and
// paths are configurable via either flags or env vars.
func envDefault(key, fallback string) string {
	if v, ok := os.LookupEnv(key); ok && v != "" {
		return v
	}
	return fallback
}
