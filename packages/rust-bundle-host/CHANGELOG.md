# Changelog

All notable changes to `penguin-bundle-host` are documented here.
Format: [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]

### Security
- `manifest`: replace `serde_yaml_ng` with `serde-saphyr` (pure safe-Rust YAML) so
  the unmaintained `unsafe-libyaml` (RUSTSEC-2024-0449) is no longer in the
  dependency tree. `ParseError::Syntax` now wraps `serde_saphyr::Error`.

### Added
- `wire`: length-prefixed frame codec (`u32` BE length + UTF-8 JSON) and a
  correlation-id multiplexed transport over any `AsyncRead + AsyncWrite`.
- `manifest`: `bundle.yaml` v2 schema types and the 31 numbered validation
  rules (V1-V31, V26 reserved/unused per spec §6.4.4), each with a stable
  `reason` code matching `app_manifest.py`.
- `manifest`: V17's `language` field now accepts `csharp` alongside
  `python`/`rust`/`javascript`/`typescript`/`other`.
