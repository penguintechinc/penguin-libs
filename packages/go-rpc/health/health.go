// Copyright 2026 Penguin Tech Inc
// SPDX-License-Identifier: Apache-2.0

package health

import (
	"context"
	"encoding/json"
	"net/http"
	"sync"

	"connectrpc.com/connect"

	healthv1 "github.com/penguintechinc/penguin-libs/packages/go-rpc/gen/prpc/health/v1"
	"github.com/penguintechinc/penguin-libs/packages/go-rpc/gen/prpc/health/v1/healthv1connect"
)

// Status is the serving status of a single service (or, for the empty-string
// key, the whole process). It intentionally has no dependency on generated
// protobuf/connect types so callers that only ever call SetStatus/GetStatus
// (background health monitors, readiness probes, etc.) don't need to import
// generated code; NewService converts Status to healthv1.ServingStatus at
// the RPC boundary. Its values are numerically aligned with
// healthv1.ServingStatus (UNSPECIFIED=0, SERVING=1, NOT_SERVING=2) purely to
// keep the conversion function trivial — the two types remain distinct so
// generated-code churn can't silently change Checker's public API.
type Status int32

const (
	// StatusUnknown is the zero value: no status has ever been recorded for
	// the service, or the service name was never registered. Maps to
	// healthv1.ServingStatus_SERVING_STATUS_UNSPECIFIED.
	StatusUnknown Status = 0
	// StatusServing maps to healthv1.ServingStatus_SERVING_STATUS_SERVING.
	StatusServing Status = 1
	// StatusNotServing maps to
	// healthv1.ServingStatus_SERVING_STATUS_NOT_SERVING.
	StatusNotServing Status = 2
)

// Checker tracks the serving status of named services in memory. The
// empty-string service name is reserved for whole-process health (spec §8)
// and is initialized to StatusServing by NewChecker. Checker is safe for
// concurrent use.
type Checker struct {
	mu       sync.RWMutex
	statuses map[string]Status
	subs     map[string]map[chan Status]struct{}
}

// NewChecker creates a Checker with the whole-process status (the
// empty-string service key) initialized to StatusServing.
func NewChecker() *Checker {
	return &Checker{
		statuses: map[string]Status{"": StatusServing},
		subs:     make(map[string]map[chan Status]struct{}),
	}
}

// SetStatus sets the serving status of a named service (empty string =
// whole process) and notifies every active Watch subscriber for that
// service. Notification is non-blocking: each subscriber channel is
// buffered to hold exactly one pending value, and a rapid run of SetStatus
// calls before a subscriber reads collapses to the latest value rather than
// blocking the caller or queuing every intermediate state.
func (c *Checker) SetStatus(service string, status Status) {
	c.mu.Lock()
	c.statuses[service] = status
	var chans []chan Status
	for ch := range c.subs[service] {
		chans = append(chans, ch)
	}
	c.mu.Unlock()

	for _, ch := range chans {
		select {
		case <-ch:
		default:
		}
		select {
		case ch <- status:
		default:
		}
	}
}

// GetStatus returns the serving status of a named service and whether any
// status has ever been recorded for it. An unrecorded service returns
// (StatusUnknown, false).
func (c *Checker) GetStatus(service string) (Status, bool) {
	c.mu.RLock()
	defer c.mu.RUnlock()
	s, ok := c.statuses[service]
	return s, ok
}

// Subscribe registers a channel-based listener for status changes on the
// named service and returns it along with an idempotent unsubscribe
// function. The returned channel has capacity 1 and carries latest-value
// (not every-transition) semantics — see SetStatus. Callers must call
// unsubscribe when done watching to avoid leaking the channel registration.
func (c *Checker) Subscribe(service string) (<-chan Status, func()) {
	ch := make(chan Status, 1)

	c.mu.Lock()
	if c.subs[service] == nil {
		c.subs[service] = make(map[chan Status]struct{})
	}
	c.subs[service][ch] = struct{}{}
	c.mu.Unlock()

	var once sync.Once
	unsubscribe := func() {
		once.Do(func() {
			c.mu.Lock()
			delete(c.subs[service], ch)
			if len(c.subs[service]) == 0 {
				delete(c.subs, service)
			}
			c.mu.Unlock()
		})
	}
	return ch, unsubscribe
}

// subscriberCount returns the number of active Watch subscribers for a
// service. It exists as a test seam (used by health_test.go, same package)
// to assert that context cancellation cleans up subscriptions.
func (c *Checker) subscriberCount(service string) int {
	c.mu.RLock()
	defer c.mu.RUnlock()
	return len(c.subs[service])
}

// statusToProto converts a Status to the generated healthv1.ServingStatus
// enum, defaulting anything other than Serving/NotServing to UNSPECIFIED —
// which is also what an unrecorded (StatusUnknown) service maps to.
func statusToProto(s Status) healthv1.ServingStatus {
	switch s {
	case StatusServing:
		return healthv1.ServingStatus_SERVING_STATUS_SERVING
	case StatusNotServing:
		return healthv1.ServingStatus_SERVING_STATUS_NOT_SERVING
	default:
		return healthv1.ServingStatus_SERVING_STATUS_UNSPECIFIED
	}
}

// healthService implements healthv1connect.HealthServiceHandler over a
// Checker.
type healthService struct {
	checker *Checker
}

// NewService builds a healthv1connect.HealthServiceHandler backed by c.
// Check treats an empty CheckRequest.Service as whole-process health (spec
// §8); a named service with no recorded status returns
// SERVING_STATUS_UNSPECIFIED. Watch sends the current status immediately
// and then pushes a message on every subsequent status change for that
// service until the request context is canceled.
func NewService(c *Checker) healthv1connect.HealthServiceHandler {
	return &healthService{checker: c}
}

// Check returns the current serving status of req.Msg.Service (empty =
// whole process).
func (s *healthService) Check(_ context.Context, req *connect.Request[healthv1.CheckRequest]) (*connect.Response[healthv1.CheckResponse], error) {
	status, _ := s.checker.GetStatus(req.Msg.GetService())
	return connect.NewResponse(&healthv1.CheckResponse{Status: statusToProto(status)}), nil
}

// Watch streams the serving status of req.Msg.Service: the current value is
// sent immediately, then a new message is sent on every subsequent change
// until ctx is canceled, at which point Watch returns nil (a clean stream
// close, not an error) after unsubscribing.
func (s *healthService) Watch(ctx context.Context, req *connect.Request[healthv1.CheckRequest], stream *connect.ServerStream[healthv1.CheckResponse]) error {
	service := req.Msg.GetService()

	ch, unsubscribe := s.checker.Subscribe(service)
	defer unsubscribe()

	status, _ := s.checker.GetStatus(service)
	if err := stream.Send(&healthv1.CheckResponse{Status: statusToProto(status)}); err != nil {
		return err
	}

	for {
		select {
		case <-ctx.Done():
			return nil
		case newStatus, ok := <-ch:
			if !ok {
				return nil
			}
			if err := stream.Send(&healthv1.CheckResponse{Status: statusToProto(newStatus)}); err != nil {
				return err
			}
		}
	}
}

// healthzBody is the JSON body served by the plain GET /healthz endpoint.
type healthzBody struct {
	Status string `json:"status"`
}

// Register mounts the generated Connect HealthService handler on mux at its
// generated path, and additionally mounts a plain GET /healthz endpoint
// returning 200 {"status":"SERVING"} or 503 {"status":"NOT_SERVING"} based
// on the whole-process status (the empty-string service key). opts are
// forwarded to the generated handler constructor — callers pass
// server.HandlerOptions() here to apply the shared MaxMessageBytes cap and
// interceptor chain.
func Register(mux *http.ServeMux, c *Checker, opts ...connect.HandlerOption) {
	path, handler := healthv1connect.NewHealthServiceHandler(NewService(c), opts...)
	mux.Handle(path, handler)
	mux.HandleFunc("GET /healthz", healthzHandler(c))
}

// healthzHandler builds the plain-HTTP /healthz responder for c.
func healthzHandler(c *Checker) http.HandlerFunc {
	return func(w http.ResponseWriter, _ *http.Request) {
		status, _ := c.GetStatus("")

		body := healthzBody{Status: "SERVING"}
		code := http.StatusOK
		if status != StatusServing {
			body.Status = "NOT_SERVING"
			code = http.StatusServiceUnavailable
		}

		w.Header().Set("Content-Type", "application/json")
		w.WriteHeader(code)
		_ = json.NewEncoder(w).Encode(body)
	}
}
