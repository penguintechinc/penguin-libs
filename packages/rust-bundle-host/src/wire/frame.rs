//! Length-prefixed frame codec: every message is a 4-byte big-endian
//! unsigned length followed by that many bytes of UTF-8 JSON (spec §6.6,
//! assumption A3). `read_frame`/`write_frame` are the primitives a
//! transport built on any `AsyncRead`/`AsyncWrite` (a TLS stream in
//! production, an in-memory duplex in tests) composes into a connection.

use tokio::io::{AsyncRead, AsyncReadExt, AsyncWrite, AsyncWriteExt};

use super::message::Frame;

/// `EXECUTOR_MAX_FRAME_BYTES` default (spec §6.6): a length greater than
/// this is a fatal protocol error.
pub const MAX_FRAME_BYTES: u32 = 1_048_576;

/// Failure modes reading or writing a frame. Every variant is a fatal
/// condition for the connection it occurred on (spec §6.6: "the stage logs
/// it and closes the connection").
#[derive(Debug, thiserror::Error)]
pub enum FrameError {
    #[error("io error on frame boundary: {0}")]
    Io(#[from] std::io::Error),

    #[error("frame length {len} exceeds MAX_FRAME_BYTES ({MAX_FRAME_BYTES})")]
    TooLarge { len: u32 },

    #[error("malformed frame JSON: {0}")]
    Malformed(#[from] serde_json::Error),
}

/// Reads one frame: a 4-byte big-endian length, then that many bytes of
/// UTF-8 JSON decoded as a [`Frame`]. Returns [`FrameError::TooLarge`]
/// without reading the payload when the declared length exceeds
/// [`MAX_FRAME_BYTES`], so a hostile or buggy peer can't force an
/// unbounded allocation.
pub async fn read_frame<R>(reader: &mut R) -> Result<Frame, FrameError>
where
    R: AsyncRead + Unpin,
{
    let mut len_buf = [0u8; 4];
    reader.read_exact(&mut len_buf).await?;
    let len = u32::from_be_bytes(len_buf);
    if len > MAX_FRAME_BYTES {
        return Err(FrameError::TooLarge { len });
    }

    let mut payload = vec![0u8; len as usize];
    reader.read_exact(&mut payload).await?;
    let frame: Frame = serde_json::from_slice(&payload)?;
    Ok(frame)
}

/// Serializes `frame` to canonical JSON and writes it as a 4-byte
/// big-endian length followed by the payload, then flushes. Returns
/// [`FrameError::TooLarge`] without writing anything when the serialized
/// payload would exceed [`MAX_FRAME_BYTES`].
pub async fn write_frame<W>(writer: &mut W, frame: &Frame) -> Result<(), FrameError>
where
    W: AsyncWrite + Unpin,
{
    let payload = serde_json::to_vec(frame)?;
    if payload.len() > MAX_FRAME_BYTES as usize {
        // Not representable as an accurate u32 len in the error in the
        // pathological case the payload exceeds u32::MAX, but that would
        // already have failed the MAX_FRAME_BYTES check with room to
        // spare (MAX_FRAME_BYTES is 1 MiB, far below u32::MAX).
        return Err(FrameError::TooLarge {
            len: payload.len() as u32,
        });
    }

    let len = payload.len() as u32;
    writer.write_all(&len.to_be_bytes()).await?;
    writer.write_all(&payload).await?;
    writer.flush().await?;
    Ok(())
}
