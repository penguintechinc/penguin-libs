//go:build linux

package buffer

import (
	"fmt"

	"golang.org/x/sys/unix"
)

// Aligned allocates a page-aligned byte buffer of the given size using mmap.
// The buffer is suitable for use as a UMEM region or DMA buffer.
//
// The caller must call Free when done to release the memory.
func Aligned(size int) ([]byte, error) {
	if size <= 0 {
		return nil, fmt.Errorf("buffer size must be positive, got %d", size)
	}
	buf, err := unix.Mmap(
		-1, 0, size,
		unix.PROT_READ|unix.PROT_WRITE,
		unix.MAP_PRIVATE|unix.MAP_ANONYMOUS,
	)
	if err != nil {
		return nil, fmt.Errorf("mmap aligned buffer (%d bytes): %w", size, err)
	}
	return buf, nil
}

// Free releases a buffer previously allocated by Aligned.
func Free(buf []byte) error {
	if err := unix.Munmap(buf); err != nil {
		return fmt.Errorf("munmap buffer: %w", err)
	}
	return nil
}
