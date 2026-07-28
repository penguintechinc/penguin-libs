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

func TestClient_Close_ReleasesResources(t *testing.T) {
	logger := zap.NewNop()
	cfg := DefaultClientConfig()
	client := New(cfg, logger)

	// Close should not panic and should successfully close resources
	err := client.Close()
	if err != nil {
		t.Errorf("Close() should not return error, got %v", err)
	}
}

func TestClient_HTTPClient_ReturnsH3Client(t *testing.T) {
	logger := zap.NewNop()
	cfg := DefaultClientConfig()
	cfg.H3Enabled = true

	client := New(cfg, logger)
	httpClient := client.HTTPClient()

	if httpClient == nil {
		t.Error("HTTPClient() should not return nil")
	}

	// Should return h3Client when protocol is h3
	if client.Protocol() != "h3" {
		t.Errorf("expected protocol h3, got %s", client.Protocol())
	}
}

func TestClient_HTTPClient_ReturnsH2Client(t *testing.T) {
	logger := zap.NewNop()
	cfg := DefaultClientConfig()
	cfg.H3Enabled = false

	client := New(cfg, logger)
	httpClient := client.HTTPClient()

	if httpClient == nil {
		t.Error("HTTPClient() should not return nil")
	}

	// Should return h2Client when protocol is h2
	if client.Protocol() != "h2" {
		t.Errorf("expected protocol h2, got %s", client.Protocol())
	}
}

func TestClient_HTTPClient_FallbackAfterH3Failure(t *testing.T) {
	logger := zap.NewNop()
	cfg := DefaultClientConfig()
	cfg.H3Enabled = true

	client := New(cfg, logger)

	// Verify we start with H3
	if client.Protocol() != "h3" {
		t.Errorf("expected initial protocol h3, got %s", client.Protocol())
	}

	// Simulate H3 failure
	client.MarkH3Failed()

	// After failure, HTTPClient should return h2 client
	httpClient := client.HTTPClient()
	if httpClient == nil {
		t.Error("HTTPClient() should not return nil after fallback")
	}

	if client.Protocol() != "h2" {
		t.Errorf("expected protocol h2 after fallback, got %s", client.Protocol())
	}
}
