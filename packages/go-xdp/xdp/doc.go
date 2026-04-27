// Package xdp provides utilities for loading and managing XDP (eXpress Data Path)
// BPF programs for high-performance packet processing.
//
// Build with -tags xdp to include XDP support. Without this tag, stub implementations
// are compiled that return ErrXDPNotSupported.
package xdp
