// Copyright 2026 Penguin Tech Inc
// SPDX-License-Identifier: Apache-2.0

package server

import (
	"context"
	"fmt"
	"net/http"
	"net/http/httptest"
	"strings"
	"sync"
	"testing"

	"connectrpc.com/connect"

	conformancev1 "github.com/penguintechinc/penguin-libs/packages/go-rpc/gen/prpc/conformance/v1"
	"github.com/penguintechinc/penguin-libs/packages/go-rpc/gen/prpc/conformance/v1/conformancev1connect"
	healthv1 "github.com/penguintechinc/penguin-libs/packages/go-rpc/gen/prpc/health/v1"
)

// unaryEchoStub is the terminal handler used by every direct-WrapUnary test
// below: reaching it and returning its argument unmodified proves the
// interceptor let a valid message through without altering it. It switches
// on the concrete message type (rather than calling the generic
// connect.NewResponse directly on req.Any(), an any) because Go cannot infer
// a generic type parameter from an any-typed argument.
func unaryEchoStub(_ context.Context, req connect.AnyRequest) (connect.AnyResponse, error) {
	switch msg := req.Any().(type) {
	case *conformancev1.EchoRequest:
		return connect.NewResponse(msg), nil
	case *healthv1.CheckRequest:
		return connect.NewResponse(msg), nil
	default:
		return nil, fmt.Errorf("unaryEchoStub: unsupported message type %T", msg)
	}
}

// --- Test 1: empty message violates EchoRequest.message's min_len 1 ---

func TestWrapUnary_EmptyMessage_MinLenViolation(t *testing.T) {
	interceptor, err := NewValidationInterceptor()
	if err != nil {
		t.Fatalf("NewValidationInterceptor: %v", err)
	}
	handler := interceptor.WrapUnary(unaryEchoStub)

	req := connect.NewRequest(&conformancev1.EchoRequest{Message: "", Repeat: 1})
	_, err = handler(context.Background(), req)
	if err == nil {
		t.Fatal("expected a validation error for an empty message")
	}
	if connect.CodeOf(err) != connect.CodeInvalidArgument {
		t.Errorf("expected CodeInvalidArgument, got %v (%v)", connect.CodeOf(err), err)
	}
	// protovalidate's human-readable message for string.min_len is "must be
	// at least N characters" rather than the literal rule id — assert on
	// that text plus the "message" field path so this actually pins down
	// the min_len rule rather than any other EchoRequest constraint.
	if !strings.Contains(err.Error(), "message") || !strings.Contains(err.Error(), "at least 1") {
		t.Errorf("expected an error mentioning the message field's min_len(1) violation, got: %v", err)
	}
}

// --- Test 2: 4097-byte message violates EchoRequest.message's max_len 4096 ---

func TestWrapUnary_OversizedMessage_MaxLenViolation(t *testing.T) {
	interceptor, err := NewValidationInterceptor()
	if err != nil {
		t.Fatalf("NewValidationInterceptor: %v", err)
	}
	handler := interceptor.WrapUnary(unaryEchoStub)

	req := connect.NewRequest(&conformancev1.EchoRequest{Message: strings.Repeat("a", 4097), Repeat: 1})
	_, err = handler(context.Background(), req)
	if err == nil {
		t.Fatal("expected a validation error for a 4097-byte message")
	}
	if connect.CodeOf(err) != connect.CodeInvalidArgument {
		t.Errorf("expected CodeInvalidArgument, got %v (%v)", connect.CodeOf(err), err)
	}
	if !strings.Contains(err.Error(), "message") || !strings.Contains(err.Error(), "at most 4096") {
		t.Errorf("expected an error mentioning the message field's max_len(4096) violation, got: %v", err)
	}
}

// --- Test 3: repeat 101 violates EchoRequest.repeat's lte 100 ---

func TestWrapUnary_RepeatOverLimit_LteViolation(t *testing.T) {
	interceptor, err := NewValidationInterceptor()
	if err != nil {
		t.Fatalf("NewValidationInterceptor: %v", err)
	}
	handler := interceptor.WrapUnary(unaryEchoStub)

	req := connect.NewRequest(&conformancev1.EchoRequest{Message: "ok", Repeat: 101})
	_, err = handler(context.Background(), req)
	if err == nil {
		t.Fatal("expected a validation error for repeat=101")
	}
	if connect.CodeOf(err) != connect.CodeInvalidArgument {
		t.Errorf("expected CodeInvalidArgument, got %v (%v)", connect.CodeOf(err), err)
	}
	if !strings.Contains(err.Error(), "repeat") || !strings.Contains(err.Error(), "less than or equal to 100") {
		t.Errorf("expected an error mentioning the repeat field's lte(100) violation, got: %v", err)
	}
}

// --- Test 4: a valid message passes through untouched ---

func TestWrapUnary_ValidMessage_PassesThroughUnmodified(t *testing.T) {
	interceptor, err := NewValidationInterceptor()
	if err != nil {
		t.Fatalf("NewValidationInterceptor: %v", err)
	}
	handler := interceptor.WrapUnary(unaryEchoStub)

	in := &conformancev1.EchoRequest{Message: "hello", Repeat: 5}
	req := connect.NewRequest(in)
	resp, err := handler(context.Background(), req)
	if err != nil {
		t.Fatalf("expected a valid message to pass, got: %v", err)
	}
	out, ok := resp.Any().(*conformancev1.EchoRequest)
	if !ok {
		t.Fatalf("expected the stub's echoed *EchoRequest, got %T", resp.Any())
	}
	if out != in {
		t.Errorf("expected the exact same message pointer to reach the handler unmodified, got a different value: %+v", out)
	}
}

// --- Test 5: a message type with no constraints validates trivially ---

func TestWrapUnary_MessageWithoutConstraints_PassesThrough(t *testing.T) {
	interceptor, err := NewValidationInterceptor()
	if err != nil {
		t.Fatalf("NewValidationInterceptor: %v", err)
	}
	handler := interceptor.WrapUnary(unaryEchoStub)

	// healthv1.CheckRequest carries no buf.validate constraints at all (see
	// gen/prpc/health/v1/health.pb.go — it doesn't even import the
	// buf/validate package), so any value, including the zero value, must
	// validate trivially.
	req := connect.NewRequest(&healthv1.CheckRequest{})
	_, err = handler(context.Background(), req)
	if err != nil {
		t.Fatalf("expected a constraint-free message type to pass, got: %v", err)
	}
}

// --- Streaming: real httptest server + generated conformancev1connect stubs ---

// recordingConformanceHandler implements
// conformancev1connect.ConformanceServiceHandler well enough to exercise
// ClientStream: it records every message's text it actually receives, which
// is this file's proof that a message reached the handler (as opposed to
// being rejected by the validation interceptor before Receive ever returned
// it). mu guards received because the handler runs on the httptest.Server's
// own goroutine, while assertions run on the test goroutine.
type recordingConformanceHandler struct {
	conformancev1connect.UnimplementedConformanceServiceHandler
	mu       sync.Mutex
	received []string
}

func (h *recordingConformanceHandler) ClientStream(_ context.Context, stream *connect.ClientStream[conformancev1.EchoRequest]) (*connect.Response[conformancev1.EchoResponse], error) {
	for stream.Receive() {
		h.mu.Lock()
		h.received = append(h.received, stream.Msg().GetMessage())
		h.mu.Unlock()
	}
	if err := stream.Err(); err != nil {
		return nil, err
	}
	return connect.NewResponse(&conformancev1.EchoResponse{Message: "ok"}), nil
}

func (h *recordingConformanceHandler) messages() []string {
	h.mu.Lock()
	defer h.mu.Unlock()
	return append([]string(nil), h.received...)
}

// newConformanceStreamingTestServer wires interceptors into a real
// conformancev1connect.ConformanceServiceHandler behind an httptest.Server —
// the same connect.WithInterceptors wiring production servers use — and
// returns a real generated client. The Connect protocol's client-streaming
// pattern (many request envelopes, one response) needs no full-duplex
// transport, so plain httptest.NewServer (HTTP/1.1) is sufficient.
func newConformanceStreamingTestServer(t *testing.T, handler conformancev1connect.ConformanceServiceHandler, interceptors []connect.Interceptor) conformancev1connect.ConformanceServiceClient {
	t.Helper()
	mux := http.NewServeMux()
	path, h := conformancev1connect.NewConformanceServiceHandler(handler, connect.WithInterceptors(interceptors...))
	mux.Handle(path, h)
	srv := httptest.NewServer(mux)
	t.Cleanup(srv.Close)
	return conformancev1connect.NewConformanceServiceClient(srv.Client(), srv.URL)
}

// --- Test 6: second client-streamed message violates min_len -> stream ---
// --- errors CodeInvalidArgument; the first (valid) message was received ---

func TestWrapStreamingHandler_ClientStream_SecondMessageInvalid_TerminatesStream(t *testing.T) {
	interceptor, err := NewValidationInterceptor()
	if err != nil {
		t.Fatalf("NewValidationInterceptor: %v", err)
	}
	handler := &recordingConformanceHandler{}
	client := newConformanceStreamingTestServer(t, handler, []connect.Interceptor{interceptor})

	stream := client.ClientStream(context.Background())
	if sendErr := stream.Send(&conformancev1.EchoRequest{Message: "valid message", Repeat: 1}); sendErr != nil {
		t.Fatalf("Send (1st, valid): unexpected error: %v", sendErr)
	}
	// The second message violates min_len(1). Send itself may or may not
	// surface an error depending on transport buffering — the assertion
	// that matters is CloseAndReceive's terminal error below, plus that the
	// handler only ever recorded the first message.
	_ = stream.Send(&conformancev1.EchoRequest{Message: "", Repeat: 1})

	_, err = stream.CloseAndReceive()
	if err == nil {
		t.Fatal("expected CloseAndReceive to return an error for the invalid second message")
	}
	if connect.CodeOf(err) != connect.CodeInvalidArgument {
		t.Errorf("expected CodeInvalidArgument, got %v (%v)", connect.CodeOf(err), err)
	}

	if got := handler.messages(); len(got) != 1 || got[0] != "valid message" {
		t.Errorf("expected the handler to have received exactly the first valid message before the stream was terminated, got %v", got)
	}
}

// --- Test 7: a fully valid client-stream completes normally ---

func TestWrapStreamingHandler_ClientStream_AllValid_Completes(t *testing.T) {
	interceptor, err := NewValidationInterceptor()
	if err != nil {
		t.Fatalf("NewValidationInterceptor: %v", err)
	}
	handler := &recordingConformanceHandler{}
	client := newConformanceStreamingTestServer(t, handler, []connect.Interceptor{interceptor})

	stream := client.ClientStream(context.Background())
	if sendErr := stream.Send(&conformancev1.EchoRequest{Message: "one", Repeat: 1}); sendErr != nil {
		t.Fatalf("Send (1st): unexpected error: %v", sendErr)
	}
	if sendErr := stream.Send(&conformancev1.EchoRequest{Message: "two", Repeat: 1}); sendErr != nil {
		t.Fatalf("Send (2nd): unexpected error: %v", sendErr)
	}

	resp, err := stream.CloseAndReceive()
	if err != nil {
		t.Fatalf("expected the fully valid stream to complete, got: %v", err)
	}
	if resp.Msg.GetMessage() != "ok" {
		t.Errorf("expected the handler's response message %q, got %q", "ok", resp.Msg.GetMessage())
	}
	if got := handler.messages(); len(got) != 2 || got[0] != "one" || got[1] != "two" {
		t.Errorf("expected both valid messages to reach the handler, got %v", got)
	}
}
