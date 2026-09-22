// Copyright 2026 Penguin Tech Inc
// SPDX-License-Identifier: Apache-2.0

//! Slack connector — **scaffold, not yet implemented.**
//!
//! Design spec §4.10 (`docs/superpowers/specs/2026-09-14-rust-data-plane-design.md`
//! in the `waddles` repo) assigns this crate: a Socket Mode `Receiver`
//! (`SLACK_APP_TOKEN` + `SLACK_BOT_TOKEN`, single-owner leased WS) and a
//! `chat.postMessage` `Sender`. Slack's Socket Mode does not carry a
//! per-message HMAC the way Twitch EventSub/Kick webhooks do, so this
//! crate has no `verify_signature` — auth is the two bot/app tokens.
//!
//! **Deferred to a follow-up wave** (M1 prioritized Twitch + Discord as the
//! highest-traffic platforms — see the `penguin-connectors` PR description
//! for the M1 completion table). Porting source for the eventual
//! implementation: `core/svc_ingest/receivers/slack_socket.py` and
//! `core/svc_action/bundles/slack_send_action.py` in the `waddles` repo.

/// Error type reserved for the eventual Socket Mode client + REST sender.
#[derive(Debug, thiserror::Error)]
pub enum SlackError {
    /// Placeholder variant — replaced with real error cases when the
    /// Socket Mode client and REST sender land.
    #[error("penguin-connector-slack not yet implemented: {0}")]
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
