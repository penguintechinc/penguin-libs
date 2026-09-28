# Changelog

All notable changes to `penguin-security` will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.1.1] - 2026-09-28

First PyPI release. `0.1.0` was tagged but never published — the
`publish-python-security.yml` workflow failed (`InvalidDistribution: Metadata
is missing required fields: Name`) because the pinned
`pypa/gh-action-pypi-publish` bundled a `twine` build too old to read
Metadata-Version 2.4. Fixed in the publish workflow (pinned to v1.14.2,
hash-pinned build/twine install); no code changes from `0.1.0`.

### Added

- Security primitives and hardening helpers.
- `penguin_security.crypto` — symmetric/hybrid encryption, key derivation
  (Argon2id, HKDF), ECC (X25519/Ed25519), hashing, and per-tenant envelope
  encryption (optional `crypto` extra, formerly the standalone
  `penguin-crypto` package).
- Argon2id password hashing (`hash_password`/`verify_password`/`needs_rehash`).

## [0.1.0] - 2026-09 (tagged, never published)

Initial tag. Publish failed due to the workflow bug described above — no
package was ever uploaded to PyPI under this version.
