//go:build linux

package xdp

import (
	"errors"
	"fmt"
	"net"

	"github.com/cilium/ebpf"
	"github.com/cilium/ebpf/link"
	gl "github.com/penguintechinc/penguin-libs/packages/go-logging/logging"
	"go.uber.org/zap"
)

// ErrXDPNotSupported is returned when XDP is not available on this platform.
var ErrXDPNotSupported = errors.New("XDP not supported on this platform")

// Program manages an XDP BPF program lifecycle.
type Program struct {
	iface  *net.Interface
	prog   *ebpf.Program
	link   link.Link
	logger *gl.SanitizedLogger
}

// ProgramOptions configures XDP program loading.
type ProgramOptions struct {
	// Interface is the network interface to attach to.
	Interface string
	// ProgramPath is the path to the compiled BPF object file.
	ProgramPath string
	// SectionName is the ELF section containing the XDP program (default: "xdp").
	SectionName string
	// Flags controls XDP attachment mode (generic/native/offload).
	Flags link.XDPAttachFlags
}

// Load loads an XDP BPF program from a compiled object file.
func Load(opts ProgramOptions) (*Program, error) {
	logger, err := gl.NewSanitizedLogger("go-xdp")
	if err != nil {
		return nil, fmt.Errorf("create logger: %w", err)
	}

	if opts.SectionName == "" {
		opts.SectionName = "xdp"
	}

	iface, err := net.InterfaceByName(opts.Interface)
	if err != nil {
		return nil, fmt.Errorf("interface %q not found: %w", opts.Interface, err)
	}

	spec, err := ebpf.LoadCollectionSpec(opts.ProgramPath)
	if err != nil {
		return nil, fmt.Errorf("load BPF spec: %w", err)
	}

	coll, err := ebpf.NewCollection(spec)
	if err != nil {
		return nil, fmt.Errorf("create BPF collection: %w", err)
	}

	prog, ok := coll.Programs[opts.SectionName]
	if !ok {
		coll.Close()
		return nil, fmt.Errorf("section %q not found in BPF object", opts.SectionName)
	}

	l, err := link.AttachXDP(link.XDPOptions{
		Program:   prog,
		Interface: iface.Index,
		Flags:     opts.Flags,
	})
	if err != nil {
		coll.Close()
		return nil, fmt.Errorf("attach XDP to %q: %w", opts.Interface, err)
	}

	logger.Info("xdp_program_loaded",
		zap.String("interface", opts.Interface),
		zap.String("section", opts.SectionName),
	)

	return &Program{
		iface:  iface,
		prog:   prog,
		link:   l,
		logger: logger,
	}, nil
}

// Close detaches and unloads the XDP program.
func (p *Program) Close() error {
	if err := p.link.Close(); err != nil {
		return fmt.Errorf("detach XDP: %w", err)
	}
	p.prog.Close()
	p.logger.Info("xdp_program_unloaded", zap.String("interface", p.iface.Name))
	return p.logger.Sync()
}

// Interface returns the network interface the program is attached to.
func (p *Program) Interface() *net.Interface { return p.iface }
