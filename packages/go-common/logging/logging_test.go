// Package logging tests for the shim re-exports from go-logging.
package logging

import (
	"testing"
)

// TestTypeAliasCompilation verifies that the type aliases compile correctly.
func TestTypeAliasCompilation(t *testing.T) {
	config := LoggerConfig{
		Name: "test-logger",
	}

	if config.Name != "test-logger" {
		t.Errorf("LoggerConfig.Name = %q, want %q", config.Name, "test-logger")
	}
}

// TestNewSanitizedLoggerAlias verifies NewSanitizedLogger is callable via alias.
func TestNewSanitizedLoggerAlias(t *testing.T) {
	logger, err := NewSanitizedLogger("test-logger")
	if err != nil {
		t.Fatalf("NewSanitizedLogger failed: %v", err)
	}
	if logger == nil {
		t.Fatal("NewSanitizedLogger returned nil logger")
	}
}

// TestNewLoggerAlias verifies NewLogger function is callable via alias.
func TestNewLoggerAlias(t *testing.T) {
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
	sink := NewStdoutSink()
	if sink == nil {
		t.Fatal("NewStdoutSink returned nil")
	}
}

// TestNewFileSinkAlias verifies NewFileSink is callable via alias.
func TestNewFileSinkAlias(t *testing.T) {
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
	sink := NewSyslogSink("localhost:514")
	if sink == nil {
		t.Fatal("NewSyslogSink returned nil")
	}
}

// TestNewCallbackSinkAlias verifies NewCallbackSink is callable via alias.
func TestNewCallbackSinkAlias(t *testing.T) {
	sink := NewCallbackSink(func(event map[string]interface{}) error { return nil })
	if sink == nil {
		t.Fatal("NewCallbackSink returned nil")
	}
}

// TestNewKillKrillSinkAlias verifies NewKillKrillSink is callable via alias.
func TestNewKillKrillSinkAlias(t *testing.T) {
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
	result := SanitizeValue("testkey", "testvalue")
	if result == nil {
		t.Error("SanitizeValue returned nil")
	}
}

// TestSanitizeFieldsAlias verifies SanitizeFields is callable via alias.
func TestSanitizeFieldsAlias(t *testing.T) {
	input := map[string]interface{}{"key": "value"}
	result := SanitizeFields(input)
	if result == nil {
		t.Error("SanitizeFields returned nil")
	}
}

// TestSanitizeFieldAlias verifies SanitizeField is callable via alias.
func TestSanitizeFieldAlias(t *testing.T) {
	key, _ := SanitizeField("test", "value")
	if key == "" {
		t.Error("SanitizeField returned empty key")
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

// TestAllFunctionsCompileCheck verifies all public functions are accessible by calling them.
func TestAllFunctionsCompileCheck(t *testing.T) {
	// Verify functions are callable — compile-time accessibility proven by package building.
	logger, err := NewLogger(LoggerConfig{Name: "compile-check"})
	if err != nil {
		t.Errorf("NewLogger: %v", err)
	}
	_ = logger

	sl, err := NewSanitizedLogger("compile-check")
	if err != nil {
		t.Errorf("NewSanitizedLogger: %v", err)
	}
	_ = sl

	_ = NewStdoutSink()

	fs, err := NewFileSink("/tmp/compile-check.log", 5)
	if err != nil {
		t.Errorf("NewFileSink: %v", err)
	}
	_ = fs

	_ = NewSyslogSink("localhost:514")
	_ = NewCallbackSink(func(map[string]interface{}) error { return nil })
	_ = NewKillKrillSink(KillKrillConfig{Endpoint: "http://localhost:8080"})
	_ = SanitizeValue("k", "v")
	_ = SanitizeFields(map[string]interface{}{})
	_, _ = SanitizeField("k", "v")
	_ = SensitiveKeys
}
