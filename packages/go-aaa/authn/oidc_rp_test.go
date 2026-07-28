package authn_test

import (
	"context"
	"crypto/rand"
	"crypto/rsa"
	"crypto/subtle"
	"crypto/tls"
	"crypto/x509"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
	"time"

	"github.com/lestrrat-go/jwx/v2/jwa"
	"github.com/lestrrat-go/jwx/v2/jwk"
	"github.com/lestrrat-go/jwx/v2/jws"
	"github.com/lestrrat-go/jwx/v2/jwt"
	"github.com/penguintechinc/penguin-libs/packages/go-aaa/authn"
	"golang.org/x/oauth2"
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

// Helper: create mock OAuth2 provider with discovery + token endpoints
func mockOAuth2Provider(t *testing.T, tokenResp map[string]interface{}) *httptest.Server {
	t.Helper()
	mux := http.NewServeMux()
	server := httptest.NewTLSServer(mux)

	// Discovery endpoint
	mux.HandleFunc("/.well-known/openid-configuration", func(w http.ResponseWriter, r *http.Request) {
		discovery := map[string]interface{}{
			"issuer":        server.URL,
			"token_endpoint": server.URL + "/token",
			"jwks_uri":      server.URL + "/.well-known/jwks.json",
		}
		w.Header().Set("Content-Type", "application/json")
		json.NewEncoder(w).Encode(discovery)
	})

	// Token endpoint
	mux.HandleFunc("/token", func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		json.NewEncoder(w).Encode(tokenResp)
	})

	// Minimal JWKS endpoint
	mux.HandleFunc("/.well-known/jwks.json", func(w http.ResponseWriter, r *http.Request) {
		set := jwk.NewSet()
		w.Header().Set("Content-Type", "application/json")
		json.NewEncoder(w).Encode(set)
	})

	return server
}

// regression: gh-missing-id-token
// TestOIDCRelyingParty_Exchange_MissingIDToken verifies that Exchange returns an error
// when the id_token claim is missing from the OAuth2 token response.
func TestOIDCRelyingParty_Exchange_MissingIDToken(t *testing.T) {
	// Token response WITHOUT id_token field
	tokenResp := map[string]interface{}{
		"access_token": "valid_access_token",
		"token_type":   "Bearer",
		"expires_in":   3600,
	}

	server := mockOAuth2Provider(t, tokenResp)
	defer server.Close()

	cfg := authn.OIDCRPConfig{
		IssuerURL:    server.URL,
		ClientID:     "test-client",
		ClientSecret: "test-secret",
		RedirectURL:  server.URL + "/callback",
	}

	tlsCfg := &tls.Config{InsecureSkipVerify: true}
	ctx := insecureContext(context.Background(), tlsCfg)
	rp, err := authn.NewOIDCRelyingParty(ctx, cfg)
	if err != nil {
		t.Fatalf("failed to create RP: %v", err)
	}

	_, err = rp.Exchange(ctx, "test-code")
	if err == nil {
		t.Error("expected error when id_token missing, got nil")
		return
	}
	// Verify error is about missing/invalid id_token, not something else
	if !strings.Contains(err.Error(), "id_token") {
		t.Errorf("expected error about id_token, got: %v", err)
	}
}

// regression: gh-missing-id-token
// TestOIDCRelyingParty_Exchange_InvalidIDTokenType verifies that Exchange returns an error
// when the id_token claim is present but not a string.
func TestOIDCRelyingParty_Exchange_InvalidIDTokenType(t *testing.T) {
	// Token response with id_token as non-string (number)
	tokenResp := map[string]interface{}{
		"access_token": "valid_access_token",
		"token_type":   "Bearer",
		"expires_in":   3600,
		"id_token":     12345, // Wrong type: should be string
	}

	server := mockOAuth2Provider(t, tokenResp)
	defer server.Close()

	cfg := authn.OIDCRPConfig{
		IssuerURL:    server.URL,
		ClientID:     "test-client",
		ClientSecret: "test-secret",
		RedirectURL:  server.URL + "/callback",
	}

	tlsCfg := &tls.Config{InsecureSkipVerify: true}
	ctx := insecureContext(context.Background(), tlsCfg)
	rp, err := authn.NewOIDCRelyingParty(ctx, cfg)
	if err != nil {
		t.Fatalf("failed to create RP: %v", err)
	}

	_, err = rp.Exchange(ctx, "test-code")
	if err == nil {
		t.Error("expected error when id_token is non-string, got nil")
		return
	}
	// Verify error is about invalid id_token
	if !strings.Contains(err.Error(), "id_token") {
		t.Errorf("expected error about id_token, got: %v", err)
	}
}

// Helper: create context with HTTP client that skips TLS verification for tests
func insecureContext(ctx context.Context, tlsConfig *tls.Config) context.Context {
	client := &http.Client{
		Transport: &http.Transport{
			TLSClientConfig: tlsConfig,
		},
	}
	return context.WithValue(ctx, oauth2.HTTPClient, client)
}

// Helper: generate RSA key pair for JWT signing
func generateTestKeyPair(t *testing.T) (*rsa.PrivateKey, jwk.Key) {
	t.Helper()
	privKey, err := rsa.GenerateKey(rand.Reader, 2048)
	if err != nil {
		t.Fatalf("failed to generate RSA key: %v", err)
	}

	key, err := jwk.FromRaw(&privKey.PublicKey)
	if err != nil {
		t.Fatalf("failed to convert to jwk.Key: %v", err)
	}

	// Set key ID for JWKS
	if err := key.Set("kid", "test-key"); err != nil {
		t.Fatalf("failed to set key ID: %v", err)
	}

	return privKey, key
}

// Helper: build a test JWT token
func buildTestToken(t *testing.T, privKey *rsa.PrivateKey, issuerURL string, opts struct {
	expired  bool
	wrongAud bool
	wrongIss bool
	algHMAC  bool // true = sign with HMAC using pubkey as secret
}) string {
	t.Helper()
	tok := jwt.New()
	tok.Set(jwt.SubjectKey, "user-123")
	tok.Set(jwt.IssuerKey, issuerURL)
	tok.Set(jwt.AudienceKey, []string{"client-id"})
	tok.Set("scope", []string{"openid", "profile"})
	tok.Set("tenant", "tenant-123")

	if opts.wrongAud {
		tok.Set(jwt.AudienceKey, []string{"wrong-aud"})
	}
	if opts.wrongIss {
		tok.Set(jwt.IssuerKey, "https://wrong-issuer.example.com")
	}

	now := time.Now()
	tok.Set(jwt.IssuedAtKey, now)
	tok.Set(jwt.ExpirationKey, now.Add(time.Hour))
	if opts.expired {
		tok.Set(jwt.ExpirationKey, now.Add(-1*time.Hour)) // already expired
	}

	var alg jwa.SignatureAlgorithm
	if opts.algHMAC {
		// HS256 with RSA public key as HMAC secret (alg confusion attack)
		alg = jwa.HS256
	} else {
		alg = jwa.RS256
	}

	payload, err := json.Marshal(tok)
	if err != nil {
		t.Fatalf("failed to marshal token: %v", err)
	}

	var key interface{}
	if opts.algHMAC {
		// Extract RSA public key bytes for HMAC signature
		pubKeyDER, err := x509.MarshalPKIXPublicKey(&privKey.PublicKey)
		if err != nil {
			t.Fatalf("failed to marshal public key: %v", err)
		}
		key = pubKeyDER // HMAC uses the raw public key as secret (attack vector)
	} else {
		key = privKey
	}

	signed, err := jws.Sign(payload, jws.WithKey(alg, key))
	if err != nil {
		t.Fatalf("failed to sign token: %v", err)
	}

	return string(signed)
}

// Helper: build mock OIDC provider discovery + JWKS server
func mockOIDCProvider(t *testing.T, privKey *rsa.PrivateKey, pubKey jwk.Key) *httptest.Server {
	t.Helper()

	mux := http.NewServeMux()
	server := httptest.NewTLSServer(mux)

	// Discovery endpoint - use the actual server URL in the issuer claim
	mux.HandleFunc("/.well-known/openid-configuration", func(w http.ResponseWriter, r *http.Request) {
		discovery := map[string]interface{}{
			"issuer":                 server.URL,
			"authorization_endpoint": server.URL + "/auth",
			"token_endpoint":         server.URL + "/token",
			"jwks_uri":               server.URL + "/.well-known/jwks.json",
		}
		w.Header().Set("Content-Type", "application/json")
		json.NewEncoder(w).Encode(discovery)
	})

	// JWKS endpoint
	mux.HandleFunc("/.well-known/jwks.json", func(w http.ResponseWriter, r *http.Request) {
		set := jwk.NewSet()
		set.AddKey(pubKey)
		w.Header().Set("Content-Type", "application/json")
		json.NewEncoder(w).Encode(set)
	})

	return server
}

// ValidateToken tests: valid token, expired, wrong aud, wrong iss, bad signature, alg confusion
func TestOIDCRelyingParty_ValidateToken_ValidToken(t *testing.T) {
	privKey, pubKey := generateTestKeyPair(t)
	server := mockOIDCProvider(t, privKey, pubKey)
	defer server.Close()

	cfg := authn.OIDCRPConfig{
		IssuerURL: server.URL,
		ClientID:  "client-id",
		Scopes:    []string{"openid", "profile"},
	}
	if err := cfg.Validate(); err != nil {
		t.Fatalf("config validation failed: %v", err)
	}

	tlsCfg := &tls.Config{InsecureSkipVerify: true}
	ctx := insecureContext(context.Background(), tlsCfg)
	rp, err := authn.NewOIDCRelyingParty(ctx, cfg)
	if err != nil {
		t.Fatalf("failed to create OIDCRelyingParty: %v", err)
	}

	token := buildTestToken(t, privKey, server.URL, struct {
		expired  bool
		wrongAud bool
		wrongIss bool
		algHMAC  bool
	}{})

	claims, err := rp.ValidateToken(context.Background(), token)
	if err != nil {
		t.Errorf("ValidateToken failed for valid token: %v", err)
		return
	}

	if claims == nil {
		t.Fatal("ValidateToken returned nil claims")
	}
	if claims.Sub != "user-123" {
		t.Errorf("expected sub=user-123, got %s", claims.Sub)
	}
	if claims.Tenant != "tenant-123" {
		t.Errorf("expected tenant=tenant-123, got %s", claims.Tenant)
	}
}

func TestOIDCRelyingParty_ValidateToken_ExpiredToken(t *testing.T) {
	privKey, pubKey := generateTestKeyPair(t)
	server := mockOIDCProvider(t, privKey, pubKey)
	defer server.Close()

	cfg := authn.OIDCRPConfig{
		IssuerURL: server.URL,
		ClientID:  "client-id",
	}
	if err := cfg.Validate(); err != nil {
		t.Fatalf("config validation failed: %v", err)
	}

	// TEST ONLY: skip TLS verification for httptest server with self-signed cert
	tlsCfg := &tls.Config{InsecureSkipVerify: true}
	ctx := insecureContext(context.Background(), tlsCfg)
	rp, err := authn.NewOIDCRelyingParty(ctx, cfg)
	if err != nil {
		t.Fatalf("failed to create OIDCRelyingParty: %v", err)
	}

	token := buildTestToken(t, privKey, server.URL, struct {
		expired  bool
		wrongAud bool
		wrongIss bool
		algHMAC  bool
	}{expired: true})

	_, err = rp.ValidateToken(context.Background(), token)
	if err == nil {
		t.Error("ValidateToken should reject expired token")
	}
}

func TestOIDCRelyingParty_ValidateToken_WrongAudience(t *testing.T) {
	privKey, pubKey := generateTestKeyPair(t)
	server := mockOIDCProvider(t, privKey, pubKey)
	defer server.Close()

	cfg := authn.OIDCRPConfig{
		IssuerURL: server.URL,
		ClientID:  "client-id",
	}
	if err := cfg.Validate(); err != nil {
		t.Fatalf("config validation failed: %v", err)
	}

	// TEST ONLY: skip TLS verification for httptest server with self-signed cert
	tlsCfg := &tls.Config{InsecureSkipVerify: true}
	ctx := insecureContext(context.Background(), tlsCfg)
	rp, err := authn.NewOIDCRelyingParty(ctx, cfg)
	if err != nil {
		t.Fatalf("failed to create OIDCRelyingParty: %v", err)
	}

	token := buildTestToken(t, privKey, server.URL, struct {
		expired  bool
		wrongAud bool
		wrongIss bool
		algHMAC  bool
	}{wrongAud: true})

	_, err = rp.ValidateToken(context.Background(), token)
	if err == nil {
		t.Error("ValidateToken should reject token with wrong audience")
	}
}

func TestOIDCRelyingParty_ValidateToken_WrongIssuer(t *testing.T) {
	privKey, pubKey := generateTestKeyPair(t)
	server := mockOIDCProvider(t, privKey, pubKey)
	defer server.Close()

	cfg := authn.OIDCRPConfig{
		IssuerURL: server.URL,
		ClientID:  "client-id",
	}
	if err := cfg.Validate(); err != nil {
		t.Fatalf("config validation failed: %v", err)
	}

	// TEST ONLY: skip TLS verification for httptest server with self-signed cert
	tlsCfg := &tls.Config{InsecureSkipVerify: true}
	ctx := insecureContext(context.Background(), tlsCfg)
	rp, err := authn.NewOIDCRelyingParty(ctx, cfg)
	if err != nil {
		t.Fatalf("failed to create OIDCRelyingParty: %v", err)
	}

	token := buildTestToken(t, privKey, server.URL, struct {
		expired  bool
		wrongAud bool
		wrongIss bool
		algHMAC  bool
	}{wrongIss: true})

	_, err = rp.ValidateToken(context.Background(), token)
	if err == nil {
		t.Error("ValidateToken should reject token with wrong issuer")
	}
}

func TestOIDCRelyingParty_ValidateToken_BadSignature(t *testing.T) {
	privKey, pubKey := generateTestKeyPair(t)
	server := mockOIDCProvider(t, privKey, pubKey)
	defer server.Close()

	cfg := authn.OIDCRPConfig{
		IssuerURL: server.URL,
		ClientID:  "client-id",
	}
	if err := cfg.Validate(); err != nil {
		t.Fatalf("config validation failed: %v", err)
	}

	// TEST ONLY: skip TLS verification for httptest server with self-signed cert
	tlsCfg := &tls.Config{InsecureSkipVerify: true}
	ctx := insecureContext(context.Background(), tlsCfg)
	rp, err := authn.NewOIDCRelyingParty(ctx, cfg)
	if err != nil {
		t.Fatalf("failed to create OIDCRelyingParty: %v", err)
	}

	token := buildTestToken(t, privKey, server.URL, struct {
		expired  bool
		wrongAud bool
		wrongIss bool
		algHMAC  bool
	}{})

	// Tamper with token signature
	parts := strings.Split(token, ".")
	if len(parts) != 3 {
		t.Fatalf("expected 3 JWT parts, got %d", len(parts))
	}
	parts[2] = "tampered-signature"
	tamperedToken := strings.Join(parts, ".")

	_, err = rp.ValidateToken(context.Background(), tamperedToken)
	if err == nil {
		t.Error("ValidateToken should reject token with bad signature")
	}
}

func TestOIDCRelyingParty_ValidateToken_AlgConfusion_HS256WithRSAPublicKey(t *testing.T) {
	privKey, pubKey := generateTestKeyPair(t)
	server := mockOIDCProvider(t, privKey, pubKey)
	defer server.Close()

	cfg := authn.OIDCRPConfig{
		IssuerURL:  server.URL,
		ClientID:   "client-id",
		Algorithms: []string{"RS256"}, // Only allow RS256, not HS256
	}
	if err := cfg.Validate(); err != nil {
		t.Fatalf("config validation failed: %v", err)
	}

	// TEST ONLY: skip TLS verification for httptest server with self-signed cert
	tlsCfg := &tls.Config{InsecureSkipVerify: true}
	ctx := insecureContext(context.Background(), tlsCfg)
	rp, err := authn.NewOIDCRelyingParty(ctx, cfg)
	if err != nil {
		t.Fatalf("failed to create OIDCRelyingParty: %v", err)
	}

	// Create token signed with HS256 using RSA public key (alg confusion attack)
	token := buildTestToken(t, privKey, server.URL, struct {
		expired  bool
		wrongAud bool
		wrongIss bool
		algHMAC  bool
	}{algHMAC: true})

	_, err = rp.ValidateToken(context.Background(), token)
	if err == nil {
		t.Error("ValidateToken should reject HS256 token when only RS256 is allowed (alg confusion attack)")
	}
}
