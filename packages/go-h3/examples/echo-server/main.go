// Command echo-server demonstrates a dual-protocol HTTP/2 + HTTP/3 server
// using ConnectRPC with the Echo service.
package main

import (
	"context"
	"fmt"
	"net/http"
	"os"
	"os/signal"
	"syscall"

	"connectrpc.com/connect"
	"go.uber.org/zap"

	"github.com/penguintechinc/penguin-libs/packages/go-h3/server"
)

func main() {
	logger, _ := zap.NewProduction()
	defer logger.Sync()

	cfg, err := server.ConfigFromEnv()
	if err != nil {
		logger.Fatal("failed to load config", zap.Error(err))
	}

	// Add interceptors.
	cfg.Interceptors = []connect.Interceptor{
		server.NewRecoveryInterceptor(logger),
		server.NewLoggingInterceptor(logger),
	}

	srv, err := server.New(cfg, logger)
	if err != nil {
		logger.Fatal("failed to create server", zap.Error(err))
	}

	// Register a simple echo handler at /echo.
	srv.Mux().HandleFunc("/echo", func(w http.ResponseWriter, r *http.Request) {
		msg := r.URL.Query().Get("msg")
		if msg == "" {
			msg = "hello"
		}
		w.Header().Set("Content-Type", "text/plain")
		fmt.Fprintf(w, "echo: %s (protocol: %s)\n", msg, r.Proto)
	})

	// Health check.
	srv.Mux().HandleFunc("/healthz", func(w http.ResponseWriter, _ *http.Request) {
		w.WriteHeader(http.StatusOK)
		fmt.Fprint(w, "ok")
	})

	ctx, cancel := signal.NotifyContext(context.Background(), syscall.SIGINT, syscall.SIGTERM)
	defer cancel()

	logger.Info("starting echo server")
	if err := srv.Start(ctx); err != nil {
		logger.Fatal("server error", zap.Error(err))
		os.Exit(1)
	}
}
