package audit

import (
	"testing"
	"time"
)

func TestNewAuditEvent_Fields(t *testing.T) {
	before := time.Now().UTC()
	event := NewAuditEvent(EventAuthSuccess, "user-1", "login", "/auth/login", OutcomeSuccess)
	after := time.Now().UTC()

	if event.ID == "" {
		t.Error("expected non-empty ID")
	}
	if event.Type != EventAuthSuccess {
		t.Errorf("expected type %q, got %q", EventAuthSuccess, event.Type)
	}
	if event.Subject != "user-1" {
		t.Errorf("expected subject user-1, got %q", event.Subject)
	}
	if event.Action != "login" {
		t.Errorf("expected action login, got %q", event.Action)
	}
	if event.Resource != "/auth/login" {
		t.Errorf("expected resource /auth/login, got %q", event.Resource)
	}
	if event.Outcome != OutcomeSuccess {
		t.Errorf("expected outcome success, got %q", event.Outcome)
	}
	if event.Timestamp.Before(before) || event.Timestamp.After(after) {
		t.Errorf("timestamp %v is outside expected range [%v, %v]", event.Timestamp, before, after)
	}
	if event.Timestamp.Location() != time.UTC {
		t.Errorf("expected UTC timestamp, got location %v", event.Timestamp.Location())
	}
}

func TestNewAuditEvent_UniqueIDs(t *testing.T) {
	e1 := NewAuditEvent(EventTokenIssued, "u", "a", "r", OutcomeSuccess)
	e2 := NewAuditEvent(EventTokenIssued, "u", "a", "r", OutcomeSuccess)
	if e1.ID == e2.ID {
		t.Error("expected unique IDs for distinct events")
	}
}

func TestAuditEvent_ToMap_ContainsAllFields(t *testing.T) {
	event := NewAuditEvent(EventAuthzDenied, "svc-account", "invoke", "/rpc/Foo", OutcomeFailure)
	m := event.ToMap()

	requiredKeys := []string{"id", "timestamp", "type", "subject", "action", "resource", "outcome"}
	for _, key := range requiredKeys {
		if _, ok := m[key]; !ok {
			t.Errorf("expected key %q in ToMap() output", key)
		}
	}

	if m["id"] != event.ID {
		t.Errorf("expected id %q, got %v", event.ID, m["id"])
	}
	if m["type"] != string(EventAuthzDenied) {
		t.Errorf("expected type %q, got %v", EventAuthzDenied, m["type"])
	}
	if m["outcome"] != string(OutcomeFailure) {
		t.Errorf("expected outcome failure, got %v", m["outcome"])
	}
}

func TestAuditEvent_ToMap_TimestampFormat(t *testing.T) {
	event := NewAuditEvent(EventSessionCreated, "u", "a", "r", OutcomeSuccess)
	m := event.ToMap()

	ts, ok := m["timestamp"].(string)
	if !ok {
		t.Fatalf("expected timestamp to be a string, got %T", m["timestamp"])
	}
	if _, err := time.Parse(time.RFC3339Nano, ts); err != nil {
		t.Errorf("timestamp %q is not RFC3339Nano: %v", ts, err)
	}
}

func TestEventTypeConstants(t *testing.T) {
	types := []EventType{
		EventAuthSuccess, EventAuthFailure,
		EventTokenIssued, EventTokenRevoked, EventTokenRefreshed,
		EventAuthzGranted, EventAuthzDenied,
		EventSPIFFEAuth,
		EventSessionCreated, EventSessionDestroyed,
	}
	seen := make(map[EventType]bool, len(types))
	for _, et := range types {
		if et == "" {
			t.Error("event type constant must not be empty string")
		}
		if seen[et] {
			t.Errorf("duplicate event type constant: %q", et)
		}
		seen[et] = true
	}
}

func TestOutcomeConstants(t *testing.T) {
	if OutcomeSuccess == "" {
		t.Error("OutcomeSuccess must not be empty")
	}
	if OutcomeFailure == "" {
		t.Error("OutcomeFailure must not be empty")
	}
	if OutcomeSuccess == OutcomeFailure {
		t.Error("OutcomeSuccess and OutcomeFailure must be distinct")
	}
}
