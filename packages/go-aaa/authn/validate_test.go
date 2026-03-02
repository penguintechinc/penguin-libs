package authn_test

import (
	"testing"
	"time"

	"github.com/penguintechinc/penguin-libs/packages/go-aaa/authn"
)

func TestOIDCRPConfig_Validate_Valid(t *testing.T) {
	cfg := authn.OIDCRPConfig{
		IssuerURL: "https://accounts.example.com",
		ClientID:  "my-client",
	}
	if err := cfg.Validate(); err != nil {
		t.Fatalf("expected valid config, got: %v", err)
	}
	if cfg.ClockSkew != 30*time.Second {
		t.Errorf("expected default clock skew 30s, got %v", cfg.ClockSkew)
	}
	if len(cfg.Scopes) == 0 || cfg.Scopes[0] != "openid" {
		t.Errorf("expected default scope [openid], got %v", cfg.Scopes)
	}
}

func TestOIDCRPConfig_Validate_HTTPIssuer(t *testing.T) {
	cfg := authn.OIDCRPConfig{
		IssuerURL: "http://accounts.example.com",
		ClientID:  "my-client",
	}
	if err := cfg.Validate(); err == nil {
		t.Fatal("expected error for HTTP issuer URL")
	}
}

func TestOIDCRPConfig_Validate_MissingClientID(t *testing.T) {
	cfg := authn.OIDCRPConfig{
		IssuerURL: "https://accounts.example.com",
	}
	if err := cfg.Validate(); err == nil {
		t.Fatal("expected error for missing client ID")
	}
}

func TestOIDCRPConfig_Validate_ClockSkewExceeded(t *testing.T) {
	cfg := authn.OIDCRPConfig{
		IssuerURL: "https://accounts.example.com",
		ClientID:  "my-client",
		ClockSkew: 10 * time.Minute,
	}
	if err := cfg.Validate(); err == nil {
		t.Fatal("expected error for clock skew > 5 minutes")
	}
}

func TestOIDCRPConfig_Validate_EmptyIssuerURL(t *testing.T) {
	cfg := authn.OIDCRPConfig{
		ClientID: "my-client",
	}
	if err := cfg.Validate(); err == nil {
		t.Fatal("expected error for empty issuer URL")
	}
}

func TestOIDCProviderConfig_Validate_Valid(t *testing.T) {
	cfg := authn.OIDCProviderConfig{
		Issuer:    "https://issuer.example.com",
		Audiences: []string{"my-app"},
	}
	if err := cfg.Validate(); err != nil {
		t.Fatalf("expected valid config, got: %v", err)
	}
	if cfg.Algorithm != "RS256" {
		t.Errorf("expected default algorithm RS256, got %q", cfg.Algorithm)
	}
	if cfg.TokenTTL != time.Hour {
		t.Errorf("expected default token TTL 1h, got %v", cfg.TokenTTL)
	}
	if cfg.RefreshTTL != 24*time.Hour {
		t.Errorf("expected default refresh TTL 24h, got %v", cfg.RefreshTTL)
	}
}

func TestOIDCProviderConfig_Validate_HTTPIssuer(t *testing.T) {
	cfg := authn.OIDCProviderConfig{
		Issuer:    "http://issuer.example.com",
		Audiences: []string{"my-app"},
	}
	if err := cfg.Validate(); err == nil {
		t.Fatal("expected error for HTTP issuer URL")
	}
}

func TestOIDCProviderConfig_Validate_EmptyAudiences(t *testing.T) {
	cfg := authn.OIDCProviderConfig{
		Issuer: "https://issuer.example.com",
	}
	if err := cfg.Validate(); err == nil {
		t.Fatal("expected error for empty audiences")
	}
}

func TestOIDCProviderConfig_Validate_InvalidAlgorithm(t *testing.T) {
	cfg := authn.OIDCProviderConfig{
		Issuer:    "https://issuer.example.com",
		Audiences: []string{"my-app"},
		Algorithm: "PS256",
	}
	if err := cfg.Validate(); err == nil {
		t.Fatal("expected error for PS256 which is not an allowed provider algorithm")
	}
}

func TestSPIFFEConfig_Validate_Valid(t *testing.T) {
	cfg := authn.SPIFFEConfig{
		TrustDomain:    "example.org",
		WorkloadSocket: "/run/spire/sockets/agent.sock",
		AllowedIDs:     []string{"spiffe://example.org/service/api"},
	}
	if err := cfg.Validate(); err != nil {
		t.Fatalf("expected valid config, got: %v", err)
	}
}

func TestSPIFFEConfig_Validate_MissingTrustDomain(t *testing.T) {
	cfg := authn.SPIFFEConfig{
		WorkloadSocket: "/run/spire/sockets/agent.sock",
		AllowedIDs:     []string{"spiffe://example.org/service/api"},
	}
	if err := cfg.Validate(); err == nil {
		t.Fatal("expected error for missing trust domain")
	}
}

func TestSPIFFEConfig_Validate_MissingWorkloadSocket(t *testing.T) {
	cfg := authn.SPIFFEConfig{
		TrustDomain: "example.org",
		AllowedIDs:  []string{"spiffe://example.org/service/api"},
	}
	if err := cfg.Validate(); err == nil {
		t.Fatal("expected error for missing workload socket")
	}
}

func TestSPIFFEConfig_Validate_EmptyAllowedIDs(t *testing.T) {
	cfg := authn.SPIFFEConfig{
		TrustDomain:    "example.org",
		WorkloadSocket: "/run/spire/sockets/agent.sock",
	}
	if err := cfg.Validate(); err == nil {
		t.Fatal("expected error for empty allowed IDs")
	}
}

func TestSPIFFEConfig_Validate_InvalidIDPrefix(t *testing.T) {
	cfg := authn.SPIFFEConfig{
		TrustDomain:    "example.org",
		WorkloadSocket: "/run/spire/sockets/agent.sock",
		AllowedIDs:     []string{"https://example.org/service/api"},
	}
	if err := cfg.Validate(); err == nil {
		t.Fatal("expected error for ID without spiffe:// prefix")
	}
}
