package logging

import (
	"testing"

	"go.uber.org/zap"
	"go.uber.org/zap/zapcore"
)

// TestSanitizeValue_SensitiveKeyExactMatch tests that exact sensitive key matches return "[REDACTED]"
func TestSanitizeValue_SensitiveKeyExactMatch(t *testing.T) {
	tests := []struct {
		name     string
		key      string
		value    interface{}
		expected interface{}
	}{
		{
			name:     "password",
			key:      "password",
			value:    "secret123",
			expected: "[REDACTED]",
		},
		{
			name:     "token",
			key:      "token",
			value:    "abc123xyz",
			expected: "[REDACTED]",
		},
		{
			name:     "api_key",
			key:      "api_key",
			value:    "sk-12345",
			expected: "[REDACTED]",
		},
		{
			name:     "auth_token",
			key:      "auth_token",
			value:    "bearer-xyz",
			expected: "[REDACTED]",
		},
		{
			name:     "secret",
			key:      "secret",
			value:    "hidden",
			expected: "[REDACTED]",
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			result := SanitizeValue(tt.key, tt.value)
			if result != tt.expected {
				t.Errorf("SanitizeValue(%q, %v) = %v, want %v", tt.key, tt.value, result, tt.expected)
			}
		})
	}
}

// TestSanitizeValue_SensitiveKeySubstring tests that keys containing sensitive substrings are redacted
func TestSanitizeValue_SensitiveKeySubstring(t *testing.T) {
	tests := []struct {
		name     string
		key      string
		value    interface{}
		expected interface{}
	}{
		{
			name:     "user_password_hash",
			key:      "user_password_hash",
			value:    "hash123",
			expected: "[REDACTED]",
		},
		{
			name:     "my_token",
			key:      "my_token",
			value:    "token456",
			expected: "[REDACTED]",
		},
		{
			name:     "api_secret_key",
			key:      "api_secret_key",
			value:    "secret789",
			expected: "[REDACTED]",
		},
		{
			name:     "refresh_token_value",
			key:      "refresh_token_value",
			value:    "refresh123",
			expected: "[REDACTED]",
		},
		{
			name:     "legacy_passwd",
			key:      "legacy_passwd",
			value:    "oldpass",
			expected: "[REDACTED]",
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			result := SanitizeValue(tt.key, tt.value)
			if result != tt.expected {
				t.Errorf("SanitizeValue(%q, %v) = %v, want %v", tt.key, tt.value, result, tt.expected)
			}
		})
	}
}

// TestSanitizeValue_CaseInsensitive tests that sensitive key matching is case-insensitive
func TestSanitizeValue_CaseInsensitive(t *testing.T) {
	tests := []struct {
		name     string
		key      string
		value    interface{}
		expected interface{}
	}{
		{
			name:     "PASSWORD uppercase",
			key:      "PASSWORD",
			value:    "secret123",
			expected: "[REDACTED]",
		},
		{
			name:     "Token mixed case",
			key:      "Token",
			value:    "abc123",
			expected: "[REDACTED]",
		},
		{
			name:     "API_KEY uppercase",
			key:      "API_KEY",
			value:    "sk-789",
			expected: "[REDACTED]",
		},
		{
			name:     "MyPassword mixed case",
			key:      "MyPassword",
			value:    "hidden",
			expected: "[REDACTED]",
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			result := SanitizeValue(tt.key, tt.value)
			if result != tt.expected {
				t.Errorf("SanitizeValue(%q, %v) = %v, want %v", tt.key, tt.value, result, tt.expected)
			}
		})
	}
}

// TestSanitizeValue_EmailMasked tests that email addresses are partially masked
func TestSanitizeValue_EmailMasked(t *testing.T) {
	tests := []struct {
		name     string
		key      string
		value    string
		expected string
	}{
		{
			name:     "standard email",
			key:      "email",
			value:    "user@example.com",
			expected: "[email]@example.com",
		},
		{
			name:     "email in name field",
			key:      "name",
			value:    "john.doe@company.co.uk",
			expected: "[email]@company.co.uk",
		},
		{
			name:     "complex email",
			key:      "contact",
			value:    "first.last+tag@subdomain.example.org",
			expected: "[email]@subdomain.example.org",
		},
		{
			name:     "numeric email",
			key:      "user_email",
			value:    "123456@test.io",
			expected: "[email]@test.io",
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			result := SanitizeValue(tt.key, tt.value)
			if result != tt.expected {
				t.Errorf("SanitizeValue(%q, %q) = %q, want %q", tt.key, tt.value, result, tt.expected)
			}
		})
	}
}

// TestSanitizeValue_NonSensitivePassthrough tests that non-sensitive keys and values pass through unchanged
func TestSanitizeValue_NonSensitivePassthrough(t *testing.T) {
	tests := []struct {
		name     string
		key      string
		value    interface{}
		expected interface{}
	}{
		{
			name:     "username",
			key:      "username",
			value:    "bob",
			expected: "bob",
		},
		{
			name:     "email without special chars",
			key:      "name",
			value:    "regular_user",
			expected: "regular_user",
		},
		{
			name:     "description",
			key:      "description",
			value:    "A user account",
			expected: "A user account",
		},
		{
			name:     "status",
			key:      "status",
			value:    "active",
			expected: "active",
		},
		{
			name:     "empty string",
			key:      "note",
			value:    "",
			expected: "",
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			result := SanitizeValue(tt.key, tt.value)
			if result != tt.expected {
				t.Errorf("SanitizeValue(%q, %v) = %v, want %v", tt.key, tt.value, result, tt.expected)
			}
		})
	}
}

// TestSanitizeValue_NonStringValue tests that non-string values pass through unchanged
func TestSanitizeValue_NonStringValue(t *testing.T) {
	tests := []struct {
		name     string
		key      string
		value    interface{}
		expected interface{}
	}{
		{
			name:     "integer value",
			key:      "count",
			value:    42,
			expected: 42,
		},
		{
			name:     "float value",
			key:      "rating",
			value:    4.5,
			expected: 4.5,
		},
		{
			name:     "boolean value",
			key:      "active",
			value:    true,
			expected: true,
		},
		{
			name:     "nil value",
			key:      "nullable",
			value:    nil,
			expected: nil,
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			result := SanitizeValue(tt.key, tt.value)
			if result != tt.expected {
				t.Errorf("SanitizeValue(%q, %v) = %v, want %v", tt.key, tt.value, result, tt.expected)
			}
		})
	}
}

// TestSanitizeField_StringFieldSanitized tests that string fields with sensitive keys are sanitized
func TestSanitizeField_StringFieldSanitized(t *testing.T) {
	tests := []struct {
		name        string
		field       zap.Field
		expectedVal string
	}{
		{
			name:        "password field",
			field:       zap.String("password", "secret123"),
			expectedVal: "[REDACTED]",
		},
		{
			name:        "api_key field",
			field:       zap.String("api_key", "sk-abcd1234"),
			expectedVal: "[REDACTED]",
		},
		{
			name:        "token field",
			field:       zap.String("token", "bearer-xyz"),
			expectedVal: "[REDACTED]",
		},
		{
			name:        "auth_token field",
			field:       zap.String("auth_token", "auth123"),
			expectedVal: "[REDACTED]",
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			result := SanitizeField(tt.field)
			if result.Key != tt.field.Key {
				t.Errorf("SanitizeField key mismatch: got %q, want %q", result.Key, tt.field.Key)
			}
			// Extract string value from sanitized field
			if result.Type != zapcore.StringType {
				t.Fatalf("Expected StringType field, got %v", result.Type)
			}
			if result.String != tt.expectedVal {
				t.Errorf("SanitizeField string value: got %q, want %q", result.String, tt.expectedVal)
			}
		})
	}
}

// TestSanitizeField_NonStringFieldPassthrough tests that non-string fields pass through unchanged
func TestSanitizeField_NonStringFieldPassthrough(t *testing.T) {
	tests := []struct {
		name          string
		field         zap.Field
		expectedType  zapcore.FieldType
		expectedValue interface{}
	}{
		{
			name:         "int field",
			field:        zap.Int("count", 42),
			expectedType: zapcore.Int64Type,
		},
		{
			name:         "float field",
			field:        zap.Float64("rating", 3.14),
			expectedType: zapcore.Float64Type,
		},
		{
			name:         "bool field",
			field:        zap.Bool("active", true),
			expectedType: zapcore.BoolType,
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			result := SanitizeField(tt.field)
			if result.Type != tt.expectedType {
				t.Errorf("SanitizeField type mismatch: got %v, want %v", result.Type, tt.expectedType)
			}
			if result.Key != tt.field.Key {
				t.Errorf("SanitizeField key mismatch: got %q, want %q", result.Key, tt.field.Key)
			}
		})
	}
}

// TestSanitizeFields_MixedFields tests sanitization of a batch of mixed sensitive and non-sensitive fields
func TestSanitizeFields_MixedFields(t *testing.T) {
	fields := []zap.Field{
		zap.String("username", "alice"),
		zap.String("password", "secret123"),
		zap.Int("user_id", 123),
		zap.String("api_key", "sk-xyz"),
		zap.String("name", "Alice Wonder"),
		zap.String("email", "alice@example.com"),
		zap.Bool("active", true),
		zap.String("session_id", "sess-abc"),
	}

	result := SanitizeFields(fields)

	if len(result) != len(fields) {
		t.Errorf("SanitizeFields length mismatch: got %d, want %d", len(result), len(fields))
	}

	// Verify specific fields
	tests := []struct {
		idx             int
		expectedKey     string
		expectedSanitize bool
	}{
		{0, "username", false},          // should not be sanitized
		{1, "password", true},           // should be sanitized
		{2, "user_id", false},           // non-string field
		{3, "api_key", true},            // should be sanitized
		{4, "name", false},              // should not be sanitized
		{5, "email", false},             // email field, but value should be masked
		{6, "active", false},            // non-string field
		{7, "session_id", true},         // should be sanitized
	}

	for _, tt := range tests {
		field := result[tt.idx]
		if field.Key != tt.expectedKey {
			t.Errorf("Field %d key mismatch: got %q, want %q", tt.idx, field.Key, tt.expectedKey)
		}

		if field.Type == zapcore.StringType {
			if tt.expectedSanitize && field.String != "[REDACTED]" {
				t.Errorf("Field %d (%q) should be sanitized but got: %q", tt.idx, tt.expectedKey, field.String)
			}
		}
	}
}

// TestNewSanitizedLogger_CreatesSuccessfully tests that NewSanitizedLogger creates a logger without error
func TestNewSanitizedLogger_CreatesSuccessfully(t *testing.T) {
	logger, err := NewSanitizedLogger("test")
	if err != nil {
		t.Fatalf("NewSanitizedLogger failed: %v", err)
	}
	if logger == nil {
		t.Error("NewSanitizedLogger returned nil logger")
	}
	defer logger.Sync() //nolint:errcheck
}

// TestNewSanitizedLogger_NameSet tests that the logger name is correctly set
func TestNewSanitizedLogger_NameSet(t *testing.T) {
	name := "myapp"
	logger, err := NewSanitizedLogger(name)
	if err != nil {
		t.Fatalf("NewSanitizedLogger failed: %v", err)
	}
	if logger.name != name {
		t.Errorf("Logger name mismatch: got %q, want %q", logger.name, name)
	}
	defer logger.Sync() //nolint:errcheck
}

// TestSanitizedLogger_Methods tests that logging methods don't panic
func TestSanitizedLogger_Methods(t *testing.T) {
	logger, err := NewSanitizedLogger("test")
	if err != nil {
		t.Fatalf("NewSanitizedLogger failed: %v", err)
	}
	defer logger.Sync() //nolint:errcheck

	tests := []struct {
		name string
		fn   func()
	}{
		{
			name: "Debug",
			fn: func() {
				logger.Debug("debug message", zap.String("key", "value"))
			},
		},
		{
			name: "Info",
			fn: func() {
				logger.Info("info message", zap.String("key", "value"))
			},
		},
		{
			name: "Warn",
			fn: func() {
				logger.Warn("warning message", zap.String("key", "value"))
			},
		},
		{
			name: "Error",
			fn: func() {
				logger.Error("error message", zap.String("key", "value"))
			},
		},
		{
			name: "Debug with sensitive field",
			fn: func() {
				logger.Debug("debug with password", zap.String("password", "secret"))
			},
		},
		{
			name: "Info with email",
			fn: func() {
				logger.Info("user info", zap.String("email", "user@example.com"))
			},
		},
		{
			name: "Warn with token",
			fn: func() {
				logger.Warn("auth warning", zap.String("auth_token", "token123"))
			},
		},
		{
			name: "Error with api_key",
			fn: func() {
				logger.Error("api error", zap.String("api_key", "sk-xyz"))
			},
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			// Should not panic
			defer func() {
				if r := recover(); r != nil {
					t.Errorf("logging method panicked: %v", r)
				}
			}()
			tt.fn()
		})
	}
}

// TestNewSanitizedLogger_MultipleNames tests creating multiple loggers with different names
func TestNewSanitizedLogger_MultipleNames(t *testing.T) {
	names := []string{"app", "database", "api", "worker"}

	loggers := make([]*SanitizedLogger, len(names))
	for i, name := range names {
		logger, err := NewSanitizedLogger(name)
		if err != nil {
			t.Fatalf("NewSanitizedLogger(%q) failed: %v", name, err)
		}
		loggers[i] = logger
	}

	for i, logger := range loggers {
		if logger.name != names[i] {
			t.Errorf("Logger %d name mismatch: got %q, want %q", i, logger.name, names[i])
		}
		defer logger.Sync() //nolint:errcheck
	}
}

// TestSanitizeValue_EdgeCases tests edge cases in sanitization
func TestSanitizeValue_EdgeCases(t *testing.T) {
	tests := []struct {
		name     string
		key      string
		value    interface{}
		expected interface{}
	}{
		{
			name:     "empty key",
			key:      "",
			value:    "anything",
			expected: "anything",
		},
		{
			name:     "value with @ but not email",
			key:      "mention",
			value:    "some@thing@weird",
			expected: "some@thing@weird",
		},
		{
			name:     "incomplete email",
			key:      "text",
			value:    "user@",
			expected: "user@",
		},
		{
			name:     "password with email value",
			key:      "password",
			value:    "user@example.com",
			expected: "[REDACTED]",
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			result := SanitizeValue(tt.key, tt.value)
			if result != tt.expected {
				t.Errorf("SanitizeValue(%q, %v) = %v, want %v", tt.key, tt.value, result, tt.expected)
			}
		})
	}
}

// BenchmarkSanitizeValue benchmarks the SanitizeValue function
func BenchmarkSanitizeValue(b *testing.B) {
	for i := 0; i < b.N; i++ {
		SanitizeValue("password", "secret123")
	}
}

// BenchmarkSanitizeFields benchmarks the SanitizeFields function
func BenchmarkSanitizeFields(b *testing.B) {
	fields := []zap.Field{
		zap.String("username", "alice"),
		zap.String("password", "secret123"),
		zap.Int("user_id", 123),
		zap.String("api_key", "sk-xyz"),
	}

	b.ResetTimer()
	for i := 0; i < b.N; i++ {
		SanitizeFields(fields)
	}
}

// BenchmarkSanitizedLogger benchmarks logging operations
func BenchmarkSanitizedLogger(b *testing.B) {
	logger, err := NewSanitizedLogger("bench")
	if err != nil {
		b.Fatalf("NewSanitizedLogger failed: %v", err)
	}
	defer logger.Sync() //nolint:errcheck

	b.ResetTimer()
	for i := 0; i < b.N; i++ {
		logger.Info("benchmark message", zap.String("password", "secret"), zap.String("username", "user"))
	}
}
