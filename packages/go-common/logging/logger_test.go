package logging

import (
	"encoding/json"
	"sync"
	"testing"

	"go.uber.org/zap"
)

// captureSink is a test helper that records every event written to it.
type captureSink struct {
	mu     sync.Mutex
	events []map[string]interface{}
}

func (c *captureSink) Write(event map[string]interface{}) error {
	c.mu.Lock()
	defer c.mu.Unlock()
	c.events = append(c.events, event)
	return nil
}

func (c *captureSink) Flush() error { return nil }
func (c *captureSink) Close() error { return nil }

func (c *captureSink) count() int {
	c.mu.Lock()
	defer c.mu.Unlock()
	return len(c.events)
}

func (c *captureSink) get(i int) map[string]interface{} {
	c.mu.Lock()
	defer c.mu.Unlock()
	return c.events[i]
}

// flushTrackingSink wraps captureSink and records whether Flush was called.
type flushTrackingSink struct {
	captureSink
	flushed bool
}

func (f *flushTrackingSink) Flush() error {
	f.mu.Lock()
	defer f.mu.Unlock()
	f.flushed = true
	return nil
}

func (f *flushTrackingSink) wasFlushed() bool {
	f.mu.Lock()
	defer f.mu.Unlock()
	return f.flushed
}

// --- NewLogger ---

func TestNewLogger_FallsBackToDefaultWhenNoSinks(t *testing.T) {
	logger, err := NewLogger(LoggerConfig{Name: "fallback"})
	if err != nil {
		t.Fatalf("NewLogger with no sinks: %v", err)
	}
	if logger == nil {
		t.Fatal("expected non-nil logger")
	}
	if logger.name != "fallback" {
		t.Errorf("name: got %q, want %q", logger.name, "fallback")
	}
	defer logger.Sync() //nolint:errcheck
}

func TestNewLogger_DefaultLevelIsInfo(t *testing.T) {
	capture := &captureSink{}

	logger, err := NewLogger(LoggerConfig{
		Name:  "level-test",
		Level: "", // empty → defaults to info
		Sinks: []Sink{capture},
		JSON:  true,
	})
	if err != nil {
		t.Fatalf("NewLogger: %v", err)
	}
	defer logger.Sync() //nolint:errcheck

	logger.Info("should appear")
	logger.Debug("should not appear at info level")

	if capture.count() < 1 {
		t.Error("expected at least one event from Info call")
	}
}

func TestNewLogger_InvalidLevelReturnsError(t *testing.T) {
	_, err := NewLogger(LoggerConfig{
		Name:  "bad-level",
		Level: "invalid",
		Sinks: []Sink{&captureSink{}},
	})
	if err == nil {
		t.Error("expected error for invalid level string, got nil")
	}
}

func TestNewLogger_CustomSinkReceivesEvents(t *testing.T) {
	capture := &captureSink{}

	logger, err := NewLogger(LoggerConfig{
		Name:  "sink-test",
		Level: "info",
		Sinks: []Sink{capture},
		JSON:  true,
	})
	if err != nil {
		t.Fatalf("NewLogger: %v", err)
	}
	defer logger.Sync() //nolint:errcheck

	logger.Info("test message", zap.String("key", "value"))

	if capture.count() == 0 {
		t.Fatal("expected sink to receive at least one event")
	}

	event := capture.get(0)
	if event["msg"] != "test message" {
		t.Errorf("msg: got %q, want %q", event["msg"], "test message")
	}
}

func TestNewLogger_SensitiveFieldsSanitized(t *testing.T) {
	capture := &captureSink{}

	logger, err := NewLogger(LoggerConfig{
		Name:  "sanitize-test",
		Level: "info",
		Sinks: []Sink{capture},
		JSON:  true,
	})
	if err != nil {
		t.Fatalf("NewLogger: %v", err)
	}
	defer logger.Sync() //nolint:errcheck

	logger.Info("user login", zap.String("password", "hunter2"), zap.String("username", "alice"))

	if capture.count() == 0 {
		t.Fatal("sink received no events")
	}

	raw, err := json.Marshal(capture.get(0))
	if err != nil {
		t.Fatalf("marshal captured event: %v", err)
	}

	if containsBytes(raw, "hunter2") {
		t.Error("sink received plaintext password; expected [REDACTED]")
	}
}

func TestNewLogger_MultiSinkDispatchesAll(t *testing.T) {
	sink1 := &captureSink{}
	sink2 := &captureSink{}

	logger, err := NewLogger(LoggerConfig{
		Name:  "multi-sink",
		Level: "info",
		Sinks: []Sink{sink1, sink2},
		JSON:  true,
	})
	if err != nil {
		t.Fatalf("NewLogger: %v", err)
	}
	defer logger.Sync() //nolint:errcheck

	logger.Info("broadcast")

	if sink1.count() == 0 {
		t.Error("sink1 received no events")
	}
	if sink2.count() == 0 {
		t.Error("sink2 received no events")
	}
}

func TestNewLogger_JSONEncoderProducesValidJSON(t *testing.T) {
	var mu sync.Mutex
	var rawEvent []byte

	callback := NewCallbackSink(func(event map[string]interface{}) {
		mu.Lock()
		defer mu.Unlock()
		if b, err := json.Marshal(event); err == nil {
			rawEvent = b
		}
	})

	logger, err := NewLogger(LoggerConfig{
		Name:  "json-test",
		Level: "info",
		Sinks: []Sink{callback},
		JSON:  true,
	})
	if err != nil {
		t.Fatalf("NewLogger: %v", err)
	}
	defer logger.Sync() //nolint:errcheck

	logger.Info("json check", zap.Int("count", 42))

	mu.Lock()
	defer mu.Unlock()

	if len(rawEvent) == 0 {
		t.Fatal("no JSON output captured")
	}

	var decoded map[string]interface{}
	if err := json.Unmarshal(rawEvent, &decoded); err != nil {
		t.Fatalf("captured output is not valid JSON: %v", err)
	}
}

// --- multiSinkWriteSyncer ---

func TestMultiSinkWriteSyncer_WritesJSONToAllSinks(t *testing.T) {
	sink1 := &captureSink{}
	sink2 := &captureSink{}

	ws := newMultiSinkWriteSyncer([]Sink{sink1, sink2})

	payload := []byte(`{"msg":"hello","level":"info"}`)
	n, err := ws.Write(payload)
	if err != nil {
		t.Fatalf("Write: %v", err)
	}
	if n != len(payload) {
		t.Errorf("Write returned n=%d, want %d", n, len(payload))
	}

	if sink1.count() != 1 {
		t.Errorf("sink1 events: got %d, want 1", sink1.count())
	}
	if sink2.count() != 1 {
		t.Errorf("sink2 events: got %d, want 1", sink2.count())
	}
	if sink1.get(0)["msg"] != "hello" {
		t.Errorf("sink1 msg: got %q, want %q", sink1.get(0)["msg"], "hello")
	}
}

func TestMultiSinkWriteSyncer_HandlesNonJSONGracefully(t *testing.T) {
	capture := &captureSink{}
	ws := newMultiSinkWriteSyncer([]Sink{capture})

	nonJSON := []byte("plain text log line\n")
	if _, err := ws.Write(nonJSON); err != nil {
		t.Fatalf("Write non-JSON: %v", err)
	}

	if capture.count() != 1 {
		t.Fatalf("expected 1 event, got %d", capture.count())
	}

	event := capture.get(0)
	if event["message"] == nil {
		t.Error("expected fallback 'message' key for non-JSON input")
	}
}

func TestMultiSinkWriteSyncer_SyncFlushesAllSinks(t *testing.T) {
	sink1 := &flushTrackingSink{}
	sink2 := &flushTrackingSink{}

	ws := newMultiSinkWriteSyncer([]Sink{sink1, sink2})

	if err := ws.Sync(); err != nil {
		t.Fatalf("Sync: %v", err)
	}

	if !sink1.wasFlushed() {
		t.Error("sink1 was not flushed by Sync")
	}
	if !sink2.wasFlushed() {
		t.Error("sink2 was not flushed by Sync")
	}
}

// --- Backward compatibility: NewSanitizedLogger still works ---

func TestNewLogger_BackwardCompatWithNewSanitizedLogger(t *testing.T) {
	fromNewLogger, err := NewLogger(LoggerConfig{Name: "compat"})
	if err != nil {
		t.Fatalf("NewLogger: %v", err)
	}

	fromDirect, err := NewSanitizedLogger("compat")
	if err != nil {
		t.Fatalf("NewSanitizedLogger: %v", err)
	}

	defer fromNewLogger.Sync() //nolint:errcheck
	defer fromDirect.Sync()    //nolint:errcheck

	if fromNewLogger.name != "compat" {
		t.Errorf("NewLogger name: got %q, want %q", fromNewLogger.name, "compat")
	}
	if fromDirect.name != "compat" {
		t.Errorf("NewSanitizedLogger name: got %q, want %q", fromDirect.name, "compat")
	}
}

// containsBytes reports whether haystack contains needle as a contiguous byte sequence.
func containsBytes(haystack []byte, needle string) bool {
	nb := []byte(needle)
	if len(nb) == 0 {
		return true
	}
	for i := 0; i+len(nb) <= len(haystack); i++ {
		match := true
		for j := range nb {
			if haystack[i+j] != nb[j] {
				match = false
				break
			}
		}
		if match {
			return true
		}
	}
	return false
}
