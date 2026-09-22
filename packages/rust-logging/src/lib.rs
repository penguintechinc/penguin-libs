//! Structured, sanitized logging plus OpenTelemetry logs/metrics/traces and
//! a `/health`/`/healthz`/`/metrics` HTTP surface for Waddles/PenguinTech
//! Rust services. See the crate README for the environment variable
//! contract and `docs/superpowers/specs/2026-09-14-rust-data-plane-design.md`
//! §4.9 for the design this crate implements.
//!
//! ```no_run
//! use penguin_logging::{health, init, ServiceConfig};
//!
//! fn main() {
//!     let cfg = ServiceConfig::from_env("svc-process");
//!     let (_guard, _level_handle, registry) = init(cfg);
//!     tracing::info!("svc-process starting");
//!     let health_state = health::HealthState::new(registry, || health::HealthReport {
//!         status: "ok".to_string(),
//!         service: "svc-process".to_string(),
//!         version: penguin_logging::VERSION.to_string(),
//!         transport: "secure",
//!         transport_detail: Default::default(),
//!         extra: serde_json::Map::new(),
//!         ready: true,
//!     });
//!     let _app = health::router(health_state);
//!     // ... merge `_app` into your own axum::Router and serve it.
//! }
//! ```

pub mod config;
pub mod error;
pub mod health;
mod layer;
pub mod level;
pub mod sanitize;
pub mod telemetry;
#[cfg(any(test, feature = "testing"))]
pub mod testing;

pub use config::{OtlpProtocol, ServiceConfig};
pub use level::{LevelError, LevelHandle};
pub use telemetry::{init, TelemetryGuard};

/// The crate's own version, exposed so a service can report it on `/health`
/// without duplicating the string from `Cargo.toml`.
pub const VERSION: &str = env!("CARGO_PKG_VERSION");

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn version_matches_cargo_toml() {
        assert_eq!(VERSION, "0.1.0");
    }
}
