package client

import (
	"testing"
	"time"
)

func TestCalcBackoff_Exponential(t *testing.T) {
	cfg := DefaultRetryConfig()
	cfg.Jitter = false

	backoff0 := calcBackoff(cfg, 0)
	backoff1 := calcBackoff(cfg, 1)
	backoff2 := calcBackoff(cfg, 2)

	// Verify exponential growth
	if backoff0 >= backoff1 {
		t.Errorf("expected backoff to increase: %v >= %v", backoff0, backoff1)
	}
	if backoff1 >= backoff2 {
		t.Errorf("expected backoff to increase: %v >= %v", backoff1, backoff2)
	}

	// Verify exponential relationship (backoff1 ≈ backoff0 * multiplier)
	expectedBackoff1 := time.Duration(float64(cfg.InitialBackoff) * cfg.Multiplier)
	if backoff1 != expectedBackoff1 {
		t.Errorf("expected backoff1 %v, got %v", expectedBackoff1, backoff1)
	}
}

func TestCalcBackoff_MaxCapped(t *testing.T) {
	cfg := DefaultRetryConfig()
	cfg.Jitter = false

	// Use a large attempt number to exceed max backoff
	backoff := calcBackoff(cfg, 100)

	if backoff > cfg.MaxBackoff {
		t.Errorf("expected backoff capped at MaxBackoff %v, got %v", cfg.MaxBackoff, backoff)
	}
}

func TestCalcBackoff_Jitter(t *testing.T) {
	cfg := DefaultRetryConfig()
	cfg.Jitter = true
	cfg.InitialBackoff = 1 * time.Second
	cfg.Multiplier = 1.0 // No exponential growth for easier testing

	backoff := calcBackoff(cfg, 0)

	// With jitter, result should be in range [0.5*base, 1.5*base]
	minExpected := time.Duration(float64(cfg.InitialBackoff) * 0.5)
	maxExpected := time.Duration(float64(cfg.InitialBackoff) * 1.5)

	if backoff < minExpected || backoff > maxExpected {
		t.Errorf("expected backoff in range [%v, %v], got %v", minExpected, maxExpected, backoff)
	}
}

func TestDefaultRetryConfig(t *testing.T) {
	cfg := DefaultRetryConfig()

	if cfg.MaxRetries != 3 {
		t.Errorf("expected MaxRetries 3, got %d", cfg.MaxRetries)
	}
	if cfg.InitialBackoff != 100*time.Millisecond {
		t.Errorf("expected InitialBackoff 100ms, got %v", cfg.InitialBackoff)
	}
	if cfg.MaxBackoff != 5*time.Second {
		t.Errorf("expected MaxBackoff 5s, got %v", cfg.MaxBackoff)
	}
	if cfg.Multiplier != 2.0 {
		t.Errorf("expected Multiplier 2.0, got %f", cfg.Multiplier)
	}
	if !cfg.Jitter {
		t.Error("expected Jitter true, got false")
	}
}
