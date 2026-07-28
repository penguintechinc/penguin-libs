// Copyright 2026 Penguin Tech Inc
// SPDX-License-Identifier: Apache-2.0

package conformance

import (
	"context"
	"errors"
	"io"
	"net/http"
	"strings"

	"connectrpc.com/connect"

	conformancev1 "github.com/penguintechinc/penguin-libs/packages/go-rpc/gen/prpc/conformance/v1"
	"github.com/penguintechinc/penguin-libs/packages/go-rpc/gen/prpc/conformance/v1/conformancev1connect"
)

// ctxKeyProtocol is the unexported context key ProtocolMiddleware uses to
// stamp the negotiated HTTP transport major version. An unexported type
// scoped to this package prevents collisions with context values set by any
// other package — the standard context.WithValue idiom.
type ctxKeyProtocol struct{}

// ProtocolMiddleware stamps r.ProtoMajor into the request context before
// invoking next, so a handler running underneath it — including a Connect
// streaming handler, which never observes *http.Request directly — can
// later recover the negotiated transport version via protocolFromContext.
// See the package doc comment ("Protocol detection") for why this HTTP-level
// mechanism was chosen over connect.Request.Peer().Protocol.
func ProtocolMiddleware(next http.Handler) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		ctx := context.WithValue(r.Context(), ctxKeyProtocol{}, r.ProtoMajor)
		next.ServeHTTP(w, r.WithContext(ctx))
	})
}

// protocolFromContext returns "h3" when ctx carries a ProtocolMiddleware
// stamp of HTTP major version 3, and "h2" in every other case — an
// unstamped context, or a stamped major version 1 or 2. The pRPC transport
// model (spec/SPEC.md) is two-lane (HTTP/2 and HTTP/3); there is no third
// value for this field to report.
func protocolFromContext(ctx context.Context) string {
	if major, ok := ctx.Value(ctxKeyProtocol{}).(int); ok && major == 3 {
		return "h3"
	}
	return "h2"
}

// service implements conformancev1connect.ConformanceServiceHandler. It
// holds no state: every method is a pure function of its request (and, for
// the protocol field, the context ProtocolMiddleware stamped).
type service struct{}

// NewService returns a stateless prpc.conformance.v1.ConformanceService
// implementation exercising all four Connect call patterns: Unary,
// ServerStream, ClientStream, and BidiStream.
func NewService() conformancev1connect.ConformanceServiceHandler {
	return &service{}
}

// Register mounts the ConformanceService handler on mux at its generated
// path, wrapped in ProtocolMiddleware so every response's protocol field
// reflects the transport that actually served the request — for all four
// call patterns, since the wrap happens at the http.Handler level shared by
// unary and streaming RPCs alike. opts are passed through to the generated
// handler constructor unchanged; callers pass server.HandlerOptions() here
// to apply the shared MaxMessageBytes cap and interceptor chain.
func Register(mux *http.ServeMux, opts ...connect.HandlerOption) {
	path, handler := conformancev1connect.NewConformanceServiceHandler(NewService(), opts...)
	mux.Handle(path, ProtocolMiddleware(handler))
}

// Unary echoes request.message unmodified. repeat has no effect on this
// method — it only drives ServerStream's response count; the unary response
// is never repeated or otherwise transformed by it.
func (s *service) Unary(ctx context.Context, req *connect.Request[conformancev1.EchoRequest]) (*connect.Response[conformancev1.EchoResponse], error) {
	return connect.NewResponse(&conformancev1.EchoResponse{
		Message:  req.Msg.GetMessage(),
		Protocol: protocolFromContext(ctx),
	}), nil
}

// ServerStream sends request.message back request.repeat times. A zero
// repeat is treated as 1, so the stream always sends at least one message.
func (s *service) ServerStream(ctx context.Context, req *connect.Request[conformancev1.EchoRequest], stream *connect.ServerStream[conformancev1.EchoResponse]) error {
	repeat := req.Msg.GetRepeat()
	if repeat == 0 {
		repeat = 1
	}
	message := req.Msg.GetMessage()
	protocol := protocolFromContext(ctx)
	for i := uint32(0); i < repeat; i++ {
		if err := stream.Send(&conformancev1.EchoResponse{Message: message, Protocol: protocol}); err != nil {
			return err
		}
	}
	return nil
}

// ClientStream concatenates every received message's text, in receive
// order, into a single response. The 4 MiB cap that bounds the overall
// stream is enforced upstream by connect.WithReadMaxBytes (wired through
// server.HandlerOptions(), passed to Register as opts) — this method does
// not re-implement that limit; it only concatenates whatever the transport
// and validation layers already let through.
func (s *service) ClientStream(ctx context.Context, stream *connect.ClientStream[conformancev1.EchoRequest]) (*connect.Response[conformancev1.EchoResponse], error) {
	var sb strings.Builder
	for stream.Receive() {
		sb.WriteString(stream.Msg().GetMessage())
	}
	if err := stream.Err(); err != nil {
		return nil, err
	}
	return connect.NewResponse(&conformancev1.EchoResponse{
		Message:  sb.String(),
		Protocol: protocolFromContext(ctx),
	}), nil
}

// BidiStream echoes each received message back to the caller as it
// arrives — full duplex, one response per request message, in the order
// received. It returns cleanly (nil error) once the client half-closes its
// send side (Receive's error wraps io.EOF), and propagates any other error
// unchanged — including one produced by the caller cancelling its context,
// which unblocks the underlying connection read with a non-EOF error so
// this loop exits promptly instead of hanging.
func (s *service) BidiStream(ctx context.Context, stream *connect.BidiStream[conformancev1.EchoRequest, conformancev1.EchoResponse]) error {
	protocol := protocolFromContext(ctx)
	for {
		req, err := stream.Receive()
		if err != nil {
			if errors.Is(err, io.EOF) {
				return nil
			}
			return err
		}
		if err := stream.Send(&conformancev1.EchoResponse{Message: req.GetMessage(), Protocol: protocol}); err != nil {
			return err
		}
	}
}
