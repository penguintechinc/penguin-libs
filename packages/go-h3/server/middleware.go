package server

import (
	"context"
	"fmt"
	"runtime/debug"
	"time"

	"connectrpc.com/connect"
	"go.uber.org/zap"
)

// correlationKey is the context key for correlation IDs.
type correlationKey struct{}

// CorrelationIDFromContext extracts the correlation ID from context.
func CorrelationIDFromContext(ctx context.Context) string {
	if v, ok := ctx.Value(correlationKey{}).(string); ok {
		return v
	}
	return ""
}

// NewLoggingInterceptor returns a ConnectRPC interceptor that logs requests.
func NewLoggingInterceptor(logger *zap.Logger) connect.UnaryInterceptorFunc {
	return func(next connect.UnaryFunc) connect.UnaryFunc {
		return func(ctx context.Context, req connect.AnyRequest) (connect.AnyResponse, error) {
			start := time.Now()
			procedure := req.Spec().Procedure
			protocol := req.Peer().Protocol

			resp, err := next(ctx, req)

			duration := time.Since(start)
			if err != nil {
				logger.Warn("rpc failed",
					zap.String("procedure", procedure),
					zap.String("protocol", protocol),
					zap.Duration("duration", duration),
					zap.Error(err),
				)
			} else {
				logger.Info("rpc completed",
					zap.String("procedure", procedure),
					zap.String("protocol", protocol),
					zap.Duration("duration", duration),
				)
			}
			return resp, err
		}
	}
}

// NewAuthInterceptor returns a ConnectRPC interceptor that validates JWT tokens.
// validateFn receives the raw Bearer token and returns an error if invalid.
func NewAuthInterceptor(validateFn func(token string) error, publicProcedures map[string]bool) connect.UnaryInterceptorFunc {
	return func(next connect.UnaryFunc) connect.UnaryFunc {
		return func(ctx context.Context, req connect.AnyRequest) (connect.AnyResponse, error) {
			if publicProcedures[req.Spec().Procedure] {
				return next(ctx, req)
			}
			auth := req.Header().Get("Authorization")
			if len(auth) < 8 || auth[:7] != "Bearer " {
				return nil, connect.NewError(connect.CodeUnauthenticated, fmt.Errorf("missing bearer token"))
			}
			if err := validateFn(auth[7:]); err != nil {
				return nil, connect.NewError(connect.CodeUnauthenticated, fmt.Errorf("invalid token: %w", err))
			}
			return next(ctx, req)
		}
	}
}

// NewMetricsInterceptor returns a ConnectRPC interceptor that records
// request counts and durations. counterFn and histogramFn are callbacks
// so callers can wire in their own Prometheus (or other) metrics.
func NewMetricsInterceptor(
	counterFn func(procedure, protocol, code string),
	histogramFn func(procedure, protocol string, durationSec float64),
) connect.UnaryInterceptorFunc {
	return func(next connect.UnaryFunc) connect.UnaryFunc {
		return func(ctx context.Context, req connect.AnyRequest) (connect.AnyResponse, error) {
			start := time.Now()
			resp, err := next(ctx, req)
			duration := time.Since(start).Seconds()

			code := "ok"
			if err != nil {
				code = connect.CodeOf(err).String()
			}

			procedure := req.Spec().Procedure
			protocol := req.Peer().Protocol
			counterFn(procedure, protocol, code)
			histogramFn(procedure, protocol, duration)

			return resp, err
		}
	}
}

// NewCorrelationInterceptor propagates or generates X-Correlation-ID headers.
func NewCorrelationInterceptor(genID func() string) connect.UnaryInterceptorFunc {
	return func(next connect.UnaryFunc) connect.UnaryFunc {
		return func(ctx context.Context, req connect.AnyRequest) (connect.AnyResponse, error) {
			cid := req.Header().Get("X-Correlation-ID")
			if cid == "" {
				cid = genID()
			}
			ctx = context.WithValue(ctx, correlationKey{}, cid)

			resp, err := next(ctx, req)
			if resp != nil {
				resp.Header().Set("X-Correlation-ID", cid)
			}
			return resp, err
		}
	}
}

// NewRecoveryInterceptor catches panics in handlers and returns an internal error.
func NewRecoveryInterceptor(logger *zap.Logger) connect.UnaryInterceptorFunc {
	return func(next connect.UnaryFunc) connect.UnaryFunc {
		return func(ctx context.Context, req connect.AnyRequest) (resp connect.AnyResponse, err error) {
			defer func() {
				if r := recover(); r != nil {
					logger.Error("panic recovered in handler",
						zap.Any("panic", r),
						zap.String("stack", string(debug.Stack())),
						zap.String("procedure", req.Spec().Procedure),
					)
					err = connect.NewError(connect.CodeInternal, fmt.Errorf("internal error"))
				}
			}()
			return next(ctx, req)
		}
	}
}
