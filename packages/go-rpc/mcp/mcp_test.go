// Copyright 2026 Penguin Tech Inc
// SPDX-License-Identifier: Apache-2.0

package mcp

import (
	"context"
	"net/http"
	"net/http/httptest"
	"testing"
	"time"

	mcpsdk "github.com/modelcontextprotocol/go-sdk/mcp"
)

// TestMount_NilArgs asserts Mount rejects a nil mux or nil server with an
// error instead of panicking, per the task-9 interface contract.
func TestMount_NilArgs(t *testing.T) {
	srv := mcpsdk.NewServer(&mcpsdk.Implementation{Name: "test-server", Version: "v0.0.1"}, nil)

	if err := Mount(nil, srv); err == nil {
		t.Fatal("Mount(nil, server) = nil error, want error")
	}
	if err := Mount(http.NewServeMux(), nil); err == nil {
		t.Fatal("Mount(mux, nil) = nil error, want error")
	}
}

// TestMount_Path asserts Mount registers the handler at exactly "/mcp"
// (spec/SPEC.md §7) and does not also answer on an unmounted path.
func TestMount_Path(t *testing.T) {
	srv := mcpsdk.NewServer(&mcpsdk.Implementation{Name: "test-server", Version: "v0.0.1"}, nil)
	mux := http.NewServeMux()

	if err := Mount(mux, srv); err != nil {
		t.Fatalf("Mount() error = %v, want nil", err)
	}

	rec := httptest.NewRecorder()
	req := httptest.NewRequest(http.MethodGet, "/not-mcp", nil)
	mux.ServeHTTP(rec, req)
	if rec.Code != http.StatusNotFound {
		t.Fatalf("GET /not-mcp = %d, want %d (mux default for an unmounted path)", rec.Code, http.StatusNotFound)
	}
}

// TestMount_InitializeHandshake exercises the mounted /mcp endpoint with the
// official MCP go-sdk client end-to-end: Client.Connect performs the full
// JSON-RPC "initialize" handshake (InitializeRequest ->
// InitializedNotification) over the SDK's own StreamableClientTransport,
// then CallTool round-trips a registered tool. This is full SDK-to-SDK
// depth, not just a mounting-contract check.
func TestMount_InitializeHandshake(t *testing.T) {
	srv := mcpsdk.NewServer(&mcpsdk.Implementation{Name: "test-server", Version: "v0.0.1"}, nil)

	type echoArgs struct {
		Message string `json:"message"`
	}
	mcpsdk.AddTool(srv, &mcpsdk.Tool{
		Name:        "echo",
		Description: "echoes the message argument back",
	}, func(_ context.Context, _ *mcpsdk.CallToolRequest, args echoArgs) (*mcpsdk.CallToolResult, any, error) {
		return &mcpsdk.CallToolResult{
			Content: []mcpsdk.Content{&mcpsdk.TextContent{Text: args.Message}},
		}, nil, nil
	})

	mux := http.NewServeMux()
	if err := Mount(mux, srv); err != nil {
		t.Fatalf("Mount() error = %v, want nil", err)
	}

	httpSrv := httptest.NewServer(mux)
	defer httpSrv.Close()

	ctx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
	defer cancel()

	client := mcpsdk.NewClient(&mcpsdk.Implementation{Name: "test-client", Version: "v0.0.1"}, nil)
	session, err := client.Connect(ctx, &mcpsdk.StreamableClientTransport{Endpoint: httpSrv.URL + Path}, nil)
	if err != nil {
		t.Fatalf("client.Connect() error = %v, want nil", err)
	}
	defer session.Close()

	if session.InitializeResult() == nil {
		t.Fatal("session.InitializeResult() = nil, want a populated result after Connect's initialize handshake")
	}

	result, err := session.CallTool(ctx, &mcpsdk.CallToolParams{
		Name:      "echo",
		Arguments: map[string]any{"message": "hello from mcp mount test"},
	})
	if err != nil {
		t.Fatalf("session.CallTool() error = %v, want nil", err)
	}
	if len(result.Content) != 1 {
		t.Fatalf("len(result.Content) = %d, want 1", len(result.Content))
	}
	text, ok := result.Content[0].(*mcpsdk.TextContent)
	if !ok {
		t.Fatalf("result.Content[0] = %T, want *mcpsdk.TextContent", result.Content[0])
	}
	if text.Text != "hello from mcp mount test" {
		t.Fatalf("result text = %q, want %q", text.Text, "hello from mcp mount test")
	}
}
