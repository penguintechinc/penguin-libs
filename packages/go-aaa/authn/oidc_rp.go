package authn

import (
	"context"
	"crypto/subtle"
	"encoding/json"
	"fmt"
	"net/http"
	"net/url"
	"strings"
	"sync"
	"time"

	gooidc "github.com/coreos/go-oidc/v3/oidc"
	"golang.org/x/oauth2"
)

// OIDCRelyingParty validates tokens issued by an external OIDC provider and
// handles the Authorization Code flow on behalf of the application.
type OIDCRelyingParty struct {
	cfg            OIDCRPConfig
	provider       *gooidc.Provider
	verifier       *gooidc.IDTokenVerifier
	oauth2         oauth2.Config
	discovery      map[string]interface{}
	discoveryOnce  sync.Once
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
// If expectedNonce is provided and non-empty, it validates the nonce claim in the token
// using constant-time comparison.
func (rp *OIDCRelyingParty) ValidateToken(ctx context.Context, rawToken string, expectedNonce ...string) (*Claims, error) {
	if len(rawToken) > MaxTokenSize {
		return nil, fmt.Errorf("oidc_rp: token size %d exceeds maximum of %d bytes", len(rawToken), MaxTokenSize)
	}

	idToken, err := rp.verifier.Verify(ctx, rawToken)
	if err != nil {
		return nil, fmt.Errorf("oidc_rp: token verification failed: %w", err)
	}

	// Validate nonce if provided
	if len(expectedNonce) > 0 && expectedNonce[0] != "" {
		var nonceClaims struct {
			Nonce string `json:"nonce"`
		}
		if err := idToken.Claims(&nonceClaims); err != nil {
			return nil, fmt.Errorf("oidc_rp: failed to extract nonce claim: %w", err)
		}
		if subtle.ConstantTimeCompare([]byte(nonceClaims.Nonce), []byte(expectedNonce[0])) != 1 {
			return nil, fmt.Errorf("oidc_rp: nonce mismatch")
		}
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

// Refresh exchanges a refresh token for a new TokenSet.
// It calls the provider's token_endpoint with grant_type=refresh_token.
func (rp *OIDCRelyingParty) Refresh(ctx context.Context, refreshToken string) (*TokenSet, error) {
	token := &oauth2.Token{RefreshToken: refreshToken}
	tokenSource := rp.oauth2.TokenSource(ctx, token)
	newToken, err := tokenSource.Token()
	if err != nil {
		return nil, fmt.Errorf("oidc_rp: refresh failed: %w", err)
	}
	idTokenRaw, _ := newToken.Extra("id_token").(string)
	expiresIn := int64(0)
	if !newToken.Expiry.IsZero() {
		expiresIn = int64(time.Until(newToken.Expiry).Seconds())
	}
	return &TokenSet{
		AccessToken:  newToken.AccessToken,
		IDToken:      idTokenRaw,
		RefreshToken: newToken.RefreshToken,
		ExpiresIn:    expiresIn,
		TokenType:    newToken.TokenType,
	}, nil
}

// Revoke calls the provider's revocation endpoint (RFC 7009) to invalidate a token.
// tokenTypeHint is optional (e.g., "access_token" or "refresh_token").
func (rp *OIDCRelyingParty) Revoke(ctx context.Context, token string, tokenTypeHint string) error {
	discovery, err := rp.getDiscovery(ctx)
	if err != nil {
		return fmt.Errorf("oidc_rp: revoke discovery failed: %w", err)
	}
	revocationEndpoint, ok := discovery["revocation_endpoint"].(string)
	if !ok || revocationEndpoint == "" {
		return fmt.Errorf("oidc_rp: provider does not support token revocation")
	}

	params := url.Values{"token": {token}, "client_id": {rp.cfg.ClientID}}
	if tokenTypeHint != "" {
		params.Set("token_type_hint", tokenTypeHint)
	}

	req, err := http.NewRequestWithContext(ctx, http.MethodPost, revocationEndpoint,
		strings.NewReader(params.Encode()))
	if err != nil {
		return fmt.Errorf("oidc_rp: revoke request creation failed: %w", err)
	}
	req.Header.Set("Content-Type", "application/x-www-form-urlencoded")
	req.SetBasicAuth(rp.cfg.ClientID, rp.cfg.ClientSecret)

	resp, err := http.DefaultClient.Do(req)
	if err != nil {
		return fmt.Errorf("oidc_rp: revoke request failed: %w", err)
	}
	defer resp.Body.Close()
	if resp.StatusCode >= 400 {
		return fmt.Errorf("oidc_rp: revoke returned status %d", resp.StatusCode)
	}
	return nil
}

// Introspect calls the provider's introspection endpoint (RFC 7662).
// Returns the introspection response as a map. "active" key indicates token validity.
func (rp *OIDCRelyingParty) Introspect(ctx context.Context, token string) (map[string]interface{}, error) {
	discovery, err := rp.getDiscovery(ctx)
	if err != nil {
		return nil, fmt.Errorf("oidc_rp: introspect discovery failed: %w", err)
	}
	introspectionEndpoint, ok := discovery["introspection_endpoint"].(string)
	if !ok || introspectionEndpoint == "" {
		return nil, fmt.Errorf("oidc_rp: provider does not support token introspection")
	}

	params := url.Values{"token": {token}, "client_id": {rp.cfg.ClientID}}
	req, err := http.NewRequestWithContext(ctx, http.MethodPost, introspectionEndpoint,
		strings.NewReader(params.Encode()))
	if err != nil {
		return nil, fmt.Errorf("oidc_rp: introspect request creation failed: %w", err)
	}
	req.Header.Set("Content-Type", "application/x-www-form-urlencoded")
	req.SetBasicAuth(rp.cfg.ClientID, rp.cfg.ClientSecret)

	resp, err := http.DefaultClient.Do(req)
	if err != nil {
		return nil, fmt.Errorf("oidc_rp: introspect request failed: %w", err)
	}
	defer resp.Body.Close()

	var result map[string]interface{}
	if err := json.NewDecoder(resp.Body).Decode(&result); err != nil {
		return nil, fmt.Errorf("oidc_rp: introspect response decode failed: %w", err)
	}
	return result, nil
}

// getDiscovery fetches and caches the OIDC provider's discovery document.
// It is called once and the result is cached in the OIDCRelyingParty instance.
func (rp *OIDCRelyingParty) getDiscovery(ctx context.Context) (map[string]interface{}, error) {
	var discoveryErr error
	rp.discoveryOnce.Do(func() {
		endpoint := strings.TrimSuffix(rp.cfg.IssuerURL, "/") + "/.well-known/openid-configuration"
		req, err := http.NewRequestWithContext(ctx, http.MethodGet, endpoint, nil)
		if err != nil {
			discoveryErr = fmt.Errorf("failed to create discovery request: %w", err)
			return
		}
		resp, err := http.DefaultClient.Do(req)
		if err != nil {
			discoveryErr = fmt.Errorf("failed to fetch discovery document: %w", err)
			return
		}
		defer resp.Body.Close()
		if resp.StatusCode != http.StatusOK {
			discoveryErr = fmt.Errorf("discovery request returned status %d", resp.StatusCode)
			return
		}
		if err := json.NewDecoder(resp.Body).Decode(&rp.discovery); err != nil {
			discoveryErr = fmt.Errorf("failed to decode discovery document: %w", err)
			return
		}
	})
	if discoveryErr != nil {
		return nil, discoveryErr
	}
	return rp.discovery, nil
}
