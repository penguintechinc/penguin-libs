//go:build linux

package numa

import (
	"sync"
)

// Pool is a NUMA-topology-aware object pool. Each NUMA node has its own
// backing sync.Pool to reduce cross-node memory traffic.
type Pool[T any] struct {
	pools []*sync.Pool
}

// NewPool creates a per-NUMA-node pool.
// alloc is called to construct a new object when none is available in the pool.
func NewPool[T any](alloc func() T) (*Pool[T], error) {
	topo, err := Get()
	if err != nil {
		return nil, err
	}
	n := len(topo.Nodes)
	if n == 0 {
		n = 1
	}
	pools := make([]*sync.Pool, n)
	for i := range pools {
		f := alloc
		pools[i] = &sync.Pool{New: func() any { v := f(); return &v }}
	}
	return &Pool[T]{pools: pools}, nil
}

// Get retrieves an object from the pool for the given NUMA node index.
// nodeIdx should be obtained from Topology.Nodes[i].ID. If out of range, node 0 is used.
func (p *Pool[T]) Get(nodeIdx int) T {
	idx := p.clamp(nodeIdx)
	v := p.pools[idx].Get().(*T)
	return *v
}

// Put returns an object to the pool for the given NUMA node index.
func (p *Pool[T]) Put(v T, nodeIdx int) {
	idx := p.clamp(nodeIdx)
	p.pools[idx].Put(&v)
}

func (p *Pool[T]) clamp(idx int) int {
	if idx < 0 || idx >= len(p.pools) {
		return 0
	}
	return idx
}
