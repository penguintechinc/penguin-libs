//go:build linux

package numa_test

import (
	"testing"

	"github.com/penguintechinc/penguin-libs/packages/go-numa/numa"
)

func TestGetTopologyNoError(t *testing.T) {
	topo, err := numa.Get()
	if err != nil {
		t.Fatalf("Get() error: %v", err)
	}
	if len(topo.Nodes) == 0 {
		t.Fatal("topology must have at least one node")
	}
	for _, node := range topo.Nodes {
		if len(node.CPUs) == 0 {
			t.Errorf("node %d has no CPUs", node.ID)
		}
	}
}

func TestPoolGetPut(t *testing.T) {
	pool, err := numa.NewPool(func() int { return 42 })
	if err != nil {
		t.Fatalf("NewPool: %v", err)
	}
	v := pool.Get(0)
	if v != 42 {
		t.Fatalf("Get() = %d, want 42", v)
	}
	// sync.Pool gives no guarantee that a value handed to Put is the value
	// a subsequent Get returns — the runtime may drop pooled items at any
	// time (notably under GC pressure, which -race amplifies), reclaiming
	// them via a fresh call to the pool's alloc func instead. Assert only
	// the documented contract: every Get() yields a value the pool is
	// allowed to produce, either the freshly allocated 42 or the recycled
	// 99, never anything else (e.g. a zero value from a bad pointer cast).
	pool.Put(99, 0)
	v2 := pool.Get(0)
	if v2 != 42 && v2 != 99 {
		t.Fatalf("Get() after Put() = %d, want 42 or 99", v2)
	}
}
