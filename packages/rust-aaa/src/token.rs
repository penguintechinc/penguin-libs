//! Minimal JWS (compact serialization) framing shared by [`crate::Es256Signer`]
//! and [`crate::Es256Verifier`] — base64url (no padding) encode/decode plus
//! the one fixed header shape this crate ever produces or accepts.

use base64::Engine;
use base64::engine::general_purpose::URL_SAFE_NO_PAD;
use serde::{Deserialize, Serialize};

/// The only JWS header shape this crate ever produces or accepts. `alg`
/// is a plain `String` field here (not an enum) because it must always be
/// *read* off an untrusted token and compared against `"ES256"` — see
/// [`crate::Es256Verifier::verify`], which rejects anything else before
/// ever looking at the signature.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub(crate) struct Header {
    pub(crate) alg: String,
    pub(crate) typ: String,
}

impl Header {
    /// The fixed header this crate always signs with.
    pub(crate) fn es256() -> Self {
        Self {
            alg: "ES256".to_string(),
            typ: "JWT".to_string(),
        }
    }
}

/// Base64url-encodes (no padding) — the JWS-mandated encoding for each of
/// a compact token's three segments.
pub(crate) fn b64url_encode(input: &[u8]) -> String {
    URL_SAFE_NO_PAD.encode(input)
}

/// Base64url-decodes (no padding).
pub(crate) fn b64url_decode(input: &str) -> Result<Vec<u8>, base64::DecodeError> {
    URL_SAFE_NO_PAD.decode(input)
}
