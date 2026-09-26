//! SPKI public-key parsing and algorithm auto-detection for
//! [`crate::Es256Verifier`].
//!
//! Extracts the raw key bytes `ring`/`p521` need directly from an
//! SPKI-wrapped PEM public key, and identifies which of the five accepted
//! JWS algorithms (`ES256`/`ES384`/`ES512`/`EdDSA`/`RS256`) the key
//! corresponds to from its `AlgorithmIdentifier` OID — and, for EC keys,
//! the named-curve parameter OID — never from caller-supplied
//! configuration. A verifier's accepted algorithm is exactly what the key
//! material cryptographically is; there is no code path where a verifier
//! built from an EC key could be coaxed into RSA verification (or vice
//! versa) by a relabeled token.

use base64::Engine;
use base64::engine::general_purpose::STANDARD;
use der::asn1::{ObjectIdentifier, UintRef};
use der::{Decode, Reader, SliceReader};
use spki::SubjectPublicKeyInfoRef;

use crate::error::AaaError;

const OID_EC_PUBLIC_KEY: &str = "1.2.840.10045.2.1";
const OID_P256: &str = "1.2.840.10045.3.1.7";
const OID_P384: &str = "1.3.132.0.34";
const OID_P521: &str = "1.3.132.0.35";
const OID_ED25519: &str = "1.3.101.112";
const OID_RSA_ENCRYPTION: &str = "1.2.840.113549.1.1.1";

/// Minimum RSA modulus size this crate accepts for `RS256` verification.
/// RSA is the *legacy* backup path only — 4096-bit is the platform's RSA
/// floor (see the crate README's crypto-backend policy). A key below this
/// is rejected at [`crate::Es256Verifier::from_public_key_pem`] time, not
/// deferred to a per-token check.
pub const RSA_MIN_MODULUS_BITS: usize = 4096;

/// A public key identified as one of the five algorithms this crate
/// accepts, carrying the raw bytes the matching verification backend
/// needs (already extracted from the SPKI wrapper).
pub(crate) enum DetectedKey {
    /// ECDSA P-256 — raw uncompressed SEC1 point (ring's expected format).
    Es256(Vec<u8>),
    /// ECDSA P-384 — raw uncompressed SEC1 point.
    Es384(Vec<u8>),
    /// ECDSA P-521 — raw uncompressed SEC1 point. `ring` has no P-521
    /// support, so this is verified via the `p521` crate directly instead.
    Es512(Vec<u8>),
    /// Ed25519 — raw 32-byte public point.
    EdDsa(Vec<u8>),
    /// RSA (legacy backup) — raw PKCS#1 `RSAPublicKey` DER; modulus bit
    /// length already validated `>= RSA_MIN_MODULUS_BITS`.
    Rs256(Vec<u8>),
}

/// Minimal PKCS#1 `RSAPublicKey ::= SEQUENCE { modulus, publicExponent }`
/// shape — decoded only far enough to measure the modulus's byte length
/// for the 4096-bit-minimum check; the exponent is read (required to
/// consume the DER correctly) but otherwise unused.
struct RsaPublicKeyRef<'a> {
    modulus: UintRef<'a>,
}

impl<'a> Decode<'a> for RsaPublicKeyRef<'a> {
    fn decode<R: Reader<'a>>(reader: &mut R) -> der::Result<Self> {
        reader.sequence(|seq| {
            let modulus = UintRef::decode(seq)?;
            let _public_exponent = UintRef::decode(seq)?;
            Ok(Self { modulus })
        })
    }
}

/// Strips PEM armor (`-----BEGIN ...-----` / `-----END ...-----`) and
/// base64 (standard, padded)-decodes the body. Generic across key types,
/// since this crate must inspect the SPKI structure itself before it
/// knows which typed decoder (if any) to hand the DER to.
fn pem_to_der(pem: &str) -> Result<Vec<u8>, AaaError> {
    let body: String = pem
        .lines()
        .filter(|line| !line.starts_with("-----"))
        .collect();
    STANDARD
        .decode(body)
        .map_err(|e| AaaError::InvalidKey(format!("invalid PEM base64: {e}")))
}

/// Parses an SPKI-wrapped public key PEM and identifies which of the five
/// accepted algorithms it corresponds to. Rejects any other key type (EC
/// curve other than P-256/P-384/P-521, RSA under the 4096-bit minimum, or
/// anything else) with a descriptive [`AaaError::InvalidKey`].
pub(crate) fn detect(pem: &str) -> Result<DetectedKey, AaaError> {
    let der_bytes = pem_to_der(pem)?;
    let spki = SubjectPublicKeyInfoRef::try_from(der_bytes.as_slice())
        .map_err(|e| AaaError::InvalidKey(format!("invalid SPKI DER: {e}")))?;
    let raw = spki.subject_public_key.raw_bytes().to_vec();

    if spki.algorithm.oid == ObjectIdentifier::new_unwrap(OID_EC_PUBLIC_KEY) {
        let curve_oid: ObjectIdentifier = spki
            .algorithm
            .parameters
            .ok_or_else(|| AaaError::InvalidKey("EC key missing curve parameters".to_string()))?
            .decode_as()
            .map_err(|e| AaaError::InvalidKey(format!("EC curve parameter not an OID: {e}")))?;
        if curve_oid == ObjectIdentifier::new_unwrap(OID_P256) {
            Ok(DetectedKey::Es256(raw))
        } else if curve_oid == ObjectIdentifier::new_unwrap(OID_P384) {
            Ok(DetectedKey::Es384(raw))
        } else if curve_oid == ObjectIdentifier::new_unwrap(OID_P521) {
            Ok(DetectedKey::Es512(raw))
        } else {
            Err(AaaError::InvalidKey(format!(
                "unsupported EC curve {curve_oid} (only P-256/P-384/P-521 accepted)"
            )))
        }
    } else if spki.algorithm.oid == ObjectIdentifier::new_unwrap(OID_ED25519) {
        Ok(DetectedKey::EdDsa(raw))
    } else if spki.algorithm.oid == ObjectIdentifier::new_unwrap(OID_RSA_ENCRYPTION) {
        let mut reader = SliceReader::new(&raw)
            .map_err(|e| AaaError::InvalidKey(format!("invalid RSAPublicKey DER: {e}")))?;
        let parsed = RsaPublicKeyRef::decode(&mut reader)
            .map_err(|e| AaaError::InvalidKey(format!("invalid RSAPublicKey DER: {e}")))?;
        let bits = parsed.modulus.as_bytes().len() * 8;
        if bits < RSA_MIN_MODULUS_BITS {
            return Err(AaaError::InvalidKey(format!(
                "RSA modulus is {bits} bits; this crate requires at least \
                 {RSA_MIN_MODULUS_BITS}-bit RSA keys (legacy RS256 backup policy)"
            )));
        }
        Ok(DetectedKey::Rs256(raw))
    } else {
        Err(AaaError::InvalidKey(format!(
            "unsupported public key algorithm {} (only ES256/ES384/ES512/EdDSA/RS256 accepted)",
            spki.algorithm.oid
        )))
    }
}
