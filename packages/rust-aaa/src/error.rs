//! Error type for ES256 sign/verify operations.

/// Errors from ES256 key loading, signing, or verification.
///
/// Verification failures deliberately collapse every underlying
/// `jsonwebtoken` failure mode (bad signature, disallowed algorithm,
/// expired, malformed, missing required claim) into one
/// [`AaaError::Verification`] variant carrying the original error —
/// callers must never branch behavior on *why* a token failed to verify,
/// only on the fact that it did (see security.md: a credential failure
/// must never leak which check failed to the caller). The original error
/// is retained for the caller's own sanitized debug-level logging, mirrored
/// from `testserver-rs`'s `JwtVerifier::verify`.
#[derive(Debug, thiserror::Error)]
pub enum AaaError {
    /// The supplied PEM was not valid EC (P-256) key material.
    #[error("invalid ES256 key material: {0}")]
    InvalidKey(jsonwebtoken::errors::Error),

    /// Signing a claim set failed (only reachable with a malformed key
    /// that slipped past construction).
    #[error("token signing failed: {0}")]
    Signing(jsonwebtoken::errors::Error),

    /// Signature, algorithm, expiration, or required-claim verification
    /// failed.
    #[error("token verification failed: {0}")]
    Verification(jsonwebtoken::errors::Error),
}
