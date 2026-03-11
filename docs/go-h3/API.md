# go-h3 API Reference

## server

Package: `github.com/penguintechinc/penguin-libs/packages/go-h3/server`

### New

```go
func New(opts ...Option) (*Server, error)
```

### Options

| Option | Description |
|--------|-------------|
| `WithAddr(addr string)` | Listen address (e.g. `":8443"`) |
| `WithTLSConfig(cfg *tls.Config)` | TLS configuration |
| `WithInterceptors(i ...connect.Interceptor)` | Add Connect interceptors |

### Server

```go
func (s *Server) ListenAndServe() error
func (s *Server) Shutdown(ctx context.Context) error
```

### Interceptors

| Constructor | Description |
|-------------|-------------|
| `NewAuthInterceptor(secretKey string) connect.Interceptor` | JWT validation interceptor |
| `NewLoggingInterceptor(logger *zap.Logger) connect.Interceptor` | Request/response logging |
| `NewMetricsInterceptor(counterFn func(string)) connect.Interceptor` | Request count metrics |
| `NewCorrelationIDInterceptor() connect.Interceptor` | Injects/propagates correlation ID |

### CorrelationIDFromContext

```go
func CorrelationIDFromContext(ctx context.Context) (string, bool)
```

Extract the correlation ID from a context set by `NewCorrelationIDInterceptor`.

## client

Package: `github.com/penguintechinc/penguin-libs/packages/go-h3/client`

### New

```go
func New(opts ...Option) (*Client, error)
```

### Options

| Option | Description |
|--------|-------------|
| `WithAddr(addr string)` | Server address |
| `WithTLSConfig(cfg *tls.Config)` | TLS configuration |
| `WithRetry(cfg RetryConfig)` | Retry configuration |

### RetryConfig

```go
type RetryConfig struct {
    MaxAttempts int
    BaseDelay   time.Duration
    MaxDelay    time.Duration
}
```

### Client

```go
func (c *Client) Get(path string) (*http.Response, error)
func (c *Client) Post(path string, body io.Reader) (*http.Response, error)
func (c *Client) Close() error
```

## health

Package: `github.com/penguintechinc/penguin-libs/packages/go-h3/health`

```go
func Handler() http.Handler
```

Returns an HTTP handler that responds to `GET /healthz` with `{"status": "ok"}`.

## TLS Helpers

```go
// server package
func LoadTLSConfig(certFile, keyFile string) (*tls.Config, error)
func SelfSignedTLSConfig() (*tls.Config, error)  // Development only
```
