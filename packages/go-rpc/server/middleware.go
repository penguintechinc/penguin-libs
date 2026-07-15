// Copyright 2026 Penguin Tech Inc
// SPDX-License-Identifier: Apache-2.0

package server

import (
	"context"
	"errors"
	"fmt"
	"runtime/debug"
	"time"

	"connectrpc.com/connect"
	"github.com/google/uuid"
	"github.com/prometheus/client_golang/prometheus"
	"go.uber.org/zap"
)

// correlationHeader is the pRPC spec §8 header used to propagate a
// correlation ID between caller and callee.
const correlationHeader = "X-Correlation-Id"

// correlationCtxKey is the context key under which the active correlation ID
// is stored by NewCorrelationInterceptor.
type correlationCtxKey struct{}

// CorrelationIDFromContext extracts the correlation ID stashed by
// NewCorrelationInterceptor from ctx, returning "" if none is present (for
// example, outside a request handled by that interceptor).
func CorrelationIDFromContext(ctx context.Context) string {
	if v, ok := ctx.Value(correlationCtxKey{}).(string); ok {
		return v
	}
	return ""
}

// NewLoggingInterceptor logs one structured entry per unary RPC: procedure,
// protocol, correlation ID, and duration, plus the error on failure. It
// never logs request or response headers, so secrets carried there
// (Authorization, Cookie, etc.) cannot leak into logs through this
// interceptor — per spec §8's sanitized-logging requirement.
func NewLoggingInterceptor(logger *zap.Logger) connect.UnaryInterceptorFunc {
	return func(next connect.UnaryFunc) connect.UnaryFunc {
		return func(ctx context.Context, req connect.AnyRequest) (connect.AnyResponse, error) {
			start := time.Now()
			procedure := req.Spec().Procedure
			protocol := req.Peer().Protocol

			resp, err := next(ctx, req)

			fields := []zap.Field{
				zap.String("procedure", procedure),
				zap.String("protocol", protocol),
				zap.String("correlation_id", CorrelationIDFromContext(ctx)),
				zap.Duration("duration", time.Since(start)),
			}
			if err != nil {
				logger.Warn("rpc failed", append(fields, zap.Error(err))...)
			} else {
				logger.Info("rpc completed", fields...)
			}
			return resp, err
		}
	}
}

// NewMetricsInterceptor returns a Prometheus-backed observability
// interceptor: a request counter, an error counter, and a duration
// histogram, all labeled by procedure and protocol (the counters are also
// labeled by the resulting status code). Metrics register against
// prometheus.DefaultRegisterer unless a Registerer is supplied — pass a
// private prometheus.NewRegistry() in tests to avoid colliding with other
// packages' metrics in the default registry. Registering the same metric
// names against the same registerer more than once (e.g. constructing
// several servers in one process) reuses the already-registered collectors
// instead of panicking.
func NewMetricsInterceptor(registerer ...prometheus.Registerer) connect.Interceptor {
	reg := prometheus.Registerer(prometheus.DefaultRegisterer)
	if len(registerer) > 0 && registerer[0] != nil {
		reg = registerer[0]
	}

	requestCount := registerCounterVec(reg, prometheus.CounterOpts{
		Name: "prpc_server_requests_total",
		Help: "Total number of pRPC unary requests processed, labeled by procedure, protocol, and result code.",
	}, []string{"procedure", "protocol", "code"})

	errorCount := registerCounterVec(reg, prometheus.CounterOpts{
		Name: "prpc_server_request_errors_total",
		Help: "Total number of pRPC unary requests that returned an error, labeled by procedure, protocol, and result code.",
	}, []string{"procedure", "protocol", "code"})

	requestDuration := registerHistogramVec(reg, prometheus.HistogramOpts{
		Name:    "prpc_server_request_duration_seconds",
		Help:    "Duration of pRPC unary requests in seconds, labeled by procedure and protocol.",
		Buckets: prometheus.DefBuckets,
	}, []string{"procedure", "protocol"})

	return connect.UnaryInterceptorFunc(func(next connect.UnaryFunc) connect.UnaryFunc {
		return func(ctx context.Context, req connect.AnyRequest) (connect.AnyResponse, error) {
			start := time.Now()
			procedure := req.Spec().Procedure
			protocol := req.Peer().Protocol

			resp, err := next(ctx, req)

			code := "ok"
			if err != nil {
				code = connect.CodeOf(err).String()
				errorCount.WithLabelValues(procedure, protocol, code).Inc()
			}
			requestCount.WithLabelValues(procedure, protocol, code).Inc()
			requestDuration.WithLabelValues(procedure, protocol).Observe(time.Since(start).Seconds())

			return resp, err
		}
	})
}

// registerCounterVec registers a new CounterVec against reg, reusing an
// already-registered collector with the same descriptor (e.g. from a prior
// call against prometheus.DefaultRegisterer) instead of panicking.
func registerCounterVec(reg prometheus.Registerer, opts prometheus.CounterOpts, labels []string) *prometheus.CounterVec {
	vec := prometheus.NewCounterVec(opts, labels)
	if err := reg.Register(vec); err != nil {
		var already prometheus.AlreadyRegisteredError
		if errors.As(err, &already) {
			if existing, ok := already.ExistingCollector.(*prometheus.CounterVec); ok {
				return existing
			}
		}
	}
	return vec
}

// registerHistogramVec is registerCounterVec's HistogramVec counterpart.
func registerHistogramVec(reg prometheus.Registerer, opts prometheus.HistogramOpts, labels []string) *prometheus.HistogramVec {
	vec := prometheus.NewHistogramVec(opts, labels)
	if err := reg.Register(vec); err != nil {
		var already prometheus.AlreadyRegisteredError
		if errors.As(err, &already) {
			if existing, ok := already.ExistingCollector.(*prometheus.HistogramVec); ok {
				return existing
			}
		}
	}
	return vec
}

// NewCorrelationInterceptor propagates the caller's X-Correlation-Id header
// (spec §8) or generates a new UUID when absent, stashes it in context for
// CorrelationIDFromContext, and echoes it back on the response header.
func NewCorrelationInterceptor() connect.Interceptor {
	return connect.UnaryInterceptorFunc(func(next connect.UnaryFunc) connect.UnaryFunc {
		return func(ctx context.Context, req connect.AnyRequest) (connect.AnyResponse, error) {
			cid := req.Header().Get(correlationHeader)
			if cid == "" {
				cid = uuid.NewString()
			}
			ctx = context.WithValue(ctx, correlationCtxKey{}, cid)

			resp, err := next(ctx, req)
			if resp != nil {
				resp.Header().Set(correlationHeader, cid)
			}
			return resp, err
		}
	})
}

// NewRecoveryInterceptor recovers from panics raised anywhere further down
// the interceptor chain or in the handler, logs the stack, and converts the
// panic into a CodeInternal error. The panic value itself is never included
// in the returned error, so it cannot leak to the caller — only to the
// server's own logs.
func NewRecoveryInterceptor(logger *zap.Logger) connect.Interceptor {
	return connect.UnaryInterceptorFunc(func(next connect.UnaryFunc) connect.UnaryFunc {
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
	})
}

// NewDeadlineInterceptor applies d as the request context's deadline for
// unary calls that arrive without a caller-supplied deadline (spec §3's
// default unary timeout). It never shortens or replaces a deadline the
// caller already set, and — because it is built on
// connect.UnaryInterceptorFunc, whose streaming wrapping is a no-op — it has
// no effect on streaming calls. d <= 0 disables the default entirely,
// leaving every context untouched.
func NewDeadlineInterceptor(d time.Duration) connect.Interceptor {
	return connect.UnaryInterceptorFunc(func(next connect.UnaryFunc) connect.UnaryFunc {
		return func(ctx context.Context, req connect.AnyRequest) (connect.AnyResponse, error) {
			if d <= 0 {
				return next(ctx, req)
			}
			if _, ok := ctx.Deadline(); !ok {
				var cancel context.CancelFunc
				ctx, cancel = context.WithTimeout(ctx, d)
				defer cancel()
			}
			return next(ctx, req)
		}
	})
}

// DefaultInterceptors returns the canonical pRPC interceptor chain in
// execution order (outermost to innermost, matching connect.WithInterceptors
// semantics): recovery, correlation, deadline, logging, metrics. Recovery
// sits outermost so it catches panics raised by any interceptor that
// follows it, or by the handler itself; metrics sits innermost so its
// duration measurement covers only the handler plus logging. cfg's
// DefaultUnaryTimeout drives the deadline interceptor; a zero value falls
// back to the package default (30s, spec §3).
func DefaultInterceptors(logger *zap.Logger, cfg Config) []connect.Interceptor {
	timeout := cfg.DefaultUnaryTimeout
	if timeout <= 0 {
		timeout = defaultUnaryTimeout
	}
	return []connect.Interceptor{
		NewRecoveryInterceptor(logger),
		NewCorrelationInterceptor(),
		NewDeadlineInterceptor(timeout),
		NewLoggingInterceptor(logger),
		NewMetricsInterceptor(),
	}
}
