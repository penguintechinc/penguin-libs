// Copyright 2026 Penguin Tech Inc
// SPDX-License-Identifier: Apache-2.0

// Package a2a mounts an A2A (Agent2Agent) agent card and JSON-RPC endpoint
// on a pRPC http.ServeMux, using the official a2aproject/a2a-go SDK rather
// than a reimplementation of the A2A wire protocol. Per spec/SPEC.md §7, a
// server exposing A2A agents MUST publish an agent card at
// /.well-known/agent-card.json and MUST expose the corresponding A2A
// JSON-RPC endpoint; Mount and MountAgent do exactly that.
//
// # JSON-RPC endpoint path
//
// spec/SPEC.md §7 pins a literal path for the agent card
// (/.well-known/agent-card.json, exported here as WellKnownAgentCardPath)
// but — unlike MCP's fixed /mcp — does NOT pin a literal path for "the
// corresponding A2A JSON-RPC endpoint". The A2A protocol resolves that
// endpoint from the URL(s) an agent publishes in its own card
// (a2a.AgentCard.SupportedInterfaces[].URL), and the official go-sdk
// (a2asrv) likewise leaves the mount path entirely to the server operator —
// its own examples use ad hoc paths such as "/invoke". This package
// establishes JSONRPCPath ("/a2a") as the pRPC-wide convention: a single,
// predictable mount point mirroring /mcp's style. Mount always serves the
// caller-supplied handler at JSONRPCPath regardless of what URL the
// caller's card bytes declare; callers building their own card SHOULD
// publish this path (or a fully-qualified URL ending in it) so the card and
// the mounted endpoint stay consistent for third-party discovery.
//
// # Authentication
//
// The agent card is unauthenticated discovery by design (spec/SPEC.md §7)
// — Mount serves it to any caller, unwrapped, always. The JSON-RPC endpoint
// is different: per spec/SPEC.md §7 it MUST inherit the server's standard
// transport (§3) and zero-trust identity/auth profile (§6) unchanged, and
// anonymous A2A task requests MUST NOT be permitted.
//
// handler, as Mount receives and installs it, is a raw http.Handler mounted
// directly on mux at JSONRPCPath via mux.Handle — it is not a generated
// connect.Handler and it sits entirely outside any connect.WithInterceptors
// chain, including the one auth.Interceptors builds. Connect interceptors
// only run inside a generated Connect handler constructor; they cannot wrap
// an arbitrary http.Handler registered on the same mux, so
// auth.Interceptors' output has no effect at all on a request to /a2a.
//
// To satisfy spec §7, wrap mux — or, to leave the public agent-card route
// unaffected, wrap only handler before passing it to Mount — with
// auth.HTTPMiddleware, the net/http-level primitive built for exactly this
// case (handlers outside the Connect interceptor chain):
//
//	mw, err := auth.HTTPMiddleware(auth.HTTPConfig{
//		Mode: auth.ModeOIDC,
//		OIDC: relyingParty,
//	})
//	if err != nil {
//		// handle error
//	}
//	if err := a2a.Mount(mux, cardBytes, mw(jsonRPCHandler)); err != nil {
//		// handle error
//	}
//	// WellKnownAgentCardPath was registered with the unwrapped mux.Handle
//	// call inside Mount and stays public; only jsonRPCHandler is wrapped.
//
// Mount applies no authentication itself, to either route: wiring
// auth.HTTPMiddleware around the JSON-RPC handler (or the whole mux) is the
// caller's responsibility. Passing an unwrapped handler to Mount, or
// serving Mount's mux without wrapping it first, serves /a2a's JSON-RPC
// endpoint to anonymous callers — a direct violation of spec §7 — even
// though the agent card at WellKnownAgentCardPath is correctly public
// either way.
package a2a
