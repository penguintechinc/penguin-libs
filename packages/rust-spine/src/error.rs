//! Placeholder — full definition lands in Task 5.

/// Placeholder error type; replaced with the full `thiserror` enum in Task 5.
#[derive(Debug, thiserror::Error)]
pub enum SpineError {
    /// A configuration or usage error not covered by a more specific variant yet.
    #[error("{0}")]
    Config(String),
}
