# Penguin Tech Go Common

Shared Go utilities for Penguin Tech applications.

## Installation

```bash
go get github.com/penguintechinc/penguin-libs/packages/go-common
```

## Usage

### Sanitized Logging

```go
package main

import (
    "github.com/penguintechinc/penguin-libs/packages/go-common/logging"
    "go.uber.org/zap"
)

func main() {
    log, err := logging.NewSanitizedLogger("MyService")
    if err != nil {
        panic(err)
    }
    defer log.Sync()

    // Automatically sanitizes sensitive data
    log.Info("User login attempt",
        zap.String("email", "user@example.com"),    // Logs as: [email]@example.com
        zap.String("password", "secret123"),        // Logs as: [REDACTED]
        zap.Bool("remember_me", true),              // Logs as-is
    )
}
```

### Sanitization Rules

The following are automatically redacted:
- Passwords, secrets, tokens
- API keys, auth tokens
- MFA/TOTP codes
- Session IDs, cookies
- Full email addresses (only domain is logged)

### Manual Sanitization

```go
import "github.com/penguintechinc/penguin-libs/packages/go-common/logging"

// Sanitize individual values
value := logging.SanitizeValue("password", "secret123")
// Returns: "[REDACTED]"

// Sanitize zap fields
fields := []zap.Field{
    zap.String("email", "user@example.com"),
    zap.String("token", "abc123"),
}
sanitized := logging.SanitizeFields(fields)
```

## License

AGPL-3.0 - See [LICENSE](../../LICENSE) for details.
