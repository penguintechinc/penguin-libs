// Copyright 2026 Penguin Tech Inc
// SPDX-License-Identifier: Apache-2.0

package a2a

import (
	"context"
	"encoding/json"
	"iter"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
	"time"

	"github.com/a2aproject/a2a-go/v2/a2a"
	"github.com/a2aproject/a2a-go/v2/a2aclient"
	"github.com/a2aproject/a2a-go/v2/a2asrv"
)

// noopHandler is a trivial http.Handler used wherever a test only cares
// that Mount accepted/rejected arguments, not what the handler does.
var noopHandler = http.HandlerFunc(func(http.ResponseWriter, *http.Request) {})

func validCard(t *testing.T) []byte {
	t.Helper()
	b, err := json.Marshal(&a2a.AgentCard{Name: "test-agent"})
	if err != nil {
		t.Fatalf("json.Marshal(card) error = %v, want nil", err)
	}
	return b
}

// TestMount_NilAndInvalidArgs asserts Mount rejects a nil mux, nil handler,
// empty card, and syntactically invalid card JSON with an error instead of
// panicking, per the task-9 interface contract.
func TestMount_NilAndInvalidArgs(t *testing.T) {
	card := validCard(t)

	tests := []struct {
		name    string
		mux     *http.ServeMux
		card    []byte
		handler http.Handler
	}{
		{"nil mux", nil, card, noopHandler},
		{"nil handler", http.NewServeMux(), card, nil},
		{"empty card", http.NewServeMux(), []byte{}, noopHandler},
		{"nil card", http.NewServeMux(), nil, noopHandler},
		{"invalid json card", http.NewServeMux(), []byte("not-json"), noopHandler},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			if err := Mount(tt.mux, tt.card, tt.handler); err == nil {
				t.Fatalf("Mount() error = nil, want error")
			}
		})
	}
}

// TestMount_ServesCardAndReachesHandler asserts Mount serves the exact card
// bytes as application/json at WellKnownAgentCardPath (GET only) and routes
// requests to JSONRPCPath through to the supplied handler unmodified.
func TestMount_ServesCardAndReachesHandler(t *testing.T) {
	mux := http.NewServeMux()
	card := validCard(t)

	var reachedMethod, reachedBody string
	handler := http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		reachedMethod = r.Method
		body := make([]byte, r.ContentLength)
		_, _ = r.Body.Read(body)
		reachedBody = string(body)
		w.WriteHeader(http.StatusOK)
	})

	if err := Mount(mux, card, handler); err != nil {
		t.Fatalf("Mount() error = %v, want nil", err)
	}

	// Agent card: GET succeeds with exact bytes and JSON content type.
	rec := httptest.NewRecorder()
	mux.ServeHTTP(rec, httptest.NewRequestWithContext(context.Background(), http.MethodGet, WellKnownAgentCardPath, nil))
	if rec.Code != http.StatusOK {
		t.Fatalf("GET %s status = %d, want %d", WellKnownAgentCardPath, rec.Code, http.StatusOK)
	}
	if ct := rec.Header().Get("Content-Type"); ct != "application/json" {
		t.Fatalf("GET %s Content-Type = %q, want %q", WellKnownAgentCardPath, ct, "application/json")
	}
	if rec.Body.String() != string(card) {
		t.Fatalf("GET %s body = %q, want %q", WellKnownAgentCardPath, rec.Body.String(), string(card))
	}

	// Agent card: non-GET is rejected, not forwarded anywhere.
	recPost := httptest.NewRecorder()
	mux.ServeHTTP(recPost, httptest.NewRequestWithContext(context.Background(), http.MethodPost, WellKnownAgentCardPath, nil))
	if recPost.Code != http.StatusMethodNotAllowed {
		t.Fatalf("POST %s status = %d, want %d", WellKnownAgentCardPath, recPost.Code, http.StatusMethodNotAllowed)
	}

	// JSON-RPC endpoint: request reaches the supplied handler unmodified.
	recRPC := httptest.NewRecorder()
	mux.ServeHTTP(recRPC, httptest.NewRequestWithContext(context.Background(), http.MethodPost, JSONRPCPath, strings.NewReader(`{"jsonrpc":"2.0"}`)))
	if recRPC.Code != http.StatusOK {
		t.Fatalf("POST %s status = %d, want %d", JSONRPCPath, recRPC.Code, http.StatusOK)
	}
	if reachedMethod != http.MethodPost {
		t.Fatalf("handler saw method = %q, want %q", reachedMethod, http.MethodPost)
	}
	if reachedBody != `{"jsonrpc":"2.0"}` {
		t.Fatalf("handler saw body = %q, want %q", reachedBody, `{"jsonrpc":"2.0"}`)
	}
}

// TestMountAgent_NilArgs asserts MountAgent rejects nil arguments with an
// error instead of panicking.
func TestMountAgent_NilArgs(t *testing.T) {
	card := &a2a.AgentCard{Name: "test-agent"}
	handler := a2asrv.NewHandler(&testExecutor{})

	if err := MountAgent(nil, card, handler); err == nil {
		t.Fatal("MountAgent(nil mux, ...) error = nil, want error")
	}
	if err := MountAgent(http.NewServeMux(), nil, handler); err == nil {
		t.Fatal("MountAgent(..., nil card, ...) error = nil, want error")
	}
	if err := MountAgent(http.NewServeMux(), card, nil); err == nil {
		t.Fatal("MountAgent(..., nil requestHandler) error = nil, want error")
	}
}

// testExecutor is a minimal a2asrv.AgentExecutor that replies to every
// message with a fixed text response, used to drive an official-SDK client
// round trip in TestMountAgent_SDKRoundTrip.
type testExecutor struct{}

var _ a2asrv.AgentExecutor = (*testExecutor)(nil)

func (*testExecutor) Execute(_ context.Context, _ *a2asrv.ExecutorContext) iter.Seq2[a2a.Event, error] {
	return func(yield func(a2a.Event, error) bool) {
		yield(a2a.NewMessage(a2a.MessageRoleAgent, a2a.NewTextPart("hello from a2a mount test")), nil)
	}
}

func (*testExecutor) Cancel(_ context.Context, _ *a2asrv.ExecutorContext) iter.Seq2[a2a.Event, error] {
	return func(yield func(a2a.Event, error) bool) {}
}

// TestMountAgent_SDKRoundTrip exercises MountAgent end-to-end with the
// official a2a-go client (a2aclient.NewFromCard + Client.SendMessage) over
// a real loopback HTTP server: full SDK-to-SDK depth, not just a mounting
// contract check. It also confirms the served agent card exposes the same
// JSONRPCPath the request actually lands on.
func TestMountAgent_SDKRoundTrip(t *testing.T) {
	mux := http.NewServeMux()

	// httptest.NewUnstartedServer binds the listener immediately, so its
	// address is known before the server starts serving — needed here
	// because the agent card must embed the final URL before Mount can run,
	// and Mount must run before the server starts routing requests.
	ts := httptest.NewUnstartedServer(mux)
	serverURL := "http://" + ts.Listener.Addr().String()

	card := &a2a.AgentCard{
		Name: "test-agent",
		SupportedInterfaces: []*a2a.AgentInterface{
			a2a.NewAgentInterface(serverURL+JSONRPCPath, a2a.TransportProtocolJSONRPC),
		},
	}

	if err := MountAgent(mux, card, a2asrv.NewHandler(&testExecutor{})); err != nil {
		t.Fatalf("MountAgent() error = %v, want nil", err)
	}

	ts.Start()
	defer ts.Close()

	ctx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
	defer cancel()

	// Confirm the served card matches what the client will discover.
	cardReq, err := http.NewRequestWithContext(ctx, http.MethodGet, serverURL+WellKnownAgentCardPath, nil)
	if err != nil {
		t.Fatalf("build agent card request error = %v, want nil", err)
	}
	resp, err := http.DefaultClient.Do(cardReq)
	if err != nil {
		t.Fatalf("GET agent card error = %v, want nil", err)
	}
	defer func() { _ = resp.Body.Close() }()
	var gotCard a2a.AgentCard
	if err := json.NewDecoder(resp.Body).Decode(&gotCard); err != nil {
		t.Fatalf("decode agent card error = %v, want nil", err)
	}
	if len(gotCard.SupportedInterfaces) != 1 || gotCard.SupportedInterfaces[0].URL != serverURL+JSONRPCPath {
		t.Fatalf("served card interfaces = %+v, want single interface at %s", gotCard.SupportedInterfaces, serverURL+JSONRPCPath)
	}

	client, err := a2aclient.NewFromCard(ctx, card)
	if err != nil {
		t.Fatalf("a2aclient.NewFromCard() error = %v, want nil", err)
	}

	msg := a2a.NewMessage(a2a.MessageRoleUser, a2a.NewTextPart("hi"))
	result, err := client.SendMessage(ctx, &a2a.SendMessageRequest{Message: msg})
	if err != nil {
		t.Fatalf("client.SendMessage() error = %v, want nil", err)
	}

	respMsg, ok := result.(*a2a.Message)
	if !ok {
		t.Fatalf("result type = %T, want *a2a.Message", result)
	}
	if len(respMsg.Parts) != 1 || respMsg.Parts[0].Text() != "hello from a2a mount test" {
		t.Fatalf("response parts = %+v, want a single text part %q", respMsg.Parts, "hello from a2a mount test")
	}
}
