# Changelog

All notable changes to `penguin-spine` are documented here.

## [Unreleased]

- Fixed `SpineClient::dead_letter` `XACK`ing the source entry under
  `d.env.app_id` instead of the consumer group the entry was actually
  delivered under. Coincidentally correct for svc_action's per-bundle
  action streams (group == env.app_id there), but wrong for svc_process's
  shared ingest-source streams (group != app_id): dead-lettered entries
  never got acked and stayed stuck in the PEL forever. `Delivered` now
  carries a `group: String` field (set by `GroupReader::read` and
  `SpineClient::claim_stale`); `dead_letter` acks under `d.group`.
  **API change**: `Delivered` gained a public field — any direct struct
  literal construction of `Delivered` must add `group: <the reading
  consumer group>`.
- Added the `binding` module: `compute_binding_mac`/`verify_binding`,
  `KeyRing`, `BindingError` (spec §5.11, D30). Reproduces
  `waddles core/svc_action/src/hop.rs`'s verified-correct
  `compute_mac`/`verify_mac` formula and keyring shape byte-for-byte, so
  that module can later swap onto this crate as a drop-in replacement.

Initial crate scaffold.
