# Penguin RPC (pRPC) — Go Implementation

Penguin RPC (pRPC) is the Go implementation of the pRPC specification (spec/SPEC.md), providing a high-performance, zero-trust Connect RPC framework over HTTP/3 (QUIC) with automatic HTTP/2 fallback. It enables secure service-to-service communication with zero-trust authentication defaults and built-in support for mounting MCP and A2A (application-to-application) agent protocols.

## Status

**Phase 0 scaffold** — Core module structure with version constant. APIs (server, client, auth, mcp, a2a, health, ziti) land in Phase 1.

## Installation

```bash
go get github.com/penguintechinc/penguin-libs/packages/go-rpc
```

## License & Trademark

This module is licensed under [Apache License 2.0](LICENSE). See [NOTICE](NOTICE) for copyright and attribution.

**Penguin RPC** is a trademark of Penguin Tech Inc.  
Visit [https://www.penguintech.io](https://www.penguintech.io) for more information.
