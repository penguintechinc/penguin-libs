// Copyright 2026 Penguin Tech Inc
// SPDX-License-Identifier: Apache-2.0

// Package client implements the pRPC multi-lane client: an ordered set of
// transport lanes (HTTP/3 preferred, HTTP/2 fallback, with a reserved slot
// for a future Ziti overlay lane) exposed as a single *http.Client suitable
// for generated Connect client constructors. It selects and fails over
// lanes per request, tracks per-lane cooldowns after transport failures,
// and opportunistically upgrades to HTTP/3 for future requests when a
// server advertises it via the Alt-Svc response header (RFC 7838).
package client
