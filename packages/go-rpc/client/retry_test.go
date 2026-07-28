// Copyright 2026 Penguin Tech Inc
// SPDX-License-Identifier: Apache-2.0

package client

import (
	"context"
	"errors"
	"testing"
	"time"

	"connectrpc.com/connect"
	"go.uber.org/zap"
)

func TestCalcBackoff_Exponential(t *testing.T) {
	cfg := DefaultRetryConfig()
	cfg.Jitter = false

	b0 := calcBackoff(cfg, 0)
	b1 := calcBackoff(cfg, 1)
	b2 := calcBackoff(cfg, 2)

	if b0 >= b1 {
		t.Errorf("expected backoff to increase: %v >= %v", b0, b1)
	}
	if b1 >= b2 {
		t.Errorf("expected backoff to increase: %v >= %v", b1, b2)
	}

	want1 := time.Duration(float64(cfg.InitialBackoff) * cfg.Multiplier)
	if b1 != want1 {
		t.Errorf("backoff1 = %v, want %v", b1, want1)
	}
}

func TestCalcBackoff_MaxCapped(t *testing.T) {
	cfg := DefaultRetryConfig()
	cfg.Jitter = false

	if b := calcBackoff(cfg, 100); b > cfg.MaxBackoff {
		t.Errorf("backoff = %v, want capped at %v", b, cfg.MaxBackoff)
	}
}

func TestCalcBackoff_Jitter(t *testing.T) {
	cfg := DefaultRetryConfig()
	cfg.Jitter = true
	cfg.InitialBackoff = 1 * time.Second
	cfg.Multiplier = 1.0

	b := calcBackoff(cfg, 0)
	min := time.Duration(float64(cfg.InitialBackoff) * 0.5)
	max := time.Duration(float64(cfg.InitialBackoff) * 1.5)
	if b < min || b > max {
		t.Errorf("backoff = %v, want in [%v, %v]", b, min, max)
	}
}

func TestDefaultRetryConfig(t *testing.T) {
	cfg := DefaultRetryConfig()
	if cfg.MaxRetries != 3 {
		t.Errorf("MaxRetries = %d, want 3", cfg.MaxRetries)
	}
	if cfg.InitialBackoff != 100*time.Millisecond {
		t.Errorf("InitialBackoff = %v, want 100ms", cfg.InitialBackoff)
	}
	if cfg.MaxBackoff != 5*time.Second {
		t.Errorf("MaxBackoff = %v, want 5s", cfg.MaxBackoff)
	}
	if cfg.Multiplier != 2.0 {
		t.Errorf("Multiplier = %f, want 2.0", cfg.Multiplier)
	}
	if !cfg.Jitter {
		t.Error("Jitter = false, want true")
	}
}

func TestIsRetryable(t *testing.T) {
	cases := []struct {
		name string
		err  error
		want bool
	}{
		{"nil", nil, false},
		{"unavailable", connect.NewError(connect.CodeUnavailable, errors.New("x")), true},
		{"deadline-exceeded", connect.NewError(connect.CodeDeadlineExceeded, errors.New("x")), true},
		{"invalid-argument", connect.NewError(connect.CodeInvalidArgument, errors.New("x")), false},
		{"permission-denied", connect.NewError(connect.CodePermissionDenied, errors.New("x")), false},
		{"unauthenticated", connect.NewError(connect.CodeUnauthenticated, errors.New("x")), false},
		{"plain-error", errors.New("not a connect error"), false},
	}
	for _, c := range cases {
		t.Run(c.name, func(t *testing.T) {
			if got := isRetryable(c.err); got != c.want {
				t.Errorf("isRetryable(%v) = %v, want %v", c.err, got, c.want)
			}
		})
	}
}

func fastRetryConfig() RetryConfig {
	cfg := DefaultRetryConfig()
	cfg.InitialBackoff = time.Millisecond
	cfg.MaxBackoff = 5 * time.Millisecond
	return cfg
}

func TestDoWithRetry_TransientThenSuccess(t *testing.T) {
	c, err := New(Config{}, zap.NewNop())
	if err != nil {
		t.Fatalf("New: %v", err)
	}

	attempts := 0
	result, err := DoWithRetry(context.Background(), c, fastRetryConfig(), zap.NewNop(), func(_ context.Context) (string, error) {
		attempts++
		if attempts < 3 {
			return "", connect.NewError(connect.CodeUnavailable, errors.New("transient"))
		}
		return "ok", nil
	})
	if err != nil {
		t.Fatalf("DoWithRetry: %v", err)
	}
	if result != "ok" {
		t.Errorf("result = %q, want ok", result)
	}
	if attempts != 3 {
		t.Errorf("attempts = %d, want 3", attempts)
	}
}

func TestDoWithRetry_PermissionDenied_OneAttemptOnly(t *testing.T) {
	c, err := New(Config{}, zap.NewNop())
	if err != nil {
		t.Fatalf("New: %v", err)
	}

	attempts := 0
	_, err = DoWithRetry(context.Background(), c, fastRetryConfig(), zap.NewNop(), func(_ context.Context) (string, error) {
		attempts++
		return "", connect.NewError(connect.CodePermissionDenied, errors.New("nope"))
	})
	if err == nil {
		t.Fatal("expected an error, got nil")
	}
	if attempts != 1 {
		t.Errorf("attempts = %d, want 1 (never retry CodePermissionDenied)", attempts)
	}
}

func TestDoWithRetry_InvalidArgument_OneAttemptOnly(t *testing.T) {
	c, err := New(Config{}, zap.NewNop())
	if err != nil {
		t.Fatalf("New: %v", err)
	}

	attempts := 0
	_, err = DoWithRetry(context.Background(), c, fastRetryConfig(), zap.NewNop(), func(_ context.Context) (string, error) {
		attempts++
		return "", connect.NewError(connect.CodeInvalidArgument, errors.New("bad request"))
	})
	if err == nil {
		t.Fatal("expected an error, got nil")
	}
	if attempts != 1 {
		t.Errorf("attempts = %d, want 1 (never retry CodeInvalidArgument)", attempts)
	}
}

func TestDoWithRetry_ExhaustsRetries_ReturnsLastError(t *testing.T) {
	c, err := New(Config{}, zap.NewNop())
	if err != nil {
		t.Fatalf("New: %v", err)
	}

	rcfg := fastRetryConfig()
	rcfg.MaxRetries = 2
	attempts := 0
	_, err = DoWithRetry(context.Background(), c, rcfg, zap.NewNop(), func(_ context.Context) (string, error) {
		attempts++
		return "", connect.NewError(connect.CodeUnavailable, errors.New("still down"))
	})
	if err == nil {
		t.Fatal("expected an error, got nil")
	}
	if attempts != rcfg.MaxRetries+1 {
		t.Errorf("attempts = %d, want %d (1 initial + MaxRetries retries)", attempts, rcfg.MaxRetries+1)
	}
}

func TestDoWithRetry_ContextCancelledDuringBackoff(t *testing.T) {
	c, err := New(Config{}, zap.NewNop())
	if err != nil {
		t.Fatalf("New: %v", err)
	}

	rcfg := DefaultRetryConfig()
	rcfg.InitialBackoff = time.Second // long enough for the cancel to win the select

	ctx, cancel := context.WithCancel(context.Background())
	attempts := 0
	go func() {
		time.Sleep(20 * time.Millisecond)
		cancel()
	}()

	_, err = DoWithRetry(ctx, c, rcfg, zap.NewNop(), func(_ context.Context) (string, error) {
		attempts++
		return "", connect.NewError(connect.CodeUnavailable, errors.New("down"))
	})
	if !errors.Is(err, context.Canceled) {
		t.Errorf("err = %v, want context.Canceled", err)
	}
	if attempts != 1 {
		t.Errorf("attempts = %d, want 1 (cancelled during first backoff wait)", attempts)
	}
}
