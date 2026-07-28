// Copyright 2026 Penguin Tech Inc
// SPDX-License-Identifier: Apache-2.0

// Command echo-client is a runnable demo of the go-rpc multi-lane client: it
// builds a client.New client preferring the H3 lane (with automatic H2
// fallback per the client's own lane-router config), calls
// ConformanceService.Unary once against echo-server, and prints the echoed
// message plus the transport ("h3" or "h2") that actually served the
// request — mirroring the non-auth client construction
// integration/integration_test.go uses for its h3Conformance/h2Conformance
// clients. TLS trust is established the same way integration_test.go's
// certPoolFromTLSConfig does — a real x509.CertPool built from the server's
// certificate, never a skipped verification check — just read from a file
// on disk instead of the server's in-memory tls.Config, since these are two
// separate processes.
package main

import (
	"context"
	"crypto/tls"
	"crypto/x509"
	"flag"
	"fmt"
	"os"
	"path/filepath"
	"time"

	"connectrpc.com/connect"
	"go.uber.org/zap"

	"github.com/penguintechinc/penguin-libs/packages/go-rpc/client"
	conformancev1 "github.com/penguintechinc/penguin-libs/packages/go-rpc/gen/prpc/conformance/v1"
	"github.com/penguintechinc/penguin-libs/packages/go-rpc/gen/prpc/conformance/v1/conformancev1connect"
)

// main resolves the echo-server address from flags/env, issues one
// ConformanceService.Unary echo call, and prints the response on success. On
// any setup or RPC error it prints to stderr and exits 1.
func main() {
	if err := run(); err != nil {
		fmt.Fprintln(os.Stderr, "echo-client:", err)
		os.Exit(1)
	}
}

// run builds the H3-first pRPC client trusting echo-server's exported
// self-signed certificate, calls Unary once, and prints the echoed message
// and negotiated protocol.
func run() error {
	addr := flag.String("addr", envDefault("PRPC_ECHO_ADDR", "127.0.0.1:8443"),
		"echo-server address (host:port), matching echo-server's -h3-addr default")
	certPath := flag.String("ca-file", envDefault("PRPC_ECHO_CERT_FILE", defaultCertPath()),
		"path to echo-server's self-signed certificate (PEM), written by echo-server on startup")
	message := flag.String("message", "hello from pRPC echo-client", "message to echo")
	flag.Parse()

	logger, err := zap.NewDevelopment()
	if err != nil {
		return fmt.Errorf("creating logger: %w", err)
	}
	defer func() { _ = logger.Sync() }()

	pool, err := loadCertPool(*certPath)
	if err != nil {
		return fmt.Errorf("loading echo-server certificate from %s (start echo-server first): %w", *certPath, err)
	}

	baseURL := "https://" + *addr
	cl, err := client.New(client.Config{
		BaseURL:   baseURL,
		TLSConfig: &tls.Config{RootCAs: pool},
		Lanes:     []client.Lane{client.LaneH3, client.LaneH2},
	}, logger)
	if err != nil {
		return fmt.Errorf("client.New: %w", err)
	}
	defer func() { _ = cl.Close() }()

	conformanceClient := conformancev1connect.NewConformanceServiceClient(cl.HTTPClient(), baseURL)

	ctx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
	defer cancel()

	req := connect.NewRequest(&conformancev1.EchoRequest{Message: *message})
	resp, err := conformanceClient.Unary(ctx, req)
	if err != nil {
		return fmt.Errorf("Unary: %w", err)
	}

	fmt.Printf("echo: %s\n", resp.Msg.GetMessage())
	fmt.Printf("protocol: %s\n", resp.Msg.GetProtocol())
	return nil
}

// loadCertPool reads a PEM-encoded certificate from path and returns an
// x509.CertPool trusting exactly that certificate — the real verification
// path (not a skipped check) for a self-signed server whose cert isn't in
// any system trust store.
func loadCertPool(path string) (*x509.CertPool, error) {
	pemBytes, err := os.ReadFile(path) //nolint:gosec // operator-controlled demo path, not user input from a request
	if err != nil {
		return nil, err
	}
	pool := x509.NewCertPool()
	if !pool.AppendCertsFromPEM(pemBytes) {
		return nil, fmt.Errorf("no valid certificates found in %s", path)
	}
	return pool, nil
}

// defaultCertPath returns the OS temp directory path echo-client reads
// echo-server's self-signed certificate from by default — kept in sync with
// echo-server's own defaultCertPath so the two binaries agree with no flags
// needed for the common local case.
func defaultCertPath() string {
	return filepath.Join(os.TempDir(), "prpc-echo-server-cert.pem")
}

// envDefault returns the named environment variable's value, or fallback if
// it is unset or empty — used to seed flag.String defaults so the target
// address and cert path are configurable via either flags or env vars.
func envDefault(key, fallback string) string {
	if v, ok := os.LookupEnv(key); ok && v != "" {
		return v
	}
	return fallback
}
