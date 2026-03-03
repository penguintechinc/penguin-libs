// Package goaaa provides top-level convenience constructors for Penguin Tech
// authentication and authorization components.
//
// It composes the authn and crypto sub-packages into ready-to-use relying party,
// provider, and Connect RPC interceptor instances with a single function call.
package goaaa

import (
	"context"

	"github.com/penguintechinc/penguin-libs/packages/go-aaa/authn"
	"github.com/penguintechinc/penguin-libs/packages/go-aaa/crypto"
)

// NewRelyingParty is a convenience constructor that creates an OIDCRelyingParty
// from the given configuration, performing OIDC provider discovery immediately.
func NewRelyingParty(ctx context.Context, cfg authn.OIDCRPConfig) (*authn.OIDCRelyingParty, error) {
	return authn.NewOIDCRelyingParty(ctx, cfg)
}

// NewProvider is a convenience constructor that creates an OIDCProvider from
// the given configuration and key store.
func NewProvider(cfg authn.OIDCProviderConfig, ks crypto.KeyStore) (*authn.OIDCProvider, error) {
	return authn.NewOIDCProvider(cfg, ks)
}

// NewConnectAuthInterceptor is a convenience constructor that creates a Connect RPC
// authentication interceptor from the given TokenValidator.
func NewConnectAuthInterceptor(validator authn.TokenValidator) (*authn.ConnectAuthInterceptor, error) {
	return authn.NewConnectAuthInterceptor(validator)
}
