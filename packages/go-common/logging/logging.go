// Package logging re-exports from go-logging for backwards compatibility.
// New code should import github.com/penguintechinc/penguin-libs/packages/go-logging/logging directly.
package logging

import gl "github.com/penguintechinc/penguin-libs/packages/go-logging/logging"

// Re-export all public types
type SanitizedLogger = gl.SanitizedLogger
type LoggerConfig = gl.LoggerConfig
type Sink = gl.Sink
type StdoutSink = gl.StdoutSink
type FileSink = gl.FileSink
type SyslogSink = gl.SyslogSink
type CallbackSink = gl.CallbackSink
type KillKrillConfig = gl.KillKrillConfig
type KillKrillSink = gl.KillKrillSink

// Re-export all public functions
var (
	NewLogger           = gl.NewLogger
	NewSanitizedLogger  = gl.NewSanitizedLogger
	NewStdoutSink       = gl.NewStdoutSink
	NewFileSink         = gl.NewFileSink
	NewSyslogSink       = gl.NewSyslogSink
	NewCallbackSink     = gl.NewCallbackSink
	NewKillKrillSink    = gl.NewKillKrillSink
	SanitizeValue       = gl.SanitizeValue
	SanitizeFields      = gl.SanitizeFields
	SanitizeField       = gl.SanitizeField
	SensitiveKeys       = gl.SensitiveKeys
)
