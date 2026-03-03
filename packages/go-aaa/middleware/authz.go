package middleware

import (
	"context"
	"fmt"

	"connectrpc.com/connect"

	"github.com/penguintechinc/penguin-libs/packages/go-aaa/authz"
)

// ProcedureScopes maps fully-qualified ConnectRPC procedure paths to the list of
// OAuth 2.0 scopes required to invoke them. Procedures absent from the map are
// allowed without scope enforcement.
type ProcedureScopes map[string][]string

// NewAuthzInterceptor returns a ConnectRPC interceptor that checks whether the Claims
// stored in the request context contain all scopes required for the procedure being
// invoked. It must run after an authentication interceptor.
func NewAuthzInterceptor(enforcer *authz.RBACEnforcer, procedures ProcedureScopes, opts ...InterceptorOption) connect.UnaryInterceptorFunc {
	cfg := applyOptions(opts)
	return func(next connect.UnaryFunc) connect.UnaryFunc {
		return func(ctx context.Context, req connect.AnyRequest) (connect.AnyResponse, error) {
			procedure := req.Spec().Procedure

			if cfg.publicProcedures[procedure] {
				return next(ctx, req)
			}

			required, ok := procedures[procedure]
			if !ok || len(required) == 0 {
				// No scope requirements defined for this procedure.
				return next(ctx, req)
			}

			claims := authz.ClaimsFromContext(ctx)
			if claims == nil {
				return nil, connect.NewError(connect.CodePermissionDenied, fmt.Errorf("no claims in context; authentication required"))
			}

			// Collect all scopes granted directly on the claims plus any from
			// roles resolved through the enforcer.
			grantedScopes := resolveScopes(enforcer, claims.Scope, claims.Roles)

			if !authz.HasAllScopes(grantedScopes, required...) {
				return nil, connect.NewError(connect.CodePermissionDenied, fmt.Errorf("insufficient scopes for procedure %q", procedure))
			}

			return next(ctx, req)
		}
	}
}

// resolveScopes merges direct scopes with scopes derived from role membership
// using the enforcer's registry.
func resolveScopes(enforcer *authz.RBACEnforcer, directScopes, roles []string) []string {
	seen := make(map[string]bool, len(directScopes))
	merged := make([]string, 0, len(directScopes))

	for _, s := range directScopes {
		if !seen[s] {
			seen[s] = true
			merged = append(merged, s)
		}
	}

	for _, role := range roles {
		roleScopes, ok := enforcer.ScopesForRole(role)
		if !ok {
			continue
		}
		for _, s := range roleScopes {
			if !seen[s] {
				seen[s] = true
				merged = append(merged, s)
			}
		}
	}

	return merged
}
