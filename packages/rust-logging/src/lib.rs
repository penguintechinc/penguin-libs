//! Structured, sanitized logging plus OpenTelemetry logs/metrics/traces and
//! a `/health`/`/healthz`/`/metrics` HTTP surface for Waddles/PenguinTech
//! Rust services. See the crate README for the environment variable
//! contract and `docs/superpowers/specs/2026-09-14-rust-data-plane-design.md`
//! §4.9 for the design this crate implements.

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
