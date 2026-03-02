package audit

import (
	"github.com/penguintechinc/penguin-libs/packages/go-common/logging"
)

// NewKillKrillSink returns a logging.Sink that batches audit events and ships them
// to the KillKrill ingestion service. cfg must specify at least an Endpoint and APIKey.
// The returned sink starts a background flush goroutine; call Close() when done.
func NewKillKrillSink(cfg logging.KillKrillConfig) logging.Sink {
	return logging.NewKillKrillSink(cfg)
}
