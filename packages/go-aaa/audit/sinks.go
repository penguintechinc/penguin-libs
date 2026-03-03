package audit

import (
	"github.com/penguintechinc/penguin-libs/packages/go-common/logging"
)

// NewStdoutSink returns a logging.Sink that writes JSON-encoded audit events to stdout.
func NewStdoutSink() logging.Sink {
	return logging.NewStdoutSink()
}

// NewFileSink returns a logging.Sink that writes JSON-encoded audit events to the file at path.
// maxSizeMB controls rotation; zero disables rotation. An error is returned if the file
// cannot be opened.
func NewFileSink(path string, maxSizeMB int64) (logging.Sink, error) {
	return logging.NewFileSink(path, maxSizeMB)
}
