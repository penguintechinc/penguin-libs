package authn_test

import (
	"crypto/sha256"
	"encoding/base64"
	"testing"

	"github.com/penguintechinc/penguin-libs/packages/go-aaa/authn"
)

func TestGeneratePKCEPair(t *testing.T) {
	pkce1, err := authn.GeneratePKCEPair()
	if err != nil {
		t.Fatalf("GeneratePKCEPair() error = %v", err)
	}

	// Verifier should be 43 characters (32 bytes base64url-encoded without padding)
	if len(pkce1.Verifier) != 43 {
		t.Errorf("verifier length = %d, want 43", len(pkce1.Verifier))
	}

	// Challenge should be 43 characters (S256 of 32 bytes)
	if len(pkce1.Challenge) != 43 {
		t.Errorf("challenge length = %d, want 43", len(pkce1.Challenge))
	}

	// Verify challenge is S256(verifier)
	sum := sha256.Sum256([]byte(pkce1.Verifier))
	expectedChallenge := base64.RawURLEncoding.EncodeToString(sum[:])
	if pkce1.Challenge != expectedChallenge {
		t.Errorf("challenge = %q, want %q", pkce1.Challenge, expectedChallenge)
	}

	// Generate another pair and verify they're different
	pkce2, err := authn.GeneratePKCEPair()
	if err != nil {
		t.Fatalf("GeneratePKCEPair() error = %v", err)
	}

	if pkce1.Verifier == pkce2.Verifier {
		t.Error("two PKCE pairs should have different verifiers")
	}
	if pkce1.Challenge == pkce2.Challenge {
		t.Error("two PKCE pairs should have different challenges")
	}
}
