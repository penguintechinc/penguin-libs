//! Guest-side SDK for `penguin:tools` WASM tool modules.
//!
//! Provides the validated [`ToolDescriptor`] type that a module returns from
//! `provider.describe`, canonical JSON Schema generation for tool input and
//! output types, a bounded [`ToolFailure`] error, and the [`tool`] attribute
//! macro that ties a function signature to a descriptor.
//!
//! The WIT contract lives in `wit/penguin-tools/` at the repository root; this
//! crate does not generate bindings itself.

mod descriptor;
mod failure;
mod schema;

pub use descriptor::{DescriptorError, Effect, ToolDescriptor};
pub use failure::{ToolFailure, MAX_FAILURE_BYTES};
pub use penguin_tools_sdk_macros::tool;
pub use schema::{canonical_json, schema_json};

/// Maximum size of a tool's argument or result payload (1 MiB), matching the
/// wire frame cap enforced by the host.
pub const MAX_PAYLOAD_BYTES: usize = 1024 * 1024;

/// Crate version, for diagnostics.
pub const VERSION: &str = env!("CARGO_PKG_VERSION");

#[doc(hidden)]
pub mod __private {
    pub use schemars;
}
