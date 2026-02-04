package server

import (
	"context"
	"errors"
	"fmt"
	"net/http"
	"sync"

	"github.com/quic-go/quic-go/http3"
	"go.uber.org/zap"
)

// Server runs HTTP/2 and HTTP/3 listeners sharing the same mux.
type Server struct {
	cfg    Config
	mux    *http.ServeMux
	logger *zap.Logger
	mu     sync.Mutex
	h2     *http.Server
	h3     *http3.Server
}

// New creates a Server with the given config and logger.
// If logger is nil, a production zap logger is created.
func New(cfg Config, logger *zap.Logger) (*Server, error) {
	if logger == nil {
		var err error
		logger, err = zap.NewProduction()
		if err != nil {
			return nil, fmt.Errorf("creating logger: %w", err)
		}
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

// Start launches enabled listeners and blocks until ctx is cancelled.
// On context cancellation it performs graceful shutdown within GracePeriod.
func (s *Server) Start(ctx context.Context) error {
	s.mu.Lock()

	errc := make(chan error, 2)
	var wg sync.WaitGroup

	if s.cfg.H2Enabled {
		s.h2 = &http.Server{
			Addr:    s.cfg.H2Addr,
			Handler: s.mux,
		}
		if s.cfg.TLSConfig != nil {
			s.h2.TLSConfig = s.cfg.TLSConfig.Clone()
		}
		wg.Add(1)
		go func() {
			defer wg.Done()
			s.logger.Info("HTTP/2 server starting", zap.String("addr", s.cfg.H2Addr))
			var err error
			if s.cfg.TLSConfig != nil {
				err = s.h2.ListenAndServeTLS("", "")
			} else {
				err = s.h2.ListenAndServe()
			}
			if err != nil && !errors.Is(err, http.ErrServerClosed) {
				errc <- fmt.Errorf("h2 server: %w", err)
			}
		}()
	}

	if s.cfg.H3Enabled {
		if s.cfg.TLSConfig == nil {
			s.mu.Unlock()
			return fmt.Errorf("TLS config required for HTTP/3")
		}
		tlsCfg := s.cfg.TLSConfig.Clone()
		tlsCfg.NextProtos = []string{"h3"}

		s.h3 = &http3.Server{
			Addr:      s.cfg.H3Addr,
			Handler:   s.mux,
			TLSConfig: tlsCfg,
		}
		wg.Add(1)
		go func() {
			defer wg.Done()
			s.logger.Info("HTTP/3 server starting", zap.String("addr", s.cfg.H3Addr))
			if err := s.h3.ListenAndServe(); err != nil && !errors.Is(err, http.ErrServerClosed) {
				errc <- fmt.Errorf("h3 server: %w", err)
			}
		}()
	}

	s.mu.Unlock()

	// Wait for context cancellation or a fatal listener error.
	select {
	case <-ctx.Done():
		s.logger.Info("shutdown signal received")
	case err := <-errc:
		s.logger.Error("listener error, shutting down", zap.Error(err))
	}

	return s.shutdown()
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
		if err := s.h3.Close(); err != nil {
			errs = append(errs, fmt.Errorf("h3 shutdown: %w", err))
		}
	}
	return errors.Join(errs...)
}

// ListenAddr returns the actual listener address once started. Useful for tests
// using ":0" ports. Returns empty string if the listener has not started.
func (s *Server) ListenAddr(protocol string) string {
	s.mu.Lock()
	defer s.mu.Unlock()
	switch protocol {
	case "h2":
		if s.h2 != nil {
			return s.cfg.H2Addr
		}
	case "h3":
		if s.h3 != nil {
			return s.cfg.H3Addr
		}
	}
	return ""
}
