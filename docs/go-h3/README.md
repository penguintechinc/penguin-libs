# go-h3

H3 protocol server, client, and middleware for Go. Provides HTTP/3 (QUIC) server and client implementations using `connectrpc` and `quic-go`, with authentication, logging, and metrics interceptors.

## Installation

```bash
go get github.com/penguintechinc/penguin-libs/packages/go-h3
```

## Quick Start

### Server

```go
package main

import (
    "github.com/penguintechinc/penguin-libs/packages/go-h3/server"
)

func main() {
    srv, err := server.New(
        server.WithAddr(":8443"),
        server.WithTLSConfig(tlsCfg),
        server.WithInterceptors(
            server.NewAuthInterceptor(secretKey),
            server.NewLoggingInterceptor(logger),
        ),
    )
    if err != nil {
        panic(err)
    }
    srv.ListenAndServe()
}
```

### Client

```go
package main

import (
    "github.com/penguintechinc/penguin-libs/packages/go-h3/client"
)

func main() {
    c, err := client.New(
        client.WithAddr("https://api.example.com:8443"),
        client.WithRetry(client.RetryConfig{MaxAttempts: 3}),
    )
    if err != nil {
        panic(err)
    }
    resp, err := c.Get("/api/v1/users")
}
```

📚 Full documentation: [docs/go-h3/](../../docs/go-h3/)
