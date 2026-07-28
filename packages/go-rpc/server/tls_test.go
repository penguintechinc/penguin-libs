// Copyright 2026 Penguin Tech Inc
// SPDX-License-Identifier: Apache-2.0

package server

import (
	"crypto/ecdsa"
	"crypto/tls"
	"crypto/x509"
	"encoding/pem"
	"os"
	"path/filepath"
	"testing"
	"time"
)

// writeTempKeyPair generates a fresh self-signed keypair and writes it to
// PEM files in a temp dir, for exercising NewTLSConfig's disk-loading path.
func writeTempKeyPair(t *testing.T) (certPath, keyPath string) {
	t.Helper()
	cfg := mustSelfSignedTLSConfig(t)

	certPEM := pem.EncodeToMemory(&pem.Block{
		Type:  "CERTIFICATE",
		Bytes: cfg.Certificates[0].Certificate[0],
	})

	privKey, ok := cfg.Certificates[0].PrivateKey.(*ecdsa.PrivateKey)
	if !ok {
		t.Fatalf("expected *ecdsa.PrivateKey, got %T", cfg.Certificates[0].PrivateKey)
	}
	keyBytes, err := x509.MarshalECPrivateKey(privKey)
	if err != nil {
		t.Fatalf("marshaling private key: %v", err)
	}
	keyPEM := pem.EncodeToMemory(&pem.Block{Type: "EC PRIVATE KEY", Bytes: keyBytes})

	dir := t.TempDir()
	certPath = filepath.Join(dir, "cert.pem")
	keyPath = filepath.Join(dir, "key.pem")
	if err := os.WriteFile(certPath, certPEM, 0o600); err != nil {
		t.Fatalf("writing cert file: %v", err)
	}
	if err := os.WriteFile(keyPath, keyPEM, 0o600); err != nil {
		t.Fatalf("writing key file: %v", err)
	}
	return certPath, keyPath
}

func TestNewTLSConfig_ValidKeyPair(t *testing.T) {
	certPath, keyPath := writeTempKeyPair(t)

	cfg, err := NewTLSConfig(certPath, keyPath)
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if cfg.MinVersion != tls.VersionTLS13 {
		t.Errorf("MinVersion = %d, want tls.VersionTLS13", cfg.MinVersion)
	}
	if len(cfg.Certificates) != 1 {
		t.Fatalf("expected 1 certificate, got %d", len(cfg.Certificates))
	}
}

func TestEnvOrDefault_Set(t *testing.T) {
	t.Setenv("TEST_VAR", "test_value")

	result := envOrDefault("TEST_VAR", "default_value")

	if result != "test_value" {
		t.Errorf("expected test_value, got %s", result)
	}
}

func TestEnvOrDefault_Unset(t *testing.T) {
	// Don't set the var
	result := envOrDefault("UNSET_TEST_VAR", "default_value")

	if result != "default_value" {
		t.Errorf("expected default_value, got %s", result)
	}
}

func TestNewTLSConfig_InvalidPaths(t *testing.T) {
	_, err := NewTLSConfig("/nonexistent/cert.pem", "/nonexistent/key.pem")

	if err == nil {
		t.Error("expected error for invalid paths, got nil")
	}
}

func TestSelfSignedTLSConfig(t *testing.T) {
	cfg, err := SelfSignedTLSConfig()
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if cfg == nil {
		t.Fatal("expected non-nil tls.Config")
	}
	if cfg.MinVersion != tls.VersionTLS13 {
		t.Errorf("expected MinVersion TLS13, got %d", cfg.MinVersion)
	}
	if len(cfg.Certificates) != 1 {
		t.Fatalf("expected exactly 1 certificate, got %d", len(cfg.Certificates))
	}

	cert, err := x509.ParseCertificate(cfg.Certificates[0].Certificate[0])
	if err != nil {
		t.Fatalf("parsing generated certificate: %v", err)
	}
	if cert.NotAfter.Before(time.Now()) {
		t.Error("certificate already expired")
	}

	foundLocalhost := false
	for _, name := range cert.DNSNames {
		if name == "localhost" {
			foundLocalhost = true
		}
	}
	if !foundLocalhost {
		t.Errorf("expected DNSNames to include localhost, got %v", cert.DNSNames)
	}

	foundLoopback := false
	for _, ip := range cert.IPAddresses {
		if ip.String() == "127.0.0.1" {
			foundLoopback = true
		}
	}
	if !foundLoopback {
		t.Errorf("expected IPAddresses to include 127.0.0.1, got %v", cert.IPAddresses)
	}
}

func TestSelfSignedTLSConfig_UniquePerCall(t *testing.T) {
	cfg1, err := SelfSignedTLSConfig()
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	cfg2, err := SelfSignedTLSConfig()
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}

	cert1, err := x509.ParseCertificate(cfg1.Certificates[0].Certificate[0])
	if err != nil {
		t.Fatalf("parsing cert1: %v", err)
	}
	cert2, err := x509.ParseCertificate(cfg2.Certificates[0].Certificate[0])
	if err != nil {
		t.Fatalf("parsing cert2: %v", err)
	}
	if cert1.SerialNumber.Cmp(cert2.SerialNumber) == 0 {
		t.Error("expected distinct serial numbers across calls")
	}
}
