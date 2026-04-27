//go:build linux

package afxdp

import (
	"fmt"
	"sync/atomic"
)

// Ring is a lock-free single-producer/single-consumer ring buffer used for
// XDP fill/completion/RX/TX queues.
type Ring struct {
	producer *atomic.Uint32
	consumer *atomic.Uint32
	size     uint32
	mask     uint32
	descs    []uint64
}

// NewRing creates a ring buffer of the given power-of-2 size.
func NewRing(size uint32) (*Ring, error) {
	if size == 0 || (size&(size-1)) != 0 {
		return nil, fmt.Errorf("ring size must be a power of 2, got %d", size)
	}
	return &Ring{
		producer: &atomic.Uint32{},
		consumer: &atomic.Uint32{},
		size:     size,
		mask:     size - 1,
		descs:    make([]uint64, size),
	}, nil
}

// Enqueue adds an address descriptor to the ring. Returns false if the ring is full.
func (r *Ring) Enqueue(addr uint64) bool {
	prod := r.producer.Load()
	cons := r.consumer.Load()
	if prod-cons >= r.size {
		return false
	}
	r.descs[prod&r.mask] = addr
	r.producer.Add(1)
	return true
}

// Dequeue removes and returns an address descriptor. Returns (0, false) if empty.
func (r *Ring) Dequeue() (uint64, bool) {
	prod := r.producer.Load()
	cons := r.consumer.Load()
	if cons == prod {
		return 0, false
	}
	addr := r.descs[cons&r.mask]
	r.consumer.Add(1)
	return addr, true
}

// Len returns the number of pending descriptors.
func (r *Ring) Len() uint32 {
	return r.producer.Load() - r.consumer.Load()
}
