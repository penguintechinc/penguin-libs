package authn_test

import (
	"testing"

	"github.com/penguintechinc/penguin-libs/packages/go-aaa/authn"
)

func TestSPIFFEAuthenticator_Authenticate(t *testing.T) {
	cfg := authn.SPIFFEConfig{
		TrustDomain:    "example.org",
		WorkloadSocket: "unix:///tmp/spiffe.sock",
		AllowedIDs: []string{
			"spiffe://example.org/service/frontend",
			"spiffe://example.org/service/backend",
		},
	}

	authenticator, err := authn.NewSPIFFEAuthenticator(cfg)
	if err != nil {
		t.Fatalf("NewSPIFFEAuthenticator() error = %v", err)
	}

	cases := []struct {
		name      string
		spiffeID  string
		wantError bool
	}{
		{
			name:      "valid allowed ID",
			spiffeID:  "spiffe://example.org/service/frontend",
			wantError: false,
		},
		{
			name:      "another valid allowed ID",
			spiffeID:  "spiffe://example.org/service/backend",
			wantError: false,
		},
		{
			name:      "empty SPIFFE ID",
			spiffeID:  "",
			wantError: true,
		},
		{
			name:      "invalid SPIFFE ID format",
			spiffeID:  "not-a-valid-spiffe-id",
			wantError: true,
		},
		{
			name:      "wrong trust domain",
			spiffeID:  "spiffe://other.org/service/frontend",
			wantError: true,
		},
		{
			name:      "not in allowed set",
			spiffeID:  "spiffe://example.org/service/unknown",
			wantError: true,
		},
	}

	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			err := authenticator.Authenticate(tc.spiffeID)
			if (err != nil) != tc.wantError {
				t.Errorf("Authenticate(%q) error = %v, wantError = %v", tc.spiffeID, err, tc.wantError)
			}
		})
	}
}
