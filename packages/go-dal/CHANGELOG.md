# Changelog

## Unreleased

### Deprecated
- Module is deprecated: Go libraries are being phased out; use rust-dal (`packages/rust-dal`). No exported API removed or renamed.

### Toolchain
- go.mod now requires `go 1.26.0` / `toolchain go1.26.10`. Exception to the Go 1.25 baseline: the stdlib HTTP/2, TLS and x509 advisories are fixed only in go1.26.9+. Consumers on older toolchains must upgrade; previously published versions are unaffected.

### Dependencies
- klauspost/compress 1.17.9 -> 1.20.2 (GO-2026-6865), aws-sdk-go-v2 1.32.7 -> 1.47.8, service/s3 1.71.0 -> 1.114.9, eventstream 1.6.7 -> 1.7.26 (GO-2026-5764, GO-2025-3540), go-redis 9.7.0 -> 9.23.0, golang.org/x/{net 0.62.0, crypto 0.58.0, text 0.44.0, sys 0.50.0, sync 0.25.0}. Supersedes the go-dal portion of fix/dependency-cve-bumps, PR #139 and PR #88.

### Security
- MongoDB: filters and `UpdateOne` update documents (including pipeline-form updates) are screened for `$where`, `$function` and `$accumulator` at any depth; rejected with `ErrUnsafeFilter`.
- NFS: all file access is confined to an `os.Root`; `GetURL` builds its path through the same validated key and root logic.
- NFS: a zero-value `NFSStore{}` (nil root) now returns `ErrInvalidConfiguration` instead of panicking; construct stores with `NewNFSStore`.
- S3: reads are bounded by `MaxReadBytes`.

### Breaking
- Top-level `$text`, `$expr` and `$comment` filters (any top-level operator other than `$and`/`$or`/`$nor`) are now rejected. Wrap application-authored filters that need them in `document.Trusted(...)`. Never wrap filters built from request input.
- `UpdateOne` updates containing `$function`/`$accumulator`/`$where` are rejected; use `document.Trusted(...)` for application-authored updates.
