// Copyright 2026 Penguin Tech Inc
// SPDX-License-Identifier: Apache-2.0

package server

import (
	"context"
	"errors"
	"reflect"
	"runtime"
	"strings"
	"testing"
	"time"

	"connectrpc.com/connect"
	"github.com/prometheus/client_golang/prometheus"
	"go.uber.org/zap"
	"go.uber.org/zap/zaptest/observer"
)

// --- Logging (salvaged from go-h3, ported green) ---

func TestLoggingInterceptor_Success(t *testing.T) {
	logger := zap.NewNop()
	interceptor := NewLoggingInterceptor(logger)
	wrapped := interceptor(func(_ context.Context, _ connect.AnyRequest) (connect.AnyResponse, error) {
		return connect.NewResponse(&struct{}{}), nil
	})

	_, err := wrapped(context.Background(), connect.NewRequest(&struct{}{}))
	if err != nil {
		t.Errorf("expected no error, got %v", err)
	}
}

func TestLoggingInterceptor_Error(t *testing.T) {
	logger := zap.NewNop()
	interceptor := NewLoggingInterceptor(logger)
	expectedErr := errors.New("test error")
	wrapped := interceptor(func(_ context.Context, _ connect.AnyRequest) (connect.AnyResponse, error) {
		return nil, expectedErr
	})

	_, err := wrapped(context.Background(), connect.NewRequest(&struct{}{}))
	if !errors.Is(err, expectedErr) {
		t.Errorf("expected original error, got %v", err)
	}
}

// TestLoggingInterceptor_SanitizesSensitiveHeaders is the NEW logging
// sanitization test required by Task 3: a request carrying Authorization and
// Cookie header values must never have those values appear anywhere in the
// logged output, across every observed entry and every structured field.
func TestLoggingInterceptor_SanitizesSensitiveHeaders(t *testing.T) {
	core, observed := observer.New(zap.DebugLevel)
	logger := zap.New(core)
	interceptor := NewLoggingInterceptor(logger)

	const secretToken = "secret-token-12345"
	const secretCookie = "session=abc"

	wrapped := interceptor(func(_ context.Context, _ connect.AnyRequest) (connect.AnyResponse, error) {
		return connect.NewResponse(&struct{}{}), nil
	})

	req := connect.NewRequest(&struct{}{})
	req.Header().Set("Authorization", "Bearer "+secretToken)
	req.Header().Set("Cookie", secretCookie)

	if _, err := wrapped(context.Background(), req); err != nil {
		t.Fatalf("unexpected error: %v", err)
	}

	// Also exercise the error path, since a failed-RPC log line is a second
	// place a naive implementation might be tempted to dump request state.
	errWrapped := interceptor(func(_ context.Context, _ connect.AnyRequest) (connect.AnyResponse, error) {
		return nil, connect.NewError(connect.CodeInvalidArgument, errors.New("bad request"))
	})
	_, _ = errWrapped(context.Background(), req)

	for _, entry := range observed.All() {
		full := entry.Message
		for k, v := range entry.ContextMap() {
			full += " " + k + "=" + toString(v)
		}
		if strings.Contains(full, secretToken) {
			t.Errorf("log entry leaked Authorization token: %q", full)
		}
		if strings.Contains(full, secretCookie) {
			t.Errorf("log entry leaked Cookie value: %q", full)
		}
	}
}

func toString(v interface{}) string {
	if err, ok := v.(error); ok {
		return err.Error()
	}
	if s, ok := v.(string); ok {
		return s
	}
	return ""
}

// --- Metrics ---

func TestMetricsInterceptor_CountsSuccess(t *testing.T) {
	reg := prometheus.NewRegistry()
	interceptor := NewMetricsInterceptor(reg)
	wrapped := interceptor.WrapUnary(func(_ context.Context, _ connect.AnyRequest) (connect.AnyResponse, error) {
		return connect.NewResponse(&struct{}{}), nil
	})

	if _, err := wrapped(context.Background(), connect.NewRequest(&struct{}{})); err != nil {
		t.Fatalf("unexpected error: %v", err)
	}

	got := counterValue(t, reg, "prpc_server_requests_total", map[string]string{
		"procedure": "", "protocol": "", "code": "ok",
	})
	if got != 1 {
		t.Errorf("prpc_server_requests_total = %v, want 1", got)
	}

	sampleCount := histogramSampleCount(t, reg, "prpc_server_request_duration_seconds", map[string]string{
		"procedure": "", "protocol": "",
	})
	if sampleCount != 1 {
		t.Errorf("prpc_server_request_duration_seconds sample count = %v, want 1", sampleCount)
	}
}

func TestMetricsInterceptor_CountsError(t *testing.T) {
	reg := prometheus.NewRegistry()
	interceptor := NewMetricsInterceptor(reg)
	wrapped := interceptor.WrapUnary(func(_ context.Context, _ connect.AnyRequest) (connect.AnyResponse, error) {
		return nil, connect.NewError(connect.CodeInternal, errors.New("boom"))
	})

	if _, err := wrapped(context.Background(), connect.NewRequest(&struct{}{})); err == nil {
		t.Fatal("expected error")
	}

	errCount := counterValue(t, reg, "prpc_server_request_errors_total", map[string]string{
		"procedure": "", "protocol": "", "code": connect.CodeInternal.String(),
	})
	if errCount != 1 {
		t.Errorf("prpc_server_request_errors_total = %v, want 1", errCount)
	}

	reqCount := counterValue(t, reg, "prpc_server_requests_total", map[string]string{
		"procedure": "", "protocol": "", "code": connect.CodeInternal.String(),
	})
	if reqCount != 1 {
		t.Errorf("prpc_server_requests_total = %v, want 1", reqCount)
	}
}

func TestMetricsInterceptor_DefaultsToDefaultRegisterer(t *testing.T) {
	// Calling with no registerer must not panic and must fall back to
	// prometheus.DefaultRegisterer. Calling it twice (as DefaultInterceptors
	// composition might via repeated server construction) must also not
	// panic on duplicate registration.
	_ = NewMetricsInterceptor()
	_ = NewMetricsInterceptor()
}

// counterValue reads the value of a single Counter sample identified by
// metric family name and exact label set from reg.
func counterValue(t *testing.T, reg *prometheus.Registry, name string, labels map[string]string) float64 {
	t.Helper()
	mfs, err := reg.Gather()
	if err != nil {
		t.Fatalf("Gather: %v", err)
	}
	for _, mf := range mfs {
		if mf.GetName() != name {
			continue
		}
		for _, m := range mf.GetMetric() {
			if !labelsMatch(m.GetLabel(), labels) {
				continue
			}
			if c := m.GetCounter(); c != nil {
				return c.GetValue()
			}
		}
	}
	t.Fatalf("no counter sample found for %s with labels %v", name, labels)
	return 0
}

// histogramSampleCount reads the sample count of a single Histogram sample
// identified by metric family name and exact label set from reg.
func histogramSampleCount(t *testing.T, reg *prometheus.Registry, name string, labels map[string]string) uint64 {
	t.Helper()
	mfs, err := reg.Gather()
	if err != nil {
		t.Fatalf("Gather: %v", err)
	}
	for _, mf := range mfs {
		if mf.GetName() != name {
			continue
		}
		for _, m := range mf.GetMetric() {
			if !labelsMatch(m.GetLabel(), labels) {
				continue
			}
			if h := m.GetHistogram(); h != nil {
				return h.GetSampleCount()
			}
		}
	}
	t.Fatalf("no histogram sample found for %s with labels %v", name, labels)
	return 0
}

// namedValue is satisfied by the generated *dto.LabelPair type without this
// file needing to import the client_model package by name.
type namedValue interface {
	GetName() string
	GetValue() string
}

func labelsMatch[T namedValue](pairs []T, want map[string]string) bool {
	got := make(map[string]string, len(pairs))
	for _, p := range pairs {
		got[p.GetName()] = p.GetValue()
	}
	if len(got) != len(want) {
		return false
	}
	for k, v := range want {
		if got[k] != v {
			return false
		}
	}
	return true
}

// --- Correlation ---

func TestCorrelationInterceptor_GeneratesID(t *testing.T) {
	interceptor := NewCorrelationInterceptor()
	var gotID string
	wrapped := interceptor.WrapUnary(func(ctx context.Context, _ connect.AnyRequest) (connect.AnyResponse, error) {
		gotID = CorrelationIDFromContext(ctx)
		return connect.NewResponse(&struct{}{}), nil
	})

	resp, err := wrapped(context.Background(), connect.NewRequest(&struct{}{}))
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if gotID == "" {
		t.Fatal("expected a generated correlation id in context, got empty string")
	}
	if got := resp.Header().Get("X-Correlation-Id"); got != gotID {
		t.Errorf("response header X-Correlation-Id = %q, want %q", got, gotID)
	}
}

func TestCorrelationInterceptor_PropagatesID(t *testing.T) {
	interceptor := NewCorrelationInterceptor()
	wrapped := interceptor.WrapUnary(func(ctx context.Context, _ connect.AnyRequest) (connect.AnyResponse, error) {
		if id := CorrelationIDFromContext(ctx); id != "existing-correlation-id" {
			t.Errorf("expected existing-correlation-id in context, got %v", id)
		}
		return connect.NewResponse(&struct{}{}), nil
	})

	req := connect.NewRequest(&struct{}{})
	req.Header().Set("X-Correlation-Id", "existing-correlation-id")

	resp, err := wrapped(context.Background(), req)
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if got := resp.Header().Get("X-Correlation-Id"); got != "existing-correlation-id" {
		t.Errorf("response header X-Correlation-Id = %q, want existing-correlation-id", got)
	}
}

func TestCorrelationIDFromContext_Absent(t *testing.T) {
	if id := CorrelationIDFromContext(context.Background()); id != "" {
		t.Errorf("expected empty string for a context with no correlation id, got %q", id)
	}
}

// --- Recovery ---

func TestRecoveryInterceptor_PanicRecovered(t *testing.T) {
	logger := zap.NewNop()
	interceptor := NewRecoveryInterceptor(logger)
	wrapped := interceptor.WrapUnary(func(_ context.Context, _ connect.AnyRequest) (connect.AnyResponse, error) {
		panic("do not leak this: tok_verysecret12345")
	})

	_, err := wrapped(context.Background(), connect.NewRequest(&struct{}{}))
	if err == nil {
		t.Fatal("expected error, got nil")
	}
	if connect.CodeOf(err) != connect.CodeInternal {
		t.Errorf("expected CodeInternal, got %v", connect.CodeOf(err))
	}
	if strings.Contains(err.Error(), "tok_verysecret12345") {
		t.Errorf("panic value leaked into connect error message: %q", err.Error())
	}
}

// --- Deadline (NEW) ---

func TestDeadlineInterceptor_AppliesDefaultWhenAbsent(t *testing.T) {
	const budget = 30 * time.Second
	interceptor := NewDeadlineInterceptor(budget)

	before := time.Now()
	var sawDeadline time.Time
	var hasDeadline bool
	wrapped := interceptor.WrapUnary(func(ctx context.Context, _ connect.AnyRequest) (connect.AnyResponse, error) {
		sawDeadline, hasDeadline = ctx.Deadline()
		return connect.NewResponse(&struct{}{}), nil
	})

	if _, err := wrapped(context.Background(), connect.NewRequest(&struct{}{})); err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if !hasDeadline {
		t.Fatal("expected handler context to have a deadline when caller supplied none")
	}
	latest := before.Add(budget + time.Second) // tolerance for test execution time
	if sawDeadline.After(latest) {
		t.Errorf("deadline %v is later than now+%v (bound %v)", sawDeadline, budget, latest)
	}
}

func TestDeadlineInterceptor_DoesNotOverrideExistingDeadline(t *testing.T) {
	interceptor := NewDeadlineInterceptor(30 * time.Second)

	parentCtx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()
	wantDeadline, _ := parentCtx.Deadline()

	var gotDeadline time.Time
	wrapped := interceptor.WrapUnary(func(ctx context.Context, _ connect.AnyRequest) (connect.AnyResponse, error) {
		gotDeadline, _ = ctx.Deadline()
		return connect.NewResponse(&struct{}{}), nil
	})

	if _, err := wrapped(parentCtx, connect.NewRequest(&struct{}{})); err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if !gotDeadline.Equal(wantDeadline) {
		t.Errorf("deadline was altered: got %v, want unchanged %v (caller's own 5s deadline must not be extended)", gotDeadline, wantDeadline)
	}
}

func TestDeadlineInterceptor_StreamingPassthrough(t *testing.T) {
	interceptor := NewDeadlineInterceptor(30 * time.Second)

	var hasDeadline bool
	fn := connect.StreamingHandlerFunc(func(ctx context.Context, _ connect.StreamingHandlerConn) error {
		_, hasDeadline = ctx.Deadline()
		return nil
	})

	wrapped := interceptor.WrapStreamingHandler(fn)
	if err := wrapped(context.Background(), nil); err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if hasDeadline {
		t.Error("expected streaming handler context to be untouched (no deadline injected)")
	}
}

func TestDeadlineInterceptor_ZeroOrNegativeIsNoOp(t *testing.T) {
	interceptor := NewDeadlineInterceptor(0)
	var hasDeadline bool
	wrapped := interceptor.WrapUnary(func(ctx context.Context, _ connect.AnyRequest) (connect.AnyResponse, error) {
		_, hasDeadline = ctx.Deadline()
		return connect.NewResponse(&struct{}{}), nil
	})
	if _, err := wrapped(context.Background(), connect.NewRequest(&struct{}{})); err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if hasDeadline {
		t.Error("expected no deadline to be injected when d <= 0")
	}
}

// --- DefaultInterceptors composition ---

func TestDefaultInterceptors_CanonicalOrder(t *testing.T) {
	logger := zap.NewNop()
	cfg := Config{DefaultUnaryTimeout: 5 * time.Second}
	interceptors := DefaultInterceptors(logger, cfg)

	if len(interceptors) != 5 {
		t.Fatalf("DefaultInterceptors returned %d interceptors, want 5", len(interceptors))
	}

	wantConstructors := []string{
		"NewRecoveryInterceptor",
		"NewCorrelationInterceptor",
		"NewDeadlineInterceptor",
		"NewLoggingInterceptor",
		"NewMetricsInterceptor",
	}
	for i, want := range wantConstructors {
		name := interceptorFuncName(t, interceptors[i])
		if !strings.Contains(name, want) {
			t.Errorf("interceptors[%d] = %q, want a closure produced by %s", i, name, want)
		}
	}
}

// TestDefaultInterceptors_Behavioral proves the composition works
// end-to-end: recovery (outermost) catches a panic raised in the handler
// underneath every other layer, and the deadline interceptor's default is
// visible by the time the handler runs.
func TestDefaultInterceptors_Behavioral(t *testing.T) {
	logger := zap.NewNop()
	cfg := Config{DefaultUnaryTimeout: 5 * time.Second}
	interceptors := DefaultInterceptors(logger, cfg)

	var hasDeadline bool
	handler := chainUnary(interceptors, func(ctx context.Context, _ connect.AnyRequest) (connect.AnyResponse, error) {
		_, hasDeadline = ctx.Deadline()
		panic("boom")
	})

	_, err := handler(context.Background(), connect.NewRequest(&struct{}{}))
	if err == nil {
		t.Fatal("expected error from recovered panic")
	}
	if connect.CodeOf(err) != connect.CodeInternal {
		t.Errorf("expected CodeInternal, got %v", connect.CodeOf(err))
	}
	if !hasDeadline {
		t.Error("expected the handler to observe a deadline injected by the chain before it panicked")
	}
}

func TestDefaultInterceptors_DefaultsZeroTimeout(t *testing.T) {
	logger := zap.NewNop()
	interceptors := DefaultInterceptors(logger, Config{}) // DefaultUnaryTimeout left zero

	var hasDeadline bool
	handler := chainUnary(interceptors, func(ctx context.Context, _ connect.AnyRequest) (connect.AnyResponse, error) {
		_, hasDeadline = ctx.Deadline()
		return connect.NewResponse(&struct{}{}), nil
	})

	if _, err := handler(context.Background(), connect.NewRequest(&struct{}{})); err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if !hasDeadline {
		t.Error("expected DefaultInterceptors to fall back to the package default timeout when cfg.DefaultUnaryTimeout is zero")
	}
}

// chainUnary composes interceptors around handler using the same onion
// ordering connect.WithInterceptors uses: interceptors[0] is outermost (acts
// first on the request, last on the response/error).
func chainUnary(interceptors []connect.Interceptor, handler connect.UnaryFunc) connect.UnaryFunc {
	next := handler
	for i := len(interceptors) - 1; i >= 0; i-- {
		next = interceptors[i].WrapUnary(next)
	}
	return next
}

// interceptorFuncName resolves the runtime function name backing i, so tests
// can assert which constructor produced a given connect.Interceptor without
// relying on unreliable function-value equality comparisons.
func interceptorFuncName(t *testing.T, i connect.Interceptor) string {
	t.Helper()
	v := reflect.ValueOf(i)
	if v.Kind() != reflect.Func {
		t.Fatalf("interceptor has kind %s, want Func (cannot introspect its name)", v.Kind())
	}
	fn := runtime.FuncForPC(v.Pointer())
	if fn == nil {
		t.Fatal("could not resolve runtime function for interceptor")
	}
	return fn.Name()
}
