package audit

import (
	"fmt"

	"github.com/penguintechinc/penguin-libs/packages/go-common/logging"
)

// Emitter fans out audit events to one or more logging Sinks.
type Emitter struct {
	sinks []logging.Sink
}

// NewEmitter creates an Emitter that writes to the provided sinks.
// At least one sink should be provided; passing no sinks results in a no-op emitter.
func NewEmitter(sinks ...logging.Sink) *Emitter {
	return &Emitter{sinks: sinks}
}

// Emit converts the event to a map and writes it to every registered sink.
// Errors from individual sinks are collected and returned as a combined error.
func (e *Emitter) Emit(event AuditEvent) error {
	payload := event.ToMap()
	var errs []error
	for _, s := range e.sinks {
		if err := s.Write(payload); err != nil {
			errs = append(errs, err)
		}
	}
	return joinErrors(errs)
}

// Close flushes and closes every registered sink.
// Errors from individual sinks are collected and returned as a combined error.
func (e *Emitter) Close() error {
	var errs []error
	for _, s := range e.sinks {
		if err := s.Close(); err != nil {
			errs = append(errs, err)
		}
	}
	return joinErrors(errs)
}

// joinErrors returns nil when errs is empty, the single error when there is one,
// and a combined error message when there are multiple.
func joinErrors(errs []error) error {
	switch len(errs) {
	case 0:
		return nil
	case 1:
		return errs[0]
	default:
		msg := errs[0].Error()
		for _, err := range errs[1:] {
			msg = fmt.Sprintf("%s; %s", msg, err.Error())
		}
		return fmt.Errorf("audit emitter: multiple sink errors: %s", msg)
	}
}
