//! ES256 JWT verification.

use jsonwebtoken::{Algorithm, DecodingKey, Validation, decode};

use crate::{claims::Claims, error::AaaError};

/// Verifies ES256 (ECDSA P-256) JWTs and returns the decoded [`Claims`].
///
/// Ported from `engines/testserver-rs/crates/core/src/auth.rs`'s
/// `JwtVerifier`.
///
/// `algorithms` is pinned to `[ES256]` only, so a token signed HS256 —
/// including the classic alg-confusion attack that reuses this verifier's
/// public key as an HMAC secret, since a public key is not secret — or one
/// declaring `alg: none` is rejected before signature verification ever
/// runs; `jsonwebtoken::Algorithm` has no `none` variant at all, so an
/// `alg: none` header fails to even parse.
#[derive(Clone)]
pub struct Es256Verifier {
    decoding_key: DecodingKey,
    validation: Validation,
}

// See `Es256Signer`'s `Debug` impl rationale — `DecodingKey`/`Validation`
// don't derive `Debug` either, and this key is a *public* key, so there is
// nothing worth hiding.
impl std::fmt::Debug for Es256Verifier {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.debug_struct("Es256Verifier").finish_non_exhaustive()
    }
}

impl Es256Verifier {
    /// Builds a verifier from an EC P-256 public key in PEM
    /// (`-----BEGIN PUBLIC KEY-----`, SPKI/DER) format. Expiration is
    /// always validated; `sub` and `exp` are required spec claims — a
    /// token missing either is rejected even before the rest of [`Claims`]
    /// is deserialized. No audience/issuer is pinned by default — since
    /// [`Claims::aud`] is always present, `jsonwebtoken`'s
    /// `validate_aud` (which defaults to `true` and errors on *any*
    /// present-but-unpinned `aud`) is explicitly disabled here; chain
    /// [`Es256Verifier::with_audience`] / [`Es256Verifier::with_issuer`] to
    /// require a specific one.
    pub fn from_ec_pem(public_key_pem: &[u8]) -> Result<Self, AaaError> {
        let decoding_key =
            DecodingKey::from_ec_pem(public_key_pem).map_err(AaaError::InvalidKey)?;
        let mut validation = Validation::new(Algorithm::ES256);
        validation.validate_exp = true;
        validation.validate_aud = false;
        validation.algorithms = vec![Algorithm::ES256];
        validation.required_spec_claims = ["exp", "sub"].into_iter().map(String::from).collect();
        Ok(Self {
            decoding_key,
            validation,
        })
    }

    /// Additionally requires the token's `aud` claim to equal `audience`.
    #[must_use]
    pub fn with_audience(mut self, audience: &str) -> Self {
        self.validation.validate_aud = true;
        self.validation.set_audience(&[audience]);
        self
    }

    /// Additionally requires the token's `iss` claim to equal `issuer`.
    #[must_use]
    pub fn with_issuer(mut self, issuer: &str) -> Self {
        self.validation.set_issuer(&[issuer]);
        self
    }

    /// Verifies signature, algorithm, expiration, and required claims,
    /// returning the decoded [`Claims`] on success. Every failure mode
    /// collapses to [`AaaError::Verification`] — see that variant's docs.
    pub fn verify(&self, token: &str) -> Result<Claims, AaaError> {
        decode::<Claims>(token, &self.decoding_key, &self.validation)
            .map(|data| data.claims)
            .map_err(AaaError::Verification)
    }
}
