# penguin-licensing (Rust) Changelog

## 0.2.0

- **BREAKING (behaviour, for callers):** `LicenseClient::flag_enabled` no longer
  returns `true` on a domain-bypass client. Bypass domains (`*.penguincloud.io`,
  `*.penguintech.cloud`, product `.app` domains) now satisfy LICENSE/entitlement
  checks only (`check_feature` passes, `tier()` is Enterprise); they never force
  PostHog feature flags or kill switches on. Flags resolve from the PostHog
  snapshot (never-seen = OFF) on every domain, and the snapshot refresh keeps
  running on bypass domains. Consumers that relied on bypass forcing flags on
  must set explicit PostHog values (or an env baseline in their own code).

## 0.1.0

- Initial release
