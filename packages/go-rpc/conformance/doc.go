// Copyright 2026 Penguin Tech Inc
// SPDX-License-Identifier: Apache-2.0

// Package conformance implements prpc.conformance.v1.ConformanceService: a
// reference echo service exercising all four Connect call patterns (unary,
// server-streaming, client-streaming, bidirectional-streaming) so the pRPC
// integration matrix (Task 10) can assert end-to-end behavior — including
// which transport lane served a request — over both HTTP/2 and HTTP/3.
//
// # Protocol detection
//
// Every EchoResponse carries protocol = "h3" when the request arrived over
// HTTP/3, else "h2" (spec/SPEC.md's two-lane transport model — there is no
// third value). connect-go v1.20.0's (*connect.Request[T]).Peer().Protocol
// was considered and rejected as the detection mechanism: it reports the
// Connect *wire* protocol — one of connect.ProtocolConnect,
// connect.ProtocolGRPC, connect.ProtocolGRPCWeb (connect.go / protocol.go;
// see newPeerForURL's call sites in protocol_connect.go and
// protocol_grpc.go) — never the underlying HTTP transport major version, so
// it cannot distinguish HTTP/3 from HTTP/2. Separately, the generated
// streaming handler signatures (ServerStream, ClientStream, BidiStream)
// never receive an *http.Request at all — only a context.Context and a
// typed connect.ServerStream/ClientStream/BidiStream wrapping a
// connect.StreamingHandlerConn — so there is no per-method surface to read
// r.ProtoMajor from even if a caller wanted to.
//
// This package instead uses an HTTP-level middleware, ProtocolMiddleware,
// that reads r.ProtoMajor — the one place the negotiated transport version
// is authoritatively known — and stamps it into the request context before
// the generated Connect handler ever runs; protocolFromContext reads that
// stamped value back out inside every RPC method. Register wraps the
// generated handler in ProtocolMiddleware unconditionally, so the mechanism
// is active identically for all four call patterns: net/http invokes
// ServeHTTP exactly once per request (unary or streaming — a stream is just
// a longer-lived request/response body), so a single HTTP-level wrap covers
// every method without per-method plumbing, and without needing connect-go
// to expose *http.Request through its typed stream wrappers.
package conformance
