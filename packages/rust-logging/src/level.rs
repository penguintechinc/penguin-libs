//! Runtime-reloadable log level, matching `penguintechinc_utils.logging`'s
//! `LOG_LEVEL` contract (`error`/`warn`/`info`/`debug`) and
//! `rules/critical-rules.md` Observability's "Level is a deliberate choice
//! per line" -- operators change verbosity without a restart.

use tracing_subscriber::filter::EnvFilter;
use tracing_subscriber::reload;
use tracing_subscriber::Registry;

/// Every error this module can produce.
#[derive(Debug, thiserror::Error)]
pub enum LevelError {
    /// `LOG_LEVEL` (or a runtime [`LevelHandle::set_level`] argument) was
    /// not one of `error`/`warn`/`info`/`debug`.
    #[error("invalid log level {0:?}: expected one of error, warn, info, debug")]
    InvalidLevel(String),
    /// The reload handle's target subscriber has already been dropped.
    #[error("log level reload failed: {0}")]
    ReloadFailed(String),
}

/// Parses the four levels this crate supports into an [`EnvFilter`]
/// directive string. Rejecting anything else (rather than forwarding
/// arbitrary `EnvFilter` syntax) keeps `LOG_LEVEL` a small, documented
/// contract instead of an accidental passthrough for filter expressions.
fn parse_level(level: &str) -> Result<EnvFilter, LevelError> {
    match level.to_lowercase().as_str() {
        "error" | "warn" | "info" | "debug" => Ok(EnvFilter::new(level.to_lowercase())),
        other => Err(LevelError::InvalidLevel(other.to_string())),
    }
}

/// A handle allowing a running service to change its log level at runtime
/// (e.g. from an admin endpoint) without restarting the process. Cloning is
/// cheap -- it shares the same underlying [`reload::Handle`].
#[derive(Clone)]
pub struct LevelHandle {
    handle: reload::Handle<EnvFilter, Registry>,
}

impl LevelHandle {
    /// Wraps a `tracing_subscriber` reload handle. Internal to this crate;
    /// callers obtain a `LevelHandle` from [`crate::telemetry::init`].
    pub(crate) fn new(handle: reload::Handle<EnvFilter, Registry>) -> Self {
        Self { handle }
    }

    /// Reloads the active filter to `level` (`error`/`warn`/`info`/`debug`).
    /// Returns [`LevelError::InvalidLevel`] for anything else, and
    /// [`LevelError::ReloadFailed`] if the underlying subscriber is gone.
    pub fn set_level(&self, level: &str) -> Result<(), LevelError> {
        let filter = parse_level(level)?;
        self.handle
            .reload(filter)
            .map_err(|err| LevelError::ReloadFailed(err.to_string()))
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use rstest::rstest;
    use tracing_subscriber::layer::SubscriberExt as _;

    #[rstest]
    #[case("error")]
    #[case("warn")]
    #[case("info")]
    #[case("debug")]
    #[case("DEBUG")]
    fn parse_level_accepts_known_levels(#[case] level: &str) {
        assert!(parse_level(level).is_ok());
    }

    #[rstest]
    #[case("")]
    #[case("trace")]
    #[case("verbose")]
    #[case("info,my_crate=debug")]
    fn parse_level_rejects_everything_else(#[case] level: &str) {
        assert!(matches!(
            parse_level(level),
            Err(LevelError::InvalidLevel(_))
        ));
    }

    #[test]
    fn set_level_round_trips_through_a_real_reload_handle() {
        let (layer, handle) = reload::Layer::new(EnvFilter::new("info"));
        // A minimal registry is enough to prove the handle actually reloads
        // -- this crate's own tests never install it as the global default
        // (see layer::tests, which use `tracing::subscriber::with_default`).
        let _subscriber = tracing_subscriber::registry().with(layer);
        let level_handle = LevelHandle::new(handle);
        assert!(level_handle.set_level("debug").is_ok());
        assert!(matches!(
            level_handle.set_level("not-a-level"),
            Err(LevelError::InvalidLevel(_))
        ));
    }
}
