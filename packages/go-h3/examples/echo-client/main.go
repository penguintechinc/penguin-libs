// Command echo-client demonstrates an HTTP/3-preferred client with HTTP/2 fallback.
package main

import (
	"crypto/tls"
	"flag"
	"fmt"
	"io"
	"os"

	"go.uber.org/zap"

	h3client "github.com/penguintechinc/penguin-libs/packages/go-h3/client"
)

func main() {
	logger, _ := zap.NewProduction()
	defer func() { _ = logger.Sync() }()

	serverURL := flag.String("url", "https://localhost:8443", "server URL")
	msg := flag.String("msg", "hello", "message to echo")
	insecure := flag.Bool("insecure", false, "skip TLS verification")
	flag.Parse()

	cfg := h3client.DefaultClientConfig()
	cfg.BaseURL = *serverURL
	if *insecure {
		// DEV ONLY — never copy into production code
		// InsecureSkipVerify disables TLS certificate verification and must never be used in production.
		cfg.TLSConfig = &tls.Config{
			InsecureSkipVerify: true, //#nosec G402 -- DEV ONLY, never use in production
			MinVersion:         tls.VersionTLS13,
		}
	}

	c := h3client.New(cfg, logger)
	defer func() { _ = c.Close() }()

	url := fmt.Sprintf("%s/echo?msg=%s", cfg.BaseURL, *msg)
	logger.Info("sending request", zap.String("url", url), zap.String("protocol", c.Protocol()))

	resp, err := c.HTTPClient().Get(url)
	if err != nil {
		// If H3 failed, try H2 fallback.
		c.MarkH3Failed()
		logger.Warn("H3 request failed, retrying with H2", zap.Error(err))

		resp, err = c.HTTPClient().Get(url)
		if err != nil {
			logger.Fatal("request failed", zap.Error(err))
			os.Exit(1)
		}
	}
	defer func() { _ = resp.Body.Close() }()

	body, err := io.ReadAll(resp.Body)
	if err != nil {
		logger.Fatal("failed to read response body", zap.Error(err))
		os.Exit(1)
	}
	_, _ = fmt.Printf("Protocol: %s\nResponse: %s\n", c.Protocol(), string(body))
}
