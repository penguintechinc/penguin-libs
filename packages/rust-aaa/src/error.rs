//! Error type for ES256 sign/verify operations.

/// Errors from ES256 key loading, signing, or verification.
///
/// Verification failures deliberately collapse every underlying failure
/// mode (malformed token structure, bad base64, disallowed `alg`, bad
/// signature, expired, missing required claim, audience/issuer mismatch)
/// into one [`AaaError::Verification`] variant carrying a description —
/// callers must never branch behavior on *why* a token failed to verify,
/// only on the fact that it did (see security.md: a credential failure
/// must never leak which check failed to the caller).
#[derive(Debug, thiserror::Error)]
pub enum AaaError {
    /// The supplied PEM was not valid EC (P-256) key material.
    #[error("invalid ES256 key material: {0}")]
    InvalidKey(String),

    /// Signing a claim set failed (only reachable with a malformed key
    /// that slipped past construction, or an unserializable claim set).
    #[error("token signing failed: {0}")]
    Signing(String),

    /// Token structure, signature, expiration, or required-claim
    /// verification failed.
    #[error("token verification failed: {0}")]
    Verification(String),
}
