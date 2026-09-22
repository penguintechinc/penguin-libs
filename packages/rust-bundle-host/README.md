# penguin-bundle-host

Two pieces of the Waddles WASM app-bundle sandbox that every side of the
system (stage, executor, `bundle-compiler`) must agree on byte-for-byte:

- `wire` — the host-API frame codec between a Waddles stage (`svc_process`,
  `svc_action`) and its executor: a 4-byte big-endian length prefix followed
  by that many bytes of UTF-8 JSON, multiplexed by a monotonically
  increasing correlation id (spec §6.6, assumption A3).
- `manifest` — the `bundle.yaml` v2 parser and its 31 numbered validation
  rules (spec §6.4.4), matching
  `waddlebot/libs/flask_core/flask_core/app_manifest.py`'s reason-code
  contract so a rejected bundle reports the same machine-checkable reason
  everywhere it is validated.

Full design: `docs/superpowers/specs/2026-09-14-rust-data-plane-design.md`
in the `waddles` repo, §5, §6.4, §6.6, §7, §16 (M1 row).

## Scope of this crate today

This is the M1 `penguin-bundle-host::wire` + `::manifest` deliverable only.
The stage-side host capability implementations (`host::http`/`kv`/`db`/...),
the executor's wasmtime runtime, and the `bundle-executor` binary are a
separate, later milestone (M1c and beyond) and are **not** part of this
crate yet — it has no `wasmtime`, `object_store`, or database dependency of
any kind, and compiles and tests in isolation from every other M1 crate.

## Development

```bash
cargo build
cargo test
cargo clippy --all-targets -- -D warnings
cargo fmt --check
cargo llvm-cov --fail-under-lines 90
cargo deny check
```
