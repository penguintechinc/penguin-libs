// Copyright 2026 Penguin Tech Inc
// SPDX-License-Identifier: Apache-2.0

package gorpc

import "testing"

func TestVersion(t *testing.T) {
	if Version != "0.1.0" {
		t.Fatalf("Version = %q, want 0.1.0", Version)
	}
}
