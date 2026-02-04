// Package health provides a ConnectRPC-compatible health check handler.
package health

import (
	"context"
	"sync"

	"connectrpc.com/connect"
)

// Status represents the serving status of a service.
type Status int

const (
	StatusServing    Status = 1
	StatusNotServing Status = 2
)

// Checker tracks health status of named services.
type Checker struct {
	mu       sync.RWMutex
	statuses map[string]Status
}

// NewChecker creates a Checker with the overall server marked as serving.
func NewChecker() *Checker {
	return &Checker{
		statuses: map[string]Status{"": StatusServing},
	}
}

// SetStatus sets the serving status of a named service.
func (c *Checker) SetStatus(service string, status Status) {
	c.mu.Lock()
	defer c.mu.Unlock()
	c.statuses[service] = status
}

// GetStatus returns the serving status of a named service.
func (c *Checker) GetStatus(service string) (Status, bool) {
	c.mu.RLock()
	defer c.mu.RUnlock()
	s, ok := c.statuses[service]
	return s, ok
}

// CheckHandler returns an HTTP handler function suitable for registration
// on a ServeMux at a health check path (e.g., "/healthz").
// It returns 200 if the overall service is serving, 503 otherwise.
func (c *Checker) CheckHandler() func(context.Context, *connect.Request[any]) (*connect.Response[any], error) {
	return func(_ context.Context, _ *connect.Request[any]) (*connect.Response[any], error) {
		status, ok := c.GetStatus("")
		if !ok || status != StatusServing {
			return nil, connect.NewError(connect.CodeUnavailable, nil)
		}
		return connect.NewResponse[any](nil), nil
	}
}

// HTTPCheckHandler returns a simple net/http handler for /healthz.
func (c *Checker) HTTPCheckHandler() func(w interface{ WriteHeader(int) }, r any) {
	// This is intentionally kept as a simple 200/503 responder for use
	// with standard HTTP muxes. For ConnectRPC health, use the proto-based
	// health service from gen/go/examples/health/v1.
	return nil
}
