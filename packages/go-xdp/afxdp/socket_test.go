//go:build linux

package afxdp_test

import (
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
