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
// — Mount serves it to any caller. The JSON-RPC endpoint is not: per
// spec/SPEC.md §7 it MUST inherit the server's standard transport (§3) and
// zero-trust identity/auth profile (§6) unchanged, so anonymous A2A task
// requests MUST be rejected the same as any other pRPC procedure. Mount
// applies no authentication itself — callers wrap mux (or the handler chain
// serving it) with the same interceptor/middleware stack used for every
// other pRPC endpoint (see the auth package) before serving it.
package a2a
