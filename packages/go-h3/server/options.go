// Package server provides a dual-protocol HTTP/2 + HTTP/3 server using ConnectRPC.
package server

import (
	"crypto/tls"
	"time"

	"connectrpc.com/connect"
)

// Config holds server configuration for both H2 and H3 listeners.
type Config struct {
	// H2Addr is the HTTP/2 listen address (e.g., ":8080").
	H2Addr string
	// H3Addr is the HTTP/3 listen address (e.g., ":8443").
	H3Addr string
	// H2Enabled controls whether the HTTP/2 listener starts. Default true.
	H2Enabled bool
	// H3Enabled controls whether the HTTP/3 listener starts. Default true.
	H3Enabled bool
	// TLSConfig is required for HTTP/3 and optional for HTTP/2.
	TLSConfig *tls.Config
	// GracePeriod is the shutdown grace period. Default 30s.
	GracePeriod time.Duration
	// Interceptors are ConnectRPC interceptors applied to all handlers.
	Interceptors []connect.Interceptor
}

// DefaultConfig returns a Config with sensible defaults.
func DefaultConfig() Config {
	return Config{
		H2Addr:      ":8080",
		H3Addr:      ":8443",
		H2Enabled:   true,
		H3Enabled:   true,
		GracePeriod: 30 * time.Second,
	}
}

// ConfigFromEnv returns a Config populated from environment variables.
// Recognized vars: H2_PORT, H3_PORT, H2_ENABLED, H3_ENABLED, TLS_CERT_PATH, TLS_KEY_PATH.
// Values not set in the environment fall back to DefaultConfig.
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
