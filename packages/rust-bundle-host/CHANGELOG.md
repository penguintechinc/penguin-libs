# Changelog

All notable changes to `penguin-bundle-host` are documented here.
Format: [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]

### Added
- `wire`: length-prefixed frame codec (`u32` BE length + UTF-8 JSON) and a
  correlation-id multiplexed transport over any `AsyncRead + AsyncWrite`.
- `manifest`: `bundle.yaml` v2 schema types and the 31 numbered validation
  rules (V1-V31, V26 reserved/unused per spec §6.4.4), each with a stable
  `reason` code matching `app_manifest.py`.
