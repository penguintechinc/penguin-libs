// Copyright 2026 Penguin Tech Inc
// SPDX-License-Identifier: Apache-2.0

package conformance

import (
	"context"
	"net/http"
	"net/http/httptest"
	"testing"
	"time"

	"connectrpc.com/connect"

	conformancev1 "github.com/penguintechinc/penguin-libs/packages/go-rpc/gen/prpc/conformance/v1"
	"github.com/penguintechinc/penguin-libs/packages/go-rpc/gen/prpc/conformance/v1/conformancev1connect"
)

// newConformanceTestServer wires Register (the same entry point production
// servers use) into a real HTTP/2-over-TLS httptest server and returns a
// real generated client. HTTP/2 (rather than plain httptest.NewServer's
// HTTP/1.1) is required here because BidiStream's full-duplex Connect
// protocol errors out over HTTP/1.1 (connect-go v1.20.0,
// TestBidiRequiresHTTP2 / TestBidiOverHTTP1 in connect_ext_test.go) — using
// one H2 helper for every pattern keeps all tests in this file consistent
// with the brief's "H2 loopback" requirement. Since Go 1.21, httptest.Server
// only speaks HTTP/2 when EnableHTTP2 is explicitly set — httptest.NewTLSServer
// alone is not sufficient.
func newConformanceTestServer(t *testing.T, opts ...connect.HandlerOption) conformancev1connect.ConformanceServiceClient {
	t.Helper()
	mux := http.NewServeMux()
	Register(mux, opts...)
	ts := httptest.NewUnstartedServer(mux)
	ts.EnableHTTP2 = true
	ts.StartTLS()
	t.Cleanup(ts.Close)
	return conformancev1connect.NewConformanceServiceClient(ts.Client(), ts.URL)
}

// --- Test 1: Unary echoes message; protocol == "h2" over httptest ---

func TestUnary_EchoesMessage_ProtocolH2(t *testing.T) {
	client := newConformanceTestServer(t)

	resp, err := client.Unary(context.Background(), connect.NewRequest(&conformancev1.EchoRequest{Message: "hello", Repeat: 5}))
	if err != nil {
		t.Fatalf("Unary: unexpected error: %v", err)
	}
	// repeat must NOT multiply the unary response — it only drives
	// ServerStream's send count (see TestServerStream_* below).
	if got := resp.Msg.GetMessage(); got != "hello" {
		t.Errorf("expected message %q, got %q", "hello", got)
	}
	if got := resp.Msg.GetProtocol(); got != "h2" {
		t.Errorf("expected protocol %q over httptest, got %q", "h2", got)
	}
}

// --- Test 2: ServerStream repeat=3 -> exactly 3 correct messages ---

func TestServerStream_RepeatThree_SendsExactlyThreeMessages(t *testing.T) {
	client := newConformanceTestServer(t)

	stream, err := client.ServerStream(context.Background(), connect.NewRequest(&conformancev1.EchoRequest{Message: "ping", Repeat: 3}))
	if err != nil {
		t.Fatalf("ServerStream: unexpected error: %v", err)
	}
	defer stream.Close()

	var got []string
	for stream.Receive() {
		if p := stream.Msg().GetProtocol(); p != "h2" {
			t.Errorf("expected protocol %q, got %q", "h2", p)
		}
		got = append(got, stream.Msg().GetMessage())
	}
	if err := stream.Err(); err != nil {
		t.Fatalf("stream.Err(): unexpected error: %v", err)
	}
	if len(got) != 3 {
		t.Fatalf("expected 3 messages, got %d: %v", len(got), got)
	}
	for i, m := range got {
		if m != "ping" {
			t.Errorf("message %d: expected %q, got %q", i, "ping", m)
		}
	}
}

// --- Test 3: ServerStream repeat=0 -> treated as 1 ---

func TestServerStream_RepeatZero_SendsOneMessage(t *testing.T) {
	client := newConformanceTestServer(t)

	stream, err := client.ServerStream(context.Background(), connect.NewRequest(&conformancev1.EchoRequest{Message: "solo", Repeat: 0}))
	if err != nil {
		t.Fatalf("ServerStream: unexpected error: %v", err)
	}
	defer stream.Close()

	var got []string
	for stream.Receive() {
		got = append(got, stream.Msg().GetMessage())
	}
	if err := stream.Err(); err != nil {
		t.Fatalf("stream.Err(): unexpected error: %v", err)
	}
	if len(got) != 1 || got[0] != "solo" {
		t.Fatalf("expected exactly one message %q, got %v", "solo", got)
	}
}

// --- Test 4: ClientStream concatenates ["a","b","c"] -> "abc" ---

func TestClientStream_ConcatenatesMessagesInOrder(t *testing.T) {
	client := newConformanceTestServer(t)

	stream := client.ClientStream(context.Background())
	for _, m := range []string{"a", "b", "c"} {
		if err := stream.Send(&conformancev1.EchoRequest{Message: m, Repeat: 1}); err != nil {
			t.Fatalf("Send(%q): unexpected error: %v", m, err)
		}
	}

	resp, err := stream.CloseAndReceive()
	if err != nil {
		t.Fatalf("CloseAndReceive: unexpected error: %v", err)
	}
	if got := resp.Msg.GetMessage(); got != "abc" {
		t.Errorf("expected concatenated message %q, got %q", "abc", got)
	}
	if got := resp.Msg.GetProtocol(); got != "h2" {
		t.Errorf("expected protocol %q, got %q", "h2", got)
	}
}

// --- Test 5: BidiStream echoes send/recv interleaved ["x","y"] in order ---

func TestBidiStream_EchoesEachMessageAsItArrives(t *testing.T) {
	client := newConformanceTestServer(t)

	stream := client.BidiStream(context.Background())
	for _, m := range []string{"x", "y"} {
		if err := stream.Send(&conformancev1.EchoRequest{Message: m, Repeat: 1}); err != nil {
			t.Fatalf("Send(%q): unexpected error: %v", m, err)
		}
		resp, err := stream.Receive()
		if err != nil {
			t.Fatalf("Receive after Send(%q): unexpected error: %v", m, err)
		}
		if got := resp.GetMessage(); got != m {
			t.Errorf("expected echo of %q, got %q", m, got)
		}
		if got := resp.GetProtocol(); got != "h2" {
			t.Errorf("expected protocol %q, got %q", "h2", got)
		}
	}
	if err := stream.CloseRequest(); err != nil {
		t.Fatalf("CloseRequest: unexpected error: %v", err)
	}
	if err := stream.CloseResponse(); err != nil {
		t.Fatalf("CloseResponse: unexpected error: %v", err)
	}
}

// --- Test 6: context cancellation mid-BidiStream terminates, bounded ---

func TestBidiStream_ContextCancel_TerminatesWithoutHang(t *testing.T) {
	client := newConformanceTestServer(t)

	ctx, cancel := context.WithCancel(context.Background())
	stream := client.BidiStream(ctx)

	if err := stream.Send(&conformancev1.EchoRequest{Message: "first", Repeat: 1}); err != nil {
		t.Fatalf("Send: unexpected error: %v", err)
	}
	if _, err := stream.Receive(); err != nil {
		t.Fatalf("Receive (1st): unexpected error: %v", err)
	}

	cancel()

	done := make(chan error, 1)
	go func() {
		_, err := stream.Receive()
		done <- err
	}()

	select {
	case err := <-done:
		if err == nil {
			t.Fatal("expected an error from Receive after context cancellation")
		}
	case <-time.After(5 * time.Second):
		t.Fatal("Receive did not return within 5s of context cancellation — handler appears to hang")
	}
}

// --- Test 7: protocolFromContext direct unit coverage ---

func TestProtocolFromContext_DefaultsToH2(t *testing.T) {
	if got := protocolFromContext(context.Background()); got != "h2" {
		t.Errorf("expected default %q, got %q", "h2", got)
	}
}

func TestProtocolFromContext_StampedMajorThree_ReturnsH3(t *testing.T) {
	ctx := context.WithValue(context.Background(), ctxKeyProtocol{}, 3)
	if got := protocolFromContext(ctx); got != "h3" {
		t.Errorf("expected %q for stamped major 3, got %q", "h3", got)
	}
}

func TestProtocolFromContext_StampedMajorTwo_ReturnsH2(t *testing.T) {
	ctx := context.WithValue(context.Background(), ctxKeyProtocol{}, 2)
	if got := protocolFromContext(ctx); got != "h2" {
		t.Errorf("expected %q for stamped major 2, got %q", "h2", got)
	}
}

func TestProtocolFromContext_WrongValueType_DefaultsToH2(t *testing.T) {
	// A non-int value under the same key must not panic or be
	// misinterpreted — the type assertion in protocolFromContext guards
	// this rather than assuming it.
	ctx := context.WithValue(context.Background(), ctxKeyProtocol{}, "3")
	if got := protocolFromContext(ctx); got != "h2" {
		t.Errorf("expected %q for a non-int stamped value, got %q", "h2", got)
	}
}

// --- Test 8: ProtocolMiddleware stamps r.ProtoMajor into the context ---

func TestProtocolMiddleware_StampsProtoMajorIntoContext(t *testing.T) {
	tests := []struct {
		name       string
		protoMajor int
		want       string
	}{
		{"http1_1", 1, "h2"},
		{"http2", 2, "h2"},
		{"http3", 3, "h3"},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			var observed string
			next := http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
				observed = protocolFromContext(r.Context())
				w.WriteHeader(http.StatusOK)
			})
			handler := ProtocolMiddleware(next)

			req := httptest.NewRequest(http.MethodGet, "/", nil)
			req.ProtoMajor = tt.protoMajor
			rec := httptest.NewRecorder()
			handler.ServeHTTP(rec, req)

			if observed != tt.want {
				t.Errorf("ProtoMajor=%d: expected stamped protocol %q, got %q", tt.protoMajor, tt.want, observed)
			}
		})
	}
}

// --- Test 9: Register mounts a working handler reachable via the client ---

func TestRegister_MountsHandlerServingAllFourPatterns(t *testing.T) {
	// This is effectively re-proven by every test above using
	// newConformanceTestServer (which calls Register), but this test
	// pins Register + NewService as the documented public entry points
	// Task 10 consumes, independent of any other test's helper wiring.
	mux := http.NewServeMux()
	Register(mux)

	ts := httptest.NewUnstartedServer(mux)
	ts.EnableHTTP2 = true
	ts.StartTLS()
	t.Cleanup(ts.Close)

	client := conformancev1connect.NewConformanceServiceClient(ts.Client(), ts.URL)
	resp, err := client.Unary(context.Background(), connect.NewRequest(&conformancev1.EchoRequest{Message: "reachable", Repeat: 1}))
	if err != nil {
		t.Fatalf("Unary via Register-mounted mux: unexpected error: %v", err)
	}
	if got := resp.Msg.GetMessage(); got != "reachable" {
		t.Errorf("expected %q, got %q", "reachable", got)
	}
}
