package server

import (
	"crypto/tls"
	"fmt"
	"os"
)

// NewTLSConfig creates a TLS 1.3 configuration from cert and key files.
func NewTLSConfig(certPath, keyPath string) (*tls.Config, error) {
	cert, err := tls.LoadX509KeyPair(certPath, keyPath)
	if err != nil {
		return nil, fmt.Errorf("loading TLS keypair: %w", err)
	}
	return &tls.Config{
		Certificates: []tls.Certificate{cert},
		MinVersion:   tls.VersionTLS13,
		NextProtos:   []string{"h3", "h2", "http/1.1"},
	}, nil
}

// envOrDefault returns the environment variable value or a default.
func envOrDefault(key, fallback string) string {
	if v, ok := os.LookupEnv(key); ok {
		return v
	}
	return fallback
}
