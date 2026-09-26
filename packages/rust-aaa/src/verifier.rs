//! JWT verification: the elliptic-curve family (`ES256`/`ES384`/`ES512`/
//! `EdDSA`) — primary and preferred — plus `RS256` (RSA, 4096-bit
//! minimum), accepted only as a legacy backup. See the crate root doc for
//! the full algorithm policy and why no bundled multi-algorithm JWT crate
//! is used.

use p521::ecdsa::signature::Verifier as _;

use crate::claims::Claims;
use crate::error::AaaError;
use crate::key::{DetectedKey, detect};
use crate::token::{Header, b64url_decode};

/// Verifies a JWT signed with one of five accepted algorithms and returns
/// the decoded [`Claims`]. Every other algorithm — every HMAC variant
/// (`HS256`/`HS384`/`HS512`) and `alg: none` — is rejected.
///
/// A verifier is built from exactly one public key, and the accepted
/// algorithm is *derived from that key's own type* (EC curve or RSA),
/// never supplied separately by the caller. This closes the alg-confusion
/// surface structurally: there is no configuration path where a verifier
/// holding an EC key would ever attempt RSA verification (or vice versa)
/// for a relabeled token, and a token's declared `alg` must match what the
/// key cryptographically is before signature verification is even
/// attempted.
pub struct Es256Verifier {
    key: VerifyKey,
    expected_audience: Option<String>,
    expected_issuer: Option<String>,
}

/// The verification backend for one detected key type. `ring` covers
/// ES256 (P-256), ES384 (P-384), EdDSA (Ed25519), and RS256 (RSA,
/// PKCS#1-v1.5-SHA256) — none of which pull in the `rsa` crate or any
/// other RUSTSEC-flagged dependency. `ring` has no P-521 support at all,
/// so ES512 is verified via the `p521` crate directly instead.
enum VerifyKey {
    /// ES256: raw uncompressed SEC1 P-256 point.
    Es256(Vec<u8>),
    /// ES384: raw uncompressed SEC1 P-384 point.
    Es384(Vec<u8>),
    /// ES512: parsed P-521 verifying key (`ring` can't do this one).
    Es512(p521::ecdsa::VerifyingKey),
    /// EdDSA: raw 32-byte Ed25519 point.
    EdDsa(Vec<u8>),
    /// RS256 (legacy backup): raw PKCS#1 `RSAPublicKey` DER, already
    /// confirmed >= the crate's RSA minimum modulus size (4096 bits).
    Rs256(Vec<u8>),
}

// `Es256Verifier`'s own `Debug` below never delegates to `key` (there's no
// value in exposing key bytes even through a derived `Debug`), so
// `VerifyKey` itself doesn't need one.
impl std::fmt::Debug for Es256Verifier {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.debug_struct("Es256Verifier").finish_non_exhaustive()
    }
}

impl Es256Verifier {
    /// Builds a verifier from an SPKI-wrapped public key PEM
    /// (`-----BEGIN PUBLIC KEY-----`). The key's algorithm is detected
    /// from the SPKI `AlgorithmIdentifier` (see [`crate::key::detect`]);
    /// construction fails for any key type other than
    /// P-256/P-384/P-521/Ed25519/RSA, and for an RSA key under the
    /// 4096-bit minimum. No audience/issuer is pinned by default; chain
    /// [`Es256Verifier::with_audience`] / [`Es256Verifier::with_issuer`]
    /// to require a specific one.
    pub fn from_public_key_pem(pem: &[u8]) -> Result<Self, AaaError> {
        let pem_str = std::str::from_utf8(pem).map_err(|e| AaaError::InvalidKey(e.to_string()))?;
        let key = match detect(pem_str)? {
            DetectedKey::Es256(raw) => VerifyKey::Es256(raw),
            DetectedKey::Es384(raw) => VerifyKey::Es384(raw),
            DetectedKey::Es512(raw) => {
                let verifying_key = p521::ecdsa::VerifyingKey::from_sec1_bytes(&raw)
                    .map_err(|e| AaaError::InvalidKey(e.to_string()))?;
                VerifyKey::Es512(verifying_key)
            }
            DetectedKey::EdDsa(raw) => VerifyKey::EdDsa(raw),
            DetectedKey::Rs256(raw) => VerifyKey::Rs256(raw),
        };
        Ok(Self {
            key,
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

    /// The one JWS `alg` string this verifier's key accepts.
    fn expected_alg(&self) -> &'static str {
        match &self.key {
            VerifyKey::Es256(_) => "ES256",
            VerifyKey::Es384(_) => "ES384",
            VerifyKey::Es512(_) => "ES512",
            VerifyKey::EdDsa(_) => "EdDSA",
            VerifyKey::Rs256(_) => "RS256",
        }
    }

    /// Verifies the signature segment against `signing_input` using the
    /// backend matching this verifier's key. Every failure mode — bad
    /// signature length, cryptographic mismatch — collapses to a single
    /// opaque error string; see [`AaaError::Verification`].
    fn verify_signature(&self, signing_input: &str, sig_bytes: &[u8]) -> Result<(), String> {
        match &self.key {
            VerifyKey::Es256(raw) => ring::signature::UnparsedPublicKey::new(
                &ring::signature::ECDSA_P256_SHA256_FIXED,
                raw,
            )
            .verify(signing_input.as_bytes(), sig_bytes)
            .map_err(|e| e.to_string()),
            VerifyKey::Es384(raw) => ring::signature::UnparsedPublicKey::new(
                &ring::signature::ECDSA_P384_SHA384_FIXED,
                raw,
            )
            .verify(signing_input.as_bytes(), sig_bytes)
            .map_err(|e| e.to_string()),
            VerifyKey::EdDsa(raw) => {
                ring::signature::UnparsedPublicKey::new(&ring::signature::ED25519, raw)
                    .verify(signing_input.as_bytes(), sig_bytes)
                    .map_err(|e| e.to_string())
            }
            VerifyKey::Rs256(raw) => ring::signature::UnparsedPublicKey::new(
                &ring::signature::RSA_PKCS1_2048_8192_SHA256,
                raw,
            )
            .verify(signing_input.as_bytes(), sig_bytes)
            .map_err(|e| e.to_string()),
            VerifyKey::Es512(verifying_key) => {
                let signature =
                    p521::ecdsa::Signature::from_slice(sig_bytes).map_err(|e| e.to_string())?;
                verifying_key
                    .verify(signing_input.as_bytes(), &signature)
                    .map_err(|e| e.to_string())
            }
        }
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
        if header.alg != self.expected_alg() {
            return Err(AaaError::Verification(format!(
                "alg {:?} does not match this verifier's key (expects {:?})",
                header.alg,
                self.expected_alg()
            )));
        }

        let sig_bytes =
            b64url_decode(sig_b64).map_err(|e| AaaError::Verification(e.to_string()))?;
        let signing_input = format!("{header_b64}.{payload_b64}");
        self.verify_signature(&signing_input, &sig_bytes)
            .map_err(AaaError::Verification)?;

        let payload_bytes =
            b64url_decode(payload_b64).map_err(|e| AaaError::Verification(e.to_string()))?;
        let claims: Claims = serde_json::from_slice(&payload_bytes)
            .map_err(|e| AaaError::Verification(e.to_string()))?;

        let now = std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
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
