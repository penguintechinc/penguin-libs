//! ES256 JWT signing.

use jsonwebtoken::{Algorithm, EncodingKey, Header, encode};

use crate::{claims::Claims, error::AaaError};

/// Signs [`Claims`] into a compact ES256 (ECDSA P-256) JWS.
///
/// Ported from `agents/node-agent/crates/core/src/jwt.rs`'s
/// `MachineJwtSigner`. Key-file loading, PEM permission checks (K8s Secret
/// mount mode enforcement), and the `sign(issuer, node_id, ...)`
/// convenience wrapper stay in `node-agent` — this crate owns only the
/// "given a private key and a claim set, produce a token" primitive.
#[derive(Clone)]
pub struct Es256Signer {
    encoding_key: EncodingKey,
}

// `EncodingKey` doesn't derive `Debug`, and there is no key material here
// worth hiding beyond what `Debug` would leak anyway — a minimal manual
// impl lets callers embed `Es256Signer` in a `Debug`-deriving struct
// without leaking internals `EncodingKey` itself withholds.
impl std::fmt::Debug for Es256Signer {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.debug_struct("Es256Signer").finish_non_exhaustive()
    }
}

impl Es256Signer {
    /// Builds a signer from an EC P-256 private key in PEM
    /// (`-----BEGIN PRIVATE KEY-----` / `-----BEGIN EC PRIVATE KEY-----`,
    /// PKCS#8 or SEC1) format.
    pub fn from_ec_pem(private_key_pem: &[u8]) -> Result<Self, AaaError> {
        let encoding_key =
            EncodingKey::from_ec_pem(private_key_pem).map_err(AaaError::InvalidKey)?;
        Ok(Self { encoding_key })
    }

    /// Signs `claims` into a compact ES256 JWS.
    pub fn sign(&self, claims: &Claims) -> Result<String, AaaError> {
        encode(&Header::new(Algorithm::ES256), claims, &self.encoding_key)
            .map_err(AaaError::Signing)
    }
}
