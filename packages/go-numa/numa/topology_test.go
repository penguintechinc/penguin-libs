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
	pool.Put(99, 0)
	v2 := pool.Get(0)
	if v2 != 99 {
		t.Fatalf("Get() after Put() = %d, want 99", v2)
	}
}
