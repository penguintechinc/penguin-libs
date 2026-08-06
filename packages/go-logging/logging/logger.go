package logging

import (
	"encoding/json"
	"fmt"

	"go.uber.org/zap"
	"go.uber.org/zap/zapcore"
)

// LoggerConfig holds configuration for building a SanitizedLogger with custom sinks.
type LoggerConfig struct {
	// Name is the logger name, used for filtering and identification in log output.
	Name string
	// Level is the minimum log level string (e.g. "debug", "info", "warn", "error").
	// Defaults to "info" when empty.
	Level string
	// Sinks is the list of destinations to receive each log event.
	// When empty, the logger falls back to the default production stdout logger.
	Sinks []Sink
	// JSON controls whether the zap encoder uses JSON format (true) or console format (false).
	// Sinks always receive JSON-encoded events regardless of this setting.
	JSON bool
}

// NewLogger builds a SanitizedLogger whose output is dispatched to all configured sinks.
// When no sinks are provided, it falls back to NewSanitizedLogger for default stdout output.
func NewLogger(cfg LoggerConfig) (*SanitizedLogger, error) {
	if len(cfg.Sinks) == 0 {
		return NewSanitizedLogger(cfg.Name)
	}

	level, err := parseLevel(cfg.Level)
	if err != nil {
		return nil, fmt.Errorf("invalid log level %q: %w", cfg.Level, err)
	}

	encoderCfg := zap.NewProductionEncoderConfig()
	encoderCfg.TimeKey = "timestamp"
	encoderCfg.EncodeTime = zapcore.ISO8601TimeEncoder

	var encoder zapcore.Encoder
	if cfg.JSON {
		encoder = zapcore.NewJSONEncoder(encoderCfg)
	} else {
		encoder = zapcore.NewConsoleEncoder(encoderCfg)
	}

	writeSyncer := newMultiSinkWriteSyncer(cfg.Sinks)
	core := zapcore.NewCore(encoder, writeSyncer, level)
	zapLogger := zap.New(core).Named(cfg.Name)

	return &SanitizedLogger{
		logger: zapLogger,
		name:   cfg.Name,
	}, nil
}

func parseLevel(levelStr string) (zapcore.Level, error) {
	if levelStr == "" {
		return zapcore.InfoLevel, nil
	}
	var level zapcore.Level
	if err := level.UnmarshalText([]byte(levelStr)); err != nil {
		return zapcore.InfoLevel, err
	}
	return level, nil
}

// multiSinkWriteSyncer implements zapcore.WriteSyncer by dispatching raw zap
// output bytes to all registered sinks. Each write is JSON-decoded into a
// map so sinks receive structured data rather than raw byte slices.
type multiSinkWriteSyncer struct {
	sinks []Sink
}

func newMultiSinkWriteSyncer(sinks []Sink) *multiSinkWriteSyncer {
	return &multiSinkWriteSyncer{sinks: sinks}
}

// Write decodes the JSON log line from zap and dispatches it to every sink.
// Errors from individual sinks are non-fatal; all sinks receive each event.
func (w *multiSinkWriteSyncer) Write(p []byte) (int, error) {
	var event map[string]interface{}
	if err := json.Unmarshal(p, &event); err != nil {
		// If the payload is not valid JSON (e.g. console encoder output), wrap it
		// as a raw message so sinks still receive something meaningful.
		event = map[string]interface{}{"message": string(p)}
	}

	for _, sink := range w.sinks {
		_ = sink.Write(event)
	}

	return len(p), nil
}

// Sync flushes all sinks. Errors from individual sinks are collected and
// the first encountered error is returned.
func (w *multiSinkWriteSyncer) Sync() error {
	var firstErr error
	for _, sink := range w.sinks {
		if err := sink.Flush(); err != nil && firstErr == nil {
			firstErr = err
		}
	}
	return firstErr
}
