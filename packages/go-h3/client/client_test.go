package client

import (
	"go.uber.org/zap"
	"testing"
	"time"
)

func TestNew_CreatesClient(t *testing.T) {
	logger := zap.NewNop()
	client := New(DefaultClientConfig(), logger)

	if client == nil {
		t.Error("expected non-nil client, got nil")
	}
}

func TestClient_Protocol_H3(t *testing.T) {
	logger := zap.NewNop()
	cfg := DefaultClientConfig()
	cfg.H3Enabled = true

	client := New(cfg, logger)

	if client.Protocol() != "h3" {
		t.Errorf("expected protocol h3, got %s", client.Protocol())
	}
}

func TestClient_Protocol_H2(t *testing.T) {
	logger := zap.NewNop()
	cfg := DefaultClientConfig()
	cfg.H3Enabled = false

	client := New(cfg, logger)

	if client.Protocol() != "h2" {
		t.Errorf("expected protocol h2, got %s", client.Protocol())
	}
}

func TestClient_MarkH3Failed(t *testing.T) {
	logger := zap.NewNop()
	cfg := DefaultClientConfig()
	cfg.H3Enabled = true

	client := New(cfg, logger)

	if client.Protocol() != "h3" {
		t.Errorf("expected initial protocol h3, got %s", client.Protocol())
	}

	client.MarkH3Failed()

	if client.Protocol() != "h2" {
		t.Errorf("expected protocol h2 after MarkH3Failed, got %s", client.Protocol())
	}
}

func TestClient_MaybeRetryH3_TooSoon(t *testing.T) {
	logger := zap.NewNop()
	cfg := DefaultClientConfig()
	cfg.H3Enabled = true
	cfg.H3RetryInterval = 1 * time.Minute

	client := New(cfg, logger)

	// Mark as failed
	client.MarkH3Failed()

	if client.Protocol() != "h2" {
		t.Errorf("expected protocol h2 after failure, got %s", client.Protocol())
	}

	// Try to retry immediately
	client.MaybeRetryH3()

	// Should still be h2
	if client.Protocol() != "h2" {
		t.Errorf("expected protocol h2 (too soon to retry), got %s", client.Protocol())
	}
}
