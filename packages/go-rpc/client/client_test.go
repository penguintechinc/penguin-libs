// Copyright 2026 Penguin Tech Inc
// SPDX-License-Identifier: Apache-2.0

package client

import (
	"crypto/tls"
	"errors"
	"testing"
	"time"

	"go.uber.org/zap"
)

func TestNew_NilLogger(t *testing.T) {
	c, err := New(Config{}, nil)
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if c == nil {
		t.Fatal("expected non-nil client")
	}
	if c.logger == nil {
		t.Error("expected a default logger to be created")
	}
}

func TestNew_RejectsLaneZiti(t *testing.T) {
	_, err := New(Config{Lanes: []Lane{LaneH2, LaneZiti}}, zap.NewNop())
	if !errors.Is(err, ErrLaneUnavailable) {
		t.Fatalf("err = %v, want ErrLaneUnavailable", err)
	}
}

// TestNew_RejectsUnknownLane is the RED/GREEN regression test for Fix 3:
// before the fix, an unrecognized lane string silently passed New()'s
// validation (only LaneZiti was checked) and any request would eventually
// hit laneRouter.RoundTrip's no-matching-transport path, which used to
// return (nil, nil) -- a guaranteed nil-pointer panic for any caller that
// checks err before touching resp (the standard net/http contract).
func TestNew_RejectsUnknownLane(t *testing.T) {
	_, err := New(Config{Lanes: []Lane{"h4"}}, zap.NewNop())
	if err == nil {
		t.Fatal("expected an error for an unrecognized lane, got nil")
	}
}

func TestNew_DefaultsEmptyLanesToH3ThenH2(t *testing.T) {
	c, err := New(Config{}, zap.NewNop())
	if err != nil {
		t.Fatalf("New: %v", err)
	}
	if c.Protocol() != "h3" {
		t.Errorf("Protocol() = %q, want h3 (default lane order [h3 h2], nothing cooling)", c.Protocol())
	}
}

func TestNew_DefaultsDialAndIdleTimeouts(t *testing.T) {
	c, err := New(Config{}, zap.NewNop())
	if err != nil {
		t.Fatalf("New: %v", err)
	}
	if c.cfg.DialTimeout != defaultDialTimeout {
		t.Errorf("DialTimeout = %v, want %v", c.cfg.DialTimeout, defaultDialTimeout)
	}
	if c.cfg.IdleTimeout != defaultIdleTimeout {
		t.Errorf("IdleTimeout = %v, want %v", c.cfg.IdleTimeout, defaultIdleTimeout)
	}
}

func TestNew_PreservesExplicitLanesOrder(t *testing.T) {
	c, err := New(Config{Lanes: []Lane{LaneH2}}, zap.NewNop())
	if err != nil {
		t.Fatalf("New: %v", err)
	}
	if c.Protocol() != "h2" {
		t.Errorf("Protocol() = %q, want h2 (explicit Lanes: [h2] must not be overridden)", c.Protocol())
	}
}

// TestNew_ForcesTLS13MinVersion mirrors server.New()'s hardening test:
// a caller-supplied TLS12 MinVersion must be forced to TLS13 in place on
// the same pointer, regardless of the value New() was given.
func TestNew_ForcesTLS13MinVersion(t *testing.T) {
	tlsCfg := &tls.Config{MinVersion: tls.VersionTLS12}

	if _, err := New(Config{TLSConfig: tlsCfg}, zap.NewNop()); err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if tlsCfg.MinVersion != tls.VersionTLS13 {
		t.Fatalf("MinVersion = %d, want tls.VersionTLS13 (New must force it)", tlsCfg.MinVersion)
	}
}

func TestNew_NilTLSConfig_DefaultsToTLS13(t *testing.T) {
	c, err := New(Config{}, zap.NewNop())
	if err != nil {
		t.Fatalf("New: %v", err)
	}
	if c.cfg.TLSConfig == nil {
		t.Fatal("expected New to construct a TLSConfig when none was supplied")
	}
	if c.cfg.TLSConfig.MinVersion != tls.VersionTLS13 {
		t.Errorf("MinVersion = %d, want tls.VersionTLS13", c.cfg.TLSConfig.MinVersion)
	}
}

// TestNew_AltSvcUpgrade_EnabledByDefault covers Fix 4: Config{}'s zero
// value for DisableAltSvcUpgrade (false) must propagate as an ENABLED
// Alt-Svc upgrade in the router, matching DefaultClientConfig()'s documented
// "default true" behavior.
func TestNew_AltSvcUpgrade_EnabledByDefault(t *testing.T) {
	c, err := New(Config{}, zap.NewNop())
	if err != nil {
		t.Fatalf("New: %v", err)
	}
	if !c.router.altSvcUpgrade {
		t.Error("router.altSvcUpgrade = false, want true (DisableAltSvcUpgrade zero value is false = enabled)")
	}
}

// TestNew_DisableAltSvcUpgrade_PropagatesToRouter covers Fix 4: explicitly
// setting DisableAltSvcUpgrade: true must disable the router's Alt-Svc
// upgrade behavior.
func TestNew_DisableAltSvcUpgrade_PropagatesToRouter(t *testing.T) {
	c, err := New(Config{DisableAltSvcUpgrade: true}, zap.NewNop())
	if err != nil {
		t.Fatalf("New: %v", err)
	}
	if c.router.altSvcUpgrade {
		t.Error("router.altSvcUpgrade = true, want false when Config.DisableAltSvcUpgrade is true")
	}
}

// TestClient_MarkLaneFailed_CooldownThenMaybeRetryLane is a fast, network-free
// exercise of the cooldown state machine backing MarkLaneFailed/
// MaybeRetryLane: mark H3 failed -> Protocol() prefers h2 immediately;
// MaybeRetryLane too soon -> still h2; after laneCooldown elapses ->
// MaybeRetryLane restores h3 as preferred.
func TestClient_MarkLaneFailed_CooldownThenMaybeRetryLane(t *testing.T) {
	orig := laneCooldown
	laneCooldown = 20 * time.Millisecond
	defer func() { laneCooldown = orig }()

	c, err := New(Config{Lanes: []Lane{LaneH3, LaneH2}}, zap.NewNop())
	if err != nil {
		t.Fatalf("New: %v", err)
	}

	if c.Protocol() != "h3" {
		t.Fatalf("Protocol() = %q, want h3 before any failure", c.Protocol())
	}

	c.MarkLaneFailed(LaneH3)
	if c.Protocol() != "h2" {
		t.Fatalf("Protocol() = %q, want h2 immediately after MarkLaneFailed(LaneH3)", c.Protocol())
	}

	c.MaybeRetryLane(LaneH3) // too soon: laneCooldown has not elapsed yet
	if c.Protocol() != "h2" {
		t.Fatalf("Protocol() = %q, want h2 (too soon to retry)", c.Protocol())
	}

	time.Sleep(30 * time.Millisecond)
	c.MaybeRetryLane(LaneH3)
	if c.Protocol() != "h3" {
		t.Fatalf("Protocol() = %q, want h3 after cooldown elapsed and MaybeRetryLane", c.Protocol())
	}
}
