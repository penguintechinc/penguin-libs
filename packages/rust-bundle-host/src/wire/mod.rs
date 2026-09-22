//! Host-API wire protocol shared by a Waddles stage (`svc_process`,
//! `svc_action`) and its credential-less executor (spec §6.6): the frame
//! envelope/message shapes (`message`), the length-prefixed codec
//! (`frame`), and the correlation-id bookkeeping that lets one duplexed
//! connection carry many requests in flight (`correlate`).

pub mod correlate;
pub mod frame;
pub mod message;

pub use correlate::{CorrelationError, CorrelationTable, IdAllocator};
pub use frame::{read_frame, write_frame, FrameError, MAX_FRAME_BYTES};
pub use message::{
    CapabilityKind, ErrorBody, ErrorCode, ExportKind, Frame, HelloBody, HelloLimits, HelloOkBody,
    HostCallBody, HostResultBody, HostResultError, InvokeBody, LoadBody, LoadLimits, LoadedBody,
    Message, ResultBody, SandboxInfo, ShutdownBody, TraceContext, UnloadBody, UnloadedBody,
};
