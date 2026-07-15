// Copyright 2026 Penguin Tech Inc
// SPDX-License-Identifier: Apache-2.0

package auth

import (
	"context"
	"fmt"

	"connectrpc.com/connect"

	"github.com/penguintechinc/penguin-libs/packages/go-aaa/audit"
	"github.com/penguintechinc/penguin-libs/packages/go-aaa/authn"
	"github.com/penguintechinc/penguin-libs/packages/go-aaa/authz"
	"github.com/penguintechinc/penguin-libs/packages/go-aaa/middleware"
)

// Supported values for Config.Mode.
const (
	// ModeOIDC authenticates every request with an OIDC bearer token.
	ModeOIDC = "oidc"
	// ModeSPIFFE authenticates every request with a SPIFFE mTLS peer identity.
	ModeSPIFFE = "spiffe"
	// ModeBoth accepts either an OIDC bearer token or a SPIFFE mTLS peer
	// identity per request (see doc.go, "Mode both").
	ModeBoth = "both"
)

// Config configures the zero-trust interceptor chain returned by
// Interceptors. Mode selects which authn interceptor(s) are wired in; the
// corresponding authenticator field(s) are required for that mode. Enforcer
// and Scopes are always required — they drive go-aaa's scope-based
// authorization and this package's deny-by-default gate. Public lists
// procedures that opt into skipping authentication and authorization
// entirely. Audit is optional; when non-nil it is wired as the outermost
// interceptor so it observes every outcome, including rejections.
type Config struct {
	// Mode selects the authentication strategy: "oidc", "spiffe", or "both".
	Mode string
	// OIDC validates bearer tokens. Required when Mode is "oidc" or "both".
	OIDC *authn.OIDCRelyingParty
	// SPIFFE validates mTLS peer identities. Required when Mode is "spiffe" or "both".
	SPIFFE *authn.SPIFFEAuthenticator
	// Enforcer resolves role-to-scope mappings for go-aaa's authz interceptor. Always required.
	Enforcer *authz.RBACEnforcer
	// Scopes maps procedure paths to their required OAuth 2.0 scopes. A
	// procedure absent from both Scopes and Public is denied by default.
	Scopes middleware.ProcedureScopes
	// Public lists procedure paths that skip authentication and authorization entirely.
	Public []string
	// Audit, when non-nil, emits an audit event for every request outcome.
	Audit *audit.Emitter
}

// Interceptors builds the spec-ordered zero-trust interceptor chain from
// cfg: audit (if configured) -> authn -> tenant -> deny-by-default gate ->
// authz. See doc.go for the full rationale behind this ordering. It returns
// an error if cfg.Mode is not one of ModeOIDC, ModeSPIFFE, or ModeBoth, if
// the authenticator(s) required by the selected mode are nil, or if
// cfg.Enforcer is nil.
func Interceptors(cfg Config) ([]connect.Interceptor, error) {
	if err := validateConfig(cfg); err != nil {
		return nil, err
	}

	authnInterceptor, err := newAuthnInterceptor(cfg)
	if err != nil {
		return nil, err
	}

	publicOpt := middleware.WithPublicProcedures(cfg.Public...)

	chain := make([]connect.Interceptor, 0, 5)
	if cfg.Audit != nil {
		chain = append(chain, middleware.NewAuditInterceptor(cfg.Audit))
	}
	chain = append(chain,
		authnInterceptor,
		middleware.NewTenantInterceptor(publicOpt),
		newDenyByDefaultInterceptor(cfg.Scopes, cfg.Public),
		middleware.NewAuthzInterceptor(cfg.Enforcer, cfg.Scopes, publicOpt),
	)

	return chain, nil
}

// validateConfig checks that cfg.Mode is supported, that the authenticator(s)
// required by that mode are present, and that cfg.Enforcer is non-nil (it is
// dereferenced by go-aaa's authz interceptor whenever a claim carries roles).
func validateConfig(cfg Config) error {
	switch cfg.Mode {
	case ModeOIDC:
		if cfg.OIDC == nil {
			return fmt.Errorf("auth: mode %q requires a non-nil OIDC relying party", cfg.Mode)
		}
	case ModeSPIFFE:
		if cfg.SPIFFE == nil {
			return fmt.Errorf("auth: mode %q requires a non-nil SPIFFE authenticator", cfg.Mode)
		}
	case ModeBoth:
		if cfg.OIDC == nil || cfg.SPIFFE == nil {
			return fmt.Errorf("auth: mode %q requires both a non-nil OIDC relying party and a non-nil SPIFFE authenticator", cfg.Mode)
		}
	default:
		return fmt.Errorf("auth: unsupported mode %q; must be one of %q, %q, %q", cfg.Mode, ModeOIDC, ModeSPIFFE, ModeBoth)
	}

	if cfg.Enforcer == nil {
		return fmt.Errorf("auth: enforcer is required")
	}

	return nil
}

// newAuthnInterceptor selects the authn interceptor for cfg.Mode. cfg has
// already passed validateConfig, so the default branch is unreachable in
// practice; it returns an error rather than panicking to keep the function
// total.
func newAuthnInterceptor(cfg Config) (connect.UnaryInterceptorFunc, error) {
	publicOpt := middleware.WithPublicProcedures(cfg.Public...)

	switch cfg.Mode {
	case ModeOIDC:
		return middleware.NewOIDCInterceptor(cfg.OIDC, publicOpt), nil
	case ModeSPIFFE:
		return middleware.NewSPIFFEInterceptor(cfg.SPIFFE, publicOpt), nil
	case ModeBoth:
		return newDualAuthnInterceptor(cfg.OIDC, cfg.SPIFFE, publicOpt), nil
	default:
		return nil, fmt.Errorf("auth: unsupported mode %q", cfg.Mode)
	}
}

// newDualAuthnInterceptor implements ModeBoth: it dispatches each request to
// go-aaa's OIDC interceptor when an "Authorization: Bearer " header is
// present, and to go-aaa's SPIFFE interceptor otherwise. Both underlying
// interceptors are used as opaque building blocks — neither's validation
// logic is reimplemented here.
func newDualAuthnInterceptor(rp *authn.OIDCRelyingParty, sa *authn.SPIFFEAuthenticator, opts ...middleware.InterceptorOption) connect.UnaryInterceptorFunc {
	oidcInterceptor := middleware.NewOIDCInterceptor(rp, opts...)
	spiffeInterceptor := middleware.NewSPIFFEInterceptor(sa, opts...)

	return func(next connect.UnaryFunc) connect.UnaryFunc {
		oidcNext := oidcInterceptor(next)
		spiffeNext := spiffeInterceptor(next)
		return func(ctx context.Context, req connect.AnyRequest) (connect.AnyResponse, error) {
			if hasBearerToken(req) {
				return oidcNext(ctx, req)
			}
			return spiffeNext(ctx, req)
		}
	}
}

// hasBearerToken reports whether req carries an "Authorization: Bearer "
// header, mirroring the check NewOIDCInterceptor itself performs.
func hasBearerToken(req connect.AnyRequest) bool {
	auth := req.Header().Get("Authorization")
	return len(auth) >= 8 && auth[:7] == "Bearer "
}

// newDenyByDefaultInterceptor builds go-rpc's own gate. See doc.go's
// "Deny-by-default gate" section for why this package supplies its own gate
// rather than relying on go-aaa's authz interceptor alone, and "Streaming
// RPCs" for why the gate is a full connect.Interceptor rather than a
// connect.UnaryInterceptorFunc like every other interceptor in the chain.
func newDenyByDefaultInterceptor(scopes middleware.ProcedureScopes, public []string) *denyByDefaultGate {
	publicSet := make(map[string]bool, len(public))
	for _, p := range public {
		publicSet[p] = true
	}
	return &denyByDefaultGate{scopes: scopes, publicSet: publicSet}
}

// denyByDefaultGate is the only interceptor in this package's chain that
// implements connect.Interceptor directly instead of being built from
// connect.UnaryInterceptorFunc. That distinction matters only for streaming
// RPCs: connect.UnaryInterceptorFunc's WrapStreamingHandler is a documented
// no-op (connectrpc.com/connect v1.20.0, interceptor.go lines 70-73), so
// every go-aaa interceptor this package wraps (authn, tenant, authz, audit)
// has zero effect on a streaming call. denyByDefaultGate is the sole
// enforcement point for streaming procedures; see doc.go's "Streaming RPCs"
// section for the full rationale and current limitations.
type denyByDefaultGate struct {
	scopes    middleware.ProcedureScopes
	publicSet map[string]bool
}

// WrapUnary rejects, with CodePermissionDenied, any unary procedure that is
// present in neither g.scopes nor g.publicSet. Behavior is unchanged from
// this package's original deny-by-default gate, except the error message no
// longer includes the procedure name (see doc.go's "Deny-by-default gate"
// section); this package has no logger to record that detail server-side,
// so the message is generic on both the client and server side.
func (g *denyByDefaultGate) WrapUnary(next connect.UnaryFunc) connect.UnaryFunc {
	return func(ctx context.Context, req connect.AnyRequest) (connect.AnyResponse, error) {
		procedure := req.Spec().Procedure
		if g.publicSet[procedure] {
			return next(ctx, req)
		}
		if _, declared := g.scopes[procedure]; !declared {
			return nil, connect.NewError(connect.CodePermissionDenied, fmt.Errorf("permission denied"))
		}
		return next(ctx, req)
	}
}

// WrapStreamingClient is a pass-through: this package's gate has no
// client-side enforcement role (see doc.go's "Streaming RPCs" section).
func (g *denyByDefaultGate) WrapStreamingClient(next connect.StreamingClientFunc) connect.StreamingClientFunc {
	return next
}

// WrapStreamingHandler fails closed: any streaming procedure whose
// conn.Spec().Procedure is not in g.publicSet is rejected with
// CodePermissionDenied before next is ever invoked, regardless of
// credentials — none of go-aaa's authn/tenant/authz interceptors run on the
// streaming path (see the denyByDefaultGate doc comment), so there is no
// scope or claim to evaluate here even if there were one to check against.
// A public streaming procedure passes straight through with zero
// enforcement, matching how public unary procedures already bypass the
// entire chain.
func (g *denyByDefaultGate) WrapStreamingHandler(next connect.StreamingHandlerFunc) connect.StreamingHandlerFunc {
	return func(ctx context.Context, conn connect.StreamingHandlerConn) error {
		procedure := conn.Spec().Procedure
		if g.publicSet[procedure] {
			return next(ctx, conn)
		}
		return connect.NewError(connect.CodePermissionDenied,
			fmt.Errorf("streaming procedures are not yet supported by the pRPC auth chain; declare public or use unary"))
	}
}
