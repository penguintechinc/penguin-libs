//! A small metrics callback surface so this crate never depends on a Rust
//! OTel/logging crate — none exists yet (`penguin-logging` is a known gap,
//! `backend-rust.md`). Callers implement [`SpineMetrics`] against whatever
//! backend their service already uses and pass it into
//! [`crate::SpineClient::connect`]/[`crate::GroupReader::connect`].

/// Callback surface for the spine-owned metric names the spec defines
/// (Sec13.1). Every method has a default no-op body — a caller overrides
/// only the signals it cares about. Object-safe: pass as
/// `Arc<dyn SpineMetrics>`.
pub trait SpineMetrics: Send + Sync {
    /// `waddles_stream_events_total{platform,source_id}` +1 — one `XADD`.
    fn stream_event_written(&self, _platform: &str, _source_id: &str) {}
    /// `waddles_stream_trimmed_total{stream}` +1 — an `XADD`'s `MAXLEN ~` evicted an entry.
    fn stream_trimmed(&self, _stream: &str) {}
    /// `waddles_stream_claimed_total{app_id}` +1 — an `XAUTOCLAIM` recovered an entry.
    fn stream_claimed(&self, _app_id: &str) {}
    /// `waddles_consumer_skipped_total{app_id,reason}` +1 — read and acked, no executor call.
    fn consumer_skipped(&self, _app_id: &str, _reason: &str) {}
    /// `waddles_spine_dlq_total{stage,reason}` +1.
    fn dlq_written(&self, _stage: &str, _reason: &str) {}
    /// `waddles_group_lag{app_id,stream}`, from `XINFO GROUPS`; `None` when
    /// the server doesn't report a lag value for that group.
    fn group_lag(&self, _app_id: &str, _stream: &str, _lag: Option<u64>) {}
    /// `waddles_group_pending{app_id,stream}` — the group's PEL size.
    fn group_pending(&self, _app_id: &str, _stream: &str, _pending: u64) {}
    /// `waddles_insecure_transport{component,aspect}` set to 1 (insecure)
    /// or 0 (secure) — `0` must be reported explicitly so "no series" and
    /// "secure" stay distinguishable (spec Sec11.6.4).
    fn insecure_transport(&self, _component: &str, _aspect: &str, _insecure: bool) {}
    /// `waddles_tenant_boundary_violations_total{stage,reason}` +1 — a
    /// Sec5.11 hop-verification failure (D30): `reason` is one of
    /// `mac_mismatch`, `unknown_kid`, `tenant_mismatch`,
    /// `community_mismatch`, `grant_scope_mismatch`,
    /// `approval_scope_mismatch`, `bundle_set_identity` (the
    /// `BoundaryError` variants the `binding` module defines, Task 19).
    fn tenant_boundary_violation(&self, _stage: &str, _reason: &str) {}
}

/// A [`SpineMetrics`] implementation that records nothing — the default
/// for tests, and for any caller not yet wired to a metrics backend.
#[derive(Debug, Clone, Copy, Default)]
pub struct NoopMetrics;

impl SpineMetrics for NoopMetrics {}

#[cfg(test)]
mod tests {
    #![allow(clippy::unwrap_used)]
    use super::*;
    use std::sync::{Arc, Mutex};

    #[derive(Default)]
    struct RecordingMetrics {
        calls: Mutex<Vec<String>>,
    }

    impl SpineMetrics for RecordingMetrics {
        fn stream_event_written(&self, platform: &str, source_id: &str) {
            self.calls
                .lock()
                .unwrap()
                .push(format!("stream_event_written({platform},{source_id})"));
        }
        fn dlq_written(&self, stage: &str, reason: &str) {
            self.calls
                .lock()
                .unwrap()
                .push(format!("dlq_written({stage},{reason})"));
        }
    }

    #[test]
    fn noop_metrics_implements_the_trait_as_a_trait_object() {
        let metrics: Arc<dyn SpineMetrics> = Arc::new(NoopMetrics);
        // Every method must be callable without panicking; the point of
        // NoopMetrics is that nothing observable happens.
        metrics.stream_event_written("twitch", "tw-channelA");
        metrics.stream_trimmed("waddles:t:acme:c:main:src:twitch:tw-channelA:events");
        metrics.stream_claimed("waddles.bot.commands.default");
        metrics.consumer_skipped("waddles.bot.commands.default", "event_type");
        metrics.dlq_written("process", "call_timeout");
        metrics.group_lag("waddles.bot.commands.default", "some-stream", Some(3));
        metrics.group_lag("waddles.bot.commands.default", "some-stream", None);
        metrics.group_pending("waddles.bot.commands.default", "some-stream", 0);
        metrics.insecure_transport("valkey", "tls", false);
        metrics.tenant_boundary_violation("process", "tenant_mismatch");
    }

    #[test]
    fn a_real_implementation_only_overrides_what_it_needs() {
        let concrete = Arc::new(RecordingMetrics::default());
        let metrics: Arc<dyn SpineMetrics> = concrete.clone();
        metrics.stream_event_written("discord", "dg-guildX");
        metrics.dlq_written("action", "max_deliveries");
        // Unoverridden methods still no-op cleanly.
        metrics.stream_trimmed("irrelevant-here");

        let calls = concrete.calls.lock().unwrap();
        assert_eq!(
            *calls,
            vec![
                "stream_event_written(discord,dg-guildX)".to_string(),
                "dlq_written(action,max_deliveries)".to_string(),
            ]
        );
    }
}
