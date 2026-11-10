# Changelog

## Unreleased

### Deprecated
- Module is deprecated: Go libraries are being phased out; use penguin-logging (`packages/rust-logging`). No exported API removed or renamed.

### Toolchain
- go.mod now requires `go 1.26.0` / `toolchain go1.26.10`. Exception to the Go 1.25 baseline: the stdlib HTTP/2, TLS and x509 advisories (10 reachable) are fixed only in go1.26.9+. Consumers on older toolchains must upgrade; previously published versions are unaffected.

### Lint
- Fixed errcheck findings (killkrill.go, sinks_test.go).
