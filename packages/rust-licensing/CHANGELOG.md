# penguin-licensing (Rust) Changelog

## 0.1.1

- **Security:** bump `url` 2.5.8 -> 2.5.9 (RUSTSEC-2026-0592, stack overflow in
  `Url::origin()` on nested `blob:` URLs); transitive `form_urlencoded` 1.2.3.

## 0.1.0 (Unreleased)

- **BREAKING (behaviour, for callers):** `LicenseClient::flag_enabled` no longer
  returns `true` on a domain-bypass client. Bypass domains (`*.penguincloud.io`,
  `*.penguintech.cloud`, product `.app` domains) now satisfy LICENSE/entitlement
  checks only (`check_feature` passes, `tier()` is Enterprise); they never force
  PostHog feature flags or kill switches on. Flags resolve from the PostHog
  snapshot (never-seen = OFF) on every domain, and the snapshot refresh keeps
  running on bypass domains. Consumers that relied on bypass forcing flags on
  must set explicit PostHog values (or an env baseline in their own code).

- **BREAKING (API):** replaced the direct `chrono` dependency (RUSTSEC-2026-0543,
  unmaintained) with `time`. `LicenseInfo::{expires_at, issued_at}`,
  `Snapshot::fetched_at` and `LicenseInfo::is_live_at` now use
  `time::OffsetDateTime` instead of `chrono::DateTime<Utc>`. The RFC 3339 wire
  format is byte-identical (UTC `Z`, fractional digits omitted/3/6/9).
- Initial release
