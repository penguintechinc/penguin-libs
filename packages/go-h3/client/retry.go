package client

import (
	"context"
	"math"
	"math/rand/v2"
	"time"

	"go.uber.org/zap"
)

// RetryConfig controls retry behavior.
type RetryConfig struct {
	MaxRetries     int
	InitialBackoff time.Duration
	MaxBackoff     time.Duration
	Multiplier     float64
	Jitter         bool
}

// DefaultRetryConfig returns a RetryConfig with sensible defaults.
func DefaultRetryConfig() RetryConfig {
	return RetryConfig{
		MaxRetries:     3,
		InitialBackoff: 100 * time.Millisecond,
		MaxBackoff:     5 * time.Second,
		Multiplier:     2.0,
		Jitter:         true,
	}
}

// DoWithRetry executes fn with exponential backoff retries.
// It calls the client's MarkH3Failed on the first failure and
// falls back to HTTP/2 for subsequent attempts.
func DoWithRetry[T any](ctx context.Context, c *Client, rcfg RetryConfig, logger *zap.Logger, fn func() (T, error)) (T, error) {
	var lastErr error
	var zero T

	for attempt := 0; attempt <= rcfg.MaxRetries; attempt++ {
		c.MaybeRetryH3()

		result, err := fn()
		if err == nil {
			return result, nil
		}
		lastErr = err

		// On first failure with H3, mark it as failed to trigger fallback.
		if attempt == 0 && c.Protocol() == "h3" {
			c.MarkH3Failed()
		}

		if attempt >= rcfg.MaxRetries {
			break
		}

		backoff := calcBackoff(rcfg, attempt)
		logger.Warn("request failed, retrying",
			zap.Int("attempt", attempt+1),
			zap.Int("max_retries", rcfg.MaxRetries),
			zap.Duration("backoff", backoff),
			zap.Error(err),
		)

		select {
		case <-ctx.Done():
			return zero, ctx.Err()
		case <-time.After(backoff):
		}
	}

	return zero, lastErr
}

func calcBackoff(cfg RetryConfig, attempt int) time.Duration {
	backoff := float64(cfg.InitialBackoff) * math.Pow(cfg.Multiplier, float64(attempt))
	if backoff > float64(cfg.MaxBackoff) {
		backoff = float64(cfg.MaxBackoff)
	}
	if cfg.Jitter {
		backoff *= 0.5 + rand.Float64()
	}
	return time.Duration(backoff)
}
