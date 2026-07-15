// Copyright 2026 Penguin Tech Inc
// SPDX-License-Identifier: Apache-2.0

package client

import (
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

func TestResolveAltSvcAuthority(t *testing.T) {
	if got := resolveAltSvcAuthority("127.0.0.1:8080", ":8443"); got != "127.0.0.1:8443" {
		t.Errorf("got %q, want 127.0.0.1:8443", got)
	}
	if got := resolveAltSvcAuthority("127.0.0.1:8080", "alt.example.com:8443"); got != "alt.example.com:8443" {
		t.Errorf("got %q, want alt.example.com:8443", got)
	}
}
