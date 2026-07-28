package authn

import (
	"crypto/rand"
	"crypto/sha256"
	"encoding/base64"
	"fmt"
)

// PKCEPair holds a PKCE code verifier and its S256 challenge.
type PKCEPair struct {
	Verifier  string
	Challenge string
}

// GeneratePKCEPair creates a cryptographically random PKCE verifier and S256 challenge.
// The verifier is 32 random bytes base64url-encoded (no padding).
// Returns an error if random number generation fails.
func GeneratePKCEPair() (*PKCEPair, error) {
	b := make([]byte, 32)
	if _, err := rand.Read(b); err != nil {
		return nil, fmt.Errorf("pkce: failed to generate verifier: %w", err)
	}
	verifier := base64.RawURLEncoding.EncodeToString(b)
	sum := sha256.Sum256([]byte(verifier))
	challenge := base64.RawURLEncoding.EncodeToString(sum[:])
	return &PKCEPair{Verifier: verifier, Challenge: challenge}, nil
}
