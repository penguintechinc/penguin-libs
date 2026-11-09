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
    expected_audience: String,
    expected_issuer: String,
}

/// Maximum accepted token lifetime (`exp - iat`), the platform's 24-hour
/// ceiling for any token. Not configurable: raising it is a policy change.
const MAX_TOKEN_LIFETIME_SECS: i64 = 86_400;

/// Clock-skew leeway applied to the `exp` and `nbf` checks. Capped small
/// so a stale token cannot be replayed long after it should have died.
const CLOCK_SKEW_LEEWAY_SECS: i64 = 60;

/// Builder for [`Es256Verifier`]. `audience` and `issuer` are mandatory:
/// [`Es256VerifierBuilder::build`] fails if either is unset, so a verifier
/// that would accept tokens minted for any service cannot be constructed.
#[derive(Debug)]
pub struct Es256VerifierBuilder {
    public_key_pem: Vec<u8>,
    audience: Option<String>,
    issuer: Option<String>,
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

impl Es256VerifierBuilder {
    /// Requires the token's `aud` claim to equal `audience` (mandatory).
    #[must_use]
    pub fn audience(mut self, audience: &str) -> Self {
        self.audience = Some(audience.to_string());
        self
    }

    /// Requires the token's `iss` claim to equal `issuer` (mandatory).
    #[must_use]
    pub fn issuer(mut self, issuer: &str) -> Self {
        self.issuer = Some(issuer.to_string());
        self
    }

    /// Parses the key and produces the verifier. Fails with
    /// [`AaaError::Config`] when `audience` or `issuer` is unset or empty,
    /// and with [`AaaError::InvalidKey`] for unusable key material.
    pub fn build(self) -> Result<Es256Verifier, AaaError> {
        let audience = self.audience.filter(|a| !a.is_empty()).ok_or_else(|| {
            AaaError::Config("audience is required and must be non-empty".to_string())
        })?;
        let issuer = self.issuer.filter(|i| !i.is_empty()).ok_or_else(|| {
            AaaError::Config("issuer is required and must be non-empty".to_string())
        })?;
        let pem_str = std::str::from_utf8(&self.public_key_pem)
            .map_err(|e| AaaError::InvalidKey(e.to_string()))?;
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
        Ok(Es256Verifier {
            key,
            expected_audience: audience,
            expected_issuer: issuer,
        })
    }
}

impl Es256Verifier {
    /// Starts a builder from an SPKI-wrapped public key PEM
    /// (`-----BEGIN PUBLIC KEY-----`). Call [`Es256VerifierBuilder::audience`]
    /// and [`Es256VerifierBuilder::issuer`], then [`Es256VerifierBuilder::build`].
    #[must_use]
    pub fn builder(public_key_pem: &[u8]) -> Es256VerifierBuilder {
        Es256VerifierBuilder {
            public_key_pem: public_key_pem.to_vec(),
            audience: None,
            issuer: None,
        }
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
            // Fixed text: the header `alg` is untrusted and must never be echoed.
            return Err(AaaError::Verification(format!(
                "algorithm does not match this verifier's key (expects {})",
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
        // Untrusted i64 arithmetic: checked/saturating so hostile values
        // fail closed instead of wrapping or panicking.
        let lifetime = claims
            .exp
            .checked_sub(claims.iat)
            .ok_or_else(|| AaaError::Verification("token lifetime is out of range".to_string()))?;
        if lifetime < 0 {
            return Err(AaaError::Verification("exp precedes iat".to_string()));
        }
        if lifetime > MAX_TOKEN_LIFETIME_SECS {
            return Err(AaaError::Verification(
                "token lifetime exceeds the 24h maximum".to_string(),
            ));
        }
        if claims.iat > now.saturating_add(CLOCK_SKEW_LEEWAY_SECS) {
            return Err(AaaError::Verification(
                "token issued in the future".to_string(),
            ));
        }
        if now.saturating_sub(CLOCK_SKEW_LEEWAY_SECS) > claims.exp {
            return Err(AaaError::Verification("token expired".to_string()));
        }
        if let Some(nbf) = claims.nbf
            && now.saturating_add(CLOCK_SKEW_LEEWAY_SECS) < nbf
        {
            return Err(AaaError::Verification("token not yet valid".to_string()));
        }
        if claims.aud != self.expected_audience {
            return Err(AaaError::Verification(format!(
                "audience mismatch: expected {:?}",
                self.expected_audience
            )));
        }
        if claims.iss != self.expected_issuer {
            return Err(AaaError::Verification(format!(
                "issuer mismatch: expected {:?}",
                self.expected_issuer
            )));
        }

        Ok(claims)
    }
}
