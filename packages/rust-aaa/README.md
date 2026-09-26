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
