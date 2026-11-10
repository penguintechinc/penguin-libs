// Package logging provides sanitized logging utilities for Penguin Tech applications.
//
// It automatically redacts sensitive data like passwords, tokens, and emails
// to prevent accidental exposure in logs.
//
// Deprecated: Go libraries are being phased out; use penguin-logging (packages/rust-logging) instead.
package logging

import (
	"bytes"
	"encoding/json"
	"regexp"
	"strings"
	"unicode"

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
	"id_token":      true,
	"jwt":           true,
	"private_key":   true,
	"bearer":        true,
	"client_secret": true,
}

// redactedValue is the replacement written for every redacted field or value.
const redactedValue = "[REDACTED]"

var emailRegex = regexp.MustCompile(`[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}`)

// nonSecretSuffixes are trailing segments marking a key as metadata about a secret
// (token_count, tokenTTL) rather than the secret itself.
var nonSecretSuffixes = map[string]bool{
	"count": true, "ttl": true, "limit": true, "expires": true, "expiry": true,
	"type": true, "len": true, "length": true, "max": true, "min": true,
}

// splitKeySegments lowercases a key and splits it on '_', '-', '.', whitespace and
// camelCase boundaries (apiKey, X-Api-Key, tokenTTL, APIKey).
func splitKeySegments(key string) []string {
	runes := []rune(key)
	var segments []string
	var cur []rune
	flush := func() {
		if len(cur) > 0 {
			segments = append(segments, strings.ToLower(string(cur)))
			cur = cur[:0]
		}
	}
	for i, r := range runes {
		if r == '_' || r == '-' || r == '.' || unicode.IsSpace(r) {
			flush()
			continue
		}
		if i > 0 && unicode.IsUpper(r) {
			prev := runes[i-1]
			nextLower := i+1 < len(runes) && unicode.IsLower(runes[i+1])
			if unicode.IsLower(prev) || unicode.IsDigit(prev) || (unicode.IsUpper(prev) && nextLower) {
				flush()
			}
		}
		cur = append(cur, r)
	}
	flush()
	return segments
}

// containsRun reports whether needle appears as a contiguous run within segments.
func containsRun(segments, needle []string) bool {
	for i := 0; i+len(needle) <= len(segments); i++ {
		match := true
		for j, n := range needle {
			if segments[i+j] != n {
				match = false
				break
			}
		}
		if match {
			return true
		}
	}
	return false
}

// isSensitiveKey reports whether a key names sensitive data. An exact SensitiveKeys match always
// redacts; otherwise the key is split into segments and redacted when any SensitiveKeys entry
// (single word or multi-word like "api key") appears as a whole-segment run, unless the key's
// last segment marks it as metadata (count, ttl, limit, ...). Substrings never match.
func isSensitiveKey(key string) bool {
	if SensitiveKeys[strings.ToLower(key)] {
		return true
	}
	segments := splitKeySegments(key)
	if len(segments) == 0 || nonSecretSuffixes[segments[len(segments)-1]] {
		return false
	}
	for sensitiveKey := range SensitiveKeys {
		if containsRun(segments, strings.Split(sensitiveKey, "_")) {
			return true
		}
	}
	return false
}

// SanitizeValue redacts sensitive values based on the key name.
func SanitizeValue(key string, value interface{}) interface{} {
	if isSensitiveKey(key) {
		return redactedValue
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

// sanitizeNested recursively redacts a decoded value (maps, slices, scalars) by key name.
func sanitizeNested(key string, value interface{}) interface{} {
	if isSensitiveKey(key) {
		return redactedValue
	}
	switch v := value.(type) {
	case map[string]interface{}:
		out := make(map[string]interface{}, len(v))
		for k, val := range v {
			out[k] = sanitizeNested(k, val)
		}
		return out
	case []interface{}:
		out := make([]interface{}, len(v))
		for i, val := range v {
			out[i] = sanitizeNested(key, val)
		}
		return out
	default:
		return SanitizeValue(key, value)
	}
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
//
// Redaction is decided by key name for every field type, so typed fields
// (zap.Any, zap.Int, zap.Error, ...) cannot bypass it. Object, array and
// reflected values are encoded and their nested keys are sanitized too.
func SanitizeField(field zap.Field) zap.Field {
	if isSensitiveKey(field.Key) {
		return zap.String(field.Key, redactedValue)
	}

	switch field.Type {
	case zapcore.StringType:
		sanitizedValue := SanitizeValue(field.Key, field.String)
		if sanitizedValue != field.String {
			return zap.String(field.Key, sanitizedValue.(string))
		}
	case zapcore.ObjectMarshalerType, zapcore.ArrayMarshalerType:
		enc := zapcore.NewMapObjectEncoder()
		field.AddTo(enc)
		return zap.Any(field.Key, sanitizeNested(field.Key, enc.Fields[field.Key]))
	case zapcore.ReflectType:
		raw, err := json.Marshal(field.Interface)
		if err != nil {
			return zap.String(field.Key, redactedValue)
		}
		dec := json.NewDecoder(bytes.NewReader(raw))
		dec.UseNumber()
		var decoded interface{}
		if err := dec.Decode(&decoded); err != nil {
			return zap.String(field.Key, redactedValue)
		}
		return zap.Any(field.Key, sanitizeNested(field.Key, decoded))
	default:
		// Scalar types with non-sensitive keys pass through unchanged.
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
