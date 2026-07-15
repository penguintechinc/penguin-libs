# Penguin RPC (pRPC) — Go Implementation

Penguin RPC (pRPC) is a high-performance, zero-trust Connect RPC framework over HTTP/3 with HTTP/2 fallback, enabling secure service-to-service communication with built-in support for interceptors, MCP mounting, and A2A (application-to-application) authentication. The Go implementation provides native async networking with XDP/AF_XDP support for ultra-low latency packet processing on capable platforms, and graceful degradation to standard Go net on systems without networking privileges.

## Status

**Phase 0 scaffold** — Core module structure with version constant. APIs (server, client, auth, mcp, a2a, health, ziti) land in Phase 1.

## Installation

```bash
go get github.com/penguintechinc/penguin-libs/packages/go-rpc@go-rpc-v0.1.0
```

## License & Trademark

This module is licensed under [Apache License 2.0](LICENSE). See [NOTICE](NOTICE) for copyright and attribution.

**Penguin RPC** is a trademark of Penguin Tech Inc.  
Visit [https://www.penguintech.io](https://www.penguintech.io) for more information.
