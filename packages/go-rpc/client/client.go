// Copyright 2026 Penguin Tech Inc
// SPDX-License-Identifier: Apache-2.0

package client

import (
	"crypto/tls"
	"fmt"
	"net"
	"net/http"

	quic "github.com/quic-go/quic-go"
	"github.com/quic-go/quic-go/http3"
	"go.uber.org/zap"
)

// Client is a multi-lane pRPC HTTP client: a single *http.Client (see
// HTTPClient) backed by an ordered-lane RoundTripper that prefers HTTP/3,
// fails over to HTTP/2 on transport errors, and upgrades back to HTTP/3 for
// future requests when a server advertises support via Alt-Svc.
type Client struct {
	cfg    Config
	logger *zap.Logger
	http   *http.Client
	router *laneRouter
}

// New creates a Client from cfg. Lanes defaults to [LaneH3, LaneH2] when
// empty; DialTimeout/IdleTimeout default per DefaultClientConfig's values
// when zero or negative. If cfg.Lanes includes LaneZiti, New returns
// ErrLaneUnavailable — Phase 1 does not implement that lane. TLSConfig's
// MinVersion is forced to tls.VersionTLS13 regardless of the value supplied
// (mutating the caller's pointer in place when non-nil, mirroring
// server.New()'s behavior), per spec §3.
func New(cfg Config, logger *zap.Logger) (*Client, error) {
	for _, lane := range cfg.Lanes {
		if lane == LaneZiti {
			return nil, ErrLaneUnavailable
		}
	}

	if logger == nil {
		var err error
		logger, err = zap.NewProduction()
		if err != nil {
			return nil, fmt.Errorf("creating logger: %w", err)
		}
	}

	if len(cfg.Lanes) == 0 {
		cfg.Lanes = []Lane{LaneH3, LaneH2}
	}
	if cfg.DialTimeout <= 0 {
		cfg.DialTimeout = defaultDialTimeout
	}
	if cfg.IdleTimeout <= 0 {
		cfg.IdleTimeout = defaultIdleTimeout
	}

	tlsCfg := cfg.TLSConfig
	if tlsCfg != nil {
		tlsCfg.MinVersion = tls.VersionTLS13
	} else {
		tlsCfg = &tls.Config{MinVersion: tls.VersionTLS13}
	}
	cfg.TLSConfig = tlsCfg

	// Both lane transports are always constructed, independent of
	// cfg.Lanes, so an Alt-Svc upgrade can promote LaneH3 into the active
	// order even when the operator configured Lanes: []Lane{LaneH2} alone.
	// Constructing a transport allocates no socket or connection — quic-go's
	// http3.Transport lazily dials on first RoundTrip — so this carries no
	// runtime cost for a lane that never gets attempted.
	h2Transport := &http.Transport{
		TLSClientConfig:     tlsCfg.Clone(),
		DialContext:         (&net.Dialer{Timeout: cfg.DialTimeout}).DialContext,
		TLSHandshakeTimeout: cfg.DialTimeout,
		IdleConnTimeout:     cfg.IdleTimeout,
		MaxIdleConnsPerHost: 100,
		ForceAttemptHTTP2:   true,
	}
	h3Transport := &http3.Transport{
		TLSClientConfig: tlsCfg.Clone(),
		QUICConfig: &quic.Config{
			HandshakeIdleTimeout: cfg.DialTimeout,
			MaxIdleTimeout:       cfg.IdleTimeout,
		},
	}

	transports := map[Lane]http.RoundTripper{
		LaneH2: h2Transport,
		LaneH3: h3Transport,
	}

	router := newLaneRouter(cfg.Lanes, transports, cfg.AltSvcUpgrade, logger)

	return &Client{
		cfg:    cfg,
		logger: logger,
		http:   &http.Client{Transport: router},
		router: router,
	}, nil
}

// HTTPClient returns the *http.Client whose RoundTripper performs per-request
// lane selection and failover. Pass this to generated Connect client
// constructors.
func (c *Client) HTTPClient() *http.Client {
	return c.http
}

// Protocol returns the last lane a request succeeded on ("h3" or "h2"). If
// no request has succeeded yet, it reports the currently preferred
// (first non-cooling) lane instead, or "" if no lane is configured.
func (c *Client) Protocol() string {
	if lane, ok := c.router.lastSuccessLane(); ok {
		return string(lane)
	}
	if order := c.router.attemptOrder(); len(order) > 0 {
		return string(order[0])
	}
	return ""
}

// MarkLaneFailed puts lane into cooldown: the router skips it in favor of
// other lanes until MaybeRetryLane clears the cooldown (or the lane
// succeeds when tried as a last resort). Generalizes go-h3's MarkH3Failed
// to an arbitrary lane.
func (c *Client) MarkLaneFailed(lane Lane) {
	c.router.markFailed(lane)
}

// MaybeRetryLane clears lane's cooldown once laneCooldown has elapsed since
// it was marked failed; otherwise it is a no-op. Generalizes go-h3's
// MaybeRetryH3 to an arbitrary lane.
func (c *Client) MaybeRetryLane(lane Lane) {
	c.router.maybeRetry(lane)
}

// Close releases resources held by every lane's transport (idle connections,
// and — for HTTP/3 — the underlying QUIC transport and UDP socket).
func (c *Client) Close() error {
	return c.router.close()
}
