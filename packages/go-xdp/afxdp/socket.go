//go:build linux

package afxdp

import (
	"errors"
	"fmt"
	"math"
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

// MaxUMEMSize is the largest UMEM region NewUMEM accepts (16 GiB). It bounds
// the mmap request so a bad size cannot exhaust memory or overflow int.
const MaxUMEMSize uint64 = 1 << 34

// ErrUMEMSize is returned when UMEM size is zero, above MaxUMEMSize, not
// representable as an int, or smaller than a single frame.
var ErrUMEMSize = errors.New("UMEM size out of range")

// validateUMEMOptions applies defaults and rejects unsafe sizes before any
// syscall or allocation, returning the normalized options and the mmap length.
func validateUMEMOptions(opts UMEMOptions) (UMEMOptions, int, error) {
	if opts.FrameSize == 0 {
		opts.FrameSize = defaultFrameSize
	}
	if opts.Size == 0 || opts.Size > MaxUMEMSize || opts.Size > uint64(math.MaxInt) {
		return opts, 0, ErrUMEMSize
	}
	if opts.Size < uint64(opts.FrameSize) {
		return opts, 0, ErrUMEMSize
	}
	if opts.Size%uint64(opts.FrameSize) != 0 {
		return opts, 0, ErrUMEMAlignment
	}
	return opts, int(opts.Size), nil
}

// NewUMEM allocates and registers a UMEM region with the kernel.
//
// The caller must call Close when done to release kernel resources.
func NewUMEM(opts UMEMOptions) (*UMEM, error) {
	opts, size, err := validateUMEMOptions(opts)
	if err != nil {
		return nil, err
	}

	logger, err := gl.NewSanitizedLogger("go-xdp/afxdp")
	if err != nil {
		return nil, fmt.Errorf("create logger: %w", err)
	}

	// Create AF_XDP socket
	fd, err := unix.Socket(unix.AF_XDP, unix.SOCK_RAW, 0)
	if err != nil {
		return nil, fmt.Errorf("create AF_XDP socket: %w", err)
	}

	// Allocate page-aligned memory (try huge pages first, fall back to standard)
	mem, err := unix.Mmap(
		-1, 0, size,
		unix.PROT_READ|unix.PROT_WRITE,
		unix.MAP_PRIVATE|unix.MAP_ANONYMOUS|unix.MAP_HUGETLB,
	)
	if err != nil {
		// Fall back to standard pages if huge pages unavailable
		mem, err = unix.Mmap(
			-1, 0, size,
			unix.PROT_READ|unix.PROT_WRITE,
			unix.MAP_PRIVATE|unix.MAP_ANONYMOUS,
		)
		if err != nil {
			_ = unix.Close(fd)
			return nil, fmt.Errorf("mmap UMEM region: %w", err)
		}
	}

	if len(mem) == 0 {
		_ = unix.Close(fd)
		return nil, fmt.Errorf("mmap UMEM region: %w", ErrUMEMSize)
	}

	// Register UMEM with kernel
	reg := unix.XDPUmemReg{
		Addr:     uint64(uintptr(unsafe.Pointer(&mem[0]))), // #nosec G103 -- mem is a non-empty mmap region, required by XDP_UMEM_REG //nolint:gosec
		Len:      opts.Size,
		Size:     opts.FrameSize,
		Headroom: opts.HeadRoom,
	}
	_, _, errno := unix.Syscall6(
		unix.SYS_SETSOCKOPT,
		uintptr(fd),
		uintptr(unix.SOL_XDP),
		uintptr(unix.XDP_UMEM_REG),
		uintptr(unsafe.Pointer(&reg)), // #nosec G103 -- reg lives on this frame for the syscall duration //nolint:gosec
		unsafe.Sizeof(reg),
		0,
	)
	if errno != 0 {
		_ = unix.Munmap(mem)
		_ = unix.Close(fd)
		return nil, fmt.Errorf("register UMEM: %w", errno)
	}

	logger.Info("umem_registered",
		zap.Uint64("size_bytes", opts.Size),
		zap.Uint32("frame_size", opts.FrameSize),
	)

	return &UMEM{mem: mem, fd: fd, logger: logger}, nil
}

// Close releases the UMEM region and closes the AF_XDP socket.
func (u *UMEM) Close() error {
	if u == nil {
		return nil
	}
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
