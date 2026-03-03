package authz

import (
	"context"

	"github.com/penguintechinc/penguin-libs/packages/go-aaa/authn"
)

// claimsKey is the unexported context key used to store authentication claims.
type claimsKey struct{}

// ContextWithClaims returns a new context carrying the given Claims.
func ContextWithClaims(ctx context.Context, claims *authn.Claims) context.Context {
	return context.WithValue(ctx, claimsKey{}, claims)
}

// ClaimsFromContext extracts the Claims stored in ctx, or nil if absent.
func ClaimsFromContext(ctx context.Context) *authn.Claims {
	claims, _ := ctx.Value(claimsKey{}).(*authn.Claims)
	return claims
}

// TenantFromContext extracts the tenant identifier from Claims stored in ctx.
// It returns an empty string when no claims are present or when the tenant field is unset.
func TenantFromContext(ctx context.Context) string {
	claims := ClaimsFromContext(ctx)
	if claims == nil {
		return ""
	}
	return claims.Tenant
}
