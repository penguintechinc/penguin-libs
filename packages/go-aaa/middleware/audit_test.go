package middleware

import (
	"context"
	"errors"
	"testing"

	"connectrpc.com/connect"

	"github.com/penguintechinc/penguin-libs/packages/go-aaa/audit"
	"github.com/penguintechinc/penguin-libs/packages/go-aaa/authn"
	"github.com/penguintechinc/penguin-libs/packages/go-aaa/authz"
	"github.com/penguintechinc/penguin-libs/packages/go-common/logging"
)

func buildAuditEmitter(events *[]audit.AuditEvent) *audit.Emitter {
	sink := logging.NewCallbackSink(func(m map[string]interface{}) {
		// Reconstruct a minimal AuditEvent from the map for assertions.
		e := audit.AuditEvent{}
		if id, ok := m["id"].(string); ok {
			e.ID = id
		}
		if t, ok := m["type"].(string); ok {
			e.Type = audit.EventType(t)
		}
		if s, ok := m["subject"].(string); ok {
			e.Subject = s
		}
		if o, ok := m["outcome"].(string); ok {
			e.Outcome = audit.Outcome(o)
		}
		*events = append(*events, e)
	})
	return audit.NewEmitter(sink)
}

func TestAuditInterceptor_SuccessEmitsGranted(t *testing.T) {
	var received []audit.AuditEvent
	emitter := buildAuditEmitter(&received)
	interceptor := NewAuditInterceptor(emitter)

	req := connect.NewRequest(&struct{}{})
	_, _ = interceptor(noopNext)(context.Background(), req)

	if len(received) != 1 {
		t.Fatalf("expected 1 audit event, got %d", len(received))
	}
	if received[0].Type != audit.EventAuthzGranted {
		t.Errorf("expected EventAuthzGranted, got %q", received[0].Type)
	}
	if received[0].Outcome != audit.OutcomeSuccess {
		t.Errorf("expected OutcomeSuccess, got %q", received[0].Outcome)
	}
}

func TestAuditInterceptor_UnauthenticatedEmitsAuthFailure(t *testing.T) {
	var received []audit.AuditEvent
	emitter := buildAuditEmitter(&received)
	interceptor := NewAuditInterceptor(emitter)

	errNext := func(_ context.Context, _ connect.AnyRequest) (connect.AnyResponse, error) {
		return nil, connect.NewError(connect.CodeUnauthenticated, errors.New("no token"))
	}

	req := connect.NewRequest(&struct{}{})
	_, _ = interceptor(errNext)(context.Background(), req)

	if len(received) != 1 {
		t.Fatalf("expected 1 audit event, got %d", len(received))
	}
	if received[0].Type != audit.EventAuthFailure {
		t.Errorf("expected EventAuthFailure, got %q", received[0].Type)
	}
	if received[0].Outcome != audit.OutcomeFailure {
		t.Errorf("expected OutcomeFailure, got %q", received[0].Outcome)
	}
}

func TestAuditInterceptor_PermissionDeniedEmitsAuthzDenied(t *testing.T) {
	var received []audit.AuditEvent
	emitter := buildAuditEmitter(&received)
	interceptor := NewAuditInterceptor(emitter)

	errNext := func(_ context.Context, _ connect.AnyRequest) (connect.AnyResponse, error) {
		return nil, connect.NewError(connect.CodePermissionDenied, errors.New("forbidden"))
	}

	req := connect.NewRequest(&struct{}{})
	_, _ = interceptor(errNext)(context.Background(), req)

	if len(received) != 1 {
		t.Fatalf("expected 1 audit event, got %d", len(received))
	}
	if received[0].Type != audit.EventAuthzDenied {
		t.Errorf("expected EventAuthzDenied, got %q", received[0].Type)
	}
}

func TestAuditInterceptor_SubjectFromClaims(t *testing.T) {
	var received []audit.AuditEvent
	emitter := buildAuditEmitter(&received)
	interceptor := NewAuditInterceptor(emitter)

	ctx := ctxWithClaims("svc-account", nil, nil, "")
	req := connect.NewRequest(&struct{}{})
	_, _ = interceptor(noopNext)(ctx, req)

	if len(received) != 1 {
		t.Fatalf("expected 1 audit event, got %d", len(received))
	}
	if received[0].Subject != "svc-account" {
		t.Errorf("expected subject svc-account, got %q", received[0].Subject)
	}
}

func TestAuditInterceptor_AnonymousSubjectWhenNoClaims(t *testing.T) {
	var received []audit.AuditEvent
	emitter := buildAuditEmitter(&received)
	interceptor := NewAuditInterceptor(emitter)

	req := connect.NewRequest(&struct{}{})
	_, _ = interceptor(noopNext)(context.Background(), req)

	if len(received) != 1 {
		t.Fatalf("expected 1 audit event, got %d", len(received))
	}
	if received[0].Subject != "anonymous" {
		t.Errorf("expected subject anonymous, got %q", received[0].Subject)
	}
}

func TestAuditInterceptor_SkipAuditType_Suppresses(t *testing.T) {
	var received []audit.AuditEvent
	emitter := buildAuditEmitter(&received)
	interceptor := NewAuditInterceptor(emitter, WithSkipAuditTypes(audit.EventAuthzGranted))

	req := connect.NewRequest(&struct{}{})
	_, _ = interceptor(noopNext)(context.Background(), req)

	if len(received) != 0 {
		t.Errorf("expected 0 events when type is skipped, got %d", len(received))
	}
}

func TestAuditInterceptor_ErrorPropagates(t *testing.T) {
	emitter := audit.NewEmitter()
	interceptor := NewAuditInterceptor(emitter)

	expectedErr := connect.NewError(connect.CodeInternal, errors.New("internal"))
	errNext := func(_ context.Context, _ connect.AnyRequest) (connect.AnyResponse, error) {
		return nil, expectedErr
	}

	req := connect.NewRequest(&struct{}{})
	_, err := interceptor(errNext)(context.Background(), req)
	if !errors.Is(err, expectedErr) {
		t.Errorf("expected original error to propagate, got %v", err)
	}
}

func TestSubjectFromContext_NoClaims(t *testing.T) {
	if s := subjectFromContext(context.Background()); s != "anonymous" {
		t.Errorf("expected anonymous, got %q", s)
	}
}

func TestSubjectFromContext_EmptySub(t *testing.T) {
	ctx := authz.ContextWithClaims(context.Background(), &authn.Claims{Sub: ""})
	if s := subjectFromContext(ctx); s != "anonymous" {
		t.Errorf("expected anonymous for empty sub, got %q", s)
	}
}
