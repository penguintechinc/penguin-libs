// Copyright 2026 Penguin Tech Inc
// SPDX-License-Identifier: Apache-2.0

// Package mcp mounts an official MCP (Model Context Protocol) go-sdk server
// on a pRPC http.ServeMux at the fixed path spec/SPEC.md §7 requires
// ("/mcp"), by hosting the SDK's own Streamable HTTP handler rather than a
// reimplementation of the MCP wire protocol. Mount applies no
// authentication of its own: per spec/SPEC.md §7, the /mcp endpoint MUST
// inherit the server's standard transport (§3) and zero-trust identity/auth
// profile (§6) unchanged, so callers wrap the mux — or the resulting
// http.Handler chain — with the same interceptor/middleware stack applied
// to every other pRPC endpoint (see the auth package) before serving it.
// Anonymous tool calls reaching /mcp are therefore rejected by that shared
// chain, never by this package.
package mcp
