// Copyright 2026 Penguin Tech Inc
// SPDX-License-Identifier: Apache-2.0

package mcp

import (
	"errors"
	"net/http"

	mcpsdk "github.com/modelcontextprotocol/go-sdk/mcp"
)

// Path is the fixed HTTP path pRPC servers mount the MCP Streamable HTTP
// endpoint at, per spec/SPEC.md §7: "A server exposing MCP tools MUST mount
// an MCP Streamable HTTP endpoint at /mcp".
const Path = "/mcp"

// Mount installs server's Streamable HTTP handler on mux at exactly Path
// ("/mcp"), using mcpsdk.NewStreamableHTTPHandler from the official MCP
// go-sdk. The same server instance answers every session — the SDK's
// getServer callback simply returns it on each request, which its own docs
// call an explicitly supported use ("It is OK for getServer to return the
// same server multiple times"). Mount installs no authentication of its
// own; per spec/SPEC.md §7 the caller is responsible for wrapping mux (or
// the handler chain serving it) with the same zero-trust middleware used
// for every other pRPC endpoint, so /mcp inherits identity/auth unchanged.
// Mount rejects a nil mux or nil server with an error instead of a panic.
func Mount(mux *http.ServeMux, server *mcpsdk.Server) error {
	if mux == nil {
		return errors.New("mcp: Mount requires a non-nil mux")
	}
	if server == nil {
		return errors.New("mcp: Mount requires a non-nil server")
	}

	handler := mcpsdk.NewStreamableHTTPHandler(func(*http.Request) *mcpsdk.Server {
		return server
	}, nil)
	mux.Handle(Path, handler)
	return nil
}
