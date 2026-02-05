package client

import (
	"testing"
	"time"
)

func TestDefaultClientConfig(t *testing.T) {
	cfg := DefaultClientConfig()

	if !cfg.H3Enabled {
		t.Error("expected H3Enabled true, got false")
	}
	if cfg.H3Timeout != 5*time.Second {
		t.Errorf("expected H3Timeout 5s, got %v", cfg.H3Timeout)
	}
	if cfg.H3RetryInterval != 5*time.Minute {
		t.Errorf("expected H3RetryInterval 5m, got %v", cfg.H3RetryInterval)
	}
	if cfg.RequestTimeout != 30*time.Second {
		t.Errorf("expected RequestTimeout 30s, got %v", cfg.RequestTimeout)
	}
}
