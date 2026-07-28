// Copyright 2026 Penguin Tech Inc
// SPDX-License-Identifier: Apache-2.0

package server

import (
	"crypto/tls"
	"time"

	"connectrpc.com/connect"
)

// defaultMaxMessageBytes is the pRPC spec §3 default maximum message size (4 MiB).
const defaultMaxMessageBytes = 4 << 20

// defaultUnaryTimeout is the deadline applied to unary calls when the caller
// supplies none, per pRPC spec §3.
const defaultUnaryTimeout = 30 * time.Second

// Config holds server configuration for the H2 and H3 listeners, transport
// hardening knobs, and the interceptor chain applied to every handler.
type Config struct {
	// H2Addr is the HTTP/2 listen address (e.g., ":8080").
	H2Addr string
	// H3Addr is the HTTP/3 (QUIC/UDP) listen address (e.g., ":8443").
	H3Addr string
	// H2Enabled controls whether the HTTP/2 listener starts. Default true.
	H2Enabled bool
	// H3Enabled controls whether the HTTP/3 listener starts. Default true.
	H3Enabled bool
	// TLSConfig is required for HTTP/3 and optional for HTTP/2. New() forces
	// MinVersion to tls.VersionTLS13 regardless of the value supplied here,
	// per spec §3 (TLS 1.2 and earlier MUST NOT be negotiated).
	TLSConfig *tls.Config
	// GracePeriod bounds graceful shutdown: in-flight requests get this long
	// to complete before listeners are forced closed.
	GracePeriod time.Duration
	// MaxMessageBytes is the maximum accepted request message size. New()
	// defaults this to 4 MiB (defaultMaxMessageBytes) when zero, per spec §3.
	MaxMessageBytes int
	// DefaultUnaryTimeout is the deadline applied to unary calls that arrive
	// without a caller-supplied deadline. New() defaults this to 30s
	// (defaultUnaryTimeout) when zero, per spec §3.
	DefaultUnaryTimeout time.Duration
	// Interceptors are ConnectRPC interceptors applied to every handler via
	// HandlerOptions().
	Interceptors []connect.Interceptor
}

// DefaultConfig returns a Config with production-sane defaults: both
// listeners enabled, a 30s grace period, a 4 MiB max message size, and a 30s
// default unary deadline. TLSConfig is left nil — callers must supply one
// (see NewTLSConfig / SelfSignedTLSConfig) before starting the H3 listener.
func DefaultConfig() Config {
	return Config{
		H2Addr:              ":8080",
		H3Addr:              ":8443",
		H2Enabled:           true,
		H3Enabled:           true,
		GracePeriod:         30 * time.Second,
		MaxMessageBytes:     defaultMaxMessageBytes,
		DefaultUnaryTimeout: defaultUnaryTimeout,
	}
}

// ConfigFromEnv builds a Config from environment variables, falling back to
// DefaultConfig for anything unset:
//
//	H2_PORT, H3_PORT           — listen ports (":"+value)
//	H2_ENABLED                 — "false" disables the HTTP/2 listener
//	H3_ENABLED                 — "false" disables the HTTP/3 listener
//	HTTP3_ENABLED              — operator kill-switch; "false" disables the
//	                              HTTP/3 listener regardless of H3_ENABLED
//	TLS_CERT_PATH, TLS_KEY_PATH — loaded via NewTLSConfig when both are set
func ConfigFromEnv() (Config, error) {
	cfg := DefaultConfig()
	if v := envOrDefault("H2_PORT", ""); v != "" {
		cfg.H2Addr = ":" + v
	}
	if v := envOrDefault("H3_PORT", ""); v != "" {
		cfg.H3Addr = ":" + v
	}
	if envOrDefault("H2_ENABLED", "true") == "false" {
		cfg.H2Enabled = false
	}
	if envOrDefault("H3_ENABLED", "true") == "false" {
		cfg.H3Enabled = false
	}
	// HTTP3_ENABLED is the operator kill-switch: it can only turn H3 off, on
	// top of whatever H3_ENABLED already decided, never turn it back on.
	if envOrDefault("HTTP3_ENABLED", "true") == "false" {
		cfg.H3Enabled = false
	}

	certPath := envOrDefault("TLS_CERT_PATH", "")
	keyPath := envOrDefault("TLS_KEY_PATH", "")
	if certPath != "" && keyPath != "" {
		tlsCfg, err := NewTLSConfig(certPath, keyPath)
		if err != nil {
			return cfg, err
		}
		cfg.TLSConfig = tlsCfg
	}
	return cfg, nil
}
