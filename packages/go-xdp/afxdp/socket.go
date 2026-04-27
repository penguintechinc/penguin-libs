//go:build linux

package afxdp

import (
	"errors"
	"fmt"
	"unsafe"

	gl "github.com/penguintechinc/penguin-libs/packages/go-logging/logging"
	"go.uber.org/zap"
	"golang.org/x/sys/unix"
)

// UMEM represents a user-space memory region registered with the kernel for
// zero-copy packet I/O via AF_XDP sockets.
type UMEM struct {
	mem    []byte
	fd     int
	logger *gl.SanitizedLogger
}

// UMEMOptions configures UMEM registration.
type UMEMOptions struct {
	// Size is the total memory region size in bytes (must be multiple of FrameSize).
	Size uint64
	// FrameSize is the size of each packet frame (default 4096).
	FrameSize uint32
	// HeadRoom is extra space reserved at the start of each frame header (default 0).
	HeadRoom uint32
}

const defaultFrameSize = 4096

// ErrUMEMAlignment is returned when UMEM size is not a multiple of FrameSize.
var ErrUMEMAlignment = errors.New("UMEM size must be a multiple of FrameSize")

// NewUMEM allocates and registers a UMEM region with the kernel.
//
// The caller must call Close when done to release kernel resources.
func NewUMEM(opts UMEMOptions) (*UMEM, error) {
	logger, err := gl.NewSanitizedLogger("go-xdp/afxdp")
	if err != nil {
		return nil, fmt.Errorf("create logger: %w", err)
	}

	if opts.FrameSize == 0 {
		opts.FrameSize = defaultFrameSize
	}
	if opts.Size%uint64(opts.FrameSize) != 0 {
		return nil, ErrUMEMAlignment
	}

	// Create AF_XDP socket
	fd, err := unix.Socket(unix.AF_XDP, unix.SOCK_RAW, 0)
	if err != nil {
		return nil, fmt.Errorf("create AF_XDP socket: %w", err)
	}

	// Allocate page-aligned memory (try huge pages first, fall back to standard)
	mem, err := unix.Mmap(
		-1, 0, int(opts.Size),
		unix.PROT_READ|unix.PROT_WRITE,
		unix.MAP_PRIVATE|unix.MAP_ANONYMOUS|unix.MAP_HUGETLB,
	)
	if err != nil {
		// Fall back to standard pages if huge pages unavailable
		mem, err = unix.Mmap(
			-1, 0, int(opts.Size),
			unix.PROT_READ|unix.PROT_WRITE,
			unix.MAP_PRIVATE|unix.MAP_ANONYMOUS,
		)
		if err != nil {
			unix.Close(fd)
			return nil, fmt.Errorf("mmap UMEM region: %w", err)
		}
	}

	// Register UMEM with kernel
	reg := unix.XDPUmemReg{
		Addr:      uint64(uintptr(unsafe.Pointer(&mem[0]))),
		Len:       opts.Size,
		Size:      opts.FrameSize,
		Headroom:  opts.HeadRoom,
	}
	if err := unix.SetsockoptXDPUmemReg(fd, unix.SOL_XDP, unix.XDP_UMEM_REG, &reg); err != nil {
		unix.Munmap(mem)
		unix.Close(fd)
		return nil, fmt.Errorf("register UMEM: %w", err)
	}

	logger.Info("umem_registered",
		zap.Uint64("size_bytes", opts.Size),
		zap.Uint32("frame_size", opts.FrameSize),
	)

	return &UMEM{mem: mem, fd: fd, logger: logger}, nil
}

// Close releases the UMEM region and closes the AF_XDP socket.
func (u *UMEM) Close() error {
	if err := unix.Munmap(u.mem); err != nil {
		return fmt.Errorf("munmap UMEM: %w", err)
	}
	if err := unix.Close(u.fd); err != nil {
		return fmt.Errorf("close AF_XDP socket: %w", err)
	}
	u.logger.Info("umem_released")
	return u.logger.Sync()
}

// Fd returns the AF_XDP socket file descriptor.
func (u *UMEM) Fd() int { return u.fd }

// Mem returns the raw memory slice backing the UMEM region.
func (u *UMEM) Mem() []byte { return u.mem }
