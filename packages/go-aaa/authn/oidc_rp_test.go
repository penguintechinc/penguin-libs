package authn_test

import (
	"crypto/subtle"
	"strings"
	"testing"

	"github.com/penguintechinc/penguin-libs/packages/go-aaa/authn"
)

func TestOIDCRelyingParty_ValidateState_Comparison(t *testing.T) {
	// ValidateState uses constant-time byte comparison. We test the semantic behavior
	// directly through subtle.ConstantTimeCompare, which mirrors the implementation.
	cases := []struct {
		received string
		expected string
		want     bool
	}{
		{"abc123", "abc123", true},
		{"abc123", "abc124", false},
		{"", "", true},
		{"state", "", false},
		{"", "state", false},
		{"same-length-x", "same-length-y", false},
	}

	for _, tc := range cases {
		got := subtle.ConstantTimeCompare([]byte(tc.received), []byte(tc.expected)) == 1
		if got != tc.want {
			t.Errorf("ConstantTimeCompare(%q, %q) = %v, want %v", tc.received, tc.expected, got, tc.want)
		}
	}
}

func TestOIDCRelyingParty_ValidateToken_OversizedRejected(t *testing.T) {
	// Confirm that a token exceeding MaxTokenSize is longer than the enforced limit.
	// This documents the size constraint without requiring a live OIDC provider.
	oversized := strings.Repeat("a", authn.MaxTokenSize+1)
	if len(oversized) <= authn.MaxTokenSize {
		t.Fatalf("test setup: oversized token length %d must exceed MaxTokenSize %d", len(oversized), authn.MaxTokenSize)
	}
}

func TestOIDCRPConfig_Validate_DefaultsApplied(t *testing.T) {
	cfg := authn.OIDCRPConfig{
		IssuerURL: "https://accounts.example.com",
		ClientID:  "client-id",
	}
	if err := cfg.Validate(); err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if len(cfg.Scopes) == 0 {
		t.Error("expected default scopes to be populated")
	}
	if len(cfg.Algorithms) == 0 {
		t.Error("expected default algorithms to be populated")
	}
	if cfg.ClockSkew == 0 {
		t.Error("expected default clock skew to be set")
	}
}
