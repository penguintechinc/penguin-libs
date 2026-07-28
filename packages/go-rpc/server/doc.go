// Copyright 2026 Penguin Tech Inc
// SPDX-License-Identifier: Apache-2.0

// Package server implements the pRPC transport core (spec/SPEC.md §3): a
// dual-listener Connect RPC server offering HTTP/3 as the primary transport
// with automatic HTTP/2 fallback, both pinned to TLS 1.3 with 0-RTT disabled.
package server
