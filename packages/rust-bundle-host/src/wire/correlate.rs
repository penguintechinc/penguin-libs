//! Correlation-id bookkeeping for the bidirectional wire protocol (spec
//! §6.6, assumption A3): the frame `id` field lets either peer have many
//! requests in flight over one connection and match each reply back to its
//! originating request.

use std::collections::HashMap;
use std::sync::atomic::{AtomicU64, Ordering};
use std::sync::Mutex;

use tokio::sync::oneshot;

use super::message::Frame;

/// Monotonically increasing id allocator, one per connection, owned by
/// whichever side is currently the sender of an initiating message (spec
/// §6.6: "`id` is a monotonically increasing `u64` allocated by the sender
/// of the initiating message; every reply reuses it").
#[derive(Debug, Default)]
pub struct IdAllocator {
    next: AtomicU64,
}

impl IdAllocator {
    /// Starts a fresh allocator at id `1` (`0` is reserved as "unset" for
    /// callers that want a sentinel).
    pub fn new() -> Self {
        Self {
            next: AtomicU64::new(1),
        }
    }

    /// Returns the next id and advances the counter. Never returns `0`;
    /// safe to call concurrently from many tasks sharing one connection.
    pub fn next_id(&self) -> u64 {
        self.next.fetch_add(1, Ordering::Relaxed)
    }
}

/// Errors surfaced by [`CorrelationTable`] when a frame's `id` cannot be
/// matched to an in-flight request, or a caller double-registers one.
#[derive(Debug, Clone, thiserror::Error, PartialEq, Eq)]
pub enum CorrelationError {
    #[error("correlation id {0} is already registered")]
    AlreadyRegistered(u64),

    #[error("no in-flight request registered for correlation id {0}")]
    Unknown(u64),
}

/// Maps an in-flight request's correlation id to the [`oneshot::Sender`]
/// that will deliver its reply, so a single duplexed connection can
/// multiplex many concurrent request/reply pairs (spec §6.6: "Frames are
/// multiplexed by `id`; both sides may have many in flight").
#[derive(Debug, Default)]
pub struct CorrelationTable {
    pending: Mutex<HashMap<u64, oneshot::Sender<Frame>>>,
}

impl CorrelationTable {
    /// Empty table, ready to register pending requests.
    pub fn new() -> Self {
        Self {
            pending: Mutex::new(HashMap::new()),
        }
    }

    /// Registers `id` as awaiting a reply, returning the receiving half of
    /// the channel [`Self::complete`] will deliver into. Fails if `id` is
    /// already pending — a bug in the caller's id allocation, never a
    /// wire-format condition.
    pub fn register(&self, id: u64) -> Result<oneshot::Receiver<Frame>, CorrelationError> {
        let (tx, rx) = oneshot::channel();
        let mut pending = self.lock();
        if pending.contains_key(&id) {
            return Err(CorrelationError::AlreadyRegistered(id));
        }
        pending.insert(id, tx);
        Ok(rx)
    }

    /// Delivers `frame` to whichever caller registered its `id`, consuming
    /// the pending slot. Returns [`CorrelationError::Unknown`] for an id
    /// nobody is waiting on (already delivered, cancelled, or never
    /// registered) rather than silently dropping the reply.
    pub fn complete(&self, frame: Frame) -> Result<(), CorrelationError> {
        let id = frame.id;
        let sender = self.lock().remove(&id);
        match sender {
            Some(tx) => {
                // The receiver may already have been dropped (its caller
                // stopped waiting, e.g. on its own deadline); that is not
                // a protocol error, just a reply nobody wanted anymore.
                let _ = tx.send(frame);
                Ok(())
            }
            None => Err(CorrelationError::Unknown(id)),
        }
    }

    /// Drops a pending registration without delivering a reply (e.g. the
    /// caller's own deadline elapsed first). Idempotent: cancelling an
    /// already-completed or already-cancelled id is a no-op.
    pub fn cancel(&self, id: u64) {
        self.lock().remove(&id);
    }

    /// Number of requests currently awaiting a reply.
    pub fn pending_count(&self) -> usize {
        self.lock().len()
    }

    fn lock(&self) -> std::sync::MutexGuard<'_, HashMap<u64, oneshot::Sender<Frame>>> {
        match self.pending.lock() {
            Ok(guard) => guard,
            // A panic while holding the lock would be a bug elsewhere in
            // this process; recovering the poisoned guard keeps the table
            // usable rather than wedging every future correlation.
            Err(poisoned) => poisoned.into_inner(),
        }
    }
}
