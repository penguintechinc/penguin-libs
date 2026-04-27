// Package numa provides NUMA (Non-Uniform Memory Access) topology discovery
// and NUMA-aware object pooling for high-performance Go applications.
//
// This package is Linux-only. On other platforms, compile with //go:build !linux
// stubs that return ErrNotSupported.
package numa
