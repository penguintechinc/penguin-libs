// Copyright 2026 Penguin Tech Inc
// SPDX-License-Identifier: Apache-2.0

//! Twitch connector: IRC chat receive/send and EventSub webhook signature
//! verification.
//!
//! Ports `libs/waddle_transports/waddle_transports/transports/irc.py`'s
//! wire protocol and `core/svc_ingest/eventsub.py`'s HMAC verification
//! (both in the `waddles` repo) into a standalone crate with no Valkey or
//! Postgres dependency — see
//! `docs/superpowers/specs/2026-09-14-rust-data-plane-design.md` §4.10 for
//! the full connector design.
//!
//! **Deferred (documented gap, not silently dropped):** the Helix REST
//! client (shoutout) and the EventSub websocket client (the
//! `TWITCH_EVENTSUB_MODE` alternative to the webhook) are not implemented
//! in this pass. The IRC receiver/sender and the webhook verification path
//! (this crate's M1 scope) are complete and tested.

pub mod error;
pub mod eventsub;
pub mod irc;

pub use error::TwitchError;

/// Crate version, sourced from Cargo.toml.
pub const VERSION: &str = env!("CARGO_PKG_VERSION");

#[cfg(test)]
mod tests {
    #[test]
    fn version_matches_workspace() {
        assert_eq!(super::VERSION, "0.1.0");
    }
}
