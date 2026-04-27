package logging

import (
	"encoding/json"
	"io"
	"net"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"sync"
	"testing"
	"time"
)

// --- StdoutSink ---

func TestStdoutSink_WriteDoesNotError(t *testing.T) {
	sink := NewStdoutSink()

	event := map[string]interface{}{"level": "info", "msg": "hello"}
	if err := sink.Write(event); err != nil {
		t.Fatalf("StdoutSink.Write returned unexpected error: %v", err)
	}
}

func TestStdoutSink_FlushAndCloseAreNoOps(t *testing.T) {
	sink := NewStdoutSink()

	if err := sink.Flush(); err != nil {
		t.Errorf("StdoutSink.Flush returned unexpected error: %v", err)
	}
	if err := sink.Close(); err != nil {
		t.Errorf("StdoutSink.Close returned unexpected error: %v", err)
	}
}

func TestStdoutSink_ConcurrentWriteIsSafe(t *testing.T) {
	sink := NewStdoutSink()

	var wg sync.WaitGroup
	for i := 0; i < 50; i++ {
		wg.Add(1)
		go func(n int) {
			defer wg.Done()
			event := map[string]interface{}{"n": n}
			if err := sink.Write(event); err != nil {
				t.Errorf("concurrent Write error: %v", err)
			}
		}(i)
	}
	wg.Wait()
}

// --- FileSink ---

func TestFileSink_WritesJSONToFile(t *testing.T) {
	dir := t.TempDir()
	path := filepath.Join(dir, "test.log")

	sink, err := NewFileSink(path, 0)
	if err != nil {
		t.Fatalf("NewFileSink: %v", err)
	}
	defer sink.Close()

	event := map[string]interface{}{"level": "info", "msg": "file test"}
	if err := sink.Write(event); err != nil {
		t.Fatalf("FileSink.Write: %v", err)
	}
	if err := sink.Flush(); err != nil {
		t.Fatalf("FileSink.Flush: %v", err)
	}

	data, err := os.ReadFile(path)
	if err != nil {
		t.Fatalf("reading log file: %v", err)
	}

	var decoded map[string]interface{}
	if err := json.Unmarshal(data, &decoded); err != nil {
		t.Fatalf("log file is not valid JSON: %v (content: %q)", err, string(data))
	}

	if decoded["msg"] != "file test" {
		t.Errorf("expected msg %q, got %q", "file test", decoded["msg"])
	}
}

func TestFileSink_RotatesWhenMaxSizeExceeded(t *testing.T) {
	dir := t.TempDir()
	path := filepath.Join(dir, "rotate.log")

	// maxSizeMB of 1 means rotation triggers once written bytes exceed 1 MiB.
	sink, err := NewFileSink(path, 1)
	if err != nil {
		t.Fatalf("NewFileSink: %v", err)
	}
	defer sink.Close()

	// Each event is roughly 60 bytes; 20,000 events ≈ 1.2 MiB, exceeding the limit.
	payload := "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa" // 40 bytes
	for i := 0; i < 20000; i++ {
		event := map[string]interface{}{"n": i, "payload": payload}
		if err := sink.Write(event); err != nil {
			t.Fatalf("Write %d: %v", i, err)
		}
	}

	rotated := path + ".1"
	if _, err := os.Stat(rotated); os.IsNotExist(err) {
		t.Error("expected rotated file to exist at", rotated)
	}
}

func TestFileSink_CloseFlushesAndClosesFile(t *testing.T) {
	dir := t.TempDir()
	path := filepath.Join(dir, "close.log")

	sink, err := NewFileSink(path, 0)
	if err != nil {
		t.Fatalf("NewFileSink: %v", err)
	}

	event := map[string]interface{}{"key": "value"}
	if err := sink.Write(event); err != nil {
		t.Fatalf("Write: %v", err)
	}
	if err := sink.Close(); err != nil {
		t.Fatalf("Close: %v", err)
	}

	// File must be readable after Close.
	if _, err := os.ReadFile(path); err != nil {
		t.Errorf("ReadFile after Close: %v", err)
	}
}

// --- SyslogSink ---

func TestSyslogSink_WriteAndClose(t *testing.T) {
	// Listen on a UDP port so the dial and send succeed.
	pc, err := net.ListenPacket("udp", "127.0.0.1:0")
	if err != nil {
		t.Fatalf("create UDP listener: %v", err)
	}
	defer pc.Close()

	sink, err := NewSyslogSink(pc.LocalAddr().String())
	if err != nil {
		t.Fatalf("NewSyslogSink: %v", err)
	}

	event := map[string]interface{}{"level": "warn", "msg": "syslog test"}
	if err := sink.Write(event); err != nil {
		t.Fatalf("SyslogSink.Write: %v", err)
	}
	if err := sink.Flush(); err != nil {
		t.Errorf("SyslogSink.Flush: %v", err)
	}
	if err := sink.Close(); err != nil {
		t.Errorf("SyslogSink.Close: %v", err)
	}
}

func TestSyslogSink_MalformedAddressReturnsError(t *testing.T) {
	// A malformed address (missing port) must cause Dial to fail.
	_, err := NewSyslogSink("not-a-valid-address")
	if err == nil {
		t.Error("expected error for malformed address, got nil")
	}
}

// --- CallbackSink ---

func TestCallbackSink_InvokesCallbackWithCopy(t *testing.T) {
	var mu sync.Mutex
	var received []map[string]interface{}

	sink := NewCallbackSink(func(event map[string]interface{}) {
		mu.Lock()
		defer mu.Unlock()
		received = append(received, event)
	})

	events := []map[string]interface{}{
		{"level": "info", "msg": "first"},
		{"level": "warn", "msg": "second"},
		{"level": "error", "msg": "third"},
	}

	for _, e := range events {
		if err := sink.Write(e); err != nil {
			t.Fatalf("CallbackSink.Write: %v", err)
		}
	}

	mu.Lock()
	defer mu.Unlock()

	if len(received) != len(events) {
		t.Fatalf("expected %d events, got %d", len(events), len(received))
	}

	for i, e := range events {
		if received[i]["msg"] != e["msg"] {
			t.Errorf("event %d msg mismatch: got %q, want %q", i, received[i]["msg"], e["msg"])
		}
	}
}

func TestCallbackSink_ReceivesCopyNotOriginal(t *testing.T) {
	var received map[string]interface{}

	sink := NewCallbackSink(func(event map[string]interface{}) {
		received = event
	})

	original := map[string]interface{}{"key": "original"}
	if err := sink.Write(original); err != nil {
		t.Fatalf("Write: %v", err)
	}

	// Mutating the original must not affect what the callback received.
	original["key"] = "mutated"

	if received["key"] != "original" {
		t.Errorf("callback received a reference instead of a copy: got %q", received["key"])
	}
}

func TestCallbackSink_FlushAndCloseAreNoOps(t *testing.T) {
	sink := NewCallbackSink(func(_ map[string]interface{}) {})

	if err := sink.Flush(); err != nil {
		t.Errorf("Flush: %v", err)
	}
	if err := sink.Close(); err != nil {
		t.Errorf("Close: %v", err)
	}
}

// --- KillKrillSink ---

func TestKillKrillSink_SendsEventsToHTTPServer(t *testing.T) {
	var mu sync.Mutex
	var receivedBatches [][]map[string]interface{}

	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path != eventsPath {
			t.Errorf("unexpected path: %s", r.URL.Path)
		}
		if r.Header.Get("Authorization") != "Bearer test-key" {
			t.Errorf("unexpected Authorization header: %s", r.Header.Get("Authorization"))
		}

		body, err := io.ReadAll(r.Body)
		if err != nil {
			t.Errorf("read body: %v", err)
			w.WriteHeader(http.StatusInternalServerError)
			return
		}

		var batch []map[string]interface{}
		if err := json.Unmarshal(body, &batch); err != nil {
			t.Errorf("unmarshal batch: %v", err)
			w.WriteHeader(http.StatusBadRequest)
			return
		}

		mu.Lock()
		receivedBatches = append(receivedBatches, batch)
		mu.Unlock()

		w.WriteHeader(http.StatusOK)
	}))
	defer server.Close()

	sink := NewKillKrillSink(KillKrillConfig{
		Endpoint:      server.URL,
		APIKey:        "test-key",
		BatchSize:     10,
		FlushInterval: 100 * time.Millisecond,
		Timeout:       5 * time.Second,
		MaxRetries:    2,
	})

	for i := 0; i < 5; i++ {
		event := map[string]interface{}{"n": i, "msg": "test event"}
		if err := sink.Write(event); err != nil {
			t.Fatalf("Write %d: %v", i, err)
		}
	}

	if err := sink.Flush(); err != nil {
		t.Fatalf("Flush: %v", err)
	}
	if err := sink.Close(); err != nil {
		t.Fatalf("Close: %v", err)
	}

	mu.Lock()
	defer mu.Unlock()

	totalEvents := 0
	for _, batch := range receivedBatches {
		totalEvents += len(batch)
	}
	if totalEvents != 5 {
		t.Errorf("expected 5 total events across all batches, got %d", totalEvents)
	}
}

func TestKillKrillSink_FlushesWhenBatchFull(t *testing.T) {
	var mu sync.Mutex
	var requestCount int

	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		mu.Lock()
		requestCount++
		mu.Unlock()
		w.WriteHeader(http.StatusOK)
	}))
	defer server.Close()

	sink := NewKillKrillSink(KillKrillConfig{
		Endpoint:      server.URL,
		APIKey:        "key",
		BatchSize:     3,
		FlushInterval: 10 * time.Second, // long so only batch-full triggers flush
		Timeout:       5 * time.Second,
		MaxRetries:    1,
	})

	// Write exactly one full batch to trigger an immediate flush.
	for i := 0; i < 3; i++ {
		if err := sink.Write(map[string]interface{}{"n": i}); err != nil {
			t.Fatalf("Write %d: %v", i, err)
		}
	}

	// Allow time for the triggered flush to complete before closing.
	time.Sleep(200 * time.Millisecond)

	if err := sink.Close(); err != nil {
		t.Fatalf("Close: %v", err)
	}

	mu.Lock()
	defer mu.Unlock()

	if requestCount < 1 {
		t.Errorf("expected at least 1 HTTP request from batch-full flush, got %d", requestCount)
	}
}

func TestKillKrillSink_RetriesOnServerError(t *testing.T) {
	var mu sync.Mutex
	attempts := 0

	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		mu.Lock()
		attempts++
		current := attempts
		mu.Unlock()

		if current < 3 {
			w.WriteHeader(http.StatusInternalServerError)
			return
		}
		w.WriteHeader(http.StatusOK)
	}))
	defer server.Close()

	sink := NewKillKrillSink(KillKrillConfig{
		Endpoint:      server.URL,
		APIKey:        "key",
		BatchSize:     10,
		FlushInterval: 10 * time.Second,
		Timeout:       5 * time.Second,
		MaxRetries:    3,
	})

	if err := sink.Write(map[string]interface{}{"msg": "retry test"}); err != nil {
		t.Fatalf("Write: %v", err)
	}
	if err := sink.Flush(); err != nil {
		t.Fatalf("Flush: %v", err)
	}
	if err := sink.Close(); err != nil {
		t.Fatalf("Close: %v", err)
	}

	mu.Lock()
	defer mu.Unlock()

	if attempts < 3 {
		t.Errorf("expected at least 3 HTTP attempts (2 failures + 1 success), got %d", attempts)
	}
}

func TestKillKrillSink_DefaultsApplied(t *testing.T) {
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		w.WriteHeader(http.StatusOK)
	}))
	defer server.Close()

	sink := NewKillKrillSink(KillKrillConfig{
		Endpoint: server.URL,
		APIKey:   "key",
	})

	if sink.cfg.BatchSize != defaultBatchSize {
		t.Errorf("BatchSize default: got %d, want %d", sink.cfg.BatchSize, defaultBatchSize)
	}
	if sink.cfg.FlushInterval != defaultFlushInterval {
		t.Errorf("FlushInterval default: got %v, want %v", sink.cfg.FlushInterval, defaultFlushInterval)
	}
	if sink.cfg.Timeout != defaultTimeout {
		t.Errorf("Timeout default: got %v, want %v", sink.cfg.Timeout, defaultTimeout)
	}
	if sink.cfg.MaxRetries != defaultMaxRetries {
		t.Errorf("MaxRetries default: got %d, want %d", sink.cfg.MaxRetries, defaultMaxRetries)
	}

	if err := sink.Close(); err != nil {
		t.Fatalf("Close: %v", err)
	}
}
