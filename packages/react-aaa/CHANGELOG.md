# Changelog

All notable changes to `@penguintechinc/react-aaa` are documented here.
Format: [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).

## [0.1.6] - 2026-11-09

### Changed (BREAKING)
- **zod upgraded 3.25.76 -> 4.6.7** (exact pin). The package exports zod schemas
  publicly (`ClaimsSchema`, `TokenSetSchema`, `RoleSchema`, `RBACConfigSchema`,
  `EventTypeSchema`, `OutcomeSchema`, `AuditEventSchema`, `OIDCClientConfigSchema`),
  so consumers that compose, extend or introspect these schemas must also use zod 4
  and review the zod 4 migration guide (error shape, `.default()` and `.record()`
  semantics, `ZodError.format()`/`flatten()` deprecations, internal `_def` layout).
- `ClaimsSchema.ext` and `AuditEventSchema.metadata` are now
  `z.record(z.string(), z.unknown())` (zod 4 requires an explicit key schema).
- `AuditEventSchema.timestamp` now uses `z.iso.datetime()`; accepted values are
  unchanged (RFC 3339 UTC with `Z`, optional fractional seconds).

### Security
- `sanitizeRedirectPath`: closes open-redirect bypasses (F-01) - rejects dot-segment (`/..//evil`, percent-encoded) and protocol-relative/control-character/backslash forms, and verifies the resolved URL stays on the current origin.
- Resolves the high-severity zod advisory in the production dependency tree
  (`npm audit --omit=dev`: 1 high -> 0).
- Dev tooling: `vitest` and `@vitest/coverage-v8` pinned to 4.1.12 (critical
  vitest advisory), `@typescript-eslint/*` 6.21.0 -> 8.72.2 (resolves vulnerable
  `minimatch` ReDoS ranges).
