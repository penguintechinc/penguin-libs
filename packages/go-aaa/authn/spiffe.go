package authn

import (
	"context"
	"crypto/x509"
	"fmt"

	"github.com/spiffe/go-spiffe/v2/spiffeid"
	"github.com/spiffe/go-spiffe/v2/svid/x509svid"
	"github.com/spiffe/go-spiffe/v2/workloadapi"
)

// SPIFFEAuthenticator validates peer certificates against a configured set of
// allowed SPIFFE IDs obtained from the SPIFFE Workload API.
type SPIFFEAuthenticator struct {
	cfg    SPIFFEConfig
	source *workloadapi.X509Source
}

// NewSPIFFEAuthenticator creates an SPIFFEAuthenticator from the given configuration.
// Call GetX509Source to connect to the Workload API before validating certificates.
func NewSPIFFEAuthenticator(cfg SPIFFEConfig) (*SPIFFEAuthenticator, error) {
	if err := cfg.Validate(); err != nil {
		return nil, fmt.Errorf("spiffe: invalid config: %w", err)
	}
	return &SPIFFEAuthenticator{cfg: cfg}, nil
}

// GetX509Source connects to the SPIFFE Workload API and stores the X.509 source
// for use during peer certificate validation. The source should be closed when
// the authenticator is no longer needed.
func (a *SPIFFEAuthenticator) GetX509Source(ctx context.Context) (*workloadapi.X509Source, error) {
	source, err := workloadapi.NewX509Source(
		ctx,
		workloadapi.WithClientOptions(workloadapi.WithAddr(a.cfg.WorkloadSocket)),
	)
	if err != nil {
		return nil, fmt.Errorf("spiffe: failed to connect to workload api at %q: %w", a.cfg.WorkloadSocket, err)
	}
	a.source = source
	return source, nil
}

// ValidatePeerCertificate validates a peer's certificate chain against the configured
// allowed SPIFFE IDs. It returns the matched SPIFFE ID string on success.
// The first certificate in certs is treated as the leaf/end-entity certificate.
func (a *SPIFFEAuthenticator) ValidatePeerCertificate(certs []*x509.Certificate) (string, error) {
	if len(certs) == 0 {
		return "", fmt.Errorf("spiffe: no peer certificates provided")
	}

	// Extract the SPIFFE ID from the leaf certificate's URI SAN.
	peerID, err := x509svid.IDFromCert(certs[0])
	if err != nil {
		return "", fmt.Errorf("spiffe: failed to extract SPIFFE ID from peer certificate: %w", err)
	}

	peerIDStr := peerID.String()

	for _, allowedID := range a.cfg.AllowedIDs {
		allowed, err := spiffeid.FromString(allowedID)
		if err != nil {
			return "", fmt.Errorf("spiffe: invalid allowed id %q: %w", allowedID, err)
		}
		if peerID == allowed {
			return peerIDStr, nil
		}
	}

	return "", fmt.Errorf("spiffe: peer id %q is not in the allowed set", peerIDStr)
}
