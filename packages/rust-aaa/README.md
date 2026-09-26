# penguin-aaa (Rust)

ES256 (ECDSA P-256) JWT signing and verification primitives shared across
PenguinTech's Rust services. Extracted from three independent
reimplementations in the `tobogganing` repository:

- `engines/testserver-rs/crates/core/src/auth.rs` — `JwtVerifier` (verify
  side).
- `agents/node-agent/crates/core/src/jwt.rs` — `MachineJwtSigner` (sign
  side).
- `services/hub-router-rs/crates/auth/` — `MachineJWTClient` (token
  exchange/refresh HTTP lifecycle; not yet consuming this crate — see
  "Planned (v0.2)" below).

## Scope (v0.1)

- [`Es256Signer`] — sign a [`Claims`] value into a compact ES256 JWS.
- [`Es256Verifier`] — verify a token back into [`Claims`]. `algorithms` is
  pinned to `[ES256]` only, so HS256/RS256 alg-confusion tokens and
  `alg: none` tokens are rejected before signature verification ever runs.
- [`Claims`] — the shared claim set: `sub`/`iss`/`aud`/`iat`/`exp`/`scope`
  are structurally required; `tenant`/`teams`/`roles` default to
  absent/empty for machine-to-machine tokens that don't carry them.
  Mirrors the platform's mandatory claim set (security.md JWT Claims).

## Crypto backend: hand-rolled ES256 JWS, no bundled JWT crate

This crate does **not** depend on `jsonwebtoken`, `jwt-simple`, or any other
general-purpose multi-algorithm JWT library. Every one evaluated bundles
RSA support (`RS256`/`PS256`) unconditionally alongside ES256 — one Cargo
feature covers the whole algorithm set, with no way to opt into P-256 only:

- `jsonwebtoken`'s `rust_crypto` feature: `["dep:ed25519-dalek", "dep:hmac",
  "dep:p256", "dep:p384", "dep:rand", "dep:rsa", "dep:sha2"]`.
- `jwt-simple`'s `pure-rust` feature: same shape, also pulls `rsa`.

The `rsa` crate carries **RUSTSEC-2023-0071** (Marvin Attack, RSA timing
sidechannel) with no patched release available upstream (still open,
tracked at RustCrypto/RSA#626/#680/#702). Depending on either library would
mean either accepting that advisory into `cargo deny check` via a
documented ignore, or is not viable since org policy treats RUSTSEC
advisories as a hard no-go regardless of whether the vulnerable code path
is reachable.

Since this crate only ever needs ES256, it implements the JWS compact
serialization directly over `p256`/`ecdsa` (pure Rust, RFC6979 deterministic
signing, SHA-256 prehash) in `src/token.rs` + `src/signer.rs` +
`src/verifier.rs` — roughly 150 lines total. `cargo tree` has zero `rsa`
entries and `cargo deny check` carries no advisory ignores. `node-agent`
and `testserver-rs` currently carry this same `jsonwebtoken`/`rsa`/
RUSTSEC-2023-0071 combination unmodified; migrating them onto this crate
(a follow-on, not part of this v0.1 scaffold) removes it from them too.

## Usage

```rust
use penguin_aaa::{Claims, Es256Signer, Es256Verifier};

let signer = Es256Signer::from_ec_pem(private_key_pem)?;
let verifier = Es256Verifier::from_ec_pem(public_key_pem)?
    .with_audience("hub-api")
    .with_issuer("auth.penguintech.io");

let claims = Claims::new("node-123", "auth.penguintech.io", "hub-api", iat, exp, "dns:config:read");
let token = signer.sign(&claims)?;
let verified = verifier.verify(&token)?;
```

## Planned (v0.2)

- Machine-token exchange/refresh HTTP lifecycle (`hub-router-rs`'s
  `MachineJWTClient`: API-key → access/refresh token exchange, rotation,
  503 + `retry_with_credentials` re-exchange, legacy-token fallback).
- Axum verification middleware (extractor + `require_scope`-style layer),
  matching the shape of `penguin-licensing`'s `axum` feature and the
  Python `penguin_aaa.middleware` package.

## Testing

```bash
cargo test
```
