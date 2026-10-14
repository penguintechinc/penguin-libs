# Changelog

All notable changes to `penguin-spine` are documented here.

## [Unreleased]

- **0.2.0 -- numeric scope (schema v3).** `StageEnvelope` gains `tenant_id: Option<i64>` + `community_id: Option<i32>` (AUTHORITATIVE scope keys; `tenant`/`community` strings become display-only; `community_id` 0 = tenant-wide). `ENVELOPE_SCHEMA_VERSION` is now 3; `LEGACY_ENVELOPE_SCHEMA_VERSION` (2) is still accepted on read and MUST NOT carry the ids. New `compute_binding_mac_v3` binds both ids (domain-tagged, length-framed); `verify_binding` dispatches on `schema_version`, so mutating either id invalidates the MAC and v2/v3 MACs never cross-verify. **API change**: `StageEnvelope` struct literals must add `tenant_id`/`community_id`; v2 producers should stamp `LEGACY_ENVELOPE_SCHEMA_VERSION`.

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
