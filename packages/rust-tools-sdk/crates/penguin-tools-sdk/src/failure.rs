use std::fmt;

/// Upper bound on a tool-defined failure message, matching the WIT contract.
pub const MAX_FAILURE_BYTES: usize = 512;

/// A tool-defined failure. The message is truncated to
/// [`MAX_FAILURE_BYTES`] on a UTF-8 boundary so it always fits the
/// `tool-error::failed` case. It must not contain secrets.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ToolFailure(String);

impl ToolFailure {
    /// Builds a failure, truncating over-long messages.
    pub fn new(message: impl Into<String>) -> Self {
        let mut message = message.into();
        if message.len() > MAX_FAILURE_BYTES {
            let mut end = MAX_FAILURE_BYTES;
            while !message.is_char_boundary(end) {
                end -= 1;
            }
            message.truncate(end);
        }
        Self(message)
    }

    /// The bounded message.
    pub fn message(&self) -> &str {
        &self.0
    }
}

impl fmt::Display for ToolFailure {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.write_str(&self.0)
    }
}

impl std::error::Error for ToolFailure {}
