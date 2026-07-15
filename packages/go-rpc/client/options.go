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
	// ErrLaneUnavailable — Phase 1 does not implement the Ziti lane. Any
	// value other than LaneH3 or LaneH2 also causes New() to return an
	// error.
	//
	// Lanes is NOT by itself a hard boundary against H3 traffic: New()
	// always constructs both the H2 and H3 transports regardless of Lanes
	// (see newLaneRouter's doc), and when Alt-Svc upgrade is enabled (the
	// default — see DisableAltSvcUpgrade) a same-origin Alt-Svc
	// advertisement can still promote LaneH3 into the active order for
	// future requests even if the operator configured Lanes: []Lane{LaneH2}
	// alone. The same-origin check pins WHICH host can ever be dialed, but
	// it does not stop H3 (UDP/QUIC) from being attempted at all.
	// Operators who must hard-disable H3 — for example because UDP is
	// blocked on the network path and a QUIC handshake attempt would waste
	// a dial timeout on every upgrade — should set BOTH
	// DisableAltSvcUpgrade: true AND omit LaneH3 from Lanes.
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
	// DisableAltSvcUpgrade, when true, disables the Alt-Svc upgrade
	// behavior: by default (zero value, false) an Alt-Svc response header
	// advertising h3, observed on a response served over HTTP/2, promotes
	// the H3 lane for future requests, subject to the same-origin check in
	// resolveAltSvcAuthority (an advertisement naming a different host
	// than the request is always ignored, regardless of this flag).
	//
	// This field is inverted relative to Lanes/DialTimeout/IdleTimeout —
	// which New() force-defaults away from their Go zero values — because
	// a plain bool cannot distinguish "caller left AltSvcUpgrade unset" from
	// "caller explicitly disabled it": both are false. Naming the field for
	// its off-state means the zero value (false) already means "enabled",
	// so a Config{} zero value and DefaultClientConfig() agree with no
	// special-casing required in New().
	//
	// See the Lanes field doc for why Lanes alone is not a hard boundary
	// against H3: DisableAltSvcUpgrade must be combined with omitting
	// LaneH3 from Lanes to fully prevent H3 activation (e.g. when UDP is
	// blocked on the network path).
	DisableAltSvcUpgrade bool
}

// DefaultClientConfig returns a Config with sensible defaults: both lanes
// enabled in H3-preferred order, a 5s dial timeout, a 90s idle timeout, and
// Alt-Svc upgrade enabled (DisableAltSvcUpgrade left at its zero value,
// false). BaseURL and TLSConfig are left unset — callers must supply
// BaseURL; TLSConfig defaults to the system trust store.
func DefaultClientConfig() Config {
	return Config{
		Lanes:       []Lane{LaneH3, LaneH2},
		DialTimeout: defaultDialTimeout,
		IdleTimeout: defaultIdleTimeout,
	}
}
