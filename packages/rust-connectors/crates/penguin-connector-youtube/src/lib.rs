// Copyright 2026 Penguin Tech Inc
// SPDX-License-Identifier: Apache-2.0

//! YouTube connector — **scaffold, not yet implemented.**
//!
//! Design spec §4.10 (`docs/superpowers/specs/2026-09-14-rust-data-plane-design.md`
//! in the `waddles` repo) assigns this crate: a Data API v3 live-chat poll
//! `Receiver` with the existing no-broadcast/quota backoff behaviour, and a
//! `liveChatMessages.insert` `Sender`. YouTube's Data API has no inbound
//! webhook in this design, so this crate has no `verify_signature` — auth
//! is an API key or OAuth2 refresh-token trio.
//!
//! **Deferred to a follow-up wave** (M1 prioritized Twitch + Discord as the
//! highest-traffic platforms — see the `penguin-connectors` PR description
//! for the M1 completion table). Porting source for the eventual
//! implementation: `core/svc_ingest/receivers/youtube_live_poll.py` and
//! `core/svc_action/bundles/youtube_send_action.py` in the `waddles` repo.

/// Error type reserved for the eventual live-chat poll client + REST sender.
#[derive(Debug, thiserror::Error)]
pub enum YoutubeError {
    /// Placeholder variant — replaced with real error cases (quota
    /// exhaustion, no active broadcast, etc.) when the poll client lands.
    #[error("penguin-connector-youtube not yet implemented: {0}")]
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
