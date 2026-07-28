# go-rpc examples

Two runnable binaries demonstrating the pRPC server and client stacks
end-to-end. They mirror the non-auth wiring
[`integration/integration_test.go`](../integration/integration_test.go)
establishes — self-signed TLS, both the H2 and H3 listeners, the default
interceptor chain plus protovalidate, and the `ConformanceService` +
`HealthService` registered on the shared mux — trimmed down to skip
auth/MCP/A2A so the example stays small and anonymous-friendly.

## echo-server

Serves `ConformanceService` and `HealthService` over both HTTP/2 (`127.0.0.1:8080`
by default) and HTTP/3 (`127.0.0.1:8443` by default), using an ephemeral
self-signed TLS certificate. On startup it writes that certificate (PEM) to a
temp file so `echo-client` can build a real trust chain against it — it never
falls back to skipping TLS verification.

```bash
go run ./examples/echo-server
```

Flags (all also settable via env var, flag wins if both are set):

| Flag          | Env var               | Default                                       |
|---------------|------------------------|------------------------------------------------|
| `-h2-addr`    | `H2_ADDR`               | `127.0.0.1:8080`                                |
| `-h3-addr`    | `H3_ADDR`               | `127.0.0.1:8443`                                |
| `-cert-file`  | `PRPC_ECHO_CERT_FILE`   | `$TMPDIR/prpc-echo-server-cert.pem`             |

Stop it with `Ctrl+C` (SIGINT) or SIGTERM — it shuts down gracefully and
removes the cert file it wrote.

## echo-client

Connects with the H3 lane preferred (automatic fallback to H2 per the
client's own lane-router config), calls `ConformanceService.Unary` once with
a sample message, and prints the echoed message plus
`EchoResponse.protocol` — so a successful run visibly shows whether the
request was actually served over `h3` or `h2`.

```bash
go run ./examples/echo-client
```

Flags (env var equivalents in parentheses):

| Flag          | Env var               | Default                                       |
|---------------|------------------------|------------------------------------------------|
| `-addr`       | `PRPC_ECHO_ADDR`        | `127.0.0.1:8443` (matches echo-server's `-h3-addr`) |
| `-ca-file`    | `PRPC_ECHO_CERT_FILE`   | `$TMPDIR/prpc-echo-server-cert.pem`             |
| `-message`    | —                       | `hello from pRPC echo-client`                   |

On success it exits 0 having printed `echo: ...` and `protocol: ...`. On any
setup or RPC error it prints to stderr and exits 1 — including if
`echo-server` isn't running yet (the cert file won't exist).

## Running both together

```bash
# terminal 1
go run ./examples/echo-server

# terminal 2 (after echo-server logs "echo-server listening")
go run ./examples/echo-client
```

Notes:

- **HTTP/3 needs UDP.** The H3 lane is QUIC over UDP, so the H3 port
  (`8443` by default) must be reachable over UDP locally, not just TCP — a
  sandboxed or firewalled environment that blocks UDP will not be able to
  complete an H3 request (the client has no H2 listener to fall back to at
  the same port, since echo-server binds H2 and H3 on different ports by
  default). Point `echo-client -addr` at echo-server's `-h2-addr` value
  instead to exercise the H2 lane directly.
- **Self-signed TLS is for local demo use only.** `server.SelfSignedTLSConfig`
  mints a fresh, ephemeral certificate on every `echo-server` run — it is
  never appropriate for production traffic. See its doc comment in
  [`../server/tls.go`](../server/tls.go).
- These binaries compile as part of the module's standard `go build ./...`
  (see `build-go-rpc` in CI) — no separate build step is required.
