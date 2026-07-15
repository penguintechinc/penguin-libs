// Copyright 2026 Penguin Tech Inc
// SPDX-License-Identifier: Apache-2.0

package client

import (
	"crypto/tls"
	"time"
)

// defaultDialTimeout bounds how long a single lane's dial (TCP+TLS for H2,
// QUIC handshake for H3) is allowed to take before that attempt fails and
// the router moves to the next lane.
const defaultDialTimeout = 5 * time.Second

// defaultIdleTimeout bounds how long an idle connection is kept open before
// the transport closes it (H2: http.Transport.IdleConnTimeout; H3:
// quic.Config.MaxIdleTimeout).
const defaultIdleTimeout = 90 * time.Second

// Config holds client configuration for the multi-lane transport engine.
type Config struct {
	// BaseURL is the server base URL (e.g., "https://localhost:8443"). It
	// supplies the authority (host:port) used for every lane unless a lane's
	// authority has been overridden — for example by an Alt-Svc upgrade.
	BaseURL string
	// Lanes is the ordered lane preference list. New() defaults this to
	// [LaneH3, LaneH2] when empty. Including LaneZiti causes New() to return
	// ErrLaneUnavailable — Phase 1 does not implement the Ziti lane.
	Lanes []Lane
	// TLSConfig is the base TLS configuration. New() forces MinVersion to
	// tls.VersionTLS13 regardless of the value supplied here (mutating the
	// caller's pointer in place, mirroring server.New()'s behavior), per
	// spec §3 (TLS 1.2 and earlier MUST NOT be negotiated). If nil, a fresh
	// TLS13-only config using the system trust store is constructed.
	TLSConfig *tls.Config
	// DialTimeout bounds how long a single lane's connection establishment
	// may take. New() defaults this to 5s when zero or negative.
	DialTimeout time.Duration
	// IdleTimeout bounds how long an idle connection is retained. New()
	// defaults this to 90s when zero or negative.
	IdleTimeout time.Duration
	// AltSvcUpgrade controls whether an Alt-Svc response header advertising
	// h3, observed on a response served over HTTP/2, promotes the H3 lane
	// for future requests. Unlike Lanes/DialTimeout/IdleTimeout, New() does
	// NOT override a caller-supplied zero value (false) for this field —
	// its "default true" is realized only via DefaultClientConfig(), the
	// same convention server.Config uses for H2Enabled/H3Enabled.
	AltSvcUpgrade bool
}

// DefaultClientConfig returns a Config with sensible defaults: both lanes
// enabled in H3-preferred order, a 5s dial timeout, a 90s idle timeout, and
// Alt-Svc upgrade enabled. BaseURL and TLSConfig are left unset — callers
// must supply BaseURL; TLSConfig defaults to the system trust store.
func DefaultClientConfig() Config {
	return Config{
		Lanes:         []Lane{LaneH3, LaneH2},
		DialTimeout:   defaultDialTimeout,
		IdleTimeout:   defaultIdleTimeout,
		AltSvcUpgrade: true,
	}
}
