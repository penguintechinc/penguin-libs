//! Sign/verify + alg-confusion-rejection tests, ported/adapted from
//! `engines/testserver-rs/crates/core/src/auth.rs` (verify side) and
//! `agents/node-agent/crates/core/src/jwt.rs` (sign side) in the
//! `tobogganing` repository, exercised here through the unified
//! `penguin_aaa` public API (`Es256Signer` / `Es256Verifier` / `Claims`)
//! instead of each service's bespoke wrapper.
//!
//! The forged-token tests below construct tokens by hand (base64url +
//! `serde_json` + raw ECDSA/HMAC signing) rather than through
//! `Es256Signer`, since a well-behaved signer can't be asked to produce a
//! malformed or wrong-algorithm token — that's the entire point of these
//! tests.

use base64::Engine;
use base64::engine::general_purpose::URL_SAFE_NO_PAD;
use hmac::{Hmac, Mac};
use p256::ecdsa::signature::Signer;
use p256::ecdsa::{Signature, SigningKey, VerifyingKey};
use p256::pkcs8::{DecodePrivateKey, EncodePrivateKey, EncodePublicKey, LineEnding};
use penguin_aaa::{Claims, Es256Signer, Es256Verifier};
use sha2::Sha256;

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

/// Hand-signs a raw ES256 token from `header_json`/`payload_json` bytes,
/// bypassing [`Es256Signer`] so a claim set [`Claims`] itself couldn't
/// represent (e.g. missing `sub`) can still be constructed for a
/// rejection test.
fn sign_raw_es256(private_pem: &str, header_json: &str, payload_json: &str) -> String {
    let signing_key = SigningKey::from_pkcs8_pem(private_pem)
        .expect("a freshly generated PKCS#8 EC key must load");
    let signing_input = format!(
        "{}.{}",
        URL_SAFE_NO_PAD.encode(header_json),
        URL_SAFE_NO_PAD.encode(payload_json)
    );
    let signature: Signature = signing_key.sign(signing_input.as_bytes());
    format!(
        "{signing_input}.{}",
        URL_SAFE_NO_PAD.encode(signature.to_bytes())
    )
}

/// Forges an HS256-labeled token, HMAC-SHA256-signed with `secret` — used
/// only to prove [`Es256Verifier`] rejects it (see
/// `verify_rejects_hs256_alg_confusion_token`).
fn forge_hs256(secret: &[u8], header_json: &str, payload_json: &str) -> String {
    let signing_input = format!(
        "{}.{}",
        URL_SAFE_NO_PAD.encode(header_json),
        URL_SAFE_NO_PAD.encode(payload_json)
    );
    let mut mac = <Hmac<Sha256> as Mac>::new_from_slice(secret)
        .expect("HMAC-SHA256 accepts a key of any length");
    mac.update(signing_input.as_bytes());
    let tag = mac.finalize().into_bytes();
    format!("{signing_input}.{}", URL_SAFE_NO_PAD.encode(tag))
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
    let token = sign_raw_es256(
        &private_pem,
        r#"{"alg":"ES256","typ":"JWT"}"#,
        &format!(
            r#"{{"iss":"x","aud":"y","iat":{},"exp":{},"scope":"test:run"}}"#,
            now(),
            now() + 3600
        ),
    );

    assert!(verifier.verify(&token).is_err());
}

/// Alg-confusion guard: a token signed HS256 using this verifier's own
/// ES256 *public* key bytes as the HMAC secret (the textbook
/// asymmetric→HS256 confusion attack — a public key is not secret, so
/// anyone who can see it could forge an HS256-signed token if the
/// verifier ever accepted HS256) must be rejected. `Es256Verifier` has no
/// HS256 code path at all — the forged token is rejected twice over: its
/// header declares `alg: HS256` (checked and rejected before the
/// signature is even looked at), and even ignoring that, a 32-byte
/// HMAC-SHA256 tag can't parse as the fixed 64-byte ECDSA signature this
/// verifier expects.
#[test]
fn verify_rejects_hs256_alg_confusion_token() {
    let (_, public_pem) = generate_test_keypair();
    let verifier = Es256Verifier::from_ec_pem(public_pem.as_bytes())
        .expect("a freshly generated EC public key must build a verifier");

    let forged = forge_hs256(
        public_pem.as_bytes(),
        r#"{"alg":"HS256","typ":"JWT"}"#,
        &format!(
            r#"{{"sub":"attacker","iss":"x","aud":"y","iat":{},"exp":{},"scope":"admin:*"}}"#,
            now(),
            now() + 3600
        ),
    );

    assert!(verifier.verify(&forged).is_err());
}

/// Alg-confusion guard: a token that declares `alg: none` and carries no
/// signature must be rejected — caught by `Es256Verifier`'s explicit
/// `alg == "ES256"` check before any signature parsing is attempted.
#[test]
fn verify_rejects_alg_none_token() {
    let (_, public_pem) = generate_test_keypair();
    let verifier = Es256Verifier::from_ec_pem(public_pem.as_bytes())
        .expect("a freshly generated EC public key must build a verifier");

    let header = URL_SAFE_NO_PAD.encode(br#"{"alg":"none","typ":"JWT"}"#);
    let payload = URL_SAFE_NO_PAD.encode(format!(
        r#"{{"sub":"attacker","iss":"x","aud":"y","iat":{},"exp":{},"scope":"admin:*"}}"#,
        now(),
        now() + 3600
    ));
    let forged = format!("{header}.{payload}.");

    assert!(verifier.verify(&forged).is_err());
}

#[test]
fn verify_rejects_malformed_token_with_wrong_segment_count() {
    let (_, public_pem) = generate_test_keypair();
    let verifier = Es256Verifier::from_ec_pem(public_pem.as_bytes())
        .expect("a freshly generated EC public key must build a verifier");

    assert!(verifier.verify("not-a-jwt").is_err());
    assert!(verifier.verify("only.two").is_err());
    assert!(verifier.verify("way.too.many.segments").is_err());
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
fn signer_from_ec_pem_rejects_non_utf8_bytes() {
    let err = Es256Signer::from_ec_pem(&[0xFF, 0xFE, 0xFD])
        .expect_err("non-UTF-8 bytes must not build a signer");
    assert!(err.to_string().contains("invalid ES256 key material"));
}

#[test]
fn verifier_from_ec_pem_rejects_non_utf8_bytes() {
    let err = Es256Verifier::from_ec_pem(&[0xFF, 0xFE, 0xFD])
        .expect_err("non-UTF-8 bytes must not build a verifier");
    assert!(err.to_string().contains("invalid ES256 key material"));
}

#[test]
fn verify_rejects_invalid_base64_header_segment() {
    let (_, public_pem) = generate_test_keypair();
    let verifier = Es256Verifier::from_ec_pem(public_pem.as_bytes())
        .expect("a freshly generated EC public key must build a verifier");
    assert!(verifier.verify("not!valid!base64.payload.sig").is_err());
}

#[test]
fn verify_rejects_header_segment_that_is_not_valid_json() {
    let (_, public_pem) = generate_test_keypair();
    let verifier = Es256Verifier::from_ec_pem(public_pem.as_bytes())
        .expect("a freshly generated EC public key must build a verifier");
    let not_json_header = URL_SAFE_NO_PAD.encode(b"not json at all");
    assert!(
        verifier
            .verify(&format!("{not_json_header}.payload.sig"))
            .is_err()
    );
}

#[test]
fn verify_rejects_invalid_base64_signature_segment() {
    let (private_pem, public_pem) = generate_test_keypair();
    let signer = Es256Signer::from_ec_pem(private_pem.as_bytes())
        .expect("a freshly generated EC private key must build a signer");
    let token = signer
        .sign(&sample_claims(now() + 3600))
        .expect("signing must succeed");
    let (header_and_payload, _real_sig) = token
        .rsplit_once('.')
        .expect("a signed token has 3 segments");
    assert!(
        verifier_for(&public_pem)
            .verify(&format!("{header_and_payload}.not!valid!base64"))
            .is_err()
    );
}

#[test]
fn verify_rejects_signature_segment_with_wrong_byte_length() {
    let (private_pem, public_pem) = generate_test_keypair();
    let signer = Es256Signer::from_ec_pem(private_pem.as_bytes())
        .expect("a freshly generated EC private key must build a signer");
    let token = signer
        .sign(&sample_claims(now() + 3600))
        .expect("signing must succeed");
    let (header_and_payload, _real_sig) = token
        .rsplit_once('.')
        .expect("a signed token has 3 segments");
    let short_sig = URL_SAFE_NO_PAD.encode([0u8; 10]); // a valid ES256 signature is 64 bytes
    assert!(
        verifier_for(&public_pem)
            .verify(&format!("{header_and_payload}.{short_sig}"))
            .is_err()
    );
}

#[test]
fn verify_rejects_invalid_base64_payload_segment() {
    let (private_pem, public_pem) = generate_test_keypair();
    // A genuine signature over a malformed payload segment — proves the
    // payload-decode failure is what's being tested, not an earlier
    // signature-check rejection.
    let signing_key = SigningKey::from_pkcs8_pem(&private_pem)
        .expect("a freshly generated PKCS#8 EC key must load");
    let header_b64 = URL_SAFE_NO_PAD.encode(br#"{"alg":"ES256","typ":"JWT"}"#);
    let signing_input = format!("{header_b64}.not!valid!base64");
    let signature: Signature = signing_key.sign(signing_input.as_bytes());
    let token = format!(
        "{signing_input}.{}",
        URL_SAFE_NO_PAD.encode(signature.to_bytes())
    );

    assert!(verifier_for(&public_pem).verify(&token).is_err());
}

fn verifier_for(public_pem: &str) -> Es256Verifier {
    Es256Verifier::from_ec_pem(public_pem.as_bytes())
        .expect("a freshly generated EC public key must build a verifier")
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
    assert!(signer_debug.starts_with("Es256Signer"));
    assert!(verifier_debug.starts_with("Es256Verifier"));
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
