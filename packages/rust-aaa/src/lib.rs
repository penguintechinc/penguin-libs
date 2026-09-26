//! ES256 (ECDSA P-256) JWT signing and verification primitives shared
//! across PenguinTech's Rust services (`node-agent`, `testserver-rs`,
//! `hub-router-rs`), replacing three independent reimplementations of the
//! same alg-confusion-safe verify + short-lived-JWT sign logic.
//!
//! v0.1 scope is deliberately narrow: [`Es256Signer`] (sign [`Claims`] into
//! a compact JWS), [`Es256Verifier`] (verify a token back into [`Claims`],
//! ES256-pinned so HS256/RS256/`alg: none` alg-confusion tokens are
//! rejected before signature verification ever runs), and the shared
//! [`Claims`] shape. The machine-token exchange/refresh HTTP lifecycle
//! (`hub-router-rs`'s `MachineJWTClient`) and an Axum verification
//! middleware are **not** in this version — see the crate README's
//! "Planned (v0.2)" section.
//!
//! Ported from `engines/testserver-rs/crates/core/src/auth.rs`
//! (`JwtVerifier`) and `agents/node-agent/crates/core/src/jwt.rs`
//! (`MachineJwtSigner`) in the `tobogganing` repository.
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
//! let verifier = Es256Verifier::from_ec_pem(public_pem.as_bytes())?;
//!
//! let claims = Claims::new("user-123", "auth.penguintech.io", "hub-api", 0, 32_503_680_000, "users:read");
//! let token = signer.sign(&claims)?;
//! let verified = verifier.verify(&token)?;
//! assert_eq!(verified.sub, "user-123");
//! # Ok::<(), penguin_aaa::AaaError>(())
//! ```

mod claims;
mod error;
mod signer;
mod verifier;

pub use claims::Claims;
pub use error::AaaError;
pub use signer::Es256Signer;
pub use verifier::Es256Verifier;
