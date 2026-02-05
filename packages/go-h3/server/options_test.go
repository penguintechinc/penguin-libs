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

func TestConfigFromEnv_Disabled(t *testing.T) {
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
