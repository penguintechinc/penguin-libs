// Package authn provides authentication types and validation for Penguin Tech applications.
//
// It supports OIDC relying party, OIDC provider, and SPIFFE/SVID-based authentication patterns.
package authn

import (
	"fmt"
	"time"
)

// MaxSubjectLength is the maximum allowed length for a subject identifier.
const MaxSubjectLength = 256

// MaxTokenSize is the maximum allowed size in bytes for a raw token string.
const MaxTokenSize = 8192

// AllowedRPAlgorithms lists the JWT signing algorithms accepted by the relying party.
var AllowedRPAlgorithms = []string{"RS256", "ES256", "PS256"}

// AllowedProviderAlgorithms lists the JWT signing algorithms that can be used when issuing tokens.
var AllowedProviderAlgorithms = []string{"RS256", "ES256"}

// Claims represents the standard and extended claims extracted from a validated JWT.
type Claims struct {
	// Sub is the subject identifier (required).
	Sub string `json:"sub"`
	// Iss is the token issuer (required).
	Iss string `json:"iss"`
	// Aud contains the intended audiences (required, at least one entry).
	Aud []string `json:"aud"`
	// Iat is the time the token was issued (required).
	Iat time.Time `json:"iat"`
	// Exp is the expiry time of the token (required).
	Exp time.Time `json:"exp"`
	// Scope lists OAuth 2.0 scopes granted to the token.
	Scope []string `json:"scope,omitempty"`
	// Roles lists application roles assigned to the subject.
	Roles []string `json:"roles,omitempty"`
	// Teams lists team memberships for the subject.
	Teams []string `json:"teams,omitempty"`
	// Tenant is the tenant identifier for multi-tenant applications.
	Tenant string `json:"tenant,omitempty"`
	// Ext holds additional application-specific claims.
	Ext map[string]interface{} `json:"ext,omitempty"`
}

// Validate checks that all required fields are present and within allowed bounds.
func (c *Claims) Validate() error {
	if c.Sub == "" {
		return fmt.Errorf("claims: sub is required")
	}
	if len(c.Sub) > MaxSubjectLength {
		return fmt.Errorf("claims: sub exceeds maximum length of %d", MaxSubjectLength)
	}
	if c.Iss == "" {
		return fmt.Errorf("claims: iss is required")
	}
	if len(c.Aud) == 0 {
		return fmt.Errorf("claims: aud must contain at least one audience")
	}
	if c.Iat.IsZero() {
		return fmt.Errorf("claims: iat is required")
	}
	if c.Exp.IsZero() {
		return fmt.Errorf("claims: exp is required")
	}
	if !c.Exp.After(c.Iat) {
		return fmt.Errorf("claims: exp must be after iat")
	}
	return nil
}

// TokenSet holds the full set of tokens returned from a token exchange.
type TokenSet struct {
	// AccessToken is the OAuth 2.0 access token.
	AccessToken string `json:"access_token"`
	// IDToken is the OpenID Connect identity token.
	IDToken string `json:"id_token,omitempty"`
	// RefreshToken is used to obtain new access tokens.
	RefreshToken string `json:"refresh_token,omitempty"`
	// ExpiresIn is the number of seconds until the access token expires.
	ExpiresIn int64 `json:"expires_in"`
	// TokenType describes the type of the access token (typically "Bearer").
	TokenType string `json:"token_type"`
}
