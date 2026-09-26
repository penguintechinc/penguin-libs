//! Sign/verify + alg-confusion-rejection tests, ported/adapted from
//! `engines/testserver-rs/crates/core/src/auth.rs` (verify side) and
//! `agents/node-agent/crates/core/src/jwt.rs` (sign side) in the
//! `tobogganing` repository, exercised here through the unified
//! `penguin_aaa` public API (`Es256Signer` / `Es256Verifier` / `Claims`)
//! instead of each service's bespoke wrapper.

use jsonwebtoken::{Algorithm, EncodingKey, Header, encode};
use p256::ecdsa::{SigningKey, VerifyingKey};
use p256::pkcs8::{EncodePrivateKey, EncodePublicKey, LineEnding};
use penguin_aaa::{Claims, Es256Signer, Es256Verifier};
use serde_json::json;

/// Generates a fresh, throwaway EC P-256 keypair as PKCS#8/SPKI PEM —
/// generated at test time, never a fixed/committed key, so nothing
/// resembling real key material ever lands in source control (mirrors
/// both ported sources' `generate_test_keypair`).
fn generate_test_keypair() -> (String, String) {
    let signing_key = SigningKey::random(&mut rand_core::OsRng);
    let private_pem = signing_key
        .to_pkcs8_pem(LineEnding::LF)
        .expect("encoding a freshly generated P-256 key as PKCS#8 PEM must succeed")
        .to_string();
    let public_pem = VerifyingKey::from(&signing_key)
        .to_public_key_pem(LineEnding::LF)
        .expect("encoding the matching public key as SPKI PEM must succeed");
    (private_pem, public_pem)
}

fn now() -> i64 {
    std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .expect("system clock must be after the unix epoch")
        .as_secs() as i64
}

fn sample_claims(exp: i64) -> Claims {
    Claims {
        tenant: Some("acme".to_string()),
        roles: vec!["viewer".to_string()],
        ..Claims::new(
            "user-123",
            "auth.penguintech.io",
            "hub-api",
            now(),
            exp,
            "test:run",
        )
    }
}

#[test]
fn sign_then_verify_round_trips_all_claims() {
    let (private_pem, public_pem) = generate_test_keypair();
    let signer = Es256Signer::from_ec_pem(private_pem.as_bytes())
        .expect("a freshly generated EC private key must build a signer");
    let verifier = Es256Verifier::from_ec_pem(public_pem.as_bytes())
        .expect("a freshly generated EC public key must build a verifier");

    let claims = sample_claims(now() + 3600);
    let token = signer
        .sign(&claims)
        .expect("signing a well-formed claim set must succeed");
    let verified = verifier
        .verify(&token)
        .expect("a token from the matching key must verify");

    assert_eq!(verified, claims);
}

#[test]
fn verify_rejects_wrong_key() {
    let (attacker_private_pem, _) = generate_test_keypair();
    let (_, real_public_pem) = generate_test_keypair();

    let signer = Es256Signer::from_ec_pem(attacker_private_pem.as_bytes())
        .expect("a freshly generated EC private key must build a signer");
    let token = signer
        .sign(&sample_claims(now() + 3600))
        .expect("signing must succeed");

    let verifier = Es256Verifier::from_ec_pem(real_public_pem.as_bytes())
        .expect("a freshly generated EC public key must build a verifier");
    assert!(verifier.verify(&token).is_err());
}

#[test]
fn verify_rejects_expired_token() {
    let (private_pem, public_pem) = generate_test_keypair();
    let signer = Es256Signer::from_ec_pem(private_pem.as_bytes())
        .expect("a freshly generated EC private key must build a signer");
    let verifier = Es256Verifier::from_ec_pem(public_pem.as_bytes())
        .expect("a freshly generated EC public key must build a verifier");

    let token = signer
        .sign(&sample_claims(1))
        .expect("signing an already-expired claim set must still succeed");

    assert!(verifier.verify(&token).is_err());
}

#[test]
fn verify_rejects_missing_required_claim() {
    let (private_pem, public_pem) = generate_test_keypair();
    let verifier = Es256Verifier::from_ec_pem(public_pem.as_bytes())
        .expect("a freshly generated EC public key must build a verifier");

    // Missing `sub` — hand-built payload, since `Claims` itself can't
    // construct an invalid claim set.
    let token = encode(
        &Header::new(Algorithm::ES256),
        &json!({"iss": "x", "aud": "y", "iat": now(), "exp": now() + 3600, "scope": "test:run"}),
        &EncodingKey::from_ec_pem(private_pem.as_bytes())
            .expect("a freshly generated EC key must load"),
    )
    .expect("signing must succeed even though the claim set is missing `sub`");

    assert!(verifier.verify(&token).is_err());
}

/// Alg-confusion guard: a token signed HS256 using this verifier's own
/// ES256 *public* key bytes as the HMAC secret (the textbook
/// asymmetric→HS256 confusion attack — a public key is not secret, so
/// anyone who can see it could forge an HS256-signed token if the
/// verifier ever accepted HS256) must be rejected, because
/// `Es256Verifier`'s `Validation::algorithms` is pinned to `[ES256]` only.
#[test]
fn verify_rejects_hs256_alg_confusion_token() {
    let (_, public_pem) = generate_test_keypair();
    let verifier = Es256Verifier::from_ec_pem(public_pem.as_bytes())
        .expect("a freshly generated EC public key must build a verifier");

    let forged = encode(
        &Header::new(Algorithm::HS256),
        &json!({"sub": "attacker", "iss": "x", "aud": "y", "iat": now(), "exp": now() + 3600, "scope": "admin:*"}),
        &EncodingKey::from_secret(public_pem.as_bytes()),
    )
    .expect("signing an HS256 token must succeed");

    assert!(verifier.verify(&forged).is_err());
}

/// Alg-confusion guard: a token that declares `alg: none` and carries no
/// signature must be rejected. `jsonwebtoken::Algorithm` has no `none`
/// variant, so this fails to parse before any claim/signature check runs
/// — asserted here so a future `jsonwebtoken` upgrade that changed that
/// behavior would be caught immediately.
#[test]
fn verify_rejects_alg_none_token() {
    let (_, public_pem) = generate_test_keypair();
    let verifier = Es256Verifier::from_ec_pem(public_pem.as_bytes())
        .expect("a freshly generated EC public key must build a verifier");

    let header = b64url(br#"{"alg":"none","typ":"JWT"}"#);
    let payload = b64url(
        format!(
            r#"{{"sub":"attacker","iss":"x","aud":"y","iat":{},"exp":{},"scope":"admin:*"}}"#,
            now(),
            now() + 3600
        )
        .as_bytes(),
    );
    let forged = format!("{header}.{payload}.");

    assert!(verifier.verify(&forged).is_err());
}

#[test]
fn with_audience_rejects_mismatched_audience_and_accepts_matching() {
    let (private_pem, public_pem) = generate_test_keypair();
    let signer = Es256Signer::from_ec_pem(private_pem.as_bytes())
        .expect("a freshly generated EC private key must build a signer");
    let token = signer
        .sign(&sample_claims(now() + 3600))
        .expect("signing must succeed"); // aud = "hub-api"

    let wrong_audience = Es256Verifier::from_ec_pem(public_pem.as_bytes())
        .expect("a freshly generated EC public key must build a verifier")
        .with_audience("other-service");
    assert!(wrong_audience.verify(&token).is_err());

    let right_audience = Es256Verifier::from_ec_pem(public_pem.as_bytes())
        .expect("a freshly generated EC public key must build a verifier")
        .with_audience("hub-api");
    assert!(right_audience.verify(&token).is_ok());
}

#[test]
fn with_issuer_rejects_mismatched_issuer_and_accepts_matching() {
    let (private_pem, public_pem) = generate_test_keypair();
    let signer = Es256Signer::from_ec_pem(private_pem.as_bytes())
        .expect("a freshly generated EC private key must build a signer");
    let token = signer
        .sign(&sample_claims(now() + 3600))
        .expect("signing must succeed"); // iss = "auth.penguintech.io"

    let wrong_issuer = Es256Verifier::from_ec_pem(public_pem.as_bytes())
        .expect("a freshly generated EC public key must build a verifier")
        .with_issuer("someone-else");
    assert!(wrong_issuer.verify(&token).is_err());

    let right_issuer = Es256Verifier::from_ec_pem(public_pem.as_bytes())
        .expect("a freshly generated EC public key must build a verifier")
        .with_issuer("auth.penguintech.io");
    assert!(right_issuer.verify(&token).is_ok());
}

#[test]
fn signer_from_ec_pem_rejects_garbage_key_material() {
    let err = Es256Signer::from_ec_pem(b"not a real key")
        .expect_err("garbage PEM bytes must not build a signer");
    assert!(err.to_string().contains("invalid ES256 key material"));
}

#[test]
fn verifier_from_ec_pem_rejects_garbage_key_material() {
    let err = Es256Verifier::from_ec_pem(b"not a real key")
        .expect_err("garbage PEM bytes must not build a verifier");
    assert!(err.to_string().contains("invalid ES256 key material"));
}

#[test]
fn signer_and_verifier_debug_impls_never_leak_key_material() {
    let (private_pem, public_pem) = generate_test_keypair();
    let signer = Es256Signer::from_ec_pem(private_pem.as_bytes())
        .expect("a freshly generated EC private key must build a signer");
    let verifier = Es256Verifier::from_ec_pem(public_pem.as_bytes())
        .expect("a freshly generated EC public key must build a verifier");

    let signer_debug = format!("{signer:?}");
    let verifier_debug = format!("{verifier:?}");
    assert_eq!(signer_debug, "Es256Signer { .. }");
    assert_eq!(verifier_debug, "Es256Verifier { .. }");
}

#[test]
fn claims_new_defaults_tenant_teams_and_roles_empty() {
    let claims = Claims::new(
        "node-123",
        "node-agent",
        "headend",
        now(),
        now() + 300,
        "dns:config:read",
    );
    assert_eq!(claims.tenant, None);
    assert!(claims.teams.is_empty());
    assert!(claims.roles.is_empty());
}

/// Minimal unpadded base64url encoder for the single `alg: none` test
/// above — deliberately hand-rolled instead of pulling in a `base64`
/// dependency just to construct one malformed test token (mirrors
/// `testserver-rs`'s `auth.rs` test helper of the same name).
fn b64url(input: &[u8]) -> String {
    const ALPHABET: &[u8] = b"ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_";
    let mut out = String::new();
    for chunk in input.chunks(3) {
        let b0 = chunk[0];
        let b1 = chunk.get(1).copied().unwrap_or(0);
        let b2 = chunk.get(2).copied().unwrap_or(0);
        let n = ((b0 as u32) << 16) | ((b1 as u32) << 8) | (b2 as u32);
        out.push(ALPHABET[((n >> 18) & 0x3F) as usize] as char);
        out.push(ALPHABET[((n >> 12) & 0x3F) as usize] as char);
        if chunk.len() > 1 {
            out.push(ALPHABET[((n >> 6) & 0x3F) as usize] as char);
        }
        if chunk.len() > 2 {
            out.push(ALPHABET[(n & 0x3F) as usize] as char);
        }
    }
    out
}
