# Changelog

## Unreleased (patch)

### Security
- go.mod: `go 1.26.0` / `toolchain go1.26.10`. SECURITY EXCEPTION to the Go 1.25 standard: the stdlib HTTP/2 and TLS advisories (GO-2026-6603..6617, GO-2026-6809) are fixed only in go1.26.9+, and golang.org/x/net v0.60.0+ requires Go 1.26.
- Bumped golang.org/x/{net,text,crypto,sys} and google.golang.org/grpc (where present) to the latest fixed releases; govulncheck reports zero reachable vulnerabilities.

### Deprecated
- This Go module is DEPRECATED (never removed; published versions untouched). Security fixes continue as patch releases. No exported API was removed or renamed.
