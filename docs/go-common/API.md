# go-common API Reference

## logging

Package: `github.com/penguintechinc/penguin-libs/packages/go-common/logging`

### NewSanitizedLogger

```go
func NewSanitizedLogger(service string) (*zap.Logger, error)
```

Returns a `*zap.Logger` configured with the sanitization core. All log fields are passed through the sanitizer before output.

### SanitizeValue

```go
func SanitizeValue(key string, value string) string
```

Sanitize a single string value. Returns `"[REDACTED]"` for sensitive keys, or the domain-only form for email keys.

### SanitizeFields

```go
func SanitizeFields(fields []zap.Field) []zap.Field
```

Returns a new slice with sensitive fields redacted. Safe to use before passing fields to any logger.

## Usage Examples

```go
// Standard structured logging
log.Info("Request received",
    zap.String("path", "/api/v1/users"),
    zap.Int("status", 200),
)

// Fields with sensitive data are auto-redacted
log.Info("Auth attempt",
    zap.String("email", "alice@example.com"),  // → "[email]@example.com"
    zap.String("token", "Bearer abc123"),       // → "[REDACTED]"
)

// Manual sanitization
safe := logging.SanitizeFields([]zap.Field{
    zap.String("api_key", "sk-live-abc123"),
})
log.Info("API call", safe...)
```
