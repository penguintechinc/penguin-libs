//! Frame envelope and message-kind types for the host-API wire protocol
//! (spec §6.6). `Frame` is the common envelope (`{"v":1,"id":42,"kind":
//! "...", ...}`); `Message` is every message kind in both directions,
//! internally tagged on `kind` so its fields flatten into the same JSON
//! object as `v`/`id` rather than nesting under a `"kind"` sub-object.

use std::collections::HashMap;

use serde::{Deserialize, Serialize};

/// The wire protocol version this crate speaks. Spec §6.6: "`v` is always
/// `1`".
pub const PROTOCOL_VERSION: u8 = 1;

/// One frame of the host-API wire protocol: the common envelope (`v`,
/// `id`) plus a [`Message`] whose fields are flattened into the same JSON
/// object.
///
/// `id` is a monotonically increasing `u64` allocated by the sender of the
/// initiating message; every reply reuses it (spec §6.6, assumption A3).
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct Frame {
    /// Always [`PROTOCOL_VERSION`] on the wire; kept as a real field
    /// (rather than assumed) so a future protocol bump is a data change,
    /// not a schema change.
    pub v: u8,
    /// Correlation id shared by a request and its reply.
    pub id: u64,
    /// The message kind and its kind-specific fields.
    #[serde(flatten)]
    pub message: Message,
}

impl Frame {
    /// Builds a frame at the current [`PROTOCOL_VERSION`] with the given
    /// correlation id and message.
    pub fn new(id: u64, message: Message) -> Self {
        Self {
            v: PROTOCOL_VERSION,
            id,
            message,
        }
    }
}

/// Every message kind in both directions of the host-API wire protocol
/// (spec §6.6). Tagged internally on `kind` (kebab-case, e.g.
/// `"hello-ok"`); the variant's own fields are merged into the frame's
/// top-level JSON object.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
#[serde(tag = "kind", rename_all = "kebab-case")]
pub enum Message {
    // -- Executor -> stage (the executor dials, so it speaks first) --
    Hello(HelloBody),
    Loaded(LoadedBody),
    Unloaded(UnloadedBody),
    Result(ResultBody),
    HostCall(HostCallBody),
    Error(ErrorBody),
    Pong,

    // -- Stage -> executor --
    HelloOk(HelloOkBody),
    Load(LoadBody),
    Unload(UnloadBody),
    Invoke(InvokeBody),
    HostResult(HostResultBody),
    Ping,
    Shutdown(ShutdownBody),
}

/// Executor's opening handshake (`kind: "hello"`). Reply: `hello-ok` or
/// `error`.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct HelloBody {
    /// Always `1` today; the stage rejects a mismatch with
    /// `error.code = "PROTOCOL_VERSION"`.
    pub protocol_version: u32,
    pub executor_version: String,
    pub wasmtime_version: String,
    pub wasmtime_abi: String,
    /// The wasmtime GC collector in use, e.g. `"drc"`.
    pub collector: String,
    pub sandbox: SandboxInfo,
}

/// The executor's reported sandbox runtime and whether the stage has
/// independently verified it (spec §6.6, §12.2).
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct SandboxInfo {
    /// `"gvisor"` or `"runc"`.
    pub runtime: String,
    pub verified: bool,
}

/// Stage's reply limits handed to the executor in `hello-ok`.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct HelloLimits {
    pub call_timeout_ms: u64,
    pub memory_mb: u32,
    pub max_concurrent_calls: u32,
}

/// Stage's reply to a successful `hello` (`kind: "hello-ok"`).
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct HelloOkBody {
    pub stage: String,
    pub protocol_version: u32,
    pub limits: HelloLimits,
}

/// Reported once a `load` completes successfully (`kind: "loaded"`, no
/// reply expected).
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct LoadedBody {
    pub app_id: String,
    pub digest: String,
    pub precompile_ms: u64,
    /// Export names actually present on the compiled component.
    pub exports: Vec<String>,
}

/// Reported once an `unload` completes (`kind: "unloaded"`, no reply
/// expected).
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct UnloadedBody {
    pub app_id: String,
    pub digest: String,
}

/// Per-call limits carried on a `load` frame.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct LoadLimits {
    pub timeout_ms: u64,
    pub memory_mb: u32,
}

/// Stage instructs the executor to load a bundle (`kind: "load"`). Reply:
/// `loaded` or `error`.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct LoadBody {
    pub app_id: String,
    pub version: String,
    /// `sha256:<64 hex>`.
    pub digest: String,
    pub component_key: String,
    pub sidecar_key: String,
    pub capabilities: Vec<CapabilityKind>,
    pub limits: LoadLimits,
}

/// Stage instructs the executor to unload a bundle (`kind: "unload"`).
/// Reply: `unloaded` or `error`.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct UnloadBody {
    pub app_id: String,
    pub digest: String,
}

/// The two script exports a bundle may implement (spec §6.5's
/// `process-stage`/`action-stage` interfaces).
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum ExportKind {
    Transform,
    Dispatch,
}

/// W3C trace context propagated from the envelope onto an `invoke` frame
/// (spec §5.11, §6.6).
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct TraceContext {
    pub traceparent: String,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub tracestate: Option<String>,
}

/// Stage invokes a loaded bundle's export (`kind: "invoke"`). Reply:
/// `result` or `error`.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct InvokeBody {
    pub app_id: String,
    pub digest: String,
    pub export: ExportKind,
    /// The export's arguments, as canonical JSON (spec assumption A2).
    pub payload: serde_json::Value,
    pub deadline_ms: u64,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub trace: Option<TraceContext>,
}

/// Executor's reply to a completed `invoke` (`kind: "result"`, no reply
/// expected).
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct ResultBody {
    pub payload: serde_json::Value,
    pub duration_ms: u64,
    /// `0` when fuel metering is off.
    pub fuel_used: u64,
}

/// The host capabilities a loaded bundle may call (spec §6.5's WIT
/// interfaces, minus `context`/`clock` which never appear on a `host-call`
/// frame because the executor answers those locally... except `context`
/// and `clock` are still routed through the host per §7.4, so both are
/// included here to match the full `capability` value space).
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum CapabilityKind {
    Http,
    Kv,
    Db,
    Relay,
    Flags,
    Log,
    Clock,
    Context,
}

/// Executor asks the stage to service a host capability call on behalf of
/// a running bundle (`kind: "host-call"`). Reply: `host-result`.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct HostCallBody {
    pub app_id: String,
    pub capability: CapabilityKind,
    /// The capability-specific operation name, e.g. `"send"`, `"get"`,
    /// `"execute"`.
    pub op: String,
    /// Capability-specific arguments, as JSON.
    pub args: serde_json::Value,
    /// The `invoke` frame id this call happened during, so the stage can
    /// charge the call against that invocation's remaining deadline.
    pub call_id: u64,
}

/// The `{code, message}` shape a failed `host-call` reports inside a
/// `host-result` frame.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct HostResultError {
    pub code: String,
    pub message: String,
}

/// Stage's reply to a `host-call` (`kind: "host-result"`). Exactly one of
/// `result`/`error` is present; both being present or absent is a
/// malformed message the receiver should reject rather than guess at.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct HostResultBody {
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub result: Option<serde_json::Value>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub error: Option<HostResultError>,
}

/// Stable error-code strings for `kind: "error"` frames (spec §6.6).
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "SCREAMING_SNAKE_CASE")]
pub enum ErrorCode {
    ProtocolVersion,
    FrameTooLarge,
    MalformedFrame,
    UnknownBundle,
    DigestMismatch,
    LoadFailed,
    ExportMissing,
    ExecutorDeadline,
    MemoryLimit,
    WasmTrap,
    HostCallDenied,
    HostCallFailed,
    UnsandboxedExecutor,
    ShuttingDown,
}

/// A protocol-level failure reported by either peer (`kind: "error"`, no
/// reply expected).
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct ErrorBody {
    pub code: ErrorCode,
    pub message: String,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub detail: Option<String>,
}

/// Stage tells the executor to drain and close (`kind: "shutdown"`). The
/// connection closes after in-flight calls drain or `grace_ms` elapses.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct ShutdownBody {
    pub grace_ms: u64,
}

/// Helper so callers building a `load` frame can assemble `capabilities`
/// from a manifest's capability set without hand-writing the enum list.
pub fn capability_from_str(value: &str) -> Option<CapabilityKind> {
    let table: HashMap<&str, CapabilityKind> = HashMap::from([
        ("http", CapabilityKind::Http),
        ("kv", CapabilityKind::Kv),
        ("db", CapabilityKind::Db),
        ("relay", CapabilityKind::Relay),
        ("flags", CapabilityKind::Flags),
        ("log", CapabilityKind::Log),
        ("clock", CapabilityKind::Clock),
        ("context", CapabilityKind::Context),
    ]);
    table.get(value).copied()
}
