package client

import (
	"crypto/tls"
	"net/http"
	"sync"
	"time"

	"github.com/quic-go/quic-go/http3"
	"go.uber.org/zap"
)

// Client is an HTTP client that prefers HTTP/3 and falls back to HTTP/2.
type Client struct {
	cfg       Config
	logger    *zap.Logger
	h2Client  *http.Client
	h3Client  *http.Client
	mu        sync.RWMutex
	useH3     bool
	lastH3Try time.Time
}

// New creates a Client with the given config and logger.
func New(cfg Config, logger *zap.Logger) *Client {
	if logger == nil {
		logger, _ = zap.NewProduction()
	}

	tlsCfg := cfg.TLSConfig
	if tlsCfg == nil {
		tlsCfg = &tls.Config{MinVersion: tls.VersionTLS13}
	}

	h2Transport := &http.Transport{
		TLSClientConfig:     tlsCfg.Clone(),
		MaxIdleConnsPerHost: 100,
		IdleConnTimeout:     90 * time.Second,
		ForceAttemptHTTP2:   true,
	}

	h3Transport := &http3.Transport{
		TLSClientConfig: tlsCfg.Clone(),
	}

	c := &Client{
		cfg:    cfg,
		logger: logger,
		h2Client: &http.Client{
			Transport: h2Transport,
			Timeout:   cfg.RequestTimeout,
		},
		h3Client: &http.Client{
			Transport: h3Transport,
			Timeout:   cfg.RequestTimeout,
		},
		useH3: cfg.H3Enabled,
	}
	return c
}

// HTTPClient returns the current preferred *http.Client.
// This can be passed to ConnectRPC client constructors.
func (c *Client) HTTPClient() *http.Client {
	c.mu.RLock()
	defer c.mu.RUnlock()
	if c.useH3 {
		return c.h3Client
	}
	return c.h2Client
}

// Protocol returns the currently active protocol ("h3" or "h2").
func (c *Client) Protocol() string {
	c.mu.RLock()
	defer c.mu.RUnlock()
	if c.useH3 {
		return "h3"
	}
	return "h2"
}

// MarkH3Failed records that an HTTP/3 request failed, triggering fallback to HTTP/2.
// Periodic re-upgrade is attempted after H3RetryInterval.
func (c *Client) MarkH3Failed() {
	c.mu.Lock()
	defer c.mu.Unlock()
	if c.useH3 {
		c.logger.Warn("HTTP/3 failed, falling back to HTTP/2")
		c.useH3 = false
		c.lastH3Try = time.Now()
	}
}

// MaybeRetryH3 checks if enough time has passed to re-attempt HTTP/3.
// Call this periodically (e.g., before each request) to enable re-upgrade.
func (c *Client) MaybeRetryH3() {
	if !c.cfg.H3Enabled {
		return
	}
	c.mu.Lock()
	defer c.mu.Unlock()
	if !c.useH3 && time.Since(c.lastH3Try) >= c.cfg.H3RetryInterval {
		c.logger.Info("re-attempting HTTP/3")
		c.useH3 = true
	}
}

// Close releases resources held by the client's transports.
func (c *Client) Close() error {
	c.h2Client.CloseIdleConnections()
	if t, ok := c.h3Client.Transport.(*http3.Transport); ok {
		return t.Close()
	}
	return nil
}
