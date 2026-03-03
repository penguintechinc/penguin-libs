package logging

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"math"
	"net/http"
	"sync"
	"time"
)

const (
	defaultBatchSize     = 100
	defaultFlushInterval = 5 * time.Second
	defaultTimeout       = 10 * time.Second
	defaultMaxRetries    = 3
	eventsPath           = "/api/v1/events"
)

// KillKrillConfig holds configuration for the KillKrill log sink.
type KillKrillConfig struct {
	// Endpoint is the base URL of the KillKrill service (e.g. "https://logs.example.com").
	Endpoint string
	// APIKey is used in the Authorization: Bearer header.
	APIKey string
	// BatchSize is the maximum number of events to send in a single flush. Defaults to 100.
	BatchSize int
	// FlushInterval controls how often the background goroutine flushes the buffer. Defaults to 5s.
	FlushInterval time.Duration
	// UseGRPC is reserved for future gRPC transport support; currently unused.
	UseGRPC bool
	// Timeout is the HTTP client timeout per request. Defaults to 10s.
	Timeout time.Duration
	// MaxRetries is the number of retry attempts on transient failure. Defaults to 3.
	MaxRetries int
}

func (c *KillKrillConfig) applyDefaults() {
	if c.BatchSize <= 0 {
		c.BatchSize = defaultBatchSize
	}
	if c.FlushInterval <= 0 {
		c.FlushInterval = defaultFlushInterval
	}
	if c.Timeout <= 0 {
		c.Timeout = defaultTimeout
	}
	if c.MaxRetries <= 0 {
		c.MaxRetries = defaultMaxRetries
	}
}

// KillKrillSink buffers log events and periodically flushes them to the
// KillKrill ingestion endpoint via HTTP POST with retry and exponential backoff.
type KillKrillSink struct {
	cfg    KillKrillConfig
	client *http.Client

	mu     sync.Mutex
	buffer []map[string]interface{}

	stopCh chan struct{}
	wg     sync.WaitGroup
}

// NewKillKrillSink creates a KillKrillSink and starts a background flush goroutine.
// Call Close() to stop the goroutine and flush remaining events.
func NewKillKrillSink(cfg KillKrillConfig) *KillKrillSink {
	cfg.applyDefaults()

	s := &KillKrillSink{
		cfg:    cfg,
		client: &http.Client{Timeout: cfg.Timeout},
		buffer: make([]map[string]interface{}, 0, cfg.BatchSize),
		stopCh: make(chan struct{}),
	}

	s.wg.Add(1)
	go s.flushLoop()

	return s
}

// Write appends the event to the internal buffer, flushing immediately if the batch is full.
func (s *KillKrillSink) Write(event map[string]interface{}) error {
	s.mu.Lock()
	s.buffer = append(s.buffer, event)
	full := len(s.buffer) >= s.cfg.BatchSize
	s.mu.Unlock()

	if full {
		return s.Flush()
	}
	return nil
}

// Flush drains the buffer and sends all pending events to KillKrill.
func (s *KillKrillSink) Flush() error {
	s.mu.Lock()
	if len(s.buffer) == 0 {
		s.mu.Unlock()
		return nil
	}
	batch := s.buffer
	s.buffer = make([]map[string]interface{}, 0, s.cfg.BatchSize)
	s.mu.Unlock()

	return s.sendWithRetry(batch)
}

// Close stops the background goroutine and flushes any remaining events.
func (s *KillKrillSink) Close() error {
	close(s.stopCh)
	s.wg.Wait()
	return s.Flush()
}

func (s *KillKrillSink) flushLoop() {
	defer s.wg.Done()

	ticker := time.NewTicker(s.cfg.FlushInterval)
	defer ticker.Stop()

	for {
		select {
		case <-ticker.C:
			_ = s.Flush()
		case <-s.stopCh:
			return
		}
	}
}

func (s *KillKrillSink) sendWithRetry(batch []map[string]interface{}) error {
	var lastErr error

	for attempt := 0; attempt <= s.cfg.MaxRetries; attempt++ {
		if attempt > 0 {
			backoff := time.Duration(math.Pow(2, float64(attempt-1))) * 100 * time.Millisecond
			time.Sleep(backoff)
		}

		if err := s.send(batch); err != nil {
			lastErr = err
			continue
		}
		return nil
	}

	return fmt.Errorf("killkrill: all %d attempts failed, last error: %w", s.cfg.MaxRetries+1, lastErr)
}

func (s *KillKrillSink) send(batch []map[string]interface{}) error {
	payload, err := json.Marshal(batch)
	if err != nil {
		return fmt.Errorf("killkrill: marshal batch: %w", err)
	}

	url := s.cfg.Endpoint + eventsPath
	req, err := http.NewRequestWithContext(context.Background(), http.MethodPost, url, bytes.NewReader(payload))
	if err != nil {
		return fmt.Errorf("killkrill: build request: %w", err)
	}

	req.Header.Set("Content-Type", "application/json")
	req.Header.Set("Authorization", "Bearer "+s.cfg.APIKey)

	resp, err := s.client.Do(req)
	if err != nil {
		return fmt.Errorf("killkrill: http request: %w", err)
	}
	defer resp.Body.Close()

	if resp.StatusCode < 200 || resp.StatusCode >= 300 {
		return fmt.Errorf("killkrill: unexpected status %d", resp.StatusCode)
	}

	return nil
}
