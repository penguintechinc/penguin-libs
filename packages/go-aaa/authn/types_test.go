package authn_test

import (
	"testing"
	"time"

	"github.com/penguintechinc/penguin-libs/packages/go-aaa/authn"
)

func TestClaims_Validate_Valid(t *testing.T) {
	now := time.Now()
	c := &authn.Claims{
		Sub: "user-123",
		Iss: "https://issuer.example.com",
		Aud: []string{"my-app"},
		Iat: now,
		Exp: now.Add(time.Hour),
	}
	if err := c.Validate(); err != nil {
		t.Fatalf("expected valid claims, got: %v", err)
	}
}

func TestClaims_Validate_MissingSub(t *testing.T) {
	now := time.Now()
	c := &authn.Claims{
		Iss: "https://issuer.example.com",
		Aud: []string{"my-app"},
		Iat: now,
		Exp: now.Add(time.Hour),
	}
	if err := c.Validate(); err == nil {
		t.Fatal("expected error for missing sub")
	}
}

func TestClaims_Validate_SubTooLong(t *testing.T) {
	now := time.Now()
	longSub := make([]byte, authn.MaxSubjectLength+1)
	for i := range longSub {
		longSub[i] = 'a'
	}
	c := &authn.Claims{
		Sub: string(longSub),
		Iss: "https://issuer.example.com",
		Aud: []string{"my-app"},
		Iat: now,
		Exp: now.Add(time.Hour),
	}
	if err := c.Validate(); err == nil {
		t.Fatal("expected error for sub exceeding MaxSubjectLength")
	}
}

func TestClaims_Validate_MissingIss(t *testing.T) {
	now := time.Now()
	c := &authn.Claims{
		Sub: "user-123",
		Aud: []string{"my-app"},
		Iat: now,
		Exp: now.Add(time.Hour),
	}
	if err := c.Validate(); err == nil {
		t.Fatal("expected error for missing iss")
	}
}

func TestClaims_Validate_EmptyAud(t *testing.T) {
	now := time.Now()
	c := &authn.Claims{
		Sub: "user-123",
		Iss: "https://issuer.example.com",
		Iat: now,
		Exp: now.Add(time.Hour),
	}
	if err := c.Validate(); err == nil {
		t.Fatal("expected error for empty aud")
	}
}

func TestClaims_Validate_ZeroIat(t *testing.T) {
	now := time.Now()
	c := &authn.Claims{
		Sub: "user-123",
		Iss: "https://issuer.example.com",
		Aud: []string{"my-app"},
		Exp: now.Add(time.Hour),
	}
	if err := c.Validate(); err == nil {
		t.Fatal("expected error for zero iat")
	}
}

func TestClaims_Validate_ZeroExp(t *testing.T) {
	now := time.Now()
	c := &authn.Claims{
		Sub: "user-123",
		Iss: "https://issuer.example.com",
		Aud: []string{"my-app"},
		Iat: now,
	}
	if err := c.Validate(); err == nil {
		t.Fatal("expected error for zero exp")
	}
}

func TestClaims_Validate_ExpBeforeIat(t *testing.T) {
	now := time.Now()
	c := &authn.Claims{
		Sub: "user-123",
		Iss: "https://issuer.example.com",
		Aud: []string{"my-app"},
		Iat: now,
		Exp: now.Add(-time.Hour),
	}
	if err := c.Validate(); err == nil {
		t.Fatal("expected error when exp is before iat")
	}
}

func TestMaxConstants(t *testing.T) {
	if authn.MaxSubjectLength != 256 {
		t.Errorf("expected MaxSubjectLength=256, got %d", authn.MaxSubjectLength)
	}
	if authn.MaxTokenSize != 8192 {
		t.Errorf("expected MaxTokenSize=8192, got %d", authn.MaxTokenSize)
	}
}

func TestAllowedAlgorithms(t *testing.T) {
	rpAlgs := map[string]bool{"RS256": true, "ES256": true, "PS256": true}
	for _, alg := range authn.AllowedRPAlgorithms {
		if !rpAlgs[alg] {
			t.Errorf("unexpected RP algorithm: %q", alg)
		}
	}

	provAlgs := map[string]bool{"RS256": true, "ES256": true}
	for _, alg := range authn.AllowedProviderAlgorithms {
		if !provAlgs[alg] {
			t.Errorf("unexpected provider algorithm: %q", alg)
		}
	}
}
