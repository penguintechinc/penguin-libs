# penguin:tools

Canonical WIT package for sandboxed WASM tools. See
`docs/superpowers/specs/2026-11-09-penguin-tools-design.md`.

- `provider` (export): `describe` + `call`, implemented by every tool module.
- `invoker`, `context`, `log`, `clock`, `feature-flags`, `kv`, `http`, `connector` (imports): host capabilities. Every call is grant-checked by the host.
- `world tool-module` links all of the above; product worlds extend it and never edit this package.

After changing any `.wit` file, regenerate the snapshot and review the diff:

    wasm-tools component wit wit/penguin-tools > wit/penguin-tools.golden.wit
    wit/check.sh
