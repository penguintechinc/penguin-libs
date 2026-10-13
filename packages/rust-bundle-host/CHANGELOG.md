# Changelog

All notable changes to `penguin-bundle-host` are documented here.
Format: [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]

### Security (PR #136 adversarial-review remediation, fail-closed)
- `NetRule::host_matches`: a wildcard no longer matches a host that reaches
  below a public suffix nested under the rule's suffix (`*.amazonaws.com` vs
  `attacker.s3.amazonaws.com`) or embeds a multi-label public suffix in the
  wildcard-matched part (`*.example.com` vs `a.github.io.example.com`). List
  shared-infra hosts as exact FQDNs.
- `network.egress` now honours the tenant egress denylist (FQDN, wildcard, and a
  wildcard that covers a denylisted host) -> `Reason::EgressHostDenylisted`.
- Parse rejects FQDNs whose last label is numeric/`0x` hex, internal-only names
  (`localhost`, `.internal`, `.local`, `.localdomain`, `.home.arpa`, `.lan`,
  `.intranet`, `.corp`, `.home`) and special-use CIDRs (loopback, link-local,
  unspecified, multicast/reserved, NAT64, unique-local, IPv4-compatible `::/96`).
  New `NetRuleError::{SpecialUseAddress, InternalHost}` (callers with exhaustive
  matches must add arms).
- IPv4-mapped IPv6 rule addresses are canonicalised to IPv4 at parse.

## [0.4.0]

### Added (bundle manifest v-next, F1 primitives)
- `net::NetRule`: validated network allowlist entry -- exact FQDN, leftmost-label
  wildcard (`*.x.com`, `cdn-*.x.com`; checked against the compiled-in Public
  Suffix List so `*.com`/`*.co.uk`/`*.github.io` are rejected), IPv4 CIDR
  (/24-/32 only) or IPv6 CIDR (/120-/128 only, TODO(confirm)). Pure matchers
  `host_matches` / `cidr_contains` (label-boundary, never substring).
- `manifest::{BundleKind, NetworkPolicy, RequiredService, satisfies_min_version}`
  and `Manifest.{kind, network, requires}`; `schema_version: 3` accepted
  alongside 2 (v3-only fields on a v2 document are rejected). New reasons
  `invalid_bundle_kind`, `invalid_network_rule`, `invalid_requires`.
- `wire::CapabilityKind::Transport` (`"transport"`).
- Dependencies: `psl =2.1.241`, `semver =1.0.28`.

### Changed (BREAKING for downstream struct literals / exhaustive matches)
- `Manifest` gained three fields and `CapabilityKind` a variant (see above), so
  `0.3.0` -> `0.4.0`.

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
