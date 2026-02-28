package audit

import (
	"errors"
	"testing"

	"github.com/penguintechinc/penguin-libs/packages/go-common/logging"
)

func TestEmitter_Emit_SingleSink(t *testing.T) {
	var received []map[string]interface{}
	sink := logging.NewCallbackSink(func(event map[string]interface{}) {
		received = append(received, event)
	})

	emitter := NewEmitter(sink)
	event := NewAuditEvent(EventAuthSuccess, "user-1", "login", "/auth", OutcomeSuccess)

	if err := emitter.Emit(event); err != nil {
		t.Fatalf("expected no error, got %v", err)
	}

	if len(received) != 1 {
		t.Fatalf("expected 1 event received by sink, got %d", len(received))
	}
	if received[0]["id"] != event.ID {
		t.Errorf("expected id %q in received event, got %v", event.ID, received[0]["id"])
	}
}

func TestEmitter_Emit_MultipleSinks(t *testing.T) {
	countA, countB := 0, 0
	sinkA := logging.NewCallbackSink(func(_ map[string]interface{}) { countA++ })
	sinkB := logging.NewCallbackSink(func(_ map[string]interface{}) { countB++ })

	emitter := NewEmitter(sinkA, sinkB)
	_ = emitter.Emit(NewAuditEvent(EventTokenIssued, "u", "a", "r", OutcomeSuccess))

	if countA != 1 {
		t.Errorf("expected sinkA to receive 1 event, got %d", countA)
	}
	if countB != 1 {
		t.Errorf("expected sinkB to receive 1 event, got %d", countB)
	}
}

func TestEmitter_NoSinks_NoError(t *testing.T) {
	emitter := NewEmitter()
	if err := emitter.Emit(NewAuditEvent(EventAuthFailure, "u", "a", "r", OutcomeFailure)); err != nil {
		t.Errorf("expected no error for emitter with no sinks, got %v", err)
	}
}

func TestEmitter_Emit_SinkError_Propagates(t *testing.T) {
	errSink := &errorSink{err: errors.New("write failed")}
	emitter := NewEmitter(errSink)

	err := emitter.Emit(NewAuditEvent(EventAuthzDenied, "u", "a", "r", OutcomeFailure))
	if err == nil {
		t.Error("expected error from failing sink, got nil")
	}
}

func TestEmitter_Emit_MultipleSinkErrors_Combined(t *testing.T) {
	sinkA := &errorSink{err: errors.New("sink-a failed")}
	sinkB := &errorSink{err: errors.New("sink-b failed")}
	emitter := NewEmitter(sinkA, sinkB)

	err := emitter.Emit(NewAuditEvent(EventAuthzDenied, "u", "a", "r", OutcomeFailure))
	if err == nil {
		t.Error("expected combined error from two failing sinks, got nil")
	}
}

func TestEmitter_Close_CallsSinkClose(t *testing.T) {
	closed := false
	sink := &closeTrackingSink{onClose: func() { closed = true }}
	emitter := NewEmitter(sink)

	if err := emitter.Close(); err != nil {
		t.Fatalf("expected no error on close, got %v", err)
	}
	if !closed {
		t.Error("expected sink.Close() to be called")
	}
}

// errorSink is a Sink that always returns an error from Write.
type errorSink struct {
	err error
}

func (s *errorSink) Write(_ map[string]interface{}) error { return s.err }
func (s *errorSink) Flush() error                         { return nil }
func (s *errorSink) Close() error                         { return nil }

// closeTrackingSink calls onClose when Close is invoked.
type closeTrackingSink struct {
	onClose func()
}

func (s *closeTrackingSink) Write(_ map[string]interface{}) error { return nil }
func (s *closeTrackingSink) Flush() error                         { return nil }
func (s *closeTrackingSink) Close() error {
	s.onClose()
	return nil
}
