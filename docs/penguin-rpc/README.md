# penguin-rpc (pRPC)

## What is pRPC

pRPC (`prpc/1.0-draft`) is PenguinTech's open, Apache-2.0-licensed RPC framework — Connect RPC carried over HTTP/3/QUIC (with automatic HTTP/2 fallback) — designed to succeed gRPC for both service-to-service and client/agent-to-service traffic. It bakes in zero-trust identity on every request (SPIFFE mTLS or OIDC JWT), enforced proto3 contracts (`buf breaking`-gated, protovalidate CEL constraints), and first-class MCP/A2A agent-protocol mounting. Three batteries-included packages (Go, Python, Rust) implement the spec against a shared `proto/prpc` contract set; any conforming Connect client can call a conforming pRPC server without protocol translation.

Full specification: [spec/SPEC.md](../../spec/SPEC.md) (`prpc/1.0-draft`) · Trademark policy: [spec/TRADEMARKS.md](../../spec/TRADEMARKS.md)

## Packages

| Package | Language | Registry | Version | Status |
|---------|----------|----------|---------|--------|
| [go-rpc](../../packages/go-rpc) | Go | `go get github.com/penguintechinc/penguin-libs/packages/go-rpc` | 0.1.0 | Phase 0 scaffold |
| [penguin-rpc](../../packages/python-rpc) | Python | PyPI | 0.1.0 | Phase 0 scaffold |
| [penguin-rpc](../../packages/rust-rpc/crates/penguin-rpc) | Rust | crates.io | 0.1.0 | Phase 0 scaffold |
| [penguin-h3-tower](../../packages/rust-rpc/crates/penguin-h3-tower) | Rust | crates.io | 0.1.0 | Phase 0 scaffold |

## Roadmap

Phase 0 (Foundations — spec draft, licensing, scaffolding, CI/publish wiring) is complete on this branch. Remaining phases, from the design doc (`docs/superpowers/specs/2026-07-14-penguin-rpc-design.md` §Phases):

1. **Go reference implementation** — salvages `go-h3`.
2. **Python implementation.**
3. **Rust implementation** — `penguin-h3-tower` first.
4. **Ziti adapters + conformance matrix + published benchmarks.**
5. **Retirement** — delete `go-h3` with a `go-h3-final` tag, remove `penguin_libs.h3`, cut v0.1.0 releases, finish docs.

## Maintainers

Manual, console-only follow-ups not achievable via CI/CD or `gh` — required before the first tagged release of each package:

- **PyPI**: create a Trusted Publisher entry for `penguin-rpc` on PyPI (repo `penguintechinc/penguin-libs`, workflow `publish.yml`, environment `pypi-rpc`), and create the `pypi-rpc` GitHub Actions environment in repo settings (mirrors `pypi-aaa`, `pypi-dal`, `pypi-secrets`, `pypi-utils`, `pypi-pytest`).
- **crates.io**: create Trusted Publishing configuration for both the `penguin-h3-tower` and `penguin-rpc` crates (repo `penguintechinc/penguin-libs`, workflow `publish.yml`; the `publish-rust-rpc` job declares no GitHub Actions environment, so no environment needs to be created for it).
- Org rules `backend.md` (in the private `admin` rules repo, not this repo) still reference `go-h3`/`penguin-h3` as the H3 building blocks — update those references after Phase 5 retires `go-h3` and `penguin_libs.h3`.
