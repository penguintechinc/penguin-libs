// Copyright 2026 Penguin Tech Inc
// SPDX-License-Identifier: Apache-2.0

package server

import (
	"testing"
	"time"
)

func TestDefaultConfig(t *testing.T) {
	cfg := DefaultConfig()

	if cfg.H2Addr != ":8080" {
		t.Errorf("expected H2Addr :8080, got %s", cfg.H2Addr)
	}
	if cfg.H3Addr != ":8443" {
		t.Errorf("expected H3Addr :8443, got %s", cfg.H3Addr)
	}
	if !cfg.H2Enabled {
		t.Error("expected H2Enabled true, got false")
	}
	if !cfg.H3Enabled {
		t.Error("expected H3Enabled true, got false")
	}
	if cfg.GracePeriod != 30*time.Second {
		t.Errorf("expected GracePeriod 30s, got %v", cfg.GracePeriod)
	}
	if cfg.TLSConfig != nil {
		t.Error("expected TLSConfig nil, got non-nil")
	}
	if cfg.MaxMessageBytes != 4<<20 {
		t.Errorf("expected MaxMessageBytes 4MiB, got %d", cfg.MaxMessageBytes)
	}
	if cfg.DefaultUnaryTimeout != 30*time.Second {
		t.Errorf("expected DefaultUnaryTimeout 30s, got %v", cfg.DefaultUnaryTimeout)
	}
}

func TestConfigFromEnv_NoVars(t *testing.T) {
	cfg, err := ConfigFromEnv()
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}

	if cfg.H2Addr != ":8080" {
		t.Errorf("expected H2Addr :8080, got %s", cfg.H2Addr)
	}
	if cfg.H3Addr != ":8443" {
		t.Errorf("expected H3Addr :8443, got %s", cfg.H3Addr)
	}
	if !cfg.H2Enabled {
		t.Error("expected H2Enabled true, got false")
	}
	if !cfg.H3Enabled {
		t.Error("expected H3Enabled true, got false")
	}
	if cfg.GracePeriod != 30*time.Second {
		t.Errorf("expected GracePeriod 30s, got %v", cfg.GracePeriod)
	}
	if cfg.TLSConfig != nil {
		t.Error("expected TLSConfig nil, got non-nil")
	}
}

func TestConfigFromEnv_WithPorts(t *testing.T) {
	t.Setenv("H2_PORT", "9090")
	t.Setenv("H3_PORT", "9443")

	cfg, err := ConfigFromEnv()
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}

	if cfg.H2Addr != ":9090" {
		t.Errorf("expected H2Addr :9090, got %s", cfg.H2Addr)
	}
	if cfg.H3Addr != ":9443" {
		t.Errorf("expected H3Addr :9443, got %s", cfg.H3Addr)
	}
}

func TestConfigFromEnv_H2Disabled(t *testing.T) {
	t.Setenv("H2_ENABLED", "false")

	cfg, err := ConfigFromEnv()
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}

	if cfg.H2Enabled {
		t.Error("expected H2Enabled false, got true")
	}
	if !cfg.H3Enabled {
		t.Error("expected H3Enabled true, got false")
	}
}

func TestConfigFromEnv_H3Disabled(t *testing.T) {
	t.Setenv("H3_ENABLED", "false")

	cfg, err := ConfigFromEnv()
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}

	if cfg.H3Enabled {
		t.Error("expected H3Enabled false, got true")
	}
	if !cfg.H2Enabled {
		t.Error("expected H2Enabled true, got false")
	}
}

// TestConfigFromEnv_HTTP3EnabledKillSwitch is a NEW hardening test (not
// present in go-h3): HTTP3_ENABLED is the operator kill-switch mandated by
// the task brief, independent of the legacy H3_ENABLED alias. It must be
// able to disable the H3 listener on its own.
func TestConfigFromEnv_HTTP3EnabledKillSwitch(t *testing.T) {
	t.Setenv("HTTP3_ENABLED", "false")

	cfg, err := ConfigFromEnv()
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}

	if cfg.H3Enabled {
		t.Error("expected H3Enabled false when HTTP3_ENABLED=false, got true")
	}
	if !cfg.H2Enabled {
		t.Error("expected H2Enabled true (unaffected by HTTP3_ENABLED), got false")
	}
}

// TestConfigFromEnv_HTTP3EnabledDefaultTrue confirms the kill-switch default
// is true (H3 stays on) when the env var is unset.
func TestConfigFromEnv_HTTP3EnabledDefaultTrue(t *testing.T) {
	cfg, err := ConfigFromEnv()
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if !cfg.H3Enabled {
		t.Error("expected H3Enabled true by default, got false")
	}
}

func TestConfigFromEnv_ValidTLSPaths(t *testing.T) {
	certPath, keyPath := writeTempKeyPair(t)
	t.Setenv("TLS_CERT_PATH", certPath)
	t.Setenv("TLS_KEY_PATH", keyPath)

	cfg, err := ConfigFromEnv()
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if cfg.TLSConfig == nil {
		t.Fatal("expected TLSConfig to be loaded from TLS_CERT_PATH/TLS_KEY_PATH")
	}
}

func TestConfigFromEnv_InvalidTLSPaths(t *testing.T) {
	t.Setenv("TLS_CERT_PATH", "/nonexistent/cert.pem")
	t.Setenv("TLS_KEY_PATH", "/nonexistent/key.pem")

	_, err := ConfigFromEnv()
	if err == nil {
		t.Fatal("expected error for invalid TLS cert/key paths")
	}
}
