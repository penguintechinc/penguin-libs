# penguin-spine

Waddles data-plane spine over Valkey Streams: key builders, byte-compatible
envelope/DLQ types, `XADD`/`XREADGROUP`/`XACK`/`XAUTOCLAIM` wrappers, and the
two client connection-separation rules (spec §5.7). See
`docs/superpowers/plans/2026-09-14-penguin-spine.md` for the implementation
plan this crate was built from.

Full documentation lands in Task 21.
