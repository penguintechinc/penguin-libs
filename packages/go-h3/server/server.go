package server

import (
	"context"
	"errors"
	"fmt"
	"net"
	"net/http"
	"sync"
	"time"

	"github.com/quic-go/quic-go"
	"github.com/quic-go/quic-go/http3"
	"go.uber.org/zap"
)

// Server runs HTTP/2 and HTTP/3 listeners sharing the same mux.
// The HTTP/3 side owns its own socket internally via http3.Server, so only the
// HTTP/2 listener is held here (h2ln) to expose the actual bound address.
type Server struct {
	cfg    Config
	mux    *http.ServeMux
	logger *zap.Logger
	mu     sync.Mutex
	h2     *http.Server
	h2ln   net.Listener // H2 listener, retained for capturing the bound address
	h3     *http3.Server
}

// New creates a Server with the given config and logger.
// If logger is nil, a production zap logger is created.
// Timeouts are set to secure defaults if zero-valued in cfg.
func New(cfg Config, logger *zap.Logger) (*Server, error) {
	if logger == nil {
		var err error
		logger, err = zap.NewProduction()
		if err != nil {
			return nil, fmt.Errorf("creating logger: %w", err)
		}
	}

	// Apply secure floor values for timeouts to prevent Slowloris attacks
	// These defaults are applied even if caller passes Config{}
	if cfg.ReadHeaderTimeout == 0 {
		cfg.ReadHeaderTimeout = 10 * time.Second
	}
	if cfg.ReadTimeout == 0 {
		cfg.ReadTimeout = 30 * time.Second
	}
	if cfg.WriteTimeout == 0 {
		cfg.WriteTimeout = 30 * time.Second
	}
	if cfg.IdleTimeout == 0 {
		cfg.IdleTimeout = 60 * time.Second
	}
	if cfg.QUICMaxIdleTimeout == 0 {
		cfg.QUICMaxIdleTimeout = 60 * time.Second
	}
	if cfg.GracePeriod == 0 {
		cfg.GracePeriod = 30 * time.Second
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

// validate reports any configuration problem that must prevent startup.
// Every precondition check belongs here so Start can reject a bad config
// before it binds anything and cannot leak a listener on the error path.
func (c Config) validate() error {
	if c.H3Enabled && c.TLSConfig == nil {
		return errors.New("TLS config required for HTTP/3")
	}
	return nil
}

// Start launches enabled listeners and blocks until ctx is cancelled.
// On context cancellation it performs graceful shutdown within GracePeriod.
func (s *Server) Start(ctx context.Context) error {
	if err := s.cfg.validate(); err != nil {
		return err
	}

	errc := make(chan error, 2)
	if err := s.listen(errc); err != nil {
		return err
	}

	// Wait for context cancellation or a fatal listener error.
	select {
	case <-ctx.Done():
		s.logger.Info("shutdown signal received")
	case err := <-errc:
		s.logger.Error("listener error, shutting down", zap.Error(err))
	}

	return s.shutdown()
}

// listen binds every enabled protocol and starts serving, reporting fatal
// serve errors on errc. Serving begins only after all binds have succeeded,
// and any listener already bound is released if a later step fails, so an
// error return never leaves a port bound.
func (s *Server) listen(errc chan<- error) (err error) {
	s.mu.Lock()
	defer s.mu.Unlock()

	defer func() {
		if err != nil {
			s.releaseLocked()
		}
	}()

	if s.cfg.H2Enabled {
		ln, lerr := net.Listen("tcp", s.cfg.H2Addr)
		if lerr != nil {
			return fmt.Errorf("h2 listen: %w", lerr)
		}
		s.h2ln = ln
		s.h2 = &http.Server{
			Handler:           s.mux,
			ReadHeaderTimeout: s.cfg.ReadHeaderTimeout,
			ReadTimeout:       s.cfg.ReadTimeout,
			WriteTimeout:      s.cfg.WriteTimeout,
			IdleTimeout:       s.cfg.IdleTimeout,
		}
		if s.cfg.TLSConfig != nil {
			s.h2.TLSConfig = s.cfg.TLSConfig.Clone()
		}
	}

	if s.cfg.H3Enabled {
		tlsCfg := s.cfg.TLSConfig.Clone()
		tlsCfg.NextProtos = []string{"h3"}

		s.h3 = &http3.Server{
			Addr:      s.cfg.H3Addr,
			Handler:   s.mux,
			TLSConfig: tlsCfg,
			QUICConfig: &quic.Config{
				MaxIdleTimeout: s.cfg.QUICMaxIdleTimeout,
			},
		}
	}

	// Everything is bound; nothing below returns an error, so the serve
	// goroutines cannot outlive a failed Start. They read locals rather than
	// server fields so cleanup can never race with them.
	if s.h2 != nil {
		h2, ln, useTLS := s.h2, s.h2ln, s.cfg.TLSConfig != nil
		go func() {
			s.logger.Info("HTTP/2 server starting", zap.String("addr", ln.Addr().String()))
			var serveErr error
			if useTLS {
				serveErr = h2.ServeTLS(ln, "", "")
			} else {
				serveErr = h2.Serve(ln)
			}
			if serveErr != nil && !errors.Is(serveErr, http.ErrServerClosed) {
				errc <- fmt.Errorf("h2 server: %w", serveErr)
			}
		}()
	}
	if s.h3 != nil {
		h3, addr := s.h3, s.cfg.H3Addr
		go func() {
			s.logger.Info("HTTP/3 server starting", zap.String("addr", addr))
			if serveErr := h3.ListenAndServe(); serveErr != nil && !errors.Is(serveErr, http.ErrServerClosed) {
				errc <- fmt.Errorf("h3 server: %w", serveErr)
			}
		}()
	}

	return nil
}

// releaseLocked closes whatever a failed listen call already bound and resets
// the server back to its pre-start state. Callers must hold s.mu.
func (s *Server) releaseLocked() {
	if s.h2ln != nil {
		if cerr := s.h2ln.Close(); cerr != nil && !errors.Is(cerr, net.ErrClosed) {
			s.logger.Error("closing HTTP/2 listener after failed start", zap.Error(cerr))
		}
		s.h2ln = nil
	}
	s.h2 = nil
	s.h3 = nil
}

func (s *Server) shutdown() error {
	s.mu.Lock()
	defer s.mu.Unlock()

	shutCtx, cancel := context.WithTimeout(context.Background(), s.cfg.GracePeriod)
	defer cancel()

	var errs []error
	if s.h2 != nil {
		// h2 and h2ln are always set together by listen, and Shutdown closes
		// the listener, so h2ln needs no separate close here.
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
// For H2, returns the bound address from the listener; for H3, returns the config value.
func (s *Server) ListenAddr(protocol string) string {
	s.mu.Lock()
	defer s.mu.Unlock()
	switch protocol {
	case "h2":
		if s.h2ln != nil {
			return s.h2ln.Addr().String()
		}
	case "h3":
		if s.h3 != nil {
			return s.cfg.H3Addr
		}
	}
	return ""
}
