// Package client provides an HTTP/3-preferred client with automatic HTTP/2 fallback.
package client

import (
	"crypto/tls"
	"time"
)

// Config holds client configuration.
type Config struct {
	// BaseURL is the server base URL (e.g., "https://localhost:8443").
	BaseURL string
	// TLSConfig for TLS connections. If nil, system defaults are used.
	TLSConfig *tls.Config
	// H3Enabled controls whether HTTP/3 is attempted. Default true.
	H3Enabled bool
	// H3Timeout is how long to wait for an HTTP/3 connection before falling back. Default 5s.
	H3Timeout time.Duration
	// H3RetryInterval controls how often to retry HTTP/3 after a fallback. Default 5m.
	H3RetryInterval time.Duration
	// RequestTimeout is the default request timeout. Default 30s.
	RequestTimeout time.Duration
}

// DefaultClientConfig returns a Config with sensible defaults.
func DefaultClientConfig() Config {
	return Config{
		H3Enabled:       true,
		H3Timeout:       5 * time.Second,
		H3RetryInterval: 5 * time.Minute,
		RequestTimeout:  30 * time.Second,
	}
}
