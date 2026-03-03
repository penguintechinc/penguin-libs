// Package audit provides structured audit event creation and emission for
// Penguin Tech applications. Events capture authentication, authorization,
// and session lifecycle actions with a consistent schema.
package audit

import (
	"time"

	"github.com/google/uuid"
)

// EventType classifies an audit event by the action that was performed.
type EventType string

// Defined event types covering authentication, token, authorization, SPIFFE, and session actions.
const (
	EventAuthSuccess      EventType = "auth.success"
	EventAuthFailure      EventType = "auth.failure"
	EventTokenIssued      EventType = "token.issued"
	EventTokenRevoked     EventType = "token.revoked"
	EventTokenRefreshed   EventType = "token.refreshed"
	EventAuthzGranted     EventType = "authz.granted"
	EventAuthzDenied      EventType = "authz.denied"
	EventSPIFFEAuth       EventType = "spiffe.auth"
	EventSessionCreated   EventType = "session.created"
	EventSessionDestroyed EventType = "session.destroyed"
)

// Outcome describes whether an audited action succeeded or failed.
type Outcome string

const (
	// OutcomeSuccess indicates the action completed successfully.
	OutcomeSuccess Outcome = "success"
	// OutcomeFailure indicates the action did not complete successfully.
	OutcomeFailure Outcome = "failure"
)

// AuditEvent is a structured record of a security-relevant action.
type AuditEvent struct {
	// ID is a globally unique identifier for this event.
	ID string `json:"id"`
	// Timestamp is the UTC time when the event occurred.
	Timestamp time.Time `json:"timestamp"`
	// Type classifies the action that was performed.
	Type EventType `json:"type"`
	// Subject identifies who performed the action (e.g., user ID or service account).
	Subject string `json:"subject"`
	// Action describes what was attempted (e.g., "login", "token.issue").
	Action string `json:"action"`
	// Resource identifies what was acted upon (e.g., a procedure path or resource name).
	Resource string `json:"resource"`
	// Outcome indicates whether the action succeeded or failed.
	Outcome Outcome `json:"outcome"`
}

// NewAuditEvent creates a new AuditEvent with a generated UUID and the current UTC time.
func NewAuditEvent(eventType EventType, subject, action, resource string, outcome Outcome) AuditEvent {
	return AuditEvent{
		ID:        uuid.New().String(),
		Timestamp: time.Now().UTC(),
		Type:      eventType,
		Subject:   subject,
		Action:    action,
		Resource:  resource,
		Outcome:   outcome,
	}
}

// ToMap converts the AuditEvent to a map suitable for passing to a logging Sink.
func (e AuditEvent) ToMap() map[string]interface{} {
	return map[string]interface{}{
		"id":        e.ID,
		"timestamp": e.Timestamp.Format(time.RFC3339Nano),
		"type":      string(e.Type),
		"subject":   e.Subject,
		"action":    e.Action,
		"resource":  e.Resource,
		"outcome":   string(e.Outcome),
	}
}
