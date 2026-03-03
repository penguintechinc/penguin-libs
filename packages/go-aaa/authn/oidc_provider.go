package authn

import (
	"context"
	"encoding/json"
	"fmt"
	"time"

	"github.com/lestrrat-go/jwx/v2/jwa"
	"github.com/lestrrat-go/jwx/v2/jwk"
	"github.com/lestrrat-go/jwx/v2/jwt"
	"github.com/penguintechinc/penguin-libs/packages/go-aaa/crypto"
)

// OIDCProvider issues JWTs for subjects using a managed key store.
type OIDCProvider struct {
	cfg OIDCProviderConfig
	ks  crypto.KeyStore
}

// NewOIDCProvider creates an OIDCProvider with the given configuration and key store.
func NewOIDCProvider(cfg OIDCProviderConfig, ks crypto.KeyStore) (*OIDCProvider, error) {
	if err := cfg.Validate(); err != nil {
		return nil, fmt.Errorf("oidc_provider: invalid config: %w", err)
	}
	if ks == nil {
		return nil, fmt.Errorf("oidc_provider: key store is required")
	}
	return &OIDCProvider{cfg: cfg, ks: ks}, nil
}

// IssueTokenSet signs and returns an access token (and optionally an ID token)
// for the provided Claims. The claims must pass validation before tokens are issued.
// The context is accepted for interface compatibility and future use (e.g., key fetching).
func (p *OIDCProvider) IssueTokenSet(_ context.Context, claims *Claims) (*TokenSet, error) {
	if err := claims.Validate(); err != nil {
		return nil, fmt.Errorf("oidc_provider: invalid claims: %w", err)
	}

	signingKey, err := p.ks.GetSigningKey()
	if err != nil {
		return nil, fmt.Errorf("oidc_provider: failed to get signing key: %w", err)
	}

	now := time.Now()
	expiry := now.Add(p.cfg.TokenTTL)

	accessToken, err := p.buildToken(signingKey, claims, now, expiry)
	if err != nil {
		return nil, fmt.Errorf("oidc_provider: failed to build access token: %w", err)
	}

	idTokenExpiry := now.Add(p.cfg.TokenTTL)
	idToken, err := p.buildToken(signingKey, claims, now, idTokenExpiry)
	if err != nil {
		return nil, fmt.Errorf("oidc_provider: failed to build id token: %w", err)
	}

	refreshExpiry := now.Add(p.cfg.RefreshTTL)
	refreshClaims := &Claims{
		Sub: claims.Sub,
		Iss: claims.Iss,
		Aud: claims.Aud,
		Iat: now,
		Exp: refreshExpiry,
	}
	refreshToken, err := p.buildToken(signingKey, refreshClaims, now, refreshExpiry)
	if err != nil {
		return nil, fmt.Errorf("oidc_provider: failed to build refresh token: %w", err)
	}

	return &TokenSet{
		AccessToken:  accessToken,
		IDToken:      idToken,
		RefreshToken: refreshToken,
		ExpiresIn:    int64(p.cfg.TokenTTL.Seconds()),
		TokenType:    "Bearer",
	}, nil
}

// buildToken constructs and signs a JWT for the given claims and time window.
func (p *OIDCProvider) buildToken(signingKey jwk.Key, claims *Claims, now, expiry time.Time) (string, error) {
	builder := jwt.NewBuilder().
		Issuer(p.cfg.Issuer).
		Subject(claims.Sub).
		IssuedAt(now).
		Expiration(expiry)

	for _, aud := range p.cfg.Audiences {
		builder = builder.Audience([]string{aud})
	}

	if len(claims.Roles) > 0 {
		builder = builder.Claim("roles", claims.Roles)
	}
	if len(claims.Teams) > 0 {
		builder = builder.Claim("teams", claims.Teams)
	}
	if len(claims.Scope) > 0 {
		builder = builder.Claim("scope", claims.Scope)
	}
	if claims.Tenant != "" {
		builder = builder.Claim("tenant", claims.Tenant)
	}
	for k, v := range claims.Ext {
		builder = builder.Claim(k, v)
	}

	token, err := builder.Build()
	if err != nil {
		return "", fmt.Errorf("failed to build jwt: %w", err)
	}

	alg := jwa.RS256
	if p.cfg.Algorithm == "ES256" {
		alg = jwa.ES256
	}

	signed, err := jwt.Sign(token, jwt.WithKey(alg, signingKey))
	if err != nil {
		return "", fmt.Errorf("failed to sign jwt: %w", err)
	}

	return string(signed), nil
}

// DiscoveryDocument returns the OIDC discovery document as a JSON-serializable map.
// This is suitable for serving at /.well-known/openid-configuration.
func (p *OIDCProvider) DiscoveryDocument() ([]byte, error) {
	keySet, err := p.ks.GetKeySet()
	if err != nil {
		return nil, fmt.Errorf("oidc_provider: failed to get key set: %w", err)
	}

	jwksURI := p.cfg.Issuer + "/.well-known/jwks.json"

	doc := map[string]interface{}{
		"issuer":                                p.cfg.Issuer,
		"authorization_endpoint":                p.cfg.Issuer + "/oauth2/authorize",
		"token_endpoint":                        p.cfg.Issuer + "/oauth2/token",
		"jwks_uri":                              jwksURI,
		"response_types_supported":              []string{"code"},
		"subject_types_supported":               []string{"public"},
		"id_token_signing_alg_values_supported": AllowedProviderAlgorithms,
		"scopes_supported":                      []string{"openid", "profile", "email"},
		"token_endpoint_auth_methods_supported": []string{"client_secret_basic", "client_secret_post"},
		"claims_supported":                      []string{"sub", "iss", "aud", "iat", "exp", "roles", "teams", "tenant"},
		"key_count":                             keySet.Len(),
	}

	return json.Marshal(doc)
}
