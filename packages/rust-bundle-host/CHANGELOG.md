# Changelog

All notable changes to `penguin-bundle-host` are documented here.
Format: [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]

## [0.3.0]

### Added
- `wire::ExportKind`: four connector exports of `waddle:connector@1.0.0`
  `receiver` -- `ConnectorOnConnect`, `ConnectorOnFrame`,
  `ConnectorOnHeartbeatDue`, `ConnectorOnDisconnect` (wire labels
  `connector_on_connect` / `connector_on_frame` / `connector_on_heartbeat_due`
  / `connector_on_disconnect`), plus `ExportKind::ALL`, `as_str()` and
  `is_connector()`.

### Changed (BREAKING for downstream `match`es)
- `ExportKind` is not `#[non_exhaustive]` by design, so adding variants breaks
  every exhaustive `match` on it (waddles `bundle_executor` has three). That is
  intended: the compiler must prove each export is routed. Hence `0.2.0` ->
  `0.3.0`. `ExportKind` also now derives `Hash`.

## [Security fixes (previously Unreleased)]

### Security
- `manifest`: replace `serde_yaml_ng` with `serde-saphyr` (pure safe-Rust YAML) so
  the unmaintained `unsafe-libyaml` (RUSTSEC-2024-0449) is no longer in the
  dependency tree. `ParseError::Syntax` now wraps `serde_saphyr::Error`.
  New `manifest::parse_raw_yaml` pins parser options (`strict_booleans`,
  `merge_keys: AsOrdinary`, `reject_unsupported_tags`) to keep `serde_yaml_ng`
  semantics; `tests/manifest_yaml_equivalence_tests.rs` pins 86 corpus cases and
  documents the accepted differences.

### Added
- `wire`: length-prefixed frame codec (`u32` BE length + UTF-8 JSON) and a
  correlation-id multiplexed transport over any `AsyncRead + AsyncWrite`.
- `manifest`: `bundle.yaml` v2 schema types and the 31 numbered validation
  rules (V1-V31, V26 reserved/unused per spec §6.4.4), each with a stable
  `reason` code matching `app_manifest.py`.
- `manifest`: V17's `language` field now accepts `csharp` alongside
  `python`/`rust`/`javascript`/`typescript`/`other`.
