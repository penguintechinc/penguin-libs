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

// TestPoolGetFallsBackToAllocator checks the one retention guarantee Pool
// actually makes: a pool with nothing cached must produce a value from the
// allocator.
func TestPoolGetFallsBackToAllocator(t *testing.T) {
	pool, err := numa.NewPool(func() int { return 42 })
	if err != nil {
		t.Fatalf("NewPool: %v", err)
	}
	if v := pool.Get(0); v != 42 {
		t.Fatalf("Get() on empty pool = %d, want allocator value 42", v)
	}
}

// TestPoolGetAfterPutReturnsLegalValue checks that Get never invents a value.
//
// Pool is backed by sync.Pool, which is explicitly permitted to discard cached
// entries at any time -- at GC, or when a Get is served by a different P than
// the one the Put landed on. Reuse is therefore best-effort, and asserting that
// Get always returns the value just Put is a flaky assertion, not a contract.
// What IS guaranteed is that Get yields either the cached value or a fresh one.
func TestPoolGetAfterPutReturnsLegalValue(t *testing.T) {
	pool, err := numa.NewPool(func() int { return 42 })
	if err != nil {
		t.Fatalf("NewPool: %v", err)
	}
	pool.Put(99, 0)
	switch v := pool.Get(0); v {
	case 99, 42:
	default:
		t.Fatalf("Get() after Put() = %d, want 99 (reused) or 42 (fresh)", v)
	}
}

// TestPoolPutIsNotANoOp guards the weakness of the test above: allowing the
// allocator value keeps it from being flaky, but on its own it would also pass
// if Put silently discarded everything. Reuse is unreliable per-attempt yet
// overwhelmingly likely across many, so observing it even once proves Put wires
// values back into the pool.
func TestPoolPutIsNotANoOp(t *testing.T) {
	pool, err := numa.NewPool(func() int { return 42 })
	if err != nil {
		t.Fatalf("NewPool: %v", err)
	}
	for i := 0; i < 1000; i++ {
		pool.Put(99, 0)
		if pool.Get(0) == 99 {
			return
		}
	}
	t.Fatal("Put() never made a value available to Get() in 1000 attempts; Put appears to be a no-op")
}
