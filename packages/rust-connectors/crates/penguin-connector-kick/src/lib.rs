// Copyright 2026 Penguin Tech Inc
// SPDX-License-Identifier: Apache-2.0

//! Kick connector — **scaffold, not yet implemented.**
//!
//! Design spec §4.10 (`docs/superpowers/specs/2026-09-14-rust-data-plane-design.md`
//! in the `waddles` repo) assigns this crate: a Pusher-protocol chat
//! `Receiver` (one WS per channel slug, public Pusher app key), inbound
//! webhook `verify_signature` (HMAC-SHA256 over the raw body, fail-closed —
//! `X-Kick-Signature`, spec §10.1), and a REST `Sender`.
//!
//! **Deferred to a follow-up wave** (M1 prioritized Twitch + Discord as the
//! highest-traffic platforms — see the `penguin-connectors` PR description
//! for the M1 completion table). Porting source for the eventual
//! implementation: `core/svc_ingest/receivers/kick_pusher.py` and
//! `core/svc_action/bundles/kick_send_action.py` in the `waddles` repo.

/// Error type reserved for the eventual Pusher client, webhook verifier and
/// REST sender.
#[derive(Debug, thiserror::Error)]
pub enum KickError {
    /// Placeholder variant — replaced with real error cases when the
    /// Pusher client and webhook verification land.
    #[error("penguin-connector-kick not yet implemented: {0}")]
    NotImplemented(String),
}

/// Crate version, sourced from Cargo.toml.
pub const VERSION: &str = env!("CARGO_PKG_VERSION");

#[cfg(test)]
mod tests {
    #[test]
    fn version_matches_workspace() {
        assert_eq!(super::VERSION, "0.1.0");
    }
}
