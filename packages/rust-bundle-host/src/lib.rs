//! Waddles WASM app-bundle sandbox: the host-API wire frame codec shared by
//! a stage (`svc_process`, `svc_action`) and its executor, and the
//! `bundle.yaml` v2 manifest validator.
//!
//! This is the M1 `penguin-bundle-host::wire` + `::manifest` deliverable
//! (`docs/superpowers/specs/2026-09-14-rust-data-plane-design.md` §16 in the
//! `waddles` repo). See `README.md` for what is and is not in scope yet.

pub mod manifest;
pub mod wire;
