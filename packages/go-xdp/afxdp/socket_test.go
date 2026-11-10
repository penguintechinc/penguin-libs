//go:build linux

package afxdp_test

import (
	"errors"
	"testing"

	"github.com/penguintechinc/penguin-libs/packages/go-xdp/afxdp"
)

func TestNewRingPowerOfTwo(t *testing.T) {
	for _, size := range []uint32{64, 128, 256, 512, 1024} {
		r, err := afxdp.NewRing(size)
		if err != nil {
			t.Fatalf("NewRing(%d): %v", size, err)
		}
		if r.Len() != 0 {
			t.Fatalf("new ring should be empty")
		}
	}
}

func TestNewRingNonPowerOfTwoFails(t *testing.T) {
	for _, size := range []uint32{0, 3, 100, 300} {
		_, err := afxdp.NewRing(size)
		if err == nil {
			t.Fatalf("NewRing(%d): expected error for non-power-of-2 size", size)
		}
	}
}

func TestRingEnqueueDequeue(t *testing.T) {
	r, _ := afxdp.NewRing(4)
	if !r.Enqueue(0xDEAD) {
		t.Fatal("Enqueue failed on empty ring")
	}
	addr, ok := r.Dequeue()
	if !ok || addr != 0xDEAD {
		t.Fatalf("Dequeue got (%x, %v), want (0xDEAD, true)", addr, ok)
	}
}

func TestRingFull(t *testing.T) {
	r, _ := afxdp.NewRing(2)
	r.Enqueue(1)
	r.Enqueue(2)
	if r.Enqueue(3) {
		t.Fatal("Enqueue should fail on full ring")
	}
}

func TestUMEMAlignmentCheck(t *testing.T) {
	_, err := afxdp.NewUMEM(afxdp.UMEMOptions{
		Size:      4097, // Not a multiple of 4096
		FrameSize: 4096,
	})
	if err == nil {
		t.Fatal("expected alignment error")
	}
}

// TestUMEMSizeBounds verifies NewUMEM rejects zero and oversized regions
// before any syscall or allocation happens (SEC-GO-10).
func TestUMEMSizeBounds(t *testing.T) {
	cases := []struct {
		name string
		opts afxdp.UMEMOptions
	}{
		{"zero size", afxdp.UMEMOptions{Size: 0, FrameSize: 4096}},
		{"zero size default frame", afxdp.UMEMOptions{Size: 0}},
		{"above max", afxdp.UMEMOptions{Size: afxdp.MaxUMEMSize + 4096, FrameSize: 4096}},
		{"max uint64 aligned", afxdp.UMEMOptions{Size: ^uint64(0) &^ 4095, FrameSize: 4096}},
		{"frame larger than size", afxdp.UMEMOptions{Size: 4096, FrameSize: 8192}},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			u, err := afxdp.NewUMEM(tc.opts)
			if u != nil {
				_ = u.Close()
			}
			if !errors.Is(err, afxdp.ErrUMEMSize) {
				t.Fatalf("NewUMEM(%+v) err = %v, want ErrUMEMSize", tc.opts, err)
			}
		})
	}
}

// TestUMEMCloseEmpty verifies Close on an empty or nil UMEM does not panic.
func TestUMEMCloseEmpty(t *testing.T) {
	var nilU *afxdp.UMEM
	if err := nilU.Close(); err != nil {
		t.Fatalf("nil Close: %v", err)
	}
}
