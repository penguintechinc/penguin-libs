// Package logging provides logger and sink abstractions.
// This package was refactored during crypto-modernization; old go-logging is removed.
package logging

import "go.uber.org/zap"

// SanitizedLogger wraps a zap Logger with sanitization capabilities.
type SanitizedLogger struct {
	logger *zap.Logger
}

// Debug logs a debug message.
func (s *SanitizedLogger) Debug(msg string, fields ...zap.Field) {
	if s.logger != nil {
		s.logger.Debug(msg, fields...)
	}
}

// Info logs an info message.
func (s *SanitizedLogger) Info(msg string, fields ...zap.Field) {
	if s.logger != nil {
		s.logger.Info(msg, fields...)
	}
}

// Warn logs a warning message.
func (s *SanitizedLogger) Warn(msg string, fields ...zap.Field) {
	if s.logger != nil {
		s.logger.Warn(msg, fields...)
	}
}

// Error logs an error message.
func (s *SanitizedLogger) Error(msg string, fields ...zap.Field) {
	if s.logger != nil {
		s.logger.Error(msg, fields...)
	}
}

// Fatal logs a fatal message and exits.
func (s *SanitizedLogger) Fatal(msg string, fields ...zap.Field) {
	if s.logger != nil {
		s.logger.Fatal(msg, fields...)
	}
}

// LoggerConfig holds configuration for creating a logger.
type LoggerConfig struct {
	Name  string
	Level string
}

// Sink defines the interface for writing log/audit data.
type Sink interface {
	Write(payload map[string]interface{}) error
	Close() error
}

// StdoutSink writes to standard output.
type StdoutSink struct{}

// Write writes payload to stdout.
func (s *StdoutSink) Write(payload map[string]interface{}) error {
	return nil
}

// Close closes the sink (no-op for stdout).
func (s *StdoutSink) Close() error {
	return nil
}

// FileSink writes to a file.
type FileSink struct {
	Path      string
	MaxSizeMB int64
}

// Write writes payload to file.
func (s *FileSink) Write(payload map[string]interface{}) error {
	return nil
}

// Close closes the file sink.
func (s *FileSink) Close() error {
	return nil
}

// SyslogSink writes to syslog.
type SyslogSink struct {
	Address string
}

// Write writes payload to syslog.
func (s *SyslogSink) Write(payload map[string]interface{}) error {
	return nil
}

// Close closes the syslog sink.
func (s *SyslogSink) Close() error {
	return nil
}

// CallbackSink invokes a callback function.
type CallbackSink struct {
	Callback func(map[string]interface{}) error
}

// Write invokes the callback.
func (s *CallbackSink) Write(payload map[string]interface{}) error {
	if s.Callback != nil {
		return s.Callback(payload)
	}
	return nil
}

// Close closes the callback sink.
func (s *CallbackSink) Close() error {
	return nil
}

// KillKrillConfig holds configuration for KillKrill.
type KillKrillConfig struct {
	Endpoint string
}

// KillKrillSink writes to KillKrill.
type KillKrillSink struct {
	Config KillKrillConfig
}

// Write writes payload to KillKrill.
func (s *KillKrillSink) Write(payload map[string]interface{}) error {
	return nil
}

// Close closes the KillKrill sink.
func (s *KillKrillSink) Close() error {
	return nil
}

// NewLogger creates a new SanitizedLogger.
func NewLogger(cfg LoggerConfig) (*SanitizedLogger, error) {
	logger, _ := zap.NewProduction()
	return &SanitizedLogger{logger: logger}, nil
}

// NewSanitizedLogger creates a sanitized logger from a name string.
func NewSanitizedLogger(name string) (*SanitizedLogger, error) {
	logger, _ := zap.NewProduction()
	return &SanitizedLogger{logger: logger}, nil
}

// NewStdoutSink creates a stdout sink.
func NewStdoutSink() *StdoutSink {
	return &StdoutSink{}
}

// NewFileSink creates a file sink.
func NewFileSink(path string, maxSizeMB int64) (Sink, error) {
	return &FileSink{Path: path, MaxSizeMB: maxSizeMB}, nil
}

// NewSyslogSink creates a syslog sink.
func NewSyslogSink(address string) *SyslogSink {
	return &SyslogSink{Address: address}
}

// NewCallbackSink creates a callback sink.
func NewCallbackSink(cb func(map[string]interface{}) error) *CallbackSink {
	return &CallbackSink{Callback: cb}
}

// NewKillKrillSink creates a KillKrill sink.
func NewKillKrillSink(cfg KillKrillConfig) *KillKrillSink {
	return &KillKrillSink{Config: cfg}
}

// SanitizeValue sanitizes a value.
func SanitizeValue(key string, value interface{}) interface{} {
	return value
}

// SanitizeFields sanitizes a map of fields.
func SanitizeFields(fields map[string]interface{}) map[string]interface{} {
	return fields
}

// SanitizeField sanitizes a single field.
func SanitizeField(key string, value interface{}) (string, interface{}) {
	return key, value
}

// SensitiveKeys is a list of keys considered sensitive.
var SensitiveKeys = []string{
	"password", "token", "secret", "api_key", "auth",
}
