package logging

import (
	"errors"
	"testing"

	"go.uber.org/zap"
	"go.uber.org/zap/zapcore"
)

// secretObject is a zapcore.ObjectMarshaler carrying a sensitive nested key.
type secretObject struct{}

// MarshalLogObject encodes a payload with a password and a benign field.
func (secretObject) MarshalLogObject(enc zapcore.ObjectEncoder) error {
	enc.AddString("password", "hunter2")
	enc.AddString("user", "alice")
	return nil
}

// structWithSecret is a struct whose JSON form carries a sensitive key.
type structWithSecret struct {
	ClientSecret string `json:"client_secret"`
	Name         string `json:"name"`
}

// encodeField renders a single sanitized field into a map for assertions.
func encodeField(t *testing.T, f zap.Field) map[string]interface{} {
	t.Helper()
	enc := zapcore.NewMapObjectEncoder()
	f.AddTo(enc)
	return enc.Fields
}

// TestSanitizeField_NonStringSensitiveKeyRedacted is a regression test: zap.Any/Reflect/Int bypassed key redaction.
func TestSanitizeField_NonStringSensitiveKeyRedacted(t *testing.T) {
	tests := []struct {
		name  string
		field zap.Field
	}{
		{"any map under password", zap.Any("password", map[string]string{"v": "x"})},
		{"reflect under id_token", zap.Reflect("id_token", []string{"abc"})},
		{"int under api_token", zap.Int("api_token", 12345)},
		{"bool under jwt", zap.Bool("jwt", true)},
		{"error under refresh_token", zap.NamedError("refresh_token", errors.New("leaked-secret"))},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			result := SanitizeField(tt.field)
			fields := encodeField(t, result)
			if got := fields[tt.field.Key]; got != "[REDACTED]" {
				t.Errorf("field %q = %v, want [REDACTED]", tt.field.Key, got)
			}
		})
	}
}

// TestSanitizeField_ObjectMarshalerNestedRedacted is a regression test: zap.Object bypassed sanitization entirely.
func TestSanitizeField_ObjectMarshalerNestedRedacted(t *testing.T) {
	result := SanitizeField(zap.Object("request", secretObject{}))
	fields := encodeField(t, result)

	inner, ok := fields["request"].(map[string]interface{})
	if !ok {
		t.Fatalf("request is %T, want map[string]interface{}", fields["request"])
	}
	if inner["password"] != "[REDACTED]" {
		t.Errorf("nested password = %v, want [REDACTED]", inner["password"])
	}
	if inner["user"] != "alice" {
		t.Errorf("nested user = %v, want alice (non-sensitive passthrough)", inner["user"])
	}
}

// TestSanitizeField_ReflectStructNestedRedacted covers struct values whose JSON form holds a secret.
func TestSanitizeField_ReflectStructNestedRedacted(t *testing.T) {
	result := SanitizeField(zap.Reflect("payload", structWithSecret{ClientSecret: "s3cr3t", Name: "svc"}))
	fields := encodeField(t, result)

	inner, ok := fields["payload"].(map[string]interface{})
	if !ok {
		t.Fatalf("payload is %T, want map[string]interface{}", fields["payload"])
	}
	if inner["client_secret"] != "[REDACTED]" {
		t.Errorf("client_secret = %v, want [REDACTED]", inner["client_secret"])
	}
	if inner["name"] != "svc" {
		t.Errorf("name = %v, want svc", inner["name"])
	}
}

// TestSanitizeField_NestedMapRedacted covers map values with sensitive keys at depth.
func TestSanitizeField_NestedMapRedacted(t *testing.T) {
	value := map[string]interface{}{
		"outer": map[string]interface{}{
			"Refresh_Token": "abc",
			"list":          []interface{}{map[string]interface{}{"private_key": "pem"}},
		},
	}
	result := SanitizeField(zap.Any("ctx", value))
	fields := encodeField(t, result)

	outer := fields["ctx"].(map[string]interface{})["outer"].(map[string]interface{})
	if outer["Refresh_Token"] != "[REDACTED]" {
		t.Errorf("Refresh_Token = %v, want [REDACTED]", outer["Refresh_Token"])
	}
	list := outer["list"].([]interface{})
	if list[0].(map[string]interface{})["private_key"] != "[REDACTED]" {
		t.Errorf("nested private_key not redacted: %v", list[0])
	}
}

// TestSanitizeValue_ExtendedSensitiveKeys is a regression test for the keys missing from SensitiveKeys.
func TestSanitizeValue_ExtendedSensitiveKeys(t *testing.T) {
	keys := []string{"id_token", "jwt", "private_key", "bearer", "refresh_token", "client_secret",
		"ID_TOKEN", "Client_Secret", "Bearer", "Private_Key", "JWT"}
	for _, k := range keys {
		t.Run(k, func(t *testing.T) {
			if got := SanitizeValue(k, "value"); got != "[REDACTED]" {
				t.Errorf("SanitizeValue(%q) = %v, want [REDACTED]", k, got)
			}
		})
	}
}

// TestSanitizeField_NonSensitiveNonStringUnchanged guards against over-redaction of ordinary typed fields.
func TestSanitizeField_NonSensitiveNonStringUnchanged(t *testing.T) {
	f := zap.Int("request_count", 7)
	result := SanitizeField(f)
	if result.Type != zapcore.Int64Type || result.Integer != 7 {
		t.Errorf("request_count changed: type=%v int=%d", result.Type, result.Integer)
	}
}

// TestIsSensitiveKey_SegmentMatching is a regression test: substring matching over-redacted
// benign keys such as token_count, max_tokens and secretary, while real secrets must stay redacted.
func TestIsSensitiveKey_SegmentMatching(t *testing.T) {
	redacted := []string{"password", "apiKey", "X-Api-Key", "id_token", "Authorization", "bearer_token",
		"user_password_hash", "sessionId", "session_id", "clientSecret", "privateKey", "accessToken",
		"db.password", "APIKey", "PASSWORD", "refresh-token", "token"}
	for _, k := range redacted {
		t.Run("redact/"+k, func(t *testing.T) {
			if !isSensitiveKey(k) {
				t.Errorf("isSensitiveKey(%q) = false, want true", k)
			}
			if got := SanitizeValue(k, "v"); got != "[REDACTED]" {
				t.Errorf("SanitizeValue(%q) = %v, want [REDACTED]", k, got)
			}
		})
	}
	kept := []string{"token_count", "max_tokens", "secretary", "tokenTTL", "token_ttl", "password_length",
		"secret_type", "tokenLimit", "token_expires", "api_key_len", "otpCount", "request_count"}
	for _, k := range kept {
		t.Run("keep/"+k, func(t *testing.T) {
			if isSensitiveKey(k) {
				t.Errorf("isSensitiveKey(%q) = true, want false", k)
			}
			if got := SanitizeValue(k, "v"); got != "v" {
				t.Errorf("SanitizeValue(%q) = %v, want v", k, got)
			}
		})
	}
}
