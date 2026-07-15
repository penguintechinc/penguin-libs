// Copyright 2026 Penguin Tech Inc
// SPDX-License-Identifier: Apache-2.0

package client

import (
	"context"
	"errors"
	"io"
	"net/http"
	"strings"
	"testing"

	"go.uber.org/zap"
)

// roundTripperFunc adapts a function to http.RoundTripper for fake,
// network-free lane transports in these white-box tests.
type roundTripperFunc func(*http.Request) (*http.Response, error)

func (f roundTripperFunc) RoundTrip(req *http.Request) (*http.Response, error) { return f(req) }

func okResponse(req *http.Request, body string) *http.Response {
	return &http.Response{
		StatusCode: http.StatusOK,
		Body:       io.NopCloser(strings.NewReader(body)),
		Header:     http.Header{},
		Request:    req,
	}
}

func TestLaneConstants(t *testing.T) {
	if LaneH3 != "h3" {
		t.Errorf("LaneH3 = %q, want h3", LaneH3)
	}
	if LaneH2 != "h2" {
		t.Errorf("LaneH2 = %q, want h2", LaneH2)
	}
	if LaneZiti != "ziti" {
		t.Errorf("LaneZiti = %q, want ziti", LaneZiti)
	}
}

func TestLaneRouter_FailsOverAndRewindsBody(t *testing.T) {
	var h3Calls, h2Calls int
	var h3Body, h2Body string

	h3RT := roundTripperFunc(func(req *http.Request) (*http.Response, error) {
		h3Calls++
		b, _ := io.ReadAll(req.Body)
		h3Body = string(b)
		return nil, errors.New("simulated h3 transport failure")
	})
	h2RT := roundTripperFunc(func(req *http.Request) (*http.Response, error) {
		h2Calls++
		b, _ := io.ReadAll(req.Body)
		h2Body = string(b)
		return okResponse(req, "ok"), nil
	})

	r := newLaneRouter([]Lane{LaneH3, LaneH2}, map[Lane]http.RoundTripper{LaneH3: h3RT, LaneH2: h2RT}, false, zap.NewNop())

	req, err := http.NewRequest(http.MethodPost, "https://example.test/rpc", strings.NewReader("payload"))
	if err != nil {
		t.Fatalf("NewRequest: %v", err)
	}
	if req.GetBody == nil {
		t.Fatal("expected http.NewRequest to auto-populate GetBody for a strings.Reader body")
	}

	resp, err := r.RoundTrip(req)
	if err != nil {
		t.Fatalf("RoundTrip: %v", err)
	}
	if resp.StatusCode != http.StatusOK {
		t.Errorf("StatusCode = %d, want 200", resp.StatusCode)
	}
	if h3Calls != 1 || h2Calls != 1 {
		t.Errorf("h3Calls=%d h2Calls=%d, want 1 and 1", h3Calls, h2Calls)
	}
	if h3Body != "payload" || h2Body != "payload" {
		t.Errorf("h3Body=%q h2Body=%q, want both %q (rewind must resend the same body)", h3Body, h2Body, "payload")
	}
	if !r.isCooling(LaneH3) {
		t.Error("expected LaneH3 to be marked cooling after its transport error")
	}
}

func TestLaneRouter_NoGetBody_DoesNotSilentlyRetry(t *testing.T) {
	var h3Calls, h2Calls int
	h3RT := roundTripperFunc(func(req *http.Request) (*http.Response, error) {
		h3Calls++
		return nil, errors.New("simulated h3 transport failure")
	})
	h2RT := roundTripperFunc(func(req *http.Request) (*http.Response, error) {
		h2Calls++
		return okResponse(req, "ok"), nil
	})

	r := newLaneRouter([]Lane{LaneH3, LaneH2}, map[Lane]http.RoundTripper{LaneH3: h3RT, LaneH2: h2RT}, false, zap.NewNop())

	req, err := http.NewRequest(http.MethodPost, "https://example.test/rpc", strings.NewReader("payload"))
	if err != nil {
		t.Fatalf("NewRequest: %v", err)
	}
	req.GetBody = nil // simulate a body the router cannot safely rewind

	_, err = r.RoundTrip(req)
	if err == nil {
		t.Fatal("expected an error when the body has no GetBody, got nil")
	}
	if h3Calls != 1 {
		t.Errorf("h3Calls = %d, want 1", h3Calls)
	}
	if h2Calls != 0 {
		t.Errorf("h2Calls = %d, want 0 (must not silently retry without a rewindable body)", h2Calls)
	}
}

func TestLaneRouter_AttemptOrder_CoolingLaneMovesLast(t *testing.T) {
	noop := roundTripperFunc(func(req *http.Request) (*http.Response, error) { return okResponse(req, "ok"), nil })
	r := newLaneRouter([]Lane{LaneH3, LaneH2}, map[Lane]http.RoundTripper{LaneH3: noop, LaneH2: noop}, false, zap.NewNop())

	r.markFailed(LaneH3)
	order := r.attemptOrder()
	if len(order) != 2 || order[0] != LaneH2 || order[1] != LaneH3 {
		t.Fatalf("attemptOrder() = %v, want [h2 h3] (cooling lane last)", order)
	}
}

func TestLaneRouter_AttemptOrder_AllCooling_StillReturnsAllAsLastResort(t *testing.T) {
	noop := roundTripperFunc(func(req *http.Request) (*http.Response, error) { return okResponse(req, "ok"), nil })
	r := newLaneRouter([]Lane{LaneH3, LaneH2}, map[Lane]http.RoundTripper{LaneH3: noop, LaneH2: noop}, false, zap.NewNop())

	r.markFailed(LaneH3)
	r.markFailed(LaneH2)
	order := r.attemptOrder()
	if len(order) != 2 {
		t.Fatalf("attemptOrder() = %v, want both lanes returned as a last resort even when both are cooling", order)
	}
}

func TestLaneRouter_MarkFailed_UnknownLane_NoPanic(t *testing.T) {
	r := newLaneRouter([]Lane{LaneH2}, map[Lane]http.RoundTripper{LaneH2: roundTripperFunc(func(req *http.Request) (*http.Response, error) {
		return okResponse(req, "ok"), nil
	})}, false, zap.NewNop())

	// LaneZiti has no transport/state entry in this router; both calls must
	// be safe no-ops rather than panicking.
	r.markFailed(LaneZiti)
	r.maybeRetry(LaneZiti)
}

func TestParseAltSvcH3(t *testing.T) {
	cases := []struct {
		name, in, want string
	}{
		{"same-host-port", `h3=":8443"; ma=2592000`, `:8443`},
		{"explicit-authority", `h3="alt.example.com:8443"; ma=2592000, h3-29=":8443"`, `alt.example.com:8443`},
		{"no-h3-entry", `h2=":443"`, ``},
		{"empty", ``, ``},
		{"h3-not-first", `h3-29=":443", h3=":444"`, `:444`},
	}
	for _, c := range cases {
		t.Run(c.name, func(t *testing.T) {
			if got := parseAltSvcH3(c.in); got != c.want {
				t.Errorf("parseAltSvcH3(%q) = %q, want %q", c.in, got, c.want)
			}
		})
	}
}

// TestResolveAltSvcAuthority asserts the same-origin rule: a bare ":port"
// (same host, alternate port) is always accepted; an explicit "host:port"
// is accepted ONLY when its host matches the request host (case-
// insensitively); any other host is rejected ("" — no promotion) because
// the client must never dial a host the caller didn't configure via
// BaseURL, no matter what a server's Alt-Svc header claims.
func TestResolveAltSvcAuthority(t *testing.T) {
	if got := resolveAltSvcAuthority("127.0.0.1:8080", ":8443"); got != "127.0.0.1:8443" {
		t.Errorf("bare port: got %q, want 127.0.0.1:8443", got)
	}
	if got := resolveAltSvcAuthority("Original-Host.example.com:8080", "original-host.example.com:8443"); got != "original-host.example.com:8443" {
		t.Errorf("explicit same-host (case-insensitive): got %q, want original-host.example.com:8443", got)
	}
	if got := resolveAltSvcAuthority("127.0.0.1:8080", "attacker.evil.example:9999"); got != "" {
		t.Errorf("cross-host: got %q, want \"\" (advertisement must be ignored)", got)
	}
}

// TestLaneRouter_AltSvc_CrossHostAdvertisement_Ignored is the RED/GREEN
// regression test for the Alt-Svc authority-hijack vulnerability: a
// malicious or misconfigured H2 response advertising an h3 authority on a
// DIFFERENT host must never cause the router to promote LaneH3 toward that
// host. Before the fix, this test fails because promote() records the
// attacker's authority and reorders LaneH3 to the front, so the second
// request would be routed to h3RT (which fails the test via t.Fatalf).
func TestLaneRouter_AltSvc_CrossHostAdvertisement_Ignored(t *testing.T) {
	h2RT := roundTripperFunc(func(req *http.Request) (*http.Response, error) {
		resp := okResponse(req, "ok")
		resp.Header.Set("Alt-Svc", `h3="attacker.evil.example:9999"; ma=3600`)
		return resp, nil
	})
	h3RT := roundTripperFunc(func(req *http.Request) (*http.Response, error) {
		t.Fatal("h3 lane must never be dialed toward an attacker-controlled cross-host Alt-Svc authority")
		return nil, nil
	})

	r := newLaneRouter([]Lane{LaneH2}, map[Lane]http.RoundTripper{LaneH2: h2RT, LaneH3: h3RT}, true, zap.NewNop())

	req, err := http.NewRequest(http.MethodGet, "https://original-host.example.com/rpc", nil)
	if err != nil {
		t.Fatalf("NewRequest: %v", err)
	}
	if _, err := r.RoundTrip(req); err != nil {
		t.Fatalf("RoundTrip: %v", err)
	}

	r.mu.RLock()
	order := append([]Lane(nil), r.order...)
	authority := r.authority[LaneH3]
	r.mu.RUnlock()

	if authority == "attacker.evil.example:9999" {
		t.Fatalf("router recorded attacker-controlled authority for LaneH3: %q", authority)
	}
	if len(order) > 0 && order[0] == LaneH3 {
		t.Fatalf("router promoted LaneH3 from a cross-host Alt-Svc advertisement: order=%v", order)
	}

	// A second request must still target the original host; if the
	// (buggy) router promoted LaneH3, this call would dial h3RT and fail
	// the test via t.Fatal above.
	req2, err := http.NewRequest(http.MethodGet, "https://original-host.example.com/rpc", nil)
	if err != nil {
		t.Fatalf("NewRequest (2nd): %v", err)
	}
	if _, err := r.RoundTrip(req2); err != nil {
		t.Fatalf("RoundTrip (2nd): %v", err)
	}
}

// TestLaneRouter_AltSvc_SameHostBarePort_Promotes is the legitimate-case
// companion to the cross-host test above: a bare ":port" advertisement
// (same host, alternate UDP port) must still promote LaneH3.
func TestLaneRouter_AltSvc_SameHostBarePort_Promotes(t *testing.T) {
	h2RT := roundTripperFunc(func(req *http.Request) (*http.Response, error) {
		resp := okResponse(req, "ok")
		resp.Header.Set("Alt-Svc", `h3=":9443"; ma=3600`)
		return resp, nil
	})
	h3RT := roundTripperFunc(func(req *http.Request) (*http.Response, error) {
		if req.URL.Host != "original-host.example.com:9443" {
			t.Errorf("h3 request host = %q, want original-host.example.com:9443", req.URL.Host)
		}
		return okResponse(req, "ok"), nil
	})

	r := newLaneRouter([]Lane{LaneH2}, map[Lane]http.RoundTripper{LaneH2: h2RT, LaneH3: h3RT}, true, zap.NewNop())

	req, err := http.NewRequest(http.MethodGet, "https://original-host.example.com/rpc", nil)
	if err != nil {
		t.Fatalf("NewRequest: %v", err)
	}
	if _, err := r.RoundTrip(req); err != nil {
		t.Fatalf("RoundTrip: %v", err)
	}

	req2, err := http.NewRequest(http.MethodGet, "https://original-host.example.com/rpc", nil)
	if err != nil {
		t.Fatalf("NewRequest (2nd): %v", err)
	}
	resp, err := r.RoundTrip(req2)
	if err != nil {
		t.Fatalf("RoundTrip (2nd): %v", err)
	}
	if resp.StatusCode != http.StatusOK {
		t.Errorf("StatusCode = %d, want 200", resp.StatusCode)
	}
}

// TestLaneRouter_AltSvc_SameHostExplicitAuthority_Promotes is the
// legitimate-case companion covering an explicit "host:port" authority
// whose host matches the request host exactly — this must still promote
// LaneH3 (only a DIFFERENT host is rejected).
func TestLaneRouter_AltSvc_SameHostExplicitAuthority_Promotes(t *testing.T) {
	h2RT := roundTripperFunc(func(req *http.Request) (*http.Response, error) {
		resp := okResponse(req, "ok")
		resp.Header.Set("Alt-Svc", `h3="original-host.example.com:9443"; ma=3600`)
		return resp, nil
	})
	h3RT := roundTripperFunc(func(req *http.Request) (*http.Response, error) {
		if req.URL.Host != "original-host.example.com:9443" {
			t.Errorf("h3 request host = %q, want original-host.example.com:9443", req.URL.Host)
		}
		return okResponse(req, "ok"), nil
	})

	r := newLaneRouter([]Lane{LaneH2}, map[Lane]http.RoundTripper{LaneH2: h2RT, LaneH3: h3RT}, true, zap.NewNop())

	req, err := http.NewRequest(http.MethodGet, "https://original-host.example.com/rpc", nil)
	if err != nil {
		t.Fatalf("NewRequest: %v", err)
	}
	if _, err := r.RoundTrip(req); err != nil {
		t.Fatalf("RoundTrip: %v", err)
	}

	req2, err := http.NewRequest(http.MethodGet, "https://original-host.example.com/rpc", nil)
	if err != nil {
		t.Fatalf("NewRequest (2nd): %v", err)
	}
	resp, err := r.RoundTrip(req2)
	if err != nil {
		t.Fatalf("RoundTrip (2nd): %v", err)
	}
	if resp.StatusCode != http.StatusOK {
		t.Errorf("StatusCode = %d, want 200", resp.StatusCode)
	}
}

// TestLaneRouter_AltSvcUpgrade_Disabled_NoPromotion covers Fix 4: when
// altSvcUpgrade is false (Config.DisableAltSvcUpgrade: true), even a
// legitimate same-host Alt-Svc advertisement must not promote LaneH3.
func TestLaneRouter_AltSvcUpgrade_Disabled_NoPromotion(t *testing.T) {
	h2RT := roundTripperFunc(func(req *http.Request) (*http.Response, error) {
		resp := okResponse(req, "ok")
		resp.Header.Set("Alt-Svc", `h3=":9443"; ma=3600`)
		return resp, nil
	})
	h3RT := roundTripperFunc(func(req *http.Request) (*http.Response, error) {
		t.Fatal("h3 lane must not be dialed when Alt-Svc upgrade is disabled")
		return nil, nil
	})

	r := newLaneRouter([]Lane{LaneH2}, map[Lane]http.RoundTripper{LaneH2: h2RT, LaneH3: h3RT}, false, zap.NewNop())

	req, err := http.NewRequest(http.MethodGet, "https://original-host.example.com/rpc", nil)
	if err != nil {
		t.Fatalf("NewRequest: %v", err)
	}
	if _, err := r.RoundTrip(req); err != nil {
		t.Fatalf("RoundTrip: %v", err)
	}

	req2, err := http.NewRequest(http.MethodGet, "https://original-host.example.com/rpc", nil)
	if err != nil {
		t.Fatalf("NewRequest (2nd): %v", err)
	}
	if _, err := r.RoundTrip(req2); err != nil {
		t.Fatalf("RoundTrip (2nd): %v", err)
	}
}

// TestLaneRouter_ContextCanceled_NoFailoverNoCooldown is the RED/GREEN
// regression test for treating caller context cancellation as a lane
// failure: before the fix, a canceled-context RoundTrip error marks the
// lane failed and fails over to the next lane (h2Calls would be 1 and the
// call would return success with err == nil rather than
// context.Canceled). After the fix, the router must return the context
// error immediately without touching lane cooldown state or attempting
// another lane.
func TestLaneRouter_ContextCanceled_NoFailoverNoCooldown(t *testing.T) {
	var h3Calls, h2Calls int
	h3RT := roundTripperFunc(func(req *http.Request) (*http.Response, error) {
		h3Calls++
		return nil, req.Context().Err()
	})
	h2RT := roundTripperFunc(func(req *http.Request) (*http.Response, error) {
		h2Calls++
		return okResponse(req, "ok"), nil
	})

	r := newLaneRouter([]Lane{LaneH3, LaneH2}, map[Lane]http.RoundTripper{LaneH3: h3RT, LaneH2: h2RT}, false, zap.NewNop())

	ctx, cancel := context.WithCancel(context.Background())
	cancel()
	req, err := http.NewRequestWithContext(ctx, http.MethodGet, "https://example.test/rpc", nil)
	if err != nil {
		t.Fatalf("NewRequest: %v", err)
	}

	_, err = r.RoundTrip(req)
	if !errors.Is(err, context.Canceled) {
		t.Fatalf("err = %v, want context.Canceled", err)
	}
	if h3Calls != 1 {
		t.Errorf("h3Calls = %d, want 1", h3Calls)
	}
	if h2Calls != 0 {
		t.Errorf("h2Calls = %d, want 0 (must not fail over on context cancellation)", h2Calls)
	}
	if r.isCooling(LaneH3) {
		t.Error("LaneH3 must not be marked cooling after a context-cancellation error")
	}
}

// TestLaneRouter_RoundTrip_NeverReturnsNilNil is the RED/GREEN regression
// test for RoundTrip returning (nil, nil) when the attempt loop completes
// without ever finding a matching transport for any configured lane (e.g.
// an unrecognized lane string slipped past New()'s validation). connect/
// net/http dereferences the response whenever err == nil, so (nil, nil)
// is a guaranteed nil-pointer panic in the caller.
func TestLaneRouter_RoundTrip_NeverReturnsNilNil(t *testing.T) {
	noop := roundTripperFunc(func(req *http.Request) (*http.Response, error) {
		return okResponse(req, "ok"), nil
	})
	// order references a lane with no corresponding transport entry, so
	// every iteration of the attempt loop hits the `if !ok { continue }`
	// branch and lastErr is never set.
	r := newLaneRouter([]Lane{"h4"}, map[Lane]http.RoundTripper{LaneH2: noop}, false, zap.NewNop())

	req, err := http.NewRequest(http.MethodGet, "https://example.test/rpc", nil)
	if err != nil {
		t.Fatalf("NewRequest: %v", err)
	}
	resp, err := r.RoundTrip(req)
	if err == nil {
		t.Fatal("expected a non-nil error when no configured lane has a matching transport")
	}
	if resp != nil {
		t.Errorf("resp = %v, want nil", resp)
	}
}
