// Copyright 2026 Penguin Tech Inc
// SPDX-License-Identifier: Apache-2.0

package client

import (
	"context"
	"math"
	"math/rand/v2"
	"time"

	"connectrpc.com/connect"
	"go.uber.org/zap"
)

// RetryConfig controls DoWithRetry's backoff behavior. Semantics are
// salvaged verbatim from go-h3's client.RetryConfig.
type RetryConfig struct {
	MaxRetries     int
	InitialBackoff time.Duration
	MaxBackoff     time.Duration
	Multiplier     float64
	Jitter         bool
}

// DefaultRetryConfig returns a RetryConfig with sensible defaults,
// identical to go-h3's: 3 retries, 100ms initial backoff doubling up to a
// 5s cap, with jitter.
func DefaultRetryConfig() RetryConfig {
	return RetryConfig{
		MaxRetries:     3,
		InitialBackoff: 100 * time.Millisecond,
		MaxBackoff:     5 * time.Second,
		Multiplier:     2.0,
		Jitter:         true,
	}
}

// retryableCodes is the allow-list of connect.Code values DoWithRetry will
// retry: transient conditions where the same request might succeed on a
// later attempt. Every other code — including CodeInvalidArgument,
// CodePermissionDenied, CodeUnauthenticated, and CodeUnknown (the code
// connect.CodeOf assigns to an error that isn't a *connect.Error at all) —
// is treated as non-retryable: retrying a rejected or malformed request
// cannot change its outcome, and retrying an unauthenticated/unauthorized
// call to a fixed lane a second time provides no benefit and needlessly
// repeats a mutating request.
var retryableCodes = map[connect.Code]bool{
	connect.CodeUnavailable:      true,
	connect.CodeDeadlineExceeded: true,
}

// isRetryable reports whether err's connect.Code is in retryableCodes.
func isRetryable(err error) bool {
	if err == nil {
		return false
	}
	return retryableCodes[connect.CodeOf(err)]
}

// DoWithRetry executes fn with exponential backoff, retrying only on
// transient connect.Code failures (see retryableCodes). Lane
// selection/failover happens per attempt inside the *http.Client's
// RoundTripper (see lanes.go); DoWithRetry's sole responsibility is
// deciding whether a given failure is worth retrying at all and, if so,
// how long to wait before the next attempt.
func DoWithRetry[T any](ctx context.Context, c *Client, rcfg RetryConfig, logger *zap.Logger, fn func(context.Context) (T, error)) (T, error) {
	var zero T
	var lastErr error

	for attempt := 0; attempt <= rcfg.MaxRetries; attempt++ {
		result, err := fn(ctx)
		if err == nil {
			return result, nil
		}
		lastErr = err

		if !isRetryable(err) {
			return zero, err
		}

		if attempt >= rcfg.MaxRetries {
			break
		}

		backoff := calcBackoff(rcfg, attempt)
		if logger != nil {
			logger.Warn("request failed, retrying",
				zap.Int("attempt", attempt+1),
				zap.Int("max_retries", rcfg.MaxRetries),
				zap.Duration("backoff", backoff),
				zap.String("protocol", c.Protocol()),
				zap.Error(err),
			)
		}

		select {
		case <-ctx.Done():
			return zero, ctx.Err()
		case <-time.After(backoff):
		}
	}

	return zero, lastErr
}

// calcBackoff computes the exponential backoff duration for attempt,
// capped at cfg.MaxBackoff and optionally jittered to +/-50%. Salvaged
// verbatim from go-h3.
func calcBackoff(cfg RetryConfig, attempt int) time.Duration {
	backoff := float64(cfg.InitialBackoff) * math.Pow(cfg.Multiplier, float64(attempt))
	if backoff > float64(cfg.MaxBackoff) {
		backoff = float64(cfg.MaxBackoff)
	}
	if cfg.Jitter {
		backoff *= 0.5 + rand.Float64() //nolint:gosec // jitter does not require crypto-grade randomness; used for exponential backoff only
	}
	return time.Duration(backoff)
}
