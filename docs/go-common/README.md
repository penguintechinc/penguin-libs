# go-common

Shared Go utilities for Penguin Tech Inc services. Provides sanitized structured logging built on `go.uber.org/zap`.

## Installation

```bash
go get github.com/penguintechinc/penguin-libs/packages/go-common
```

## Quick Start

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

    log.Info("User login attempt",
        zap.String("email", "user@example.com"),  // Logged as: [email]@example.com
        zap.String("password", "secret123"),       // Logged as: [REDACTED]
        zap.Bool("remember_me", true),             // Logged as-is
    )
}
```

## Sanitization Rules

Automatically redacted fields (case-insensitive):
- `password`, `secret`, `token`, `api_key`, `auth_token`, `refresh_token`
- `mfa_code`, `session_id`, `cookie`
- `email` — logged as `[email]@domain.com` (domain only)

📚 Full documentation: [docs/go-common/](../../docs/go-common/)
