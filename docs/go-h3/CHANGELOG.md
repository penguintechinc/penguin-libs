# go-h3 Changelog

## 0.1.0

- Initial release
- `server` package: HTTP/3 server with Connect interceptor support
- `client` package: HTTP/3 client with retry and exponential backoff
- `health` package: `/healthz` health check handler
- Server interceptors: `NewAuthInterceptor`, `NewLoggingInterceptor`, `NewMetricsInterceptor`, `NewCorrelationIDInterceptor`
- `CorrelationIDFromContext` helper
- TLS helpers: `LoadTLSConfig`, `SelfSignedTLSConfig`
- Powered by `connectrpc.com/connect` and `github.com/quic-go/quic-go`
