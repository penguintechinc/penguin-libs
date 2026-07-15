// Copyright 2026 Penguin Tech Inc
// SPDX-License-Identifier: Apache-2.0

package a2a

import (
	"encoding/json"
	"errors"
	"fmt"
	"net/http"

	"github.com/a2aproject/a2a-go/v2/a2a"
	"github.com/a2aproject/a2a-go/v2/a2asrv"
)

// WellKnownAgentCardPath is the fixed HTTP path pRPC servers publish the
// A2A agent card at, per spec/SPEC.md §7. It is the same literal value as
// a2asrv.WellKnownAgentCardPath; re-exported here so callers of this
// package don't need to import a2asrv just to reference it.
const WellKnownAgentCardPath = a2asrv.WellKnownAgentCardPath

// JSONRPCPath is the fixed HTTP path pRPC servers mount the A2A JSON-RPC
// endpoint at. See the package doc comment ("JSON-RPC endpoint path") for
// why this is a pRPC-established convention rather than a literal spec
// requirement.
const JSONRPCPath = "/a2a"

// Mount serves card at WellKnownAgentCardPath (GET only, unauthenticated
// discovery per spec/SPEC.md §7) and mounts handler — the A2A JSON-RPC
// endpoint — at JSONRPCPath. card MUST be non-empty, valid JSON; Mount
// returns an error, never panics, for a nil mux, nil handler, or invalid
// card. Mount applies no authentication to handler itself: see the package
// doc comment ("Authentication") for the shared zero-trust chain this
// endpoint is expected to inherit.
func Mount(mux *http.ServeMux, card []byte, handler http.Handler) error {
	if mux == nil {
		return errors.New("a2a: Mount requires a non-nil mux")
	}
	if handler == nil {
		return errors.New("a2a: Mount requires a non-nil handler")
	}
	if len(card) == 0 {
		return errors.New("a2a: Mount requires a non-empty agent card")
	}
	if !json.Valid(card) {
		return errors.New("a2a: Mount requires the agent card to be valid JSON")
	}

	// Defensive copy: the served body must not change if the caller mutates
	// the slice it passed in after Mount returns.
	body := append([]byte(nil), card...)

	mux.HandleFunc(WellKnownAgentCardPath, func(w http.ResponseWriter, r *http.Request) {
		if r.Method != http.MethodGet {
			w.WriteHeader(http.StatusMethodNotAllowed)
			return
		}
		w.Header().Set("Content-Type", "application/json")
		_, _ = w.Write(body)
	})
	mux.Handle(JSONRPCPath, handler)
	return nil
}

// MountAgent is a convenience wrapper around Mount for callers that already
// hold the official go-sdk's typed a2a.AgentCard and a2asrv.RequestHandler
// rather than raw bytes: it marshals card to JSON and builds the JSON-RPC
// handler via a2asrv.NewJSONRPCHandler(requestHandler, opts...), then
// mounts both through Mount, preserving Mount's path and auth contracts.
func MountAgent(mux *http.ServeMux, card *a2a.AgentCard, requestHandler a2asrv.RequestHandler, opts ...a2asrv.TransportOption) error {
	if card == nil {
		return errors.New("a2a: MountAgent requires a non-nil card")
	}
	if requestHandler == nil {
		return errors.New("a2a: MountAgent requires a non-nil requestHandler")
	}

	cardBytes, err := json.Marshal(card)
	if err != nil {
		return fmt.Errorf("a2a: MountAgent: marshal card: %w", err)
	}

	handler := a2asrv.NewJSONRPCHandler(requestHandler, opts...)
	return Mount(mux, cardBytes, handler)
}
