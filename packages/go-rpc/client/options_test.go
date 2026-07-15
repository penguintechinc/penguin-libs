// Copyright 2026 Penguin Tech Inc
// SPDX-License-Identifier: Apache-2.0

package client

import (
	"testing"
	"time"
)

func TestDefaultClientConfig(t *testing.T) {
	cfg := DefaultClientConfig()

	if len(cfg.Lanes) != 2 || cfg.Lanes[0] != LaneH3 || cfg.Lanes[1] != LaneH2 {
		t.Errorf("Lanes = %v, want [h3 h2]", cfg.Lanes)
	}
	if cfg.DialTimeout != 5*time.Second {
		t.Errorf("DialTimeout = %v, want 5s", cfg.DialTimeout)
	}
	if cfg.IdleTimeout != 90*time.Second {
		t.Errorf("IdleTimeout = %v, want 90s", cfg.IdleTimeout)
	}
	if !cfg.AltSvcUpgrade {
		t.Error("AltSvcUpgrade = false, want true")
	}
	if cfg.TLSConfig != nil {
		t.Error("TLSConfig should be left nil by DefaultClientConfig (system trust store default)")
	}
	if cfg.BaseURL != "" {
		t.Error("BaseURL should be left empty by DefaultClientConfig")
	}
}
