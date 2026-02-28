package authn

import (
	"context"
	"crypto/subtle"
	"fmt"
	"time"

	gooidc "github.com/coreos/go-oidc/v3/oidc"
	"golang.org/x/oauth2"
)

// OIDCRelyingParty validates tokens issued by an external OIDC provider and
// handles the Authorization Code flow on behalf of the application.
type OIDCRelyingParty struct {
	cfg      OIDCRPConfig
	provider *gooidc.Provider
	verifier *gooidc.IDTokenVerifier
	oauth2   oauth2.Config
}

// NewOIDCRelyingParty creates an OIDCRelyingParty by discovering the provider's
// OIDC configuration from cfg.IssuerURL and configuring token verification.
func NewOIDCRelyingParty(ctx context.Context, cfg OIDCRPConfig) (*OIDCRelyingParty, error) {
	if err := cfg.Validate(); err != nil {
		return nil, fmt.Errorf("oidc_rp: invalid config: %w", err)
	}

	provider, err := gooidc.NewProvider(ctx, cfg.IssuerURL)
	if err != nil {
		return nil, fmt.Errorf("oidc_rp: provider discovery failed for %q: %w", cfg.IssuerURL, err)
	}

	verifierCfg := &gooidc.Config{
		ClientID:             cfg.ClientID,
		SupportedSigningAlgs: cfg.Algorithms,
		Now:                  time.Now,
	}
	verifier := provider.Verifier(verifierCfg)

	oauth2Cfg := oauth2.Config{
		ClientID:     cfg.ClientID,
		ClientSecret: cfg.ClientSecret,
		RedirectURL:  cfg.RedirectURL,
		Endpoint:     provider.Endpoint(),
		Scopes:       cfg.Scopes,
	}

	return &OIDCRelyingParty{
		cfg:      cfg,
		provider: provider,
		verifier: verifier,
		oauth2:   oauth2Cfg,
	}, nil
}

// ValidateToken verifies rawToken against the configured provider and returns
// the extracted Claims. It enforces the MaxTokenSize limit before parsing.
func (rp *OIDCRelyingParty) ValidateToken(ctx context.Context, rawToken string) (*Claims, error) {
	if len(rawToken) > MaxTokenSize {
		return nil, fmt.Errorf("oidc_rp: token size %d exceeds maximum of %d bytes", len(rawToken), MaxTokenSize)
	}

	idToken, err := rp.verifier.Verify(ctx, rawToken)
	if err != nil {
		return nil, fmt.Errorf("oidc_rp: token verification failed: %w", err)
	}

	var raw struct {
		Scope  []string               `json:"scope"`
		Roles  []string               `json:"roles"`
		Teams  []string               `json:"teams"`
		Tenant string                 `json:"tenant"`
		Ext    map[string]interface{} `json:"ext"`
	}
	if err := idToken.Claims(&raw); err != nil {
		return nil, fmt.Errorf("oidc_rp: failed to extract custom claims: %w", err)
	}

	claims := &Claims{
		Sub:    idToken.Subject,
		Iss:    idToken.Issuer,
		Aud:    idToken.Audience,
		Iat:    idToken.IssuedAt,
		Exp:    idToken.Expiry,
		Scope:  raw.Scope,
		Roles:  raw.Roles,
		Teams:  raw.Teams,
		Tenant: raw.Tenant,
		Ext:    raw.Ext,
	}

	if err := claims.Validate(); err != nil {
		return nil, fmt.Errorf("oidc_rp: invalid claims: %w", err)
	}

	return claims, nil
}

// AuthCodeURL returns the URL to redirect the user to for authorization.
func (rp *OIDCRelyingParty) AuthCodeURL(state string, opts ...oauth2.AuthCodeOption) string {
	return rp.oauth2.AuthCodeURL(state, opts...)
}

// Exchange exchanges the authorization code for a TokenSet.
func (rp *OIDCRelyingParty) Exchange(ctx context.Context, code string, opts ...oauth2.AuthCodeOption) (*TokenSet, error) {
	token, err := rp.oauth2.Exchange(ctx, code, opts...)
	if err != nil {
		return nil, fmt.Errorf("oidc_rp: code exchange failed: %w", err)
	}

	idTokenRaw, _ := token.Extra("id_token").(string)
	expiresIn := int64(0)
	if !token.Expiry.IsZero() {
		expiresIn = int64(time.Until(token.Expiry).Seconds())
	}

	return &TokenSet{
		AccessToken:  token.AccessToken,
		IDToken:      idTokenRaw,
		RefreshToken: token.RefreshToken,
		ExpiresIn:    expiresIn,
		TokenType:    token.TokenType,
	}, nil
}

// ValidateState compares the received state with the expected state using
// constant-time comparison to prevent timing attacks.
func (rp *OIDCRelyingParty) ValidateState(received, expected string) bool {
	return subtle.ConstantTimeCompare([]byte(received), []byte(expected)) == 1
}
