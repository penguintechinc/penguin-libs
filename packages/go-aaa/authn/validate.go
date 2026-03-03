package authn

import (
	"fmt"
	"net/url"
	"strings"
	"time"
)

// OIDCRPConfig holds configuration for an OIDC Relying Party.
type OIDCRPConfig struct {
	// IssuerURL is the HTTPS URL of the OIDC provider (required).
	IssuerURL string
	// ClientID is the OAuth 2.0 client identifier (required).
	ClientID string
	// ClientSecret is the OAuth 2.0 client secret.
	ClientSecret string
	// RedirectURL is the callback URL registered with the provider.
	RedirectURL string
	// Scopes lists the OAuth 2.0 scopes to request. Defaults to ["openid"] if empty.
	Scopes []string
	// Algorithms lists the accepted JWT signing algorithms. Defaults to AllowedRPAlgorithms.
	Algorithms []string
	// ClockSkew is the allowed clock skew when validating token timestamps.
	// Minimum is zero, maximum is 5 minutes. Defaults to 30 seconds.
	ClockSkew time.Duration
}

// Validate checks that the OIDCRPConfig is complete and valid.
func (c *OIDCRPConfig) Validate() error {
	if err := validateHTTPSURL(c.IssuerURL); err != nil {
		return fmt.Errorf("oidc_rp_config: issuer_url: %w", err)
	}
	if c.ClientID == "" {
		return fmt.Errorf("oidc_rp_config: client_id is required")
	}
	if len(c.Scopes) == 0 {
		c.Scopes = []string{"openid"}
	}
	if len(c.Algorithms) == 0 {
		c.Algorithms = AllowedRPAlgorithms
	}
	if c.ClockSkew == 0 {
		c.ClockSkew = 30 * time.Second
	}
	const maxClockSkew = 5 * time.Minute
	if c.ClockSkew > maxClockSkew {
		return fmt.Errorf("oidc_rp_config: clock_skew must not exceed %s", maxClockSkew)
	}
	return nil
}

// OIDCProviderConfig holds configuration for an OIDC token provider (issuer).
type OIDCProviderConfig struct {
	// Issuer is the HTTPS URL that identifies this provider (required).
	Issuer string
	// Audiences lists the token audiences this provider issues tokens for (required).
	Audiences []string
	// Algorithm is the JWT signing algorithm. Must be RS256 or ES256. Defaults to RS256.
	Algorithm string
	// TokenTTL is the lifetime of issued access tokens. Defaults to 1 hour.
	TokenTTL time.Duration
	// RefreshTTL is the lifetime of issued refresh tokens. Defaults to 24 hours.
	RefreshTTL time.Duration
}

// Validate checks that the OIDCProviderConfig is complete and valid.
func (c *OIDCProviderConfig) Validate() error {
	if err := validateHTTPSURL(c.Issuer); err != nil {
		return fmt.Errorf("oidc_provider_config: issuer: %w", err)
	}
	if len(c.Audiences) == 0 {
		return fmt.Errorf("oidc_provider_config: audiences must contain at least one entry")
	}
	if c.Algorithm == "" {
		c.Algorithm = "RS256"
	}
	if !isAllowedProviderAlgorithm(c.Algorithm) {
		return fmt.Errorf("oidc_provider_config: algorithm %q is not allowed; must be one of %v", c.Algorithm, AllowedProviderAlgorithms)
	}
	if c.TokenTTL == 0 {
		c.TokenTTL = time.Hour
	}
	if c.RefreshTTL == 0 {
		c.RefreshTTL = 24 * time.Hour
	}
	return nil
}

// SPIFFEConfig holds configuration for SPIFFE/SVID-based authentication.
type SPIFFEConfig struct {
	// TrustDomain is the SPIFFE trust domain (e.g., "example.org") (required).
	TrustDomain string
	// WorkloadSocket is the path to the SPIFFE Workload API socket (required).
	WorkloadSocket string
	// AllowedIDs lists SPIFFE IDs that are permitted to authenticate.
	// Each entry must begin with "spiffe://" (required, at least one entry).
	AllowedIDs []string
}

// Validate checks that the SPIFFEConfig is complete and valid.
func (c *SPIFFEConfig) Validate() error {
	if c.TrustDomain == "" {
		return fmt.Errorf("spiffe_config: trust_domain is required")
	}
	if c.WorkloadSocket == "" {
		return fmt.Errorf("spiffe_config: workload_socket is required")
	}
	if len(c.AllowedIDs) == 0 {
		return fmt.Errorf("spiffe_config: allowed_ids must contain at least one entry")
	}
	for i, id := range c.AllowedIDs {
		if !strings.HasPrefix(id, "spiffe://") {
			return fmt.Errorf("spiffe_config: allowed_ids[%d] %q must begin with \"spiffe://\"", i, id)
		}
	}
	return nil
}

// validateHTTPSURL returns an error if s is not a valid HTTPS URL.
func validateHTTPSURL(s string) error {
	if s == "" {
		return fmt.Errorf("url is required")
	}
	u, err := url.Parse(s)
	if err != nil {
		return fmt.Errorf("invalid url %q: %w", s, err)
	}
	if u.Scheme != "https" {
		return fmt.Errorf("url %q must use HTTPS scheme", s)
	}
	if u.Host == "" {
		return fmt.Errorf("url %q must include a host", s)
	}
	return nil
}

// isAllowedProviderAlgorithm reports whether alg is in AllowedProviderAlgorithms.
func isAllowedProviderAlgorithm(alg string) bool {
	for _, allowed := range AllowedProviderAlgorithms {
		if alg == allowed {
			return true
		}
	}
	return false
}
