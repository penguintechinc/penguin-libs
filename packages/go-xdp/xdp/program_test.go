//go:build linux

package xdp_test

import (
	"testing"

	"github.com/penguintechinc/penguin-libs/packages/go-xdp/xdp"
)

func TestProgramOptionsDefaults(t *testing.T) {
	opts := xdp.ProgramOptions{
		Interface:   "lo",
		ProgramPath: "/nonexistent.o",
	}
	// Should fail on load (file not found) — validates struct is usable
	_, err := xdp.Load(opts)
	if err == nil {
		t.Fatal("expected error loading nonexistent BPF file")
	}
}

func TestErrXDPNotSupported(t *testing.T) {
	if xdp.ErrXDPNotSupported == nil {
		t.Fatal("ErrXDPNotSupported must not be nil")
	}
}
