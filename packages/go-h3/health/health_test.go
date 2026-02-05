package health

import (
	"connectrpc.com/connect"
	"context"
	"testing"
)

func TestNewChecker(t *testing.T) {
	checker := NewChecker()

	if checker == nil {
		t.Error("expected non-nil checker, got nil")
	}

	// Initial overall status should be StatusServing
	status, ok := checker.GetStatus("")
	if !ok {
		t.Error("expected overall status to exist")
	}
	if status != StatusServing {
		t.Errorf("expected initial overall status StatusServing, got %v", status)
	}
}

func TestChecker_SetGetStatus(t *testing.T) {
	checker := NewChecker()

	checker.SetStatus("db", StatusNotServing)

	status, ok := checker.GetStatus("db")
	if !ok {
		t.Error("expected status to exist for db service")
	}
	if status != StatusNotServing {
		t.Errorf("expected StatusNotServing, got %v", status)
	}
}

func TestChecker_GetStatus_Unknown(t *testing.T) {
	checker := NewChecker()

	_, ok := checker.GetStatus("unknown-service")
	if ok {
		t.Error("expected ok to be false for unknown service")
	}
}

func TestChecker_CheckHandler_Serving(t *testing.T) {
	checker := NewChecker()
	checker.SetStatus("", StatusServing)

	handler := checker.CheckHandler()

	_, err := handler(context.Background(), (*connect.Request[any])(nil))
	if err != nil {
		t.Errorf("expected no error when serving, got %v", err)
	}
}

func TestChecker_CheckHandler_NotServing(t *testing.T) {
	checker := NewChecker()
	checker.SetStatus("", StatusNotServing)

	handler := checker.CheckHandler()

	_, err := handler(context.Background(), (*connect.Request[any])(nil))
	if err == nil {
		t.Error("expected error when not serving, got nil")
	}
	if connect.CodeOf(err) != connect.CodeUnavailable {
		t.Errorf("expected CodeUnavailable, got %v", connect.CodeOf(err))
	}
}
