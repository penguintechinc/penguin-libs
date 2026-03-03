package middleware

import (
	"context"

	"connectrpc.com/connect"

	"github.com/penguintechinc/penguin-libs/packages/go-aaa/audit"
	"github.com/penguintechinc/penguin-libs/packages/go-aaa/authz"
)

// NewAuditInterceptor returns a ConnectRPC interceptor that automatically emits an
// audit event after each RPC completes. The event type is EventAuthzGranted on success
// and EventAuthzDenied on failure. Events whose type appears in the WithSkipAuditTypes
// option are silently suppressed.
func NewAuditInterceptor(emitter *audit.Emitter, opts ...InterceptorOption) connect.UnaryInterceptorFunc {
	cfg := applyOptions(opts)
	return func(next connect.UnaryFunc) connect.UnaryFunc {
		return func(ctx context.Context, req connect.AnyRequest) (connect.AnyResponse, error) {
			procedure := req.Spec().Procedure
			subject := subjectFromContext(ctx)

			resp, err := next(ctx, req)

			eventType, outcome := classifyResult(err)
			if cfg.skipAuditTypes[eventType] {
				return resp, err
			}

			event := audit.NewAuditEvent(eventType, subject, "rpc", procedure, outcome)
			_ = emitter.Emit(event)

			return resp, err
		}
	}
}

// subjectFromContext extracts the subject from Claims in context, falling back to
// "anonymous" when no claims are present.
func subjectFromContext(ctx context.Context) string {
	claims := authz.ClaimsFromContext(ctx)
	if claims == nil || claims.Sub == "" {
		return "anonymous"
	}
	return claims.Sub
}

// classifyResult maps an RPC outcome to an EventType and Outcome pair.
func classifyResult(err error) (audit.EventType, audit.Outcome) {
	if err == nil {
		return audit.EventAuthzGranted, audit.OutcomeSuccess
	}

	code := connect.CodeOf(err)
	switch code {
	case connect.CodeUnauthenticated:
		return audit.EventAuthFailure, audit.OutcomeFailure
	case connect.CodePermissionDenied:
		return audit.EventAuthzDenied, audit.OutcomeFailure
	default:
		return audit.EventAuthzDenied, audit.OutcomeFailure
	}
}
