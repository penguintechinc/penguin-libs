package logging

import (
	"encoding/json"
	"fmt"
	"net"
	"os"
	"sync"
)

// Sink is the interface implemented by all log destinations.
type Sink interface {
	Write(event map[string]interface{}) error
	Flush() error
	Close() error
}

// StdoutSink writes JSON-encoded log events to os.Stdout.
type StdoutSink struct {
	mu      sync.Mutex
	encoder *json.Encoder
}

// NewStdoutSink creates a StdoutSink that writes to os.Stdout.
func NewStdoutSink() *StdoutSink {
	return &StdoutSink{
		encoder: json.NewEncoder(os.Stdout),
	}
}

// Write encodes the event as JSON and writes it to stdout.
func (s *StdoutSink) Write(event map[string]interface{}) error {
	s.mu.Lock()
	defer s.mu.Unlock()
	return s.encoder.Encode(event)
}

// Flush is a no-op for StdoutSink; stdout is unbuffered at this level.
func (s *StdoutSink) Flush() error { return nil }

// Close is a no-op for StdoutSink; the process owns stdout.
func (s *StdoutSink) Close() error { return nil }

// FileSink writes JSON-encoded log events to a file with simple size-based rotation.
// When the file exceeds maxSizeMB, it is renamed with a ".1" suffix and a fresh file is opened.
type FileSink struct {
	mu           sync.Mutex
	path         string
	maxSizeMB    int64
	file         *os.File
	writtenBytes int64
}

// NewFileSink opens (or creates) the file at path and returns a FileSink.
// maxSizeMB controls when rotation occurs; zero disables rotation.
func NewFileSink(path string, maxSizeMB int64) (*FileSink, error) {
	f, err := os.OpenFile(path, os.O_CREATE|os.O_APPEND|os.O_WRONLY, 0600)
	if err != nil {
		return nil, fmt.Errorf("open log file: %w", err)
	}

	info, err := f.Stat()
	if err != nil {
		_ = f.Close()
		return nil, fmt.Errorf("stat log file: %w", err)
	}

	return &FileSink{
		path:         path,
		maxSizeMB:    maxSizeMB,
		file:         f,
		writtenBytes: info.Size(),
	}, nil
}

// Write encodes the event as JSON and writes it to the file, rotating if needed.
func (s *FileSink) Write(event map[string]interface{}) error {
	// Pre-marshal to measure size before acquiring the lock so we can update
	// writtenBytes accurately without an extra Stat syscall.
	payload, err := json.Marshal(event)
	if err != nil {
		return fmt.Errorf("marshal log event: %w", err)
	}
	// json.Encoder.Encode appends a newline; account for it.
	lineSize := int64(len(payload)) + 1

	s.mu.Lock()
	defer s.mu.Unlock()

	if err := s.rotateIfNeeded(); err != nil {
		return err
	}

	if _, err := s.file.Write(append(payload, '\n')); err != nil {
		return err
	}

	s.writtenBytes += lineSize
	return nil
}

func (s *FileSink) rotateIfNeeded() error {
	if s.maxSizeMB <= 0 {
		return nil
	}
	if s.writtenBytes < s.maxSizeMB*1024*1024 {
		return nil
	}

	if err := s.file.Close(); err != nil {
		return fmt.Errorf("close log file for rotation: %w", err)
	}
	if err := os.Rename(s.path, s.path+".1"); err != nil {
		return fmt.Errorf("rename log file for rotation: %w", err)
	}

	f, err := os.OpenFile(s.path, os.O_CREATE|os.O_APPEND|os.O_WRONLY, 0600)
	if err != nil {
		return fmt.Errorf("open new log file after rotation: %w", err)
	}

	s.file = f
	s.writtenBytes = 0
	return nil
}

// Flush syncs the underlying file to disk.
func (s *FileSink) Flush() error {
	s.mu.Lock()
	defer s.mu.Unlock()
	return s.file.Sync()
}

// Close flushes and closes the underlying file.
func (s *FileSink) Close() error {
	s.mu.Lock()
	defer s.mu.Unlock()
	if err := s.file.Sync(); err != nil {
		return err
	}
	return s.file.Close()
}

// SyslogSink sends JSON-encoded log events over UDP to a syslog host.
type SyslogSink struct {
	mu   sync.Mutex
	conn net.Conn
}

// NewSyslogSink dials the given host:port over UDP and returns a SyslogSink.
func NewSyslogSink(hostPort string) (*SyslogSink, error) {
	conn, err := net.Dial("udp", hostPort)
	if err != nil {
		return nil, fmt.Errorf("dial syslog %s: %w", hostPort, err)
	}
	return &SyslogSink{conn: conn}, nil
}

// Write JSON-encodes the event and sends it as a single UDP datagram.
func (s *SyslogSink) Write(event map[string]interface{}) error {
	s.mu.Lock()
	defer s.mu.Unlock()

	payload, err := json.Marshal(event)
	if err != nil {
		return fmt.Errorf("marshal syslog event: %w", err)
	}

	_, err = s.conn.Write(payload)
	return err
}

// Flush is a no-op for SyslogSink; UDP datagrams are sent immediately.
func (s *SyslogSink) Flush() error { return nil }

// Close closes the underlying UDP connection.
func (s *SyslogSink) Close() error {
	s.mu.Lock()
	defer s.mu.Unlock()
	return s.conn.Close()
}

// CallbackSink invokes a user-provided function for each log event.
type CallbackSink struct {
	fn func(event map[string]interface{})
}

// NewCallbackSink creates a CallbackSink that calls fn on every Write.
func NewCallbackSink(fn func(event map[string]interface{})) *CallbackSink {
	return &CallbackSink{fn: fn}
}

// Write calls the user-provided callback with a shallow copy of the event map.
func (s *CallbackSink) Write(event map[string]interface{}) error {
	eventCopy := make(map[string]interface{}, len(event))
	for k, v := range event {
		eventCopy[k] = v
	}
	s.fn(eventCopy)
	return nil
}

// Flush is a no-op for CallbackSink.
func (s *CallbackSink) Flush() error { return nil }

// Close is a no-op for CallbackSink.
func (s *CallbackSink) Close() error { return nil }
