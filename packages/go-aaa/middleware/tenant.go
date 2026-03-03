package middleware

import (
	"context"
	"fmt"

	"connectrpc.com/connect"

	"github.com/penguintechinc/penguin-libs/packages/go-aaa/authz"
)

// NewTenantInterceptor returns a ConnectRPC interceptor that enforces the presence
// of a non-empty tenant claim on every non-public procedure. It must run after an
// authentication interceptor that stores Claims in the context.
func NewTenantInterceptor(opts ...InterceptorOption) connect.UnaryInterceptorFunc {
	cfg := applyOptions(opts)
	return func(next connect.UnaryFunc) connect.UnaryFunc {
		return func(ctx context.Context, req connect.AnyRequest) (connect.AnyResponse, error) {
			if cfg.publicProcedures[req.Spec().Procedure] {
				return next(ctx, req)
			}

			tenant := authz.TenantFromContext(ctx)
			if tenant == "" {
				return nil, connect.NewError(connect.CodePermissionDenied, fmt.Errorf("missing tenant claim"))
			}

			return next(ctx, req)
		}
	}
}
