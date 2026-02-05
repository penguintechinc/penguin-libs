package server

import (
	"context"
	"errors"
	"testing"

	"connectrpc.com/connect"
	"go.uber.org/zap"
)

func TestAuthInterceptor_ValidToken(t *testing.T) {
	validateFn := func(token string) error {
		if token != "valid-token" {
			return errors.New("invalid token")
		}
		return nil
	}

	interceptor := NewAuthInterceptor(validateFn, nil)
	nextCalled := false
	wrapped := interceptor(func(ctx context.Context, req connect.AnyRequest) (connect.AnyResponse, error) {
		nextCalled = true
		return nil, nil
	})

	req := connect.NewRequest(&struct{}{})
	req.Header().Set("Authorization", "Bearer valid-token")

	_, err := wrapped(context.Background(), req)
	if err != nil {
		t.Errorf("expected no error, got %v", err)
	}
	if !nextCalled {
		t.Error("next handler should have been called")
	}
}

func TestAuthInterceptor_InvalidToken(t *testing.T) {
	validateFn := func(token string) error {
		return errors.New("invalid token")
	}

	interceptor := NewAuthInterceptor(validateFn, nil)
	wrapped := interceptor(func(ctx context.Context, req connect.AnyRequest) (connect.AnyResponse, error) {
		return nil, nil
	})

	req := connect.NewRequest(&struct{}{})
	req.Header().Set("Authorization", "Bearer invalid-token")

	_, err := wrapped(context.Background(), req)
	if err == nil {
		t.Error("expected error, got nil")
	}
	if connect.CodeOf(err) != connect.CodeUnauthenticated {
		t.Errorf("expected CodeUnauthenticated, got %v", connect.CodeOf(err))
	}
}

func TestAuthInterceptor_MissingToken(t *testing.T) {
	validateFn := func(token string) error {
		return nil
	}

	interceptor := NewAuthInterceptor(validateFn, nil)
	wrapped := interceptor(func(ctx context.Context, req connect.AnyRequest) (connect.AnyResponse, error) {
		return nil, nil
	})

	req := connect.NewRequest(&struct{}{})
	// No Authorization header

	_, err := wrapped(context.Background(), req)
	if err == nil {
		t.Error("expected error, got nil")
	}
	if connect.CodeOf(err) != connect.CodeUnauthenticated {
		t.Errorf("expected CodeUnauthenticated, got %v", connect.CodeOf(err))
	}
}

func TestAuthInterceptor_PublicProcedure(t *testing.T) {
	validateFn := func(token string) error {
		return errors.New("should not be called")
	}

	// Note: connect.NewRequest creates a Spec with empty Procedure.
	// PublicProcedures map checks req.Spec().Procedure, which is "" for our test request.
	publicProcedures := map[string]bool{
		"": true, // empty procedure treated as public for test
	}

	interceptor := NewAuthInterceptor(validateFn, publicProcedures)
	wrapped := interceptor(func(ctx context.Context, req connect.AnyRequest) (connect.AnyResponse, error) {
		return nil, nil
	})

	req := connect.NewRequest(&struct{}{})
	// No Authorization header — but procedure is public

	_, err := wrapped(context.Background(), req)
	if err != nil {
		t.Errorf("expected no error for public procedure, got %v", err)
	}
}

func TestLoggingInterceptor_Success(t *testing.T) {
	logger := zap.NewNop()
	interceptor := NewLoggingInterceptor(logger)
	wrapped := interceptor(func(ctx context.Context, req connect.AnyRequest) (connect.AnyResponse, error) {
		return nil, nil
	})

	req := connect.NewRequest(&struct{}{})

	_, err := wrapped(context.Background(), req)
	if err != nil {
		t.Errorf("expected no error, got %v", err)
	}
}

func TestLoggingInterceptor_Error(t *testing.T) {
	logger := zap.NewNop()
	interceptor := NewLoggingInterceptor(logger)
	expectedErr := errors.New("test error")
	wrapped := interceptor(func(ctx context.Context, req connect.AnyRequest) (connect.AnyResponse, error) {
		return nil, expectedErr
	})

	req := connect.NewRequest(&struct{}{})

	_, err := wrapped(context.Background(), req)
	if !errors.Is(err, expectedErr) {
		t.Errorf("expected original error, got %v", err)
	}
}

func TestMetricsInterceptor_Callbacks(t *testing.T) {
	counterCalled := false
	histogramCalled := false

	counterFn := func(procedure, protocol, code string) {
		counterCalled = true
		if code != "ok" {
			t.Errorf("expected code ok, got %s", code)
		}
	}

	histogramFn := func(procedure, protocol string, duration float64) {
		histogramCalled = true
		if duration < 0 {
			t.Error("duration should be non-negative")
		}
	}

	interceptor := NewMetricsInterceptor(counterFn, histogramFn)
	wrapped := interceptor(func(ctx context.Context, req connect.AnyRequest) (connect.AnyResponse, error) {
		return nil, nil
	})

	req := connect.NewRequest(&struct{}{})

	_, _ = wrapped(context.Background(), req)

	if !counterCalled {
		t.Error("counter callback should have been called")
	}
	if !histogramCalled {
		t.Error("histogram callback should have been called")
	}
}

func TestCorrelationInterceptor_GeneratesID(t *testing.T) {
	genIDCalled := false
	genID := func() string {
		genIDCalled = true
		return "test-correlation-id"
	}

	interceptor := NewCorrelationInterceptor(genID)
	wrapped := interceptor(func(ctx context.Context, req connect.AnyRequest) (connect.AnyResponse, error) {
		id := CorrelationIDFromContext(ctx)
		if id != "test-correlation-id" {
			t.Errorf("expected test-correlation-id in context, got %v", id)
		}
		return nil, nil
	})

	req := connect.NewRequest(&struct{}{})

	_, _ = wrapped(context.Background(), req)

	if !genIDCalled {
		t.Error("genID should have been called")
	}
}

func TestCorrelationInterceptor_PropagatesID(t *testing.T) {
	genID := func() string {
		t.Error("genID should not be called when header present")
		return "should-not-use"
	}

	interceptor := NewCorrelationInterceptor(genID)
	wrapped := interceptor(func(ctx context.Context, req connect.AnyRequest) (connect.AnyResponse, error) {
		id := CorrelationIDFromContext(ctx)
		if id != "existing-correlation-id" {
			t.Errorf("expected existing-correlation-id in context, got %v", id)
		}
		return nil, nil
	})

	req := connect.NewRequest(&struct{}{})
	req.Header().Set("X-Correlation-ID", "existing-correlation-id")

	_, _ = wrapped(context.Background(), req)
}

func TestRecoveryInterceptor_PanicRecovered(t *testing.T) {
	logger := zap.NewNop()
	interceptor := NewRecoveryInterceptor(logger)
	wrapped := interceptor(func(ctx context.Context, req connect.AnyRequest) (connect.AnyResponse, error) {
		panic("test panic")
	})

	req := connect.NewRequest(&struct{}{})

	_, err := wrapped(context.Background(), req)
	if err == nil {
		t.Error("expected error, got nil")
	}
	if connect.CodeOf(err) != connect.CodeInternal {
		t.Errorf("expected CodeInternal, got %v", connect.CodeOf(err))
	}
}
