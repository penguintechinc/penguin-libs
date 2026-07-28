// Copyright 2026 Penguin Tech Inc
// SPDX-License-Identifier: Apache-2.0

//! Phase 0 scaffold — implementation lands in Phase 3. See spec/SPEC.md.

#![forbid(unsafe_code)]
#![deny(missing_docs)]

/// Crate version, sourced from Cargo.toml.
pub const VERSION: &str = env!("CARGO_PKG_VERSION");

#[cfg(test)]
mod tests {
    #[test]
    fn version_matches_workspace() {
        assert_eq!(super::VERSION, "0.1.0");
    }
}
