// Copyright 2026 Penguin Tech Inc
// SPDX-License-Identifier: Apache-2.0

package server

import (
	"context"
	"crypto/tls"
	"errors"
	"fmt"
	"net"
	"net/http"
	"sync"
	"time"

	"connectrpc.com/connect"
	quic "github.com/quic-go/quic-go"
	"github.com/quic-go/quic-go/http3"
	"go.uber.org/zap"
)

const (
	// h2ReadHeaderTimeout bounds how long the H2 listener waits to read
	// request headers, mitigating Slowloris-style attacks (spec §3 does not
	// mandate a specific value; this is a conservative, connection-hygiene
	// default independent of the RPC-level DefaultUnaryTimeout).
	h2ReadHeaderTimeout = 10 * time.Second
	// h2IdleTimeout bounds how long an idle keep-alive H2 connection is held
	// open between requests.
	h2IdleTimeout = 120 * time.Second
)

// Server runs HTTP/2 and HTTP/3 listeners sharing the same mux.
type Server struct {
	cfg    Config
	mux    *http.ServeMux
	logger *zap.Logger

	mu     sync.Mutex
	h2     *http.Server
	h3     *http3.Server
	h3Conn net.PacketConn
	h2Addr string
	h3Addr string
}

// New creates a Server with the given config and logger. If logger is nil, a
// production zap logger is created. Zero-valued MaxMessageBytes and
// DefaultUnaryTimeout are defaulted to 4 MiB / 30s (spec §3). If
// cfg.TLSConfig is set, its MinVersion is forced to tls.VersionTLS13
// regardless of the caller-supplied value: TLS 1.2 and earlier MUST NOT be
// negotiated per spec §3.
func New(cfg Config, logger *zap.Logger) (*Server, error) {
	if logger == nil {
		var err error
		logger, err = zap.NewProduction()
		if err != nil {
			return nil, fmt.Errorf("creating logger: %w", err)
		}
	}

	if cfg.MaxMessageBytes == 0 {
		cfg.MaxMessageBytes = defaultMaxMessageBytes
	}
	if cfg.DefaultUnaryTimeout == 0 {
		cfg.DefaultUnaryTimeout = defaultUnaryTimeout
	}
	if cfg.TLSConfig != nil {
		cfg.TLSConfig.MinVersion = tls.VersionTLS13
	}

	return &Server{
		cfg:    cfg,
		mux:    http.NewServeMux(),
		logger: logger,
	}, nil
}

// Mux returns the underlying ServeMux for registering ConnectRPC handlers.
func (s *Server) Mux() *http.ServeMux {
	return s.mux
}

// HandlerOptions returns the ConnectRPC HandlerOptions every mounted service
// must apply: the configured MaxMessageBytes cap and the configured
// interceptor chain. Service registration (health, conformance, etc.) passes
// these to its generated NewXHandler constructor.
func (s *Server) HandlerOptions() []connect.HandlerOption {
	return []connect.HandlerOption{
		connect.WithReadMaxBytes(s.cfg.MaxMessageBytes),
		connect.WithInterceptors(s.cfg.Interceptors...),
	}
}

// newQUICConfig returns the QUIC configuration used for the HTTP/3 listener.
// 0-RTT is explicitly disabled (Allow0RTT: false) per spec §3: 0-RTT data is
// replayable and pRPC procedures are not guaranteed idempotent. This must be
// constructed explicitly — quic-go's http3.Server defaults to
// &quic.Config{Allow0RTT: true} when QUICConfig is left nil.
func newQUICConfig() *quic.Config {
	return &quic.Config{
		Allow0RTT: false,
	}
}

// Start launches the enabled listeners and blocks until ctx is cancelled or
// a listener fails fatally. On cancellation it performs a graceful shutdown.
func (s *Server) Start(ctx context.Context) error {
	s.mu.Lock()

	errc := make(chan error, 2)
	var wg sync.WaitGroup

	if s.cfg.H2Enabled {
		s.h2 = &http.Server{
			Addr:              s.cfg.H2Addr,
			Handler:           s.mux,
			ReadHeaderTimeout: h2ReadHeaderTimeout,
			IdleTimeout:       h2IdleTimeout,
		}
		if s.cfg.TLSConfig != nil {
			s.h2.TLSConfig = s.cfg.TLSConfig.Clone()
		}

		ln, err := net.Listen("tcp", s.cfg.H2Addr)
		if err != nil {
			s.mu.Unlock()
			return fmt.Errorf("h2 listen: %w", err)
		}
		s.h2Addr = ln.Addr().String()

		wg.Add(1)
		go func() {
			defer wg.Done()
			s.logger.Info("HTTP/2 server starting", zap.String("addr", s.h2Addr))
			var serveErr error
			if s.cfg.TLSConfig != nil {
				serveErr = s.h2.ServeTLS(ln, "", "")
			} else {
				serveErr = s.h2.Serve(ln)
			}
			if serveErr != nil && !errors.Is(serveErr, http.ErrServerClosed) {
				errc <- fmt.Errorf("h2 server: %w", serveErr)
			}
		}()
	}

	if s.cfg.H3Enabled {
		if s.cfg.TLSConfig == nil {
			s.mu.Unlock()
			return s.abortStartup(&wg, fmt.Errorf("TLS config required for HTTP/3"))
		}
		tlsCfg := s.cfg.TLSConfig.Clone()
		tlsCfg.NextProtos = []string{"h3"}

		s.h3 = &http3.Server{
			Addr:       s.cfg.H3Addr,
			Handler:    s.mux,
			TLSConfig:  tlsCfg,
			QUICConfig: newQUICConfig(),
		}

		pconn, err := net.ListenPacket("udp", s.cfg.H3Addr)
		if err != nil {
			s.mu.Unlock()
			return s.abortStartup(&wg, fmt.Errorf("h3 listen: %w", err))
		}
		s.h3Conn = pconn
		s.h3Addr = pconn.LocalAddr().String()

		wg.Add(1)
		go func() {
			defer wg.Done()
			s.logger.Info("HTTP/3 server starting", zap.String("addr", s.h3Addr))
			if serveErr := s.h3.Serve(pconn); serveErr != nil && !errors.Is(serveErr, http.ErrServerClosed) {
				errc <- fmt.Errorf("h3 server: %w", serveErr)
			}
		}()
	}

	s.mu.Unlock()

	select {
	case <-ctx.Done():
		s.logger.Info("shutdown signal received")
	case err := <-errc:
		s.logger.Error("listener error, shutting down", zap.Error(err))
	}

	shutdownErr := s.shutdown()
	wg.Wait()
	return shutdownErr
}

// abortStartup releases any listeners already opened during a partially
// failed Start call and waits for their serve goroutines to exit, so a
// startup error never leaks a bound socket. wg must be the WaitGroup Start
// used to track those goroutines; the mutex must NOT be held by the caller.
func (s *Server) abortStartup(wg *sync.WaitGroup, startErr error) error {
	s.mu.Lock()
	if s.h2 != nil {
		_ = s.h2.Close()
	}
	if s.h3Conn != nil {
		_ = s.h3Conn.Close()
	}
	s.mu.Unlock()
	wg.Wait()
	return startErr
}

func (s *Server) shutdown() error {
	s.mu.Lock()
	defer s.mu.Unlock()

	shutCtx, cancel := context.WithTimeout(context.Background(), s.cfg.GracePeriod)
	defer cancel()

	var errs []error
	if s.h2 != nil {
		s.logger.Info("shutting down HTTP/2 server")
		if err := s.h2.Shutdown(shutCtx); err != nil {
			errs = append(errs, fmt.Errorf("h2 shutdown: %w", err))
		}
	}
	if s.h3 != nil {
		s.logger.Info("shutting down HTTP/3 server")
		if err := s.h3.Shutdown(shutCtx); err != nil {
			errs = append(errs, fmt.Errorf("h3 shutdown: %w", err))
		}
		if s.h3Conn != nil {
			if err := s.h3Conn.Close(); err != nil {
				errs = append(errs, fmt.Errorf("h3 packet conn close: %w", err))
			}
		}
	}
	return errors.Join(errs...)
}

// ListenAddr returns the actual resolved listener address for "h2" or "h3"
// once Start has bound that listener (useful when Config uses ":0" wildcard
// ports, e.g. in tests). Returns "" if the listener has not started or the
// protocol name is unrecognized.
func (s *Server) ListenAddr(protocol string) string {
	s.mu.Lock()
	defer s.mu.Unlock()
	switch protocol {
	case "h2":
		return s.h2Addr
	case "h3":
		return s.h3Addr
	}
	return ""
}
