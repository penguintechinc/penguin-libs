// Copyright 2026 Penguin Tech Inc
// SPDX-License-Identifier: Apache-2.0

package client

import (
	"context"
	"errors"
	"fmt"
	"io"
	"net"
	"net/http"
	"strings"
	"sync"
	"time"

	"go.uber.org/zap"
)

// Lane identifies a transport path a client request can travel over.
type Lane string

const (
	// LaneH3 is the HTTP/3 (QUIC) transport lane.
	LaneH3 Lane = "h3"
	// LaneH2 is the HTTP/2 (TCP+TLS) transport lane.
	LaneH2 Lane = "h2"
	// LaneZiti is reserved for the Phase 4 OpenZiti overlay lane. Any
	// attempt to enable it in Phase 1 causes New() to return
	// ErrLaneUnavailable.
	LaneZiti Lane = "ziti"
)

// ErrLaneUnavailable is returned by New when cfg.Lanes requests a lane this
// build does not implement yet (currently LaneZiti only).
var ErrLaneUnavailable = errors.New("client: lane unavailable in this phase")

// laneCooldown is how long a lane stays marked as failed (skipped in favor
// of other lanes) after MarkLaneFailed, before MaybeRetryLane will clear it.
// It is a package variable rather than a Config field so tests can shrink it
// without adding a knob to the public, Task-10-consumed Config shape.
var laneCooldown = 5 * time.Minute

// laneState tracks the cooldown status of a single lane.
type laneState struct {
	mu       sync.Mutex
	cooling  bool
	failedAt time.Time
}

// laneRouter is an http.RoundTripper that selects a Lane per request from an
// ordered preference list, fails transport-level errors over to the next
// lane within the same call (rewinding the request body via GetBody when
// possible), tracks per-lane cooldowns, and promotes the H3 lane for future
// requests when a response carries an Alt-Svc hint.
//
// transports and state are populated once at construction for every lane
// New() built a transport for (always LaneH2 and LaneH3) and are never
// mutated afterward, so they are read without holding mu. order and
// authority DO mutate at runtime (lane failover ordering, Alt-Svc-driven
// authority overrides) and are guarded by mu.
type laneRouter struct {
	mu        sync.RWMutex
	order     []Lane
	authority map[Lane]string

	transports map[Lane]http.RoundTripper
	state      map[Lane]*laneState

	altSvcUpgrade bool
	logger        *zap.Logger

	lastSuccess lastSuccessTracker
}

// lastSuccessTracker is a minimal, mutex-guarded last-written-Lane holder
// used to back (*Client).Protocol()'s "last successful lane" semantics.
// Named to avoid any collision with the sync/atomic package used elsewhere
// in this package.
type lastSuccessTracker struct {
	mu   sync.RWMutex
	lane Lane
	set  bool
}

func (t *lastSuccessTracker) Store(l Lane) {
	t.mu.Lock()
	t.lane = l
	t.set = true
	t.mu.Unlock()
}

func (t *lastSuccessTracker) Load() (Lane, bool) {
	t.mu.RLock()
	defer t.mu.RUnlock()
	return t.lane, t.set
}

// newLaneRouter builds a router over the given preference order and
// transports map. transports must contain an entry for every lane order can
// possibly ever be promoted to (Phase 1: LaneH2 and LaneH3, always both
// built regardless of cfg.Lanes, so Alt-Svc can promote H3 even when the
// operator configured Lanes: []Lane{LaneH2} alone).
func newLaneRouter(order []Lane, transports map[Lane]http.RoundTripper, altSvcUpgrade bool, logger *zap.Logger) *laneRouter {
	state := make(map[Lane]*laneState, len(transports))
	for lane := range transports {
		state[lane] = &laneState{}
	}
	return &laneRouter{
		order:         append([]Lane(nil), order...),
		authority:     make(map[Lane]string),
		transports:    transports,
		state:         state,
		altSvcUpgrade: altSvcUpgrade,
		logger:        logger,
	}
}

// RoundTrip implements http.RoundTripper. It attempts lanes in
// attemptOrder() (non-cooling lanes first, cooling lanes as a last resort),
// stopping at the first success. A transport-level failure (the only kind of
// error http.RoundTripper.RoundTrip ever returns — application-level HTTP
// errors come back as a non-nil *http.Response with a nil error) marks that
// lane failed and moves to the next lane, cloning the request and rewinding
// its body via GetBody. If the request carries a body with no GetBody, the
// first failure is returned immediately rather than silently retried on
// another lane with a stale/consumed body.
//
// A caller context cancellation/deadline is never treated as a lane
// failure: if req.Context().Err() is set, or the transport error is (or
// wraps) context.Canceled/context.DeadlineExceeded, that error is returned
// immediately without marking the lane failed or attempting another lane —
// the caller gave up, the transport didn't. Only genuine transport/dial
// errors mark a lane and fail over.
//
// RoundTrip never returns (nil, nil): http.RoundTripper's contract (and
// every caller built on it, including connect-go and net/http itself)
// dereferences the response whenever err == nil, so returning a nil
// response with a nil error is a guaranteed nil-pointer panic. If the
// attempt loop completes without ever finding a matching transport for any
// configured lane, an explicit error is returned instead of a nil lastErr.
func (r *laneRouter) RoundTrip(req *http.Request) (*http.Response, error) {
	order := r.attemptOrder()
	if len(order) == 0 {
		return nil, errors.New("client: no lanes configured")
	}

	var lastErr error
	for i, lane := range order {
		rt, ok := r.transports[lane]
		if !ok {
			continue
		}

		attemptReq, err := r.prepareRequest(req, lane, i)
		if err != nil {
			// Could not safely prepare this lane's request (typically: a
			// prior lane already consumed a body with no GetBody to rewind
			// it). Surface the most actionable error: the previous lane's
			// real transport failure if we have one, else the prepare error.
			if lastErr != nil {
				return nil, lastErr
			}
			return nil, err
		}

		resp, roundTripErr := rt.RoundTrip(attemptReq)
		if roundTripErr == nil {
			r.onSuccess(lane, resp)
			return resp, nil
		}

		if req.Context().Err() != nil ||
			errors.Is(roundTripErr, context.Canceled) ||
			errors.Is(roundTripErr, context.DeadlineExceeded) {
			return nil, roundTripErr
		}

		r.markFailed(lane)
		lastErr = fmt.Errorf("lane %s: %w", lane, roundTripErr)
	}
	if lastErr == nil {
		lastErr = errors.New("client: no lane attempted (no matching transport for any configured lane)")
	}
	return nil, lastErr
}

// prepareRequest returns the *http.Request to send on lane at the given
// attempt index (0 = first attempt). Index 0 reuses req unless an Alt-Svc
// authority override applies. Index > 0 always clones req (a fresh attempt
// on a different lane must not share the previous attempt's Request struct)
// and rewinds the body via GetBody, returning an error if a non-empty body
// has no GetBody to rewind.
func (r *laneRouter) prepareRequest(req *http.Request, lane Lane, attemptIndex int) (*http.Request, error) {
	r.mu.RLock()
	authority := r.authority[lane]
	r.mu.RUnlock()

	hasBody := req.Body != nil && req.Body != http.NoBody

	if attemptIndex == 0 && (authority == "" || authority == req.URL.Host) {
		return req, nil
	}

	if attemptIndex > 0 && hasBody && req.GetBody == nil {
		return nil, fmt.Errorf("client: cannot fail over to lane %s: request body has no GetBody", lane)
	}

	clone := req.Clone(req.Context())
	if authority != "" {
		clone.URL.Host = authority
		clone.Host = authority
	}
	if attemptIndex > 0 && hasBody {
		body, err := req.GetBody()
		if err != nil {
			return nil, fmt.Errorf("client: rewinding request body for lane %s: %w", lane, err)
		}
		clone.Body = body
	}
	return clone, nil
}

// attemptOrder returns the current lane preference order with non-cooling
// lanes first (in configured order) and cooling lanes appended as a last
// resort, so a request only fails outright once every lane — including ones
// still in cooldown — has been tried.
func (r *laneRouter) attemptOrder() []Lane {
	r.mu.RLock()
	order := append([]Lane(nil), r.order...)
	r.mu.RUnlock()

	warm := make([]Lane, 0, len(order))
	cooling := make([]Lane, 0, len(order))
	for _, lane := range order {
		if r.isCooling(lane) {
			cooling = append(cooling, lane)
		} else {
			warm = append(warm, lane)
		}
	}
	return append(warm, cooling...)
}

// lastSuccessLane returns the most recently successful lane and whether any
// request has succeeded yet.
func (r *laneRouter) lastSuccessLane() (Lane, bool) {
	return r.lastSuccess.Load()
}

func (r *laneRouter) isCooling(lane Lane) bool {
	st, ok := r.state[lane]
	if !ok {
		return false
	}
	st.mu.Lock()
	defer st.mu.Unlock()
	return st.cooling
}

// markFailed puts lane into cooldown. It is the shared implementation
// behind both the router's own internal failover and (*Client).MarkLaneFailed.
func (r *laneRouter) markFailed(lane Lane) {
	st, ok := r.state[lane]
	if !ok {
		return
	}
	st.mu.Lock()
	st.cooling = true
	st.failedAt = time.Now()
	st.mu.Unlock()
	if r.logger != nil {
		r.logger.Warn("lane failed, entering cooldown", zap.String("lane", string(lane)))
	}
}

// maybeRetry clears lane's cooldown once laneCooldown has elapsed since it
// was marked failed. It is the shared implementation behind
// (*Client).MaybeRetryLane.
func (r *laneRouter) maybeRetry(lane Lane) {
	st, ok := r.state[lane]
	if !ok {
		return
	}
	st.mu.Lock()
	defer st.mu.Unlock()
	if st.cooling && time.Since(st.failedAt) >= laneCooldown {
		st.cooling = false
		if r.logger != nil {
			r.logger.Info("lane cooldown elapsed, eligible again", zap.String("lane", string(lane)))
		}
	}
}

// onSuccess records lane as the last-successful lane, clears its cooldown
// (a successful round trip proves it is no longer failing, even if it was
// only attempted as a cooling last resort), and — for H2 successes with
// Alt-Svc upgrade enabled (Config.DisableAltSvcUpgrade is false) — checks
// the response for an Alt-Svc hint.
func (r *laneRouter) onSuccess(lane Lane, resp *http.Response) {
	if st, ok := r.state[lane]; ok {
		st.mu.Lock()
		st.cooling = false
		st.mu.Unlock()
	}
	r.lastSuccess.Store(lane)

	if r.altSvcUpgrade && lane == LaneH2 {
		r.maybeUpgradeFromAltSvc(resp)
	}
}

// maybeUpgradeFromAltSvc inspects resp's Alt-Svc header(s) for an h3 entry
// and, if its authority passes the same-origin check in
// resolveAltSvcAuthority, promotes LaneH3 for future requests via promote.
// An advertisement naming a different host than the request is ignored
// entirely — no promotion, no error, just a debug log — since a server (or
// an on-path attacker able to inject/modify response headers) must never
// be able to redirect the client's future traffic to a host the caller
// didn't configure via BaseURL.
func (r *laneRouter) maybeUpgradeFromAltSvc(resp *http.Response) {
	reqHost := ""
	if resp.Request != nil && resp.Request.URL != nil {
		reqHost = resp.Request.URL.Host
	}
	for _, value := range resp.Header.Values("Alt-Svc") {
		authority := parseAltSvcH3(value)
		if authority == "" {
			continue
		}
		resolved := resolveAltSvcAuthority(reqHost, authority)
		if resolved == "" {
			if r.logger != nil {
				r.logger.Debug("alt-svc upgrade: ignoring cross-host advertisement",
					zap.String("advertised_authority", authority), zap.String("request_host", reqHost))
			}
			return
		}
		r.promote(LaneH3, resolved)
		return
	}
}

// promote moves lane to the front of the preference order, records its
// authority override (if any), and clears its cooldown so the very next
// request prefers it.
func (r *laneRouter) promote(lane Lane, authority string) {
	if _, ok := r.transports[lane]; !ok {
		return
	}

	r.mu.Lock()
	if authority != "" {
		r.authority[lane] = authority
	}
	newOrder := make([]Lane, 0, len(r.order)+1)
	newOrder = append(newOrder, lane)
	for _, l := range r.order {
		if l != lane {
			newOrder = append(newOrder, l)
		}
	}
	r.order = newOrder
	r.mu.Unlock()

	if st, ok := r.state[lane]; ok {
		st.mu.Lock()
		st.cooling = false
		st.mu.Unlock()
	}
	if r.logger != nil {
		r.logger.Info("alt-svc upgrade: promoting lane",
			zap.String("lane", string(lane)), zap.String("authority", authority))
	}
}

// close releases resources held by every lane's transport.
func (r *laneRouter) close() error {
	var errs []error
	for _, rt := range r.transports {
		if idler, ok := rt.(interface{ CloseIdleConnections() }); ok {
			idler.CloseIdleConnections()
		}
		if closer, ok := rt.(io.Closer); ok {
			if err := closer.Close(); err != nil {
				errs = append(errs, err)
			}
		}
	}
	return errors.Join(errs...)
}

// parseAltSvcH3 extracts the h3 entry's authority from a single Alt-Svc
// header value, e.g. `h3=":8443"; ma=2592000` or
// `h3="alt.example.com:8443"; ma=2592000, h3-29=":8443"`. It returns "" if
// no h3 entry is present.
func parseAltSvcH3(value string) string {
	for _, entry := range strings.Split(value, ",") {
		fields := strings.SplitN(strings.TrimSpace(entry), ";", 2)
		kv := strings.SplitN(fields[0], "=", 2)
		if len(kv) != 2 {
			continue
		}
		if !strings.EqualFold(strings.TrimSpace(kv[0]), "h3") {
			continue
		}
		return strings.Trim(strings.TrimSpace(kv[1]), `"`)
	}
	return ""
}

// resolveAltSvcAuthority resolves an Alt-Svc authority against reqHost into
// a full host:port suitable for http.Request.URL.Host, enforcing a
// same-origin rule: only a host the caller already configured (via
// BaseURL) may ever be dialed as a result of a server-supplied header.
//
// Two shapes are accepted:
//   - a bare ":port" (same host, alternate UDP port) — always accepted,
//     resolved against reqHost's host.
//   - an explicit "host:port" whose host matches reqHost's host
//     case-insensitively — accepted as-is.
//
// Any other authority — most importantly one naming a different host — is
// rejected by returning "", which the caller (maybeUpgradeFromAltSvc)
// treats as "ignore this advertisement entirely, do not promote".
func resolveAltSvcAuthority(reqHost, altSvcAuthority string) string {
	reqHostOnly := reqHost
	if h, _, err := net.SplitHostPort(reqHost); err == nil {
		reqHostOnly = h
	}

	if strings.HasPrefix(altSvcAuthority, ":") {
		return reqHostOnly + altSvcAuthority
	}

	advHostOnly, _, err := net.SplitHostPort(altSvcAuthority)
	if err != nil {
		// Malformed authority (e.g. missing port) — reject rather than
		// guess.
		return ""
	}
	if !strings.EqualFold(advHostOnly, reqHostOnly) {
		return ""
	}
	return altSvcAuthority
}
