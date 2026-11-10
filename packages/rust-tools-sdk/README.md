# penguin-tools-sdk

Guest-side SDK for `penguin:tools` WASM tool modules. See the design spec at
`docs/superpowers/specs/2026-11-09-penguin-tools-design.md` and the WIT
contract in `wit/penguin-tools/`.

| Crate | Purpose |
|---|---|
| `penguin-tools-sdk` | `ToolDescriptor` (validated), `Effect`, `ToolFailure` (bounded to 512 bytes), canonical JSON Schema generation, and the `#[tool]` re-export |
| `penguin-tools-sdk-macros` | The `#[tool]` attribute macro |

## Example

```rust
use penguin_tools_sdk::{tool, ToolFailure};
use schemars::JsonSchema;
use serde::{Deserialize, Serialize};

#[derive(Deserialize, JsonSchema)]
struct EchoIn { text: String }

#[derive(Serialize, JsonSchema)]
struct EchoOut { text: String }

#[tool(name = "echo", version = "0.1.0", description = "Echoes text", effect = "read")]
fn echo(input: EchoIn) -> Result<EchoOut, ToolFailure> {
    Ok(EchoOut { text: input.text })
}

// Generated: echo_descriptor() -> Result<ToolDescriptor, DescriptorError>
```

The macro leaves the function unchanged and adds `<fn>_descriptor()`. Input and
output schemas come from the signature types (`schemars::JsonSchema`) and are
emitted as canonical JSON (sorted keys, no whitespace) so identical contracts
hash identically.

## Validation

`ToolDescriptor::new` rejects, with a typed error: names outside
`[a-z][a-z0-9_.-]{0,63}`, non `major.minor.patch` versions, capability ids that
are not namespaced `ns:name` (or are duplicated), empty or over-1024-byte
descriptions, and schemas that are not JSON. Because the macro builds the
descriptor at call time, a bad attribute value surfaces as an error from
`<fn>_descriptor()`; hosts treat that as a load failure.

## Not yet included

Guest bindings (`wit-bindgen` glue) and the fixture guests arrive with the
rest of Phase 1; this crate has no WASM target code yet.

## Development

```bash
cd packages/rust-tools-sdk
cargo fmt --all --check
cargo clippy --workspace --all-targets -- -D warnings
cargo test --workspace
cargo deny check
```
