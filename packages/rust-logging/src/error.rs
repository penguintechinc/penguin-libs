//! Crate-wide error types. Every fallible function this crate exposes
//! outside of best-effort telemetry bootstrap (which logs and degrades
//! rather than failing -- see `rules/critical-rules.md` Observability, "A
//! dead exporter never breaks the app") returns one of these.

/// Failures rendering the Prometheus `/metrics` exposition body.
#[derive(Debug, thiserror::Error)]
pub enum MetricsRenderError {
    /// The `prometheus` crate could not encode the gathered metric
    /// families into the text exposition format.
    #[error("failed to encode metrics: {0}")]
    Encode(#[from] prometheus::Error),
    /// The encoded exposition body was not valid UTF-8 -- should be
    /// unreachable in practice (the Prometheus text format is ASCII), kept
    /// as a typed error rather than an `.unwrap()` on principle.
    #[error("metrics output was not valid UTF-8: {0}")]
    Utf8(#[from] std::string::FromUtf8Error),
}
