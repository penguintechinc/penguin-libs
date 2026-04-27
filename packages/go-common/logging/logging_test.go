// Package logging tests for the shim re-exports from go-logging.
package logging

import (
	"testing"

	"go.uber.org/zap"
)

// TestTypeAliasCompilation verifies that the type aliases compile correctly.
// This is a compile-time check that ensures SanitizedLogger is a valid alias.
func TestTypeAliasCompilation(t *testing.T) {
	// Create a LoggerConfig to verify the type alias works
	config := LoggerConfig{
		Name: "test-logger",
	}

	if config.Name != "test-logger" {
		t.Errorf("LoggerConfig.Name = %q, want %q", config.Name, "test-logger")
	}
}

// TestNewSanitizedLoggerAlias verifies NewSanitizedLogger is callable via alias.
func TestNewSanitizedLoggerAlias(t *testing.T) {
	if NewSanitizedLogger == nil {
		t.Fatal("NewSanitizedLogger is nil, expected callable function")
	}

	// Call NewSanitizedLogger with test input
	logger, err := NewSanitizedLogger("test-logger")
	if err != nil {
		t.Fatalf("NewSanitizedLogger failed: %v", err)
	}
	if logger == nil {
		t.Fatal("NewSanitizedLogger returned nil logger")
	}

	// Verify no panic when calling Info
	logger.Info("test message")
}

// TestNewLoggerAlias verifies NewLogger function is callable via alias.
func TestNewLoggerAlias(t *testing.T) {
	if NewLogger == nil {
		t.Fatal("NewLogger is nil, expected callable function")
	}

	config := LoggerConfig{
		Name: "test",
	}

	logger, err := NewLogger(config)
	if err != nil {
		t.Fatalf("NewLogger failed: %v", err)
	}
	if logger == nil {
		t.Fatal("NewLogger returned nil logger")
	}
}

// TestLoggerConfigStruct instantiates LoggerConfig with expected fields.
func TestLoggerConfigStruct(t *testing.T) {
	config := LoggerConfig{
		Name: "my-logger",
	}

	if config.Name == "" {
		t.Error("LoggerConfig.Name is empty")
	}
}

// TestNewStdoutSinkAlias verifies NewStdoutSink is callable via alias.
func TestNewStdoutSinkAlias(t *testing.T) {
	if NewStdoutSink == nil {
		t.Fatal("NewStdoutSink is nil")
	}

	sink := NewStdoutSink()
	if sink == nil {
		t.Fatal("NewStdoutSink returned nil")
	}
}

// TestNewFileSinkAlias verifies NewFileSink is callable via alias.
func TestNewFileSinkAlias(t *testing.T) {
	if NewFileSink == nil {
		t.Fatal("NewFileSink is nil")
	}

	sink, err := NewFileSink("/tmp/test.log", 10)
	if err != nil {
		t.Fatalf("NewFileSink failed: %v", err)
	}
	if sink == nil {
		t.Fatal("NewFileSink returned nil")
	}
}

// TestNewSyslogSinkAlias verifies NewSyslogSink is callable via alias.
func TestNewSyslogSinkAlias(t *testing.T) {
	if NewSyslogSink == nil {
		t.Fatal("NewSyslogSink is nil")
	}

	sink, err := NewSyslogSink("localhost:514")
	if err != nil {
		t.Fatalf("NewSyslogSink failed: %v", err)
	}
	if sink == nil {
		t.Fatal("NewSyslogSink returned nil")
	}
}

// TestNewCallbackSinkAlias verifies NewCallbackSink is callable via alias.
func TestNewCallbackSinkAlias(t *testing.T) {
	if NewCallbackSink == nil {
		t.Fatal("NewCallbackSink is nil")
	}

	sink := NewCallbackSink(func(event map[string]interface{}) {})
	if sink == nil {
		t.Fatal("NewCallbackSink returned nil")
	}
}

// TestNewKillKrillSinkAlias verifies NewKillKrillSink is callable via alias.
func TestNewKillKrillSinkAlias(t *testing.T) {
	if NewKillKrillSink == nil {
		t.Fatal("NewKillKrillSink is nil")
	}

	config := KillKrillConfig{
		Endpoint: "http://localhost:8080",
	}

	sink := NewKillKrillSink(config)
	if sink == nil {
		t.Fatal("NewKillKrillSink returned nil")
	}
}

// TestSanitizeValueAlias verifies SanitizeValue is callable via alias.
func TestSanitizeValueAlias(t *testing.T) {
	if SanitizeValue == nil {
		t.Fatal("SanitizeValue is nil")
	}

	result := SanitizeValue("testkey", "testvalue")
	if result == nil {
		t.Error("SanitizeValue returned nil")
	}
}

// TestSanitizeFieldsAlias verifies SanitizeFields is callable via alias.
func TestSanitizeFieldsAlias(t *testing.T) {
	if SanitizeFields == nil {
		t.Fatal("SanitizeFields is nil")
	}

	// SanitizeFields accepts []zap.Field and returns []zap.Field
	// Call with empty slice to verify function is callable
	result := SanitizeFields(nil)
	if result == nil {
		t.Error("SanitizeFields returned nil")
	}
}

// TestSanitizeFieldAlias verifies SanitizeField is callable via alias.
func TestSanitizeFieldAlias(t *testing.T) {
	if SanitizeField == nil {
		t.Fatal("SanitizeField is nil")
	}

	// SanitizeField accepts a zap.Field and returns a zap.Field
	// Create a test field and verify sanitization works
	testField := zap.String("test", "value")
	result := SanitizeField(testField)
	if result.Key == "" {
		t.Error("SanitizeField returned zero-value field")
	}
}

// TestSensitiveKeysAlias verifies SensitiveKeys is accessible via alias.
func TestSensitiveKeysAlias(t *testing.T) {
	if SensitiveKeys == nil {
		t.Error("SensitiveKeys is nil")
	}

	if len(SensitiveKeys) == 0 {
		t.Error("SensitiveKeys is empty")
	}
}

// TestAllTypesCompileCheck verifies all public types are accessible.
func TestAllTypesCompileCheck(t *testing.T) {
	// Compile-time checks: all types accessible
	_ = (*SanitizedLogger)(nil)
	_ = LoggerConfig{}
	_ = (*Sink)(nil)
	_ = (*StdoutSink)(nil)
	_ = (*FileSink)(nil)
	_ = (*SyslogSink)(nil)
	_ = (*CallbackSink)(nil)
	_ = KillKrillConfig{}
	_ = (*KillKrillSink)(nil)
}

// TestAllFunctionsCompileCheck verifies all public functions are accessible.
func TestAllFunctionsCompileCheck(t *testing.T) {
	// Compile-time checks: all functions accessible as non-nil
	if NewLogger == nil {
		t.Error("NewLogger is nil")
	}
	if NewSanitizedLogger == nil {
		t.Error("NewSanitizedLogger is nil")
	}
	if NewStdoutSink == nil {
		t.Error("NewStdoutSink is nil")
	}
	if NewFileSink == nil {
		t.Error("NewFileSink is nil")
	}
	if NewSyslogSink == nil {
		t.Error("NewSyslogSink is nil")
	}
	if NewCallbackSink == nil {
		t.Error("NewCallbackSink is nil")
	}
	if NewKillKrillSink == nil {
		t.Error("NewKillKrillSink is nil")
	}
	if SanitizeValue == nil {
		t.Error("SanitizeValue is nil")
	}
	if SanitizeFields == nil {
		t.Error("SanitizeFields is nil")
	}
	if SanitizeField == nil {
		t.Error("SanitizeField is nil")
	}
	if SensitiveKeys == nil {
		t.Error("SensitiveKeys is nil")
	}
}
