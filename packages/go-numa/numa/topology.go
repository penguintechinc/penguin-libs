//go:build linux

package numa

import (
	"fmt"
	"os"
	"path/filepath"
	"strconv"
	"strings"
	"sync"

	gl "github.com/penguintechinc/penguin-libs/packages/go-logging/logging"
	"go.uber.org/zap"
	"golang.org/x/sys/unix"
)

const sysFsNumaNodes = "/sys/devices/system/node"

var (
	once     sync.Once
	topology *Topology
	topoErr  error
)

// Node represents a single NUMA node.
type Node struct {
	ID   int
	CPUs []int
}

// Topology describes the NUMA layout of the system.
type Topology struct {
	Nodes []Node
}

// Get returns the system NUMA topology, cached after the first call.
func Get() (*Topology, error) {
	once.Do(func() {
		topology, topoErr = discover()
	})
	return topology, topoErr
}

func discover() (*Topology, error) {
	logger, err := gl.NewSanitizedLogger("go-numa/topology")
	if err != nil {
		return nil, fmt.Errorf("create logger: %w", err)
	}

	entries, err := os.ReadDir(sysFsNumaNodes)
	if err != nil {
		// Single-node system — synthesize a node 0
		logger.Info("numa_topology_fallback", zap.String("reason", "sysfs not available"))
		return &Topology{Nodes: []Node{{ID: 0, CPUs: availableCPUs()}}}, nil
	}

	var nodes []Node
	for _, e := range entries {
		if !strings.HasPrefix(e.Name(), "node") {
			continue
		}
		idStr := strings.TrimPrefix(e.Name(), "node")
		id, err := strconv.Atoi(idStr)
		if err != nil {
			continue
		}
		cpus, err := parseCPUList(filepath.Join(sysFsNumaNodes, e.Name(), "cpulist"))
		if err != nil {
			return nil, fmt.Errorf("parse cpulist for node %d: %w", id, err)
		}
		nodes = append(nodes, Node{ID: id, CPUs: cpus})
	}

	if len(nodes) == 0 {
		nodes = []Node{{ID: 0, CPUs: availableCPUs()}}
	}

	logger.Info("numa_topology_discovered", zap.Int("nodes", len(nodes)))
	if err := logger.Sync(); err != nil {
		return nil, fmt.Errorf("sync logger: %w", err)
	}

	return &Topology{Nodes: nodes}, nil
}

func parseCPUList(path string) ([]int, error) {
	data, err := os.ReadFile(path)
	if err != nil {
		return nil, err
	}
	return expandCPUList(strings.TrimSpace(string(data)))
}

// expandCPUList expands a kernel cpu-list string (e.g. "0-3,8,10-12") to a slice of CPU IDs.
func expandCPUList(s string) ([]int, error) {
	var cpus []int
	for _, part := range strings.Split(s, ",") {
		part = strings.TrimSpace(part)
		if strings.Contains(part, "-") {
			bounds := strings.SplitN(part, "-", 2)
			lo, err := strconv.Atoi(bounds[0])
			if err != nil {
				return nil, fmt.Errorf("invalid cpu range %q: %w", part, err)
			}
			hi, err := strconv.Atoi(bounds[1])
			if err != nil {
				return nil, fmt.Errorf("invalid cpu range %q: %w", part, err)
			}
			for i := lo; i <= hi; i++ {
				cpus = append(cpus, i)
			}
		} else if part != "" {
			n, err := strconv.Atoi(part)
			if err != nil {
				return nil, fmt.Errorf("invalid cpu %q: %w", part, err)
			}
			cpus = append(cpus, n)
		}
	}
	return cpus, nil
}

func availableCPUs() []int {
	var cs unix.CPUSet
	if err := unix.SchedGetaffinity(0, &cs); err != nil {
		return []int{0}
	}
	var cpus []int
	for i := 0; i < unix.CPU_SETSIZE; i++ {
		if cs.IsSet(i) {
			cpus = append(cpus, i)
		}
	}
	return cpus
}
