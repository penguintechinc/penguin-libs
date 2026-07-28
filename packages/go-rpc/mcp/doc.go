// Copyright 2026 Penguin Tech Inc
// SPDX-License-Identifier: Apache-2.0

// Package mcp mounts an official MCP (Model Context Protocol) go-sdk server
// on a pRPC http.ServeMux at the fixed path spec/SPEC.md §7 requires
// ("/mcp"), by hosting the SDK's own Streamable HTTP handler rather than a
// reimplementation of the MCP wire protocol. Mount applies no
// authentication of its own.
//
// # Authentication — this is a raw http.Handler, not a Connect handler
//
// The SDK handler Mount registers is a plain http.Handler mounted directly
// on mux via mux.Handle. It is NOT a generated connect.Handler, and it sits
// entirely outside any connect.WithInterceptors chain — including the one
// auth.Interceptors builds. Connect interceptors only ever run inside a
// generated Connect handler constructor; they have no hook into, and
// therefore cannot wrap, an arbitrary http.Handler registered on the same
// mux. Concretely: calling auth.Interceptors and passing the result to a
// Connect service's handler constructor does nothing at all for a request
// to /mcp — that request never passes through any interceptor in the
// chain.
//
// Per spec/SPEC.md §7, the /mcp endpoint MUST inherit the server's standard
// transport (§3) and zero-trust identity/auth profile (§6) unchanged, and
// anonymous tool invocations MUST NOT be permitted. To satisfy that, wrap
// mux (or, equivalently, wrap only the http.Handler this package installs
// at Path) with auth.HTTPMiddleware — the net/http-level primitive built
// specifically for handlers outside the Connect interceptor chain — before
// the server ever starts serving:
//
//	mw, err := auth.HTTPMiddleware(auth.HTTPConfig{
//		Mode: auth.ModeOIDC,
//		OIDC: relyingParty,
//	})
//	if err != nil {
//		// handle error
//	}
//	if err := mcp.Mount(mux, mcpServer); err != nil {
//		// handle error
//	}
//	// mux itself may host other, already-secured Connect handlers; wrapping
//	// the whole mux here is what actually puts /mcp behind the same
//	// zero-trust profile as every other endpoint.
//	server.Start(mw(mux))
//
// Mounting this package's handler on a mux that is then served without such
// a wrapper serves /mcp to anonymous callers — a direct violation of spec
// §7. This package never applies auth.HTTPMiddleware itself: Mount's job is
// only to install the SDK handler at the correct path; wiring the mux (or
// the whole server) behind auth.HTTPMiddleware is the operator's
// responsibility, exactly as it is for any other endpoint mounted outside
// the Connect interceptor chain.
package mcp
