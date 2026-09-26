//! JWT signing and verification primitives shared across PenguinTech's
//! Rust services (`node-agent`, `testserver-rs`, `hub-router-rs`),
//! replacing three independent reimplementations of the same
//! alg-confusion-safe verify + short-lived-JWT sign logic.
//!
//! ## Algorithm policy
//!
//! - **Elliptic-curve family — primary/preferred**: `ES256` (P-256),
//!   `ES384` (P-384), `ES512` (P-521), `EdDSA` (Ed25519). All four are
//!   accepted for *verification*; **`ES256` is the only one this crate
//!   signs** — new services sign ES256, matching every current consumer.
//! - **`RS256` (RSA, 4096-bit minimum) — legacy backup, verify-only**.
//!   Existing Python issuers that can't yet sign EC keep working; this
//!   crate never mints an RS256 token.
//! - **Forbidden, unconditionally**: every HMAC variant
//!   (`HS256`/`HS384`/`HS512`) and `alg: none`.
//!
//! [`Es256Signer`] signs [`Claims`] into a compact ES256 JWS.
//! [`Es256Verifier`] is built from exactly one public key; the algorithm
//! it accepts is *derived from that key's own type* (EC curve or RSA),
//! never supplied by the caller — see [`Es256Verifier::from_public_key_pem`].
//! The machine-token exchange/refresh HTTP lifecycle (`hub-router-rs`'s
//! `MachineJWTClient`) and an Axum verification middleware are **not** in
//! this version — see the crate README's "Planned (v0.2)" section.
//!
//! Ported from `engines/testserver-rs/crates/core/src/auth.rs`
//! (`JwtVerifier`) and `agents/node-agent/crates/core/src/jwt.rs`
//! (`MachineJwtSigner`) in the `tobogganing` repository.
//!
//! **No bundled multi-algorithm JWT crate**: every general-purpose Rust
//! JWT library evaluated (`jsonwebtoken`'s `rust_crypto` feature,
//! `jwt-simple`'s `pure-rust` feature) unconditionally pulls in the `rsa`
//! crate (RSA/RS256/PS256 support) alongside ES256 — one Cargo feature
//! covers the whole algorithm bundle, with no way to get P-256 without
//! also getting RSA. `rsa` carries RUSTSEC-2023-0071 (Marvin Attack RSA
//! timing sidechannel) with no patched release available upstream. This
//! crate implements the JWS framing directly instead: `ring` covers
//! ES256/ES384/EdDSA/RS256 verification (`ring` has no RSA-*crate*
//! dependency and no P-521 support), `p521` covers ES512 verification
//! (the one gap `ring` leaves), and `p256` covers ES256 signing. `cargo
//! tree` has zero `rsa` entries and `cargo deny check` carries no
//! advisory ignores.
//!
//! ```
//! use penguin_aaa::{Claims, Es256Signer, Es256Verifier};
//!
//! # fn generate_test_keypair() -> (String, String) {
//! #     use p256::ecdsa::{SigningKey, VerifyingKey};
//! #     use p256::pkcs8::{EncodePrivateKey, EncodePublicKey, LineEnding};
//! #     let signing_key = SigningKey::random(&mut rand_core::OsRng);
//! #     let private_pem = signing_key.to_pkcs8_pem(LineEnding::LF).unwrap().to_string();
//! #     let public_pem = VerifyingKey::from(&signing_key).to_public_key_pem(LineEnding::LF).unwrap();
//! #     (private_pem, public_pem)
//! # }
//! let (private_pem, public_pem) = generate_test_keypair();
//! let signer = Es256Signer::from_ec_pem(private_pem.as_bytes())?;
//! let verifier = Es256Verifier::from_public_key_pem(public_pem.as_bytes())?;
//!
//! let claims = Claims::new("user-123", "auth.penguintech.io", "hub-api", 0, 32_503_680_000, "users:read");
//! let token = signer.sign(&claims)?;
//! let verified = verifier.verify(&token)?;
//! assert_eq!(verified.sub, "user-123");
//! # Ok::<(), penguin_aaa::AaaError>(())
//! ```

mod claims;
mod error;
mod key;
mod signer;
mod token;
mod verifier;

pub use claims::Claims;
pub use error::AaaError;
pub use signer::Es256Signer;
pub use verifier::Es256Verifier;
