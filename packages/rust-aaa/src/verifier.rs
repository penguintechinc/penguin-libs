//! ES256 JWT verification — hand-rolled JWS framing, see the crate root
//! doc for why this doesn't go through a bundled multi-algorithm JWT
//! crate.

use p256::ecdsa::signature::Verifier as _;
use p256::ecdsa::{Signature, VerifyingKey};
use p256::pkcs8::DecodePublicKey;
use std::time::{SystemTime, UNIX_EPOCH};

use crate::claims::Claims;
use crate::error::AaaError;
use crate::token::{Header, b64url_decode};

/// Verifies ES256 (ECDSA P-256, SHA-256) JWTs and returns the decoded
/// [`Claims`].
///
/// Ported from `engines/testserver-rs/crates/core/src/auth.rs`'s
/// `JwtVerifier`. There is exactly one verification code path — parse the
/// header, require `alg == "ES256"`, then ECDSA-verify the signature
/// segment against the configured P-256 public key — so there is no `alg`
/// dispatch to confuse: an HS256- or `alg: none`-labeled token is rejected
/// by the explicit `alg` check before its signature segment is ever
/// interpreted, and even without that check a genuine HMAC tag or an empty
/// signature cannot parse as the fixed 64-byte ECDSA R‖S value this
/// verifier expects.
#[derive(Debug, Clone)]
pub struct Es256Verifier {
    verifying_key: VerifyingKey,
    expected_audience: Option<String>,
    expected_issuer: Option<String>,
}

impl Es256Verifier {
    /// Builds a verifier from an EC P-256 public key in SPKI PEM
    /// (`-----BEGIN PUBLIC KEY-----`) format. No audience/issuer is pinned
    /// by default; chain [`Es256Verifier::with_audience`] /
    /// [`Es256Verifier::with_issuer`] to require a specific one.
    pub fn from_ec_pem(public_key_pem: &[u8]) -> Result<Self, AaaError> {
        let pem =
            std::str::from_utf8(public_key_pem).map_err(|e| AaaError::InvalidKey(e.to_string()))?;
        let verifying_key = VerifyingKey::from_public_key_pem(pem)
            .map_err(|e| AaaError::InvalidKey(e.to_string()))?;
        Ok(Self {
            verifying_key,
            expected_audience: None,
            expected_issuer: None,
        })
    }

    /// Additionally requires the token's `aud` claim to equal `audience`.
    #[must_use]
    pub fn with_audience(mut self, audience: &str) -> Self {
        self.expected_audience = Some(audience.to_string());
        self
    }

    /// Additionally requires the token's `iss` claim to equal `issuer`.
    #[must_use]
    pub fn with_issuer(mut self, issuer: &str) -> Self {
        self.expected_issuer = Some(issuer.to_string());
        self
    }

    /// Verifies structure, `alg`, signature, expiration, and (if
    /// configured) audience/issuer, returning the decoded [`Claims`] on
    /// success. Every failure mode collapses to [`AaaError::Verification`]
    /// — see that variant's docs.
    pub fn verify(&self, token: &str) -> Result<Claims, AaaError> {
        let mut segments = token.split('.');
        let (Some(header_b64), Some(payload_b64), Some(sig_b64), None) = (
            segments.next(),
            segments.next(),
            segments.next(),
            segments.next(),
        ) else {
            return Err(AaaError::Verification(
                "malformed token: expected exactly 3 '.'-separated segments".to_string(),
            ));
        };

        let header_bytes =
            b64url_decode(header_b64).map_err(|e| AaaError::Verification(e.to_string()))?;
        let header: Header = serde_json::from_slice(&header_bytes)
            .map_err(|e| AaaError::Verification(e.to_string()))?;
        if header.alg != "ES256" {
            return Err(AaaError::Verification(format!(
                "unsupported alg {:?}: only ES256 is accepted",
                header.alg
            )));
        }

        let sig_bytes =
            b64url_decode(sig_b64).map_err(|e| AaaError::Verification(e.to_string()))?;
        let signature =
            Signature::from_slice(&sig_bytes).map_err(|e| AaaError::Verification(e.to_string()))?;
        let signing_input = format!("{header_b64}.{payload_b64}");
        self.verifying_key
            .verify(signing_input.as_bytes(), &signature)
            .map_err(|e| AaaError::Verification(e.to_string()))?;

        let payload_bytes =
            b64url_decode(payload_b64).map_err(|e| AaaError::Verification(e.to_string()))?;
        let claims: Claims = serde_json::from_slice(&payload_bytes)
            .map_err(|e| AaaError::Verification(e.to_string()))?;

        let now = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .map_err(|e| AaaError::Verification(e.to_string()))?
            .as_secs() as i64;
        if claims.exp < now {
            return Err(AaaError::Verification("token expired".to_string()));
        }
        if let Some(expected) = &self.expected_audience
            && &claims.aud != expected
        {
            return Err(AaaError::Verification(format!(
                "audience mismatch: expected {expected:?}"
            )));
        }
        if let Some(expected) = &self.expected_issuer
            && &claims.iss != expected
        {
            return Err(AaaError::Verification(format!(
                "issuer mismatch: expected {expected:?}"
            )));
        }

        Ok(claims)
    }
}
