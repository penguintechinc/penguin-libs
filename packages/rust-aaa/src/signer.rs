//! ES256 JWT signing — hand-rolled JWS framing over `p256`/`ecdsa` (P-256
//! ECDSA, SHA-256 prehash, RFC6979 deterministic nonce). See the crate
//! root doc for why this doesn't go through a bundled multi-algorithm JWT
//! crate.

use p256::ecdsa::signature::Signer as _;
use p256::ecdsa::{Signature, SigningKey};
use p256::pkcs8::DecodePrivateKey;

use crate::claims::Claims;
use crate::error::AaaError;
use crate::token::{Header, b64url_encode};

/// Signs [`Claims`] into a compact ES256 (ECDSA P-256, SHA-256) JWS.
///
/// Ported from `agents/node-agent/crates/core/src/jwt.rs`'s
/// `MachineJwtSigner`. Key-file loading, PEM permission checks (K8s Secret
/// mount mode enforcement), and the `sign(issuer, node_id, ...)`
/// convenience wrapper stay in `node-agent` — this crate owns only the
/// "given a private key and a claim set, produce a token" primitive.
#[derive(Debug, Clone)]
pub struct Es256Signer {
    signing_key: SigningKey,
}

impl Es256Signer {
    /// Builds a signer from an EC P-256 private key in PKCS#8 PEM
    /// (`-----BEGIN PRIVATE KEY-----`) format.
    pub fn from_ec_pem(private_key_pem: &[u8]) -> Result<Self, AaaError> {
        let pem = std::str::from_utf8(private_key_pem)
            .map_err(|e| AaaError::InvalidKey(e.to_string()))?;
        let signing_key =
            SigningKey::from_pkcs8_pem(pem).map_err(|e| AaaError::InvalidKey(e.to_string()))?;
        Ok(Self { signing_key })
    }

    /// Signs `claims` into a compact ES256 JWS: base64url(header) + "." +
    /// base64url(claims), ECDSA-signed over that exact byte string with
    /// SHA-256, signature appended as a third base64url segment.
    pub fn sign(&self, claims: &Claims) -> Result<String, AaaError> {
        let header_json =
            serde_json::to_vec(&Header::es256()).map_err(|e| AaaError::Signing(e.to_string()))?;
        let payload_json =
            serde_json::to_vec(claims).map_err(|e| AaaError::Signing(e.to_string()))?;
        let signing_input = format!(
            "{}.{}",
            b64url_encode(&header_json),
            b64url_encode(&payload_json)
        );

        let signature: Signature = self
            .signing_key
            .try_sign(signing_input.as_bytes())
            .map_err(|e| AaaError::Signing(e.to_string()))?;

        Ok(format!(
            "{signing_input}.{}",
            b64url_encode(&signature.to_bytes())
        ))
    }
}
