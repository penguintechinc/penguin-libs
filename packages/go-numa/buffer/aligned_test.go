//go:build linux

package buffer_test

import (
	"testing"

	"github.com/penguintechinc/penguin-libs/packages/go-numa/buffer"
)

func TestAligned(t *testing.T) {
	buf, err := buffer.Aligned(4096)
	if err != nil {
		t.Fatalf("Aligned: %v", err)
	}
	if len(buf) != 4096 {
		t.Fatalf("len = %d, want 4096", len(buf))
	}
	if err := buffer.Free(buf); err != nil {
		t.Fatalf("Free: %v", err)
	}
}

func TestAlignedZeroSizeFails(t *testing.T) {
	_, err := buffer.Aligned(0)
	if err == nil {
		t.Fatal("expected error for zero size")
	}
}

func TestAlignedLargeBuffer(t *testing.T) {
	size := 1024 * 1024 // 1MB
	buf, err := buffer.Aligned(size)
	if err != nil {
		t.Fatalf("Aligned(%d): %v", size, err)
	}
	defer buffer.Free(buf)
	// Write to verify it's usable
	buf[0] = 0xAB
	buf[size-1] = 0xCD
	if buf[0] != 0xAB || buf[size-1] != 0xCD {
		t.Fatal("buffer not writable")
	}
}
