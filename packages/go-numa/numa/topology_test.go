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

// TestPoolGetPut verifies Pool's actual guarantees, not sync.Pool retention.
// sync.Pool never promises a Put value survives to the next Get -- the GC
// may drop pooled items at any time -- so this test does not assert that a
// value round-trips through Put/Get. Instead it asserts what Pool does
// guarantee: Get always returns a usable, correctly-initialized value
// (falling back to alloc/New when the pool is empty), Put never corrupts
// the pool, and out-of-range node indices clamp instead of panicking.
func TestPoolGetPut(t *testing.T) {
	var allocs int
	pool, err := numa.NewPool(func() int {
		allocs++
		return 42
	})
	if err != nil {
		t.Fatalf("NewPool: %v", err)
	}

	// An empty pool must fall back to alloc() and return its value.
	v := pool.Get(0)
	if v != 42 {
		t.Fatalf("Get() on empty pool = %d, want 42 (from alloc)", v)
	}
	if allocs == 0 {
		t.Fatal("Get() on empty pool did not invoke alloc/New")
	}

	// Put() must not panic or corrupt the pool. Because sync.Pool gives no
	// retention guarantee, the next Get() may return either the just-Put
	// value or a freshly alloc'd one -- both are correct; only a value
	// produced by neither path indicates a bug.
	pool.Put(99, 0)
	v2 := pool.Get(0)
	if v2 != 99 && v2 != 42 {
		t.Fatalf("Get() after Put() = %d, want 99 (retained) or 42 (alloc'd)", v2)
	}

	// Out-of-range node indices must clamp to node 0 rather than panic,
	// and still return a value produced by alloc or a prior Put.
	v3 := pool.Get(-1)
	if v3 != 99 && v3 != 42 {
		t.Fatalf("Get(-1) = %d, want a value produced by alloc or a prior Put", v3)
	}
}
