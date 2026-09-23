# Changelog

All notable changes to `penguin-spine` are documented here.

## [Unreleased]

- Added the `binding` module: `compute_binding_mac`/`verify_binding`,
  `KeyRing`, `BindingError` (spec §5.11, D30). Reproduces
  `waddles core/svc_action/src/hop.rs`'s verified-correct
  `compute_mac`/`verify_mac` formula and keyring shape byte-for-byte, so
  that module can later swap onto this crate as a drop-in replacement.

Initial crate scaffold.
