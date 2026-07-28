# penguin-rpc Changelog

## [Unreleased]

Phase 0 (Foundations):

- `spec/SPEC.md` — pRPC specification draft (`prpc/1.0-draft`), Apache-2.0; `spec/TRADEMARKS.md` — trademark policy.
- `proto/prpc/health/v1` and `proto/prpc/conformance/v1` contracts, with protovalidate constraints and a `buf breaking` CI gate on the proto package.
- Three package scaffolds, all versioned `0.1.0`, Apache-2.0 licensed: `packages/go-rpc` (Go module), `packages/python-rpc` (PyPI `penguin-rpc`), `packages/rust-rpc` (crates.io `penguin-rpc` + `penguin-h3-tower`).
- `Makefile` targets for all three packages (`build`, `lint`, `test`, `security`) plus `prpc-proto` (buf lint/breaking/format-check).
- `.github/workflows/prpc-packages.yml` — buf breaking merge gate; `ci.yml` build jobs for all three packages.
- `.github/workflows/publish.yml` — tag-driven publish/validate jobs: `publish-python-rpc` (PyPI, tag `penguin-rpc-v*`), `validate-go-rpc` (tag `go-rpc-v*`), `publish-rust-rpc` (crates.io, tag `rust-rpc-v*`).
