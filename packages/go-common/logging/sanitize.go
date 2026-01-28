// Package logging provides sanitized logging utilities for Penguin Tech applications.
//
// It automatically redacts sensitive data like passwords, tokens, and emails
// to prevent accidental exposure in logs.
package logging

import (
	"regexp"
	"strings"

	"go.uber.org/zap"
	"go.uber.org/zap/zapcore"
)

// SensitiveKeys contains keys that should always be redacted in logs.
var SensitiveKeys = map[string]bool{
	"password":      true,
	"passwd":        true,
	"secret":        true,
	"token":         true,
	"api_key":       true,
	"apikey":        true,
	"auth_token":    true,
	"authtoken":     true,
	"access_token":  true,
	"refresh_token": true,
	"credential":    true,
	"credentials":   true,
	"mfa_code":      true,
	"totp_code":     true,
	"otp":           true,
	"captcha_token": true,
	"session_id":    true,
	"sessionid":     true,
	"cookie":        true,
	"authorization": true,
}

var emailRegex = regexp.MustCompile(`[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}`)

// SanitizeValue redacts sensitive values based on the key name.
func SanitizeValue(key string, value interface{}) interface{} {
	keyLower := strings.ToLower(key)

	// Check if key is sensitive
	if SensitiveKeys[keyLower] {
		return "[REDACTED]"
	}

	// Check if key contains sensitive substring
	for sensitiveKey := range SensitiveKeys {
		if strings.Contains(keyLower, sensitiveKey) {
			return "[REDACTED]"
		}
	}

	// Check for email addresses
	if strVal, ok := value.(string); ok {
		if strings.Contains(strVal, "@") && emailRegex.MatchString(strVal) {
			parts := strings.Split(strVal, "@")
			if len(parts) == 2 {
				return "[email]@" + parts[1]
			}
			return "[REDACTED_EMAIL]"
		}
	}

	return value
}

// SanitizeFields sanitizes a slice of zap fields for safe logging.
func SanitizeFields(fields []zap.Field) []zap.Field {
	sanitized := make([]zap.Field, len(fields))
	for i, field := range fields {
		sanitized[i] = SanitizeField(field)
	}
	return sanitized
}

// SanitizeField sanitizes a single zap field.
func SanitizeField(field zap.Field) zap.Field {
	switch field.Type {
	case zapcore.StringType:
		sanitizedValue := SanitizeValue(field.Key, field.String)
		if sanitizedValue != field.String {
			return zap.String(field.Key, sanitizedValue.(string))
		}
	}
	return field
}

// SanitizedLogger wraps a zap logger with automatic sanitization.
type SanitizedLogger struct {
	logger *zap.Logger
	name   string
}

// NewSanitizedLogger creates a new sanitized logger.
func NewSanitizedLogger(name string) (*SanitizedLogger, error) {
	config := zap.NewProductionConfig()
	config.EncoderConfig.TimeKey = "timestamp"
	config.EncoderConfig.EncodeTime = zapcore.ISO8601TimeEncoder

	logger, err := config.Build()
	if err != nil {
		return nil, err
	}

	return &SanitizedLogger{
		logger: logger.Named(name),
		name:   name,
	}, nil
}

// Debug logs a debug message with sanitized fields.
func (l *SanitizedLogger) Debug(msg string, fields ...zap.Field) {
	l.logger.Debug(msg, SanitizeFields(fields)...)
}

// Info logs an info message with sanitized fields.
func (l *SanitizedLogger) Info(msg string, fields ...zap.Field) {
	l.logger.Info(msg, SanitizeFields(fields)...)
}

// Warn logs a warning message with sanitized fields.
func (l *SanitizedLogger) Warn(msg string, fields ...zap.Field) {
	l.logger.Warn(msg, SanitizeFields(fields)...)
}

// Error logs an error message with sanitized fields.
func (l *SanitizedLogger) Error(msg string, fields ...zap.Field) {
	l.logger.Error(msg, SanitizeFields(fields)...)
}

// Sync flushes any buffered log entries.
func (l *SanitizedLogger) Sync() error {
	return l.logger.Sync()
}
