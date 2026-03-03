package authn

import (
	"context"
	"errors"
	"strings"

	"connectrpc.com/connect"
	"github.com/penguintechinc/penguin-libs/packages/go-common/logging"
	"go.uber.org/zap"
)

// contextKey is an unexported type for context keys in this package.
type contextKey struct{}

// claimsKey is the context key for storing validated Claims.
var claimsKey = contextKey{}

// ClaimsFromContext returns the Claims stored in ctx by ConnectAuthInterceptor,
// along with a boolean indicating whether claims were present.
func ClaimsFromContext(ctx context.Context) (*Claims, bool) {
	claims, ok := ctx.Value(claimsKey).(*Claims)
	return claims, ok
}

// TokenValidator is implemented by any type that can validate a raw JWT and
// return Claims. OIDCRelyingParty satisfies this interface.
type TokenValidator interface {
	ValidateToken(ctx context.Context, rawToken string) (*Claims, error)
}

// ConnectAuthInterceptor is a Connect RPC unary interceptor that validates
// Bearer tokens from the Authorization header and injects the resulting
// Claims into the request context.
type ConnectAuthInterceptor struct {
	validator TokenValidator
	logger    *logging.SanitizedLogger
}

// NewConnectAuthInterceptor creates a ConnectAuthInterceptor using the given
// TokenValidator. Requests without a valid Bearer token are rejected with
// connect.CodeUnauthenticated. A sanitized logger is created internally to
// avoid leaking token values into logs.
func NewConnectAuthInterceptor(validator TokenValidator) (*ConnectAuthInterceptor, error) {
	logger, err := logging.NewSanitizedLogger("authn.connect")
	if err != nil {
		return nil, err
	}
	return &ConnectAuthInterceptor{validator: validator, logger: logger}, nil
}

// WrapUnary implements connect.Interceptor for unary RPCs.
func (i *ConnectAuthInterceptor) WrapUnary(next connect.UnaryFunc) connect.UnaryFunc {
	return func(ctx context.Context, req connect.AnyRequest) (connect.AnyResponse, error) {
		token, err := extractBearerToken(req.Header().Get("Authorization"))
		if err != nil {
			i.logger.Warn("unauthenticated unary request: missing or malformed bearer token",
				zap.String("procedure", req.Spec().Procedure))
			return nil, connect.NewError(connect.CodeUnauthenticated, err)
		}

		claims, err := i.validator.ValidateToken(ctx, token)
		if err != nil {
			i.logger.Warn("unauthenticated unary request: token validation failed",
				zap.String("procedure", req.Spec().Procedure),
				zap.Error(err))
			return nil, connect.NewError(connect.CodeUnauthenticated, err)
		}

		i.logger.Debug("authenticated unary request",
			zap.String("procedure", req.Spec().Procedure),
			zap.String("sub", claims.Sub))
		ctx = context.WithValue(ctx, claimsKey, claims)
		return next(ctx, req)
	}
}

// WrapStreamingClient implements connect.Interceptor for streaming clients (no-op).
func (i *ConnectAuthInterceptor) WrapStreamingClient(next connect.StreamingClientFunc) connect.StreamingClientFunc {
	return next
}

// WrapStreamingHandler implements connect.Interceptor for streaming server handlers.
func (i *ConnectAuthInterceptor) WrapStreamingHandler(next connect.StreamingHandlerFunc) connect.StreamingHandlerFunc {
	return func(ctx context.Context, conn connect.StreamingHandlerConn) error {
		token, err := extractBearerToken(conn.RequestHeader().Get("Authorization"))
		if err != nil {
			i.logger.Warn("unauthenticated streaming request: missing or malformed bearer token")
			return connect.NewError(connect.CodeUnauthenticated, err)
		}

		claims, err := i.validator.ValidateToken(ctx, token)
		if err != nil {
			i.logger.Warn("unauthenticated streaming request: token validation failed", zap.Error(err))
			return connect.NewError(connect.CodeUnauthenticated, err)
		}

		i.logger.Debug("authenticated streaming request", zap.String("sub", claims.Sub))
		ctx = context.WithValue(ctx, claimsKey, claims)
		return next(ctx, conn)
	}
}

// extractBearerToken parses a Bearer token from an Authorization header value.
func extractBearerToken(authHeader string) (string, error) {
	const prefix = "Bearer "
	if !strings.HasPrefix(authHeader, prefix) {
		return "", connect.NewError(connect.CodeUnauthenticated, errors.New("authorization header must use Bearer scheme"))
	}
	token := strings.TrimPrefix(authHeader, prefix)
	if token == "" {
		return "", connect.NewError(connect.CodeUnauthenticated, errors.New("bearer token must not be empty"))
	}
	return token, nil
}
