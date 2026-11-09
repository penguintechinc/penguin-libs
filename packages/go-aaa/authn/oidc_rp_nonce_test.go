package authn_test

import (
	"context"
	"crypto/rsa"
	"testing"
	"time"

	"github.com/lestrrat-go/jwx/v2/jwa"
	"github.com/lestrrat-go/jwx/v2/jws"
	"github.com/lestrrat-go/jwx/v2/jwt"
	"github.com/penguintechinc/penguin-libs/packages/go-aaa/authn"
	"golang.org/x/oauth2"
)

// signIDTokenWithNonce signs an RS256 token with the given nonce claim.
// A nil nonce omits the claim entirely.
func signIDTokenWithNonce(t *testing.T, privKey *rsa.PrivateKey, issuer string, nonce *string) string {
	t.Helper()
	tok := jwt.New()
	_ = tok.Set(jwt.SubjectKey, "user-123")
	_ = tok.Set(jwt.IssuerKey, issuer)
	_ = tok.Set(jwt.AudienceKey, []string{"client-id"})
	_ = tok.Set("scope", []string{"openid"})
	_ = tok.Set("tenant", "tenant-123")
	now := time.Now()
	_ = tok.Set(jwt.IssuedAtKey, now)
	_ = tok.Set(jwt.ExpirationKey, now.Add(time.Hour))
	if nonce != nil {
		_ = tok.Set("nonce", *nonce)
	}
	payload, err := jwt.NewSerializer().Serialize(tok)
	if err != nil {
		t.Fatalf("serialize token: %v", err)
	}
	signed, err := jws.Sign(payload, jws.WithKey(jwa.RS256, privKey))
	if err != nil {
		t.Fatalf("sign token: %v", err)
	}
	return string(signed)
}

// newNonceTestRP builds an RP against a mock provider and returns it with the signing key.
func newNonceTestRP(t *testing.T) (*authn.OIDCRelyingParty, *rsa.PrivateKey, string) {
	t.Helper()
	privKey, pubKey := generateTestKeyPair(t)
	server := mockOIDCProvider(t, privKey, pubKey)
	t.Cleanup(server.Close)
	cfg := authn.OIDCRPConfig{IssuerURL: server.URL, ClientID: "client-id", Scopes: []string{"openid"}}
	ctx := context.WithValue(context.Background(), oauth2.HTTPClient, server.Client())
	rp, err := authn.NewOIDCRelyingParty(ctx, cfg)
	if err != nil {
		t.Fatalf("NewOIDCRelyingParty: %v", err)
	}
	return rp, privKey, server.URL
}

// SEC-GO-06 regression: an ID token carrying a nonce must never validate when the
// caller supplies an empty expected nonce (previously the nonce check was skipped).
func TestValidateToken_EmptyExpectedNonceRejected(t *testing.T) {
	rp, privKey, issuer := newNonceTestRP(t)
	n := "attacker-nonce"
	tok := signIDTokenWithNonce(t, privKey, issuer, &n)

	if _, err := rp.ValidateToken(context.Background(), tok, ""); err == nil {
		t.Fatal("ValidateToken with empty expected nonce must fail, got nil error")
	}
}

// SEC-GO-06: ID-token validation requires a non-empty expected nonce, a present
// nonce claim, and an exact match.
func TestValidateIDToken_NonceRequired(t *testing.T) {
	good := "abc123xyz"
	mismatch := "abc123xyw"
	cases := []struct {
		name          string
		tokenNonce    *string
		expectedNonce string
		wantErr       bool
	}{
		{"matching nonce", &good, good, false},
		{"mismatched nonce", &good, mismatch, true},
		{"empty expected nonce", &good, "", true},
		{"token nonce missing", nil, good, true},
		{"token nonce empty, expected set", ptrTo(""), good, true},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			rp, privKey, issuer := newNonceTestRP(t)
			tok := signIDTokenWithNonce(t, privKey, issuer, tc.tokenNonce)
			claims, err := rp.ValidateIDToken(context.Background(), tok, tc.expectedNonce)
			if tc.wantErr {
				if err == nil {
					t.Fatalf("expected error, got claims %+v", claims)
				}
				return
			}
			if err != nil {
				t.Fatalf("unexpected error: %v", err)
			}
			if claims.Sub != "user-123" {
				t.Errorf("sub = %q, want user-123", claims.Sub)
			}
		})
	}
}

// ptrTo returns a pointer to s, used for optional nonce claims in table tests.
func ptrTo(s string) *string { return &s }
