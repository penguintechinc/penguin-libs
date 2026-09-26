# penguin-aaa (Rust)

JWT signing and verification primitives shared across PenguinTech's Rust
services. Extracted from three independent reimplementations in the
`tobogganing` repository:

- `engines/testserver-rs/crates/core/src/auth.rs` — `JwtVerifier` (verify
  side).
- `agents/node-agent/crates/core/src/jwt.rs` — `MachineJwtSigner` (sign
  side).
- `services/hub-router-rs/crates/auth/` — `MachineJWTClient` (token
  exchange/refresh HTTP lifecycle; not yet consuming this crate — see
  "Planned (v0.2)" below).

## Algorithm policy (v0.1)

| Algorithm | Family | Role | Backend |
|---|---|---|---|
| `ES256` (P-256) | Elliptic-curve — primary | **Sign + verify** — the only algorithm this crate signs | `p256` (sign), `ring` (verify) |
| `ES384` (P-384) | Elliptic-curve — primary | Verify only | `ring` |
| `ES512` (P-521) | Elliptic-curve — primary | Verify only | `p521` (`ring` has no P-521 support) |
| `EdDSA` (Ed25519) | Elliptic-curve — primary | Verify only | `ring` |
| `RS256` (RSA, **4096-bit minimum**) | RSA — legacy backup | Verify only, for issuers that can't yet sign EC | `ring` |
| HMAC (`HS256`/`HS384`/`HS512`), `alg: none` | — | **Forbidden, unconditionally** | — |

- **Elliptic-curve family is primary/preferred.** New services sign
  `ES256`; `ES384`/`ES512`/`EdDSA` are verify-only support for other
  EC-signing issuers.
- **`RS256` is a legacy backup, verify-only.** This crate never mints an
  RS256 token — existing Python issuers that can't yet sign EC keep
  working, at a 4096-bit RSA floor.
- [`Es256Signer`] — sign a [`Claims`] value into a compact ES256 JWS.
- [`Es256Verifier`] — built from exactly one public key via
  [`Es256Verifier::from_public_key_pem`]; the accepted algorithm is
  *derived from the key's own type* (EC curve or RSA), never supplied by
  the caller. A token's declared `alg` must match what the key
  cryptographically is before signature verification is even attempted —
  this closes the alg-confusion surface structurally rather than via an
  allowlist check alone.
- [`Claims`] — the shared claim set: `sub`/`iss`/`aud`/`iat`/`exp`/`scope`
  are structurally required; `tenant`/`teams`/`roles` default to
  absent/empty for machine-to-machine tokens that don't carry them.
  Mirrors the platform's mandatory claim set (security.md JWT Claims).

## Crypto backend: no bundled multi-algorithm JWT crate

This crate does **not** depend on `jsonwebtoken`, `jwt-simple`, or any
other general-purpose multi-algorithm JWT library. Every one evaluated
bundles RSA support (`RS256`/`PS256`) unconditionally alongside ES256 —
one Cargo feature covers the whole algorithm set, with no way to opt into
EC-only:

- `jsonwebtoken`'s `rust_crypto` feature: `["dep:ed25519-dalek", "dep:hmac",
  "dep:p256", "dep:p384", "dep:rand", "dep:rsa", "dep:sha2"]`.
- `jwt-simple`'s `pure-rust` feature: same shape, also pulls `rsa`.

The `rsa` crate carries **RUSTSEC-2023-0071** (Marvin Attack, RSA timing
sidechannel) with no patched release available upstream (still open,
tracked at RustCrypto/RSA#626/#680/#702). Org policy treats RUSTSEC
advisories as a hard no-go — not an ignore-with-justification, even for
one whose vulnerable code path is unreachable — so this crate implements
the JWS mechanics directly instead:

- **`ring`** (≥0.17.14) covers ES256 (P-256), ES384 (P-384), EdDSA
  (Ed25519), and RS256 (RSA, `RSA_PKCS1_2048_8192_SHA256`) verification.
  `ring` has no `rsa`-crate dependency (its RSA support is hand-written,
  not the RustCrypto `rsa` crate) and carries no RUSTSEC advisories.
- **`p521`** covers ES512 verification — the one gap `ring` leaves (it has
  no P-521/secp521r1 support at all).
- **`p256`** covers ES256 signing (pure-Rust RustCrypto, RFC6979
  deterministic signing, SHA-256 prehash).
- **`spki`/`der`** parse the SPKI public-key wrapper generically (OID +
  named-curve detection, RSA modulus bit-length check) — both are
  already-resolved transitive dependencies of `p256` itself, so declaring
  them directly adds zero new entries to the dependency tree.

`cargo tree` has zero `rsa` entries and `cargo deny check` carries no
advisory ignores. `node-agent` and `testserver-rs` currently carry the
`jsonwebtoken`/`rsa`/RUSTSEC-2023-0071 combination unmodified; migrating
them onto this crate (a follow-on, not part of this v0.1 scaffold) removes
it from them too.

### Known ecosystem gap: `p521` PEM support

`p521` 0.13.3's `pem` Cargo feature doesn't forward `ecdsa-core/pem` (unlike
`p256`/`p384`, which do), so `SigningKey`/`VerifyingKey`'s PEM/PKCS8 decode
methods aren't available for that crate version. This crate works around
it by parsing the SPKI wrapper itself (via `spki`/`der`) and constructing
the P-521 verifying key from the raw SEC1 point via
`VerifyingKey::from_sec1_bytes` instead of `from_public_key_pem` — fully
equivalent for verification, and invisible to callers of
[`Es256Verifier::from_public_key_pem`].

## Usage

```rust
use penguin_aaa::{Claims, Es256Signer, Es256Verifier};

let signer = Es256Signer::from_ec_pem(private_key_pem)?;
let verifier = Es256Verifier::from_public_key_pem(public_key_pem)?
    .with_audience("hub-api")
    .with_issuer("auth.penguintech.io");

let claims = Claims::new("node-123", "auth.penguintech.io", "hub-api", iat, exp, "dns:config:read");
let token = signer.sign(&claims)?;
let verified = verifier.verify(&token)?;
```

Accepting either a modern EC key or a legacy RSA key from the same issuer
is a caller-side concern — construct two `Es256Verifier`s (one per key)
and try each; this crate deliberately doesn't orchestrate multi-key/JWKS
resolution itself.

## Planned (v0.2)

- Machine-token exchange/refresh HTTP lifecycle (`hub-router-rs`'s
  `MachineJWTClient`: API-key → access/refresh token exchange, rotation,
  503 + `retry_with_credentials` re-exchange, legacy-token fallback).
- Axum verification middleware (extractor + `require_scope`-style layer),
  matching the shape of `penguin-licensing`'s `axum` feature and the
  Python `penguin_aaa.middleware` package.
- ES384/ES512/EdDSA *signing* (currently verify-only) if a consumer needs
  it — not required by any current service.

## Testing

```bash
cargo test
```

RS256 and ES512 tests shell out to the `openssl` CLI to generate test-only
key material (RSA-4096 keygen and P-521 SPKI encoding have no pure-Rust
path in this crate's dependency set by design — see above). Requires
`openssl` on `PATH`; present on every GitHub Actions `ubuntu-latest`
runner and virtually every dev workstation.
