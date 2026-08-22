// Copyright 2026 Penguin Tech Inc
// SPDX-License-Identifier: Apache-2.0

package health

import (
	"context"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"sync"
	"testing"
	"time"

	"connectrpc.com/connect"

	healthv1 "github.com/penguintechinc/penguin-libs/packages/go-rpc/gen/prpc/health/v1"
	"github.com/penguintechinc/penguin-libs/packages/go-rpc/gen/prpc/health/v1/healthv1connect"
)

// --- Group A: Checker (pure, no wire) ---

func TestNewChecker_WholeProcessDefaultsServing(t *testing.T) {
	checker := NewChecker()

	status, ok := checker.GetStatus("")
	if !ok {
		t.Fatal("expected whole-process status to exist")
	}
	if status != StatusServing {
		t.Errorf("expected StatusServing, got %v", status)
	}
}

func TestChecker_SetGetStatus(t *testing.T) {
	checker := NewChecker()

	checker.SetStatus("db", StatusNotServing)

	status, ok := checker.GetStatus("db")
	if !ok {
		t.Fatal("expected status to exist for db service")
	}
	if status != StatusNotServing {
		t.Errorf("expected StatusNotServing, got %v", status)
	}
}

func TestChecker_GetStatus_UnknownService(t *testing.T) {
	checker := NewChecker()

	status, ok := checker.GetStatus("unknown-service")
	if ok {
		t.Error("expected ok=false for unknown service")
	}
	if status != StatusUnknown {
		t.Errorf("expected StatusUnknown, got %v", status)
	}
}

// --- Group B: Check over the wire (real httptest server + generated client) ---

func newHealthTestServer(t *testing.T, checker *Checker) healthv1connect.HealthServiceClient {
	t.Helper()
	mux := http.NewServeMux()
	Register(mux, checker)
	srv := httptest.NewServer(mux)
	t.Cleanup(srv.Close)
	return healthv1connect.NewHealthServiceClient(srv.Client(), srv.URL)
}

func TestService_Check_EmptyServiceWholeProcess_RoundTrips(t *testing.T) {
	checker := NewChecker()
	client := newHealthTestServer(t, checker)

	checker.SetStatus("", StatusNotServing)

	resp, err := client.Check(context.Background(), connect.NewRequest(&healthv1.CheckRequest{}))
	if err != nil {
		t.Fatalf("Check: %v", err)
	}
	if got := resp.Msg.GetStatus(); got != healthv1.ServingStatus_SERVING_STATUS_NOT_SERVING {
		t.Errorf("expected NOT_SERVING, got %v", got)
	}
}

func TestService_Check_UnknownNamedService_ReturnsUnspecified(t *testing.T) {
	checker := NewChecker()
	client := newHealthTestServer(t, checker)

	resp, err := client.Check(context.Background(), connect.NewRequest(&healthv1.CheckRequest{Service: "unknown-service"}))
	if err != nil {
		t.Fatalf("Check: %v", err)
	}
	if got := resp.Msg.GetStatus(); got != healthv1.ServingStatus_SERVING_STATUS_UNSPECIFIED {
		t.Errorf("expected UNSPECIFIED, got %v", got)
	}
}

// --- Group C: Watch (streaming, channel-driven status flips) ---

func TestService_Watch_InitialStatusThenTransition(t *testing.T) {
	checker := NewChecker()
	checker.SetStatus("db", StatusNotServing)
	client := newHealthTestServer(t, checker)

	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()

	stream, err := client.Watch(ctx, connect.NewRequest(&healthv1.CheckRequest{Service: "db"}))
	if err != nil {
		t.Fatalf("Watch: %v", err)
	}
	defer stream.Close()

	if !stream.Receive() {
		t.Fatalf("expected initial message, got err: %v", stream.Err())
	}
	if got := stream.Msg().GetStatus(); got != healthv1.ServingStatus_SERVING_STATUS_NOT_SERVING {
		t.Fatalf("expected initial NOT_SERVING, got %v", got)
	}

	checker.SetStatus("db", StatusServing)

	if !stream.Receive() {
		t.Fatalf("expected transition message, got err: %v", stream.Err())
	}
	if got := stream.Msg().GetStatus(); got != healthv1.ServingStatus_SERVING_STATUS_SERVING {
		t.Fatalf("expected transition to SERVING, got %v", got)
	}
}

func TestService_Watch_ContextCancel_UnsubscribesCleanly(t *testing.T) {
	checker := NewChecker()
	client := newHealthTestServer(t, checker)

	ctx, cancel := context.WithCancel(context.Background())

	stream, err := client.Watch(ctx, connect.NewRequest(&healthv1.CheckRequest{Service: "watched"}))
	if err != nil {
		t.Fatalf("Watch: %v", err)
	}
	if !stream.Receive() {
		t.Fatalf("expected initial message, got err: %v", stream.Err())
	}

	// Confirm the server actually registered a subscriber before canceling,
	// otherwise the return-to-zero assertion below would be vacuously true.
	waitForCondition(t, func() bool { return checker.subscriberCount("watched") == 1 })

	cancel()
	_ = stream.Close()

	waitForCondition(t, func() bool { return checker.subscriberCount("watched") == 0 })
}

// waitForCondition polls cond on a short, fixed tick bounded by an overall
// deadline. It exists only because subscriber cleanup happens asynchronously
// on the server's handler goroutine after the client cancels — there is no
// synchronous signal for "the server has finished unsubscribing" to block
// on, so a short bounded poll is the least-flaky option that still fails
// fast on a real leak instead of relying on a fixed sleep duration.
func waitForCondition(t *testing.T, cond func() bool) {
	t.Helper()
	deadline := time.Now().Add(2 * time.Second)
	ticker := time.NewTicker(5 * time.Millisecond)
	defer ticker.Stop()
	for {
		if cond() {
			return
		}
		if time.Now().After(deadline) {
			t.Fatal("condition not met within timeout")
		}
		<-ticker.C
	}
}

// --- Group D: /healthz plain HTTP endpoint ---

func TestRegister_Healthz_ServingReturns200(t *testing.T) {
	checker := NewChecker()
	mux := http.NewServeMux()
	Register(mux, checker)
	srv := httptest.NewServer(mux)
	t.Cleanup(srv.Close)

	req, err := http.NewRequestWithContext(context.Background(), http.MethodGet, srv.URL+"/healthz", nil)
	if err != nil {
		t.Fatalf("build /healthz request: %v", err)
	}
	resp, err := http.DefaultClient.Do(req)
	if err != nil {
		t.Fatalf("GET /healthz: %v", err)
	}
	defer resp.Body.Close()

	if resp.StatusCode != http.StatusOK {
		t.Errorf("expected 200, got %d", resp.StatusCode)
	}
	if ct := resp.Header.Get("Content-Type"); ct != "application/json" {
		t.Errorf("expected application/json content-type, got %q", ct)
	}
	var body map[string]string
	if err := json.NewDecoder(resp.Body).Decode(&body); err != nil {
		t.Fatalf("decode body: %v", err)
	}
	if body["status"] != "SERVING" {
		t.Errorf("expected status SERVING, got %v", body)
	}
}

func TestRegister_Healthz_NotServingReturns503(t *testing.T) {
	checker := NewChecker()
	checker.SetStatus("", StatusNotServing)
	mux := http.NewServeMux()
	Register(mux, checker)
	srv := httptest.NewServer(mux)
	t.Cleanup(srv.Close)

	req, err := http.NewRequestWithContext(context.Background(), http.MethodGet, srv.URL+"/healthz", nil)
	if err != nil {
		t.Fatalf("build /healthz request: %v", err)
	}
	resp, err := http.DefaultClient.Do(req)
	if err != nil {
		t.Fatalf("GET /healthz: %v", err)
	}
	defer resp.Body.Close()

	if resp.StatusCode != http.StatusServiceUnavailable {
		t.Errorf("expected 503, got %d", resp.StatusCode)
	}
	if ct := resp.Header.Get("Content-Type"); ct != "application/json" {
		t.Errorf("expected application/json content-type, got %q", ct)
	}
	var body map[string]string
	if err := json.NewDecoder(resp.Body).Decode(&body); err != nil {
		t.Fatalf("decode body: %v", err)
	}
	if body["status"] != "NOT_SERVING" {
		t.Errorf("expected status NOT_SERVING, got %v", body)
	}
}

// --- Group E: concurrency hammer (go test -race is the actual assertion) ---

func TestChecker_ConcurrentSetStatusAndWatch_Hammer(t *testing.T) {
	checker := NewChecker()
	const workers = 20
	const iterations = 50

	var wg sync.WaitGroup

	for i := 0; i < workers; i++ {
		wg.Add(1)
		go func() {
			defer wg.Done()
			for j := 0; j < iterations; j++ {
				ch, unsubscribe := checker.Subscribe("hammer")
				select {
				case <-ch:
				case <-time.After(10 * time.Millisecond):
				}
				unsubscribe()
			}
		}()
	}

	for i := 0; i < workers; i++ {
		wg.Add(1)
		go func(n int) {
			defer wg.Done()
			for j := 0; j < iterations; j++ {
				s := StatusServing
				if (n+j)%2 == 0 {
					s = StatusNotServing
				}
				checker.SetStatus("hammer", s)
			}
		}(i)
	}

	wg.Wait()

	if got := checker.subscriberCount("hammer"); got != 0 {
		t.Errorf("expected 0 subscribers after hammer completes, got %d", got)
	}
}
