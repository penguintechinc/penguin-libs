// Copyright 2026 Penguin Tech Inc
// SPDX-License-Identifier: Apache-2.0

//! Discord connector: Gateway client (identify/heartbeat/dispatch parsing)
//! and REST message send.
//!
//! `receivers/discord_gateway.py` (the `waddles` repo) delegates its wire
//! protocol entirely to py-cord, so this crate implements Discord's public
//! Gateway v10 protocol directly rather than porting repo source — see
//! [`gateway`]'s module doc for exactly which fixtures are synthetic. The
//! REST sender ports `core/svc_action/bundles/discord_send_action.py`'s
//! status-code handling — see [`rest`]'s module doc.
//!
//! No Valkey or Postgres dependency — see
//! `docs/superpowers/specs/2026-09-14-rust-data-plane-design.md` §4.10 in
//! the `waddles` repo for the full connector design.

pub mod error;
pub mod gateway;
pub mod rest;

pub use error::DiscordError;

/// Crate version, sourced from Cargo.toml.
pub const VERSION: &str = env!("CARGO_PKG_VERSION");

#[cfg(test)]
mod tests {
    #[test]
    fn version_matches_workspace() {
        assert_eq!(super::VERSION, "0.1.0");
    }
}
