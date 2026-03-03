package middleware

import (
	"context"
	"crypto/tls"
	"crypto/x509"
	"fmt"
	"net"

	"connectrpc.com/connect"

	"github.com/penguintechinc/penguin-libs/packages/go-aaa/authn"
	"github.com/penguintechinc/penguin-libs/packages/go-aaa/authz"
)

// NewOIDCInterceptor returns a ConnectRPC interceptor that validates Bearer tokens
// using the provided OIDCRelyingParty. On success the extracted Claims are stored
// in the request context via authz.ContextWithClaims.
func NewOIDCInterceptor(rp *authn.OIDCRelyingParty, opts ...InterceptorOption) connect.UnaryInterceptorFunc {
	cfg := applyOptions(opts)
	return func(next connect.UnaryFunc) connect.UnaryFunc {
		return func(ctx context.Context, req connect.AnyRequest) (connect.AnyResponse, error) {
			if cfg.publicProcedures[req.Spec().Procedure] {
				return next(ctx, req)
			}

			auth := req.Header().Get("Authorization")
			if len(auth) < 8 || auth[:7] != "Bearer " {
				return nil, connect.NewError(connect.CodeUnauthenticated, fmt.Errorf("missing bearer token"))
			}

			claims, err := rp.ValidateToken(ctx, auth[7:])
			if err != nil {
				return nil, connect.NewError(connect.CodeUnauthenticated, fmt.Errorf("invalid token: %w", err))
			}

			ctx = authz.ContextWithClaims(ctx, claims)
			return next(ctx, req)
		}
	}
}

// NewSPIFFEInterceptor returns a ConnectRPC interceptor that validates the mTLS peer
// certificate chain using the provided SPIFFEAuthenticator. On success synthetic Claims
// are stored in the request context using the matched SPIFFE ID as the subject.
//
// The interceptor extracts peer certificates from the TLS connection state. This requires
// the server to use mutual TLS with ClientAuth set to at least tls.RequestClientCert.
// The TLS net.Conn must be stored in the context under connContextKey so the interceptor
// can retrieve the connection state.
func NewSPIFFEInterceptor(sa *authn.SPIFFEAuthenticator, opts ...InterceptorOption) connect.UnaryInterceptorFunc {
	cfg := applyOptions(opts)
	return func(next connect.UnaryFunc) connect.UnaryFunc {
		return func(ctx context.Context, req connect.AnyRequest) (connect.AnyResponse, error) {
			if cfg.publicProcedures[req.Spec().Procedure] {
				return next(ctx, req)
			}

			certs, err := tlsPeerCertsFromContext(ctx)
			if err != nil {
				return nil, connect.NewError(connect.CodeUnauthenticated, fmt.Errorf("spiffe: could not read peer certificates: %w", err))
			}

			spiffeID, err := sa.ValidatePeerCertificate(certs)
			if err != nil {
				return nil, connect.NewError(connect.CodeUnauthenticated, fmt.Errorf("spiffe: peer validation failed: %w", err))
			}

			claims := &authn.Claims{
				Sub: spiffeID,
				Iss: "spiffe",
			}
			ctx = authz.ContextWithClaims(ctx, claims)
			return next(ctx, req)
		}
	}
}

// connContextKey is the context key used to store the raw net.Conn for TLS inspection.
// Callers must store the connection in the context using this key before the interceptor runs.
type connContextKey struct{}

// ConnContextKey is the exported key for storing a net.Conn in the request context.
// Use this with http.Server.ConnContext to make the TLS connection available to
// NewSPIFFEInterceptor.
var ConnContextKey = connContextKey{}

// tlsPeerCertsFromContext retrieves TLS peer certificates from the net.Conn stored in
// ctx under ConnContextKey. Returns an error when the connection is absent, not a TLS
// connection, or has no peer certificates.
func tlsPeerCertsFromContext(ctx context.Context) ([]*x509.Certificate, error) {
	connVal := ctx.Value(connContextKey{})
	if connVal == nil {
		return nil, fmt.Errorf("no connection found in context; set ConnContextKey via http.Server.ConnContext")
	}

	tlsConn, ok := connVal.(*tls.Conn)
	if !ok {
		// connVal may be stored as the net.Conn interface; unwrap and retry.
		if nc, isConn := connVal.(net.Conn); isConn {
			tlsConn, ok = nc.(*tls.Conn)
		}
		if !ok {
			return nil, fmt.Errorf("connection value in context (type %T) is not a *tls.Conn", connVal)
		}
	}

	state := tlsConn.ConnectionState()
	if len(state.PeerCertificates) == 0 {
		return nil, fmt.Errorf("no peer certificates in TLS connection state")
	}

	return state.PeerCertificates, nil
}
