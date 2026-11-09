//! Verifier policy regression tests (S-06, S-12).
//!
//! S-06: audience and issuer pinning is mandatory at construction, `nbf` is
//! enforced, `exp` must be present, token lifetime is capped at 24 hours,
//! and clock-skew leeway is limited to 60 seconds. S-12: a header `alg`
//! from an untrusted token is never echoed into error text.
//!
//! Tokens are signed with throwaway keys generated per test, never fixed
//! key material.

use base64::Engine;
use base64::engine::general_purpose::URL_SAFE_NO_PAD;
use p256::ecdsa::signature::Signer as _;
use p256::ecdsa::{Signature, SigningKey, VerifyingKey};
use p256::pkcs8::{DecodePrivateKey, EncodePrivateKey, EncodePublicKey, LineEnding};
use penguin_aaa::{AaaError, Claims, Es256Signer, Es256Verifier};

const AUD: &str = "hub-api";
const ISS: &str = "auth.penguintech.io";
const DAY: i64 = 86_400;

/// Fresh P-256 keypair as (PKCS#8 private PEM, SPKI public PEM).
fn keypair() -> (String, String) {
    let signing_key = loop {
        if let Ok(key) = SigningKey::from_slice(&os_random_32()) {
            break key;
        }
    };
    let private_pem = signing_key
        .to_pkcs8_pem(LineEnding::LF)
        .expect("PKCS#8 encoding of a fresh P-256 key must succeed")
        .to_string();
    let public_pem = VerifyingKey::from(&signing_key)
        .to_public_key_pem(LineEnding::LF)
        .expect("SPKI encoding of the matching public key must succeed");
    (private_pem, public_pem)
}

/// 32 random bytes from the OS RNG (test-only key material source).
fn os_random_32() -> [u8; 32] {
    let mut bytes = [0u8; 32];
    getrandom::fill(&mut bytes).expect("the OS RNG must be available to tests");
    bytes
}

/// Current Unix time in whole seconds.
fn now() -> i64 {
    std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .expect("system clock must be after the unix epoch")
        .as_secs() as i64
}

/// Claims for the pinned audience and issuer with the given window.
fn claims(iat: i64, exp: i64) -> Claims {
    Claims::new("user-123", ISS, AUD, iat, exp, "test:run")
}

/// Signs `claims` with a fresh key and returns (token, public PEM).
fn sign(claims: &Claims) -> (String, String) {
    let (private_pem, public_pem) = keypair();
    let signer = Es256Signer::from_ec_pem(private_pem.as_bytes())
        .expect("a freshly generated PKCS#8 key must build a signer");
    let token = signer
        .sign(claims)
        .expect("signing a valid claim set must succeed");
    (token, public_pem)
}

/// Verifier pinned to the audience and issuer every test token uses.
fn pinned(public_pem: &str) -> Es256Verifier {
    Es256Verifier::builder(public_pem.as_bytes())
        .audience(AUD)
        .issuer(ISS)
        .build()
        .expect("a pinned builder with a valid key must build")
}

/// Hand-signs a token from raw header and payload JSON, so claim shapes
/// `Claims` can't express (e.g. a missing `exp`) can be tested.
fn sign_raw(private_pem: &str, header_json: &str, payload_json: &str) -> String {
    let signing_key =
        SigningKey::from_pkcs8_pem(private_pem).expect("a freshly generated PKCS#8 key must load");
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

#[test]
fn builder_without_audience_is_a_construction_error() {
    let (_, public_pem) = keypair();
    let err = Es256Verifier::builder(public_pem.as_bytes())
        .issuer(ISS)
        .build()
        .expect_err("a verifier with no audience pin must not build");
    assert!(matches!(err, AaaError::Config(_)), "got {err:?}");
    assert!(err.to_string().contains("audience"));
}

#[test]
fn builder_without_issuer_is_a_construction_error() {
    let (_, public_pem) = keypair();
    let err = Es256Verifier::builder(public_pem.as_bytes())
        .audience(AUD)
        .build()
        .expect_err("a verifier with no issuer pin must not build");
    assert!(matches!(err, AaaError::Config(_)), "got {err:?}");
    assert!(err.to_string().contains("issuer"));
}

#[test]
fn builder_with_garbage_key_still_reports_invalid_key() {
    let err = Es256Verifier::builder(b"not a real key")
        .audience(AUD)
        .issuer(ISS)
        .build()
        .expect_err("garbage key material must not build");
    assert!(matches!(err, AaaError::InvalidKey(_)), "got {err:?}");
}

#[test]
fn pinned_builder_accepts_matching_token() {
    let t = now();
    let (token, public_pem) = sign(&claims(t, t + 3600));
    assert!(pinned(&public_pem).verify(&token).is_ok());
}

#[test]
fn wrong_audience_is_rejected() {
    let t = now();
    let other = Claims::new("user-123", ISS, "other-service", t, t + 3600, "test:run");
    let (token, public_pem) = sign(&other);
    let err = pinned(&public_pem)
        .verify(&token)
        .expect_err("token minted for another audience must be rejected");
    assert!(matches!(err, AaaError::Verification(_)), "got {err:?}");
}

#[test]
fn wrong_issuer_is_rejected() {
    let t = now();
    let other = Claims::new("user-123", "evil.example", AUD, t, t + 3600, "test:run");
    let (token, public_pem) = sign(&other);
    let err = pinned(&public_pem)
        .verify(&token)
        .expect_err("token minted by another issuer must be rejected");
    assert!(matches!(err, AaaError::Verification(_)), "got {err:?}");
}

#[test]
fn nbf_in_future_beyond_leeway_is_rejected() {
    let t = now();
    let future = Claims {
        nbf: Some(t + 300),
        ..claims(t, t + 3600)
    };
    let (token, public_pem) = sign(&future);
    let err = pinned(&public_pem)
        .verify(&token)
        .expect_err("a token not valid until 5 minutes from now must be rejected");
    assert!(matches!(err, AaaError::Verification(_)), "got {err:?}");
}

#[test]
fn nbf_within_leeway_is_accepted() {
    let t = now();
    let near = Claims {
        nbf: Some(t + 30),
        ..claims(t, t + 3600)
    };
    let (token, public_pem) = sign(&near);
    assert!(pinned(&public_pem).verify(&token).is_ok());
}

#[test]
fn lifetime_over_24_hours_is_rejected() {
    let t = now();
    let (token, public_pem) = sign(&claims(t, t + DAY + 120));
    let err = pinned(&public_pem)
        .verify(&token)
        .expect_err("a token living longer than 24h must be rejected");
    assert!(matches!(err, AaaError::Verification(_)), "got {err:?}");
}

#[test]
fn lifetime_exactly_24_hours_is_accepted() {
    let t = now();
    let (token, public_pem) = sign(&claims(t, t + DAY));
    assert!(pinned(&public_pem).verify(&token).is_ok());
}

#[test]
fn missing_exp_is_rejected() {
    let (private_pem, public_pem) = keypair();
    let t = now();
    let token = sign_raw(
        &private_pem,
        r#"{"alg":"ES256","typ":"JWT"}"#,
        &format!(r#"{{"sub":"u","iss":"{ISS}","aud":"{AUD}","iat":{t},"scope":"x"}}"#),
    );
    assert!(pinned(&public_pem).verify(&token).is_err());
}

#[test]
fn exp_before_iat_is_rejected() {
    let t = now();
    let (token, public_pem) = sign(&claims(t, t - 10));
    assert!(pinned(&public_pem).verify(&token).is_err());
}

#[test]
fn expired_within_leeway_is_accepted() {
    let t = now();
    let (token, public_pem) = sign(&claims(t - 100, t - 30));
    assert!(pinned(&public_pem).verify(&token).is_ok());
}

#[test]
fn expired_beyond_leeway_is_rejected() {
    let t = now();
    let (token, public_pem) = sign(&claims(t - 3600, t - 120));
    assert!(pinned(&public_pem).verify(&token).is_err());
}

#[test]
fn untrusted_alg_is_not_echoed_into_error_text() {
    let (private_pem, public_pem) = keypair();
    let t = now();
    let token = sign_raw(
        &private_pem,
        r#"{"alg":"EVIL_MARKER_\u0007\n","typ":"JWT"}"#,
        &format!(
            r#"{{"sub":"u","iss":"{ISS}","aud":"{AUD}","iat":{t},"exp":{},"scope":"x"}}"#,
            t + 60
        ),
    );
    let err = pinned(&public_pem)
        .verify(&token)
        .expect_err("an alg mismatch must be rejected");
    let text = err.to_string();
    assert!(
        !text.contains("EVIL_MARKER"),
        "error echoed header alg: {text}"
    );
    assert!(
        !text.contains('\u{7}'),
        "error echoed control bytes: {text}"
    );
}

#[test]
fn far_future_iat_with_valid_lifetime_is_rejected() {
    // Regression: iat = now + 10y, exp = iat + 1h passed the lifetime cap
    // and the exp check because iat was never bounded against now.
    let iat = now() + 10 * 365 * DAY;
    let (token, public_pem) = sign(&claims(iat, iat + 3_600));
    let err = pinned(&public_pem)
        .verify(&token)
        .expect_err("a token issued in the far future must be rejected");
    assert!(matches!(err, AaaError::Verification(_)), "got {err:?}");
    assert!(err.to_string().contains("issued in the future"), "{err}");
}

#[test]
fn iat_just_beyond_leeway_is_rejected() {
    let iat = now() + 120;
    let (token, public_pem) = sign(&claims(iat, iat + 3_600));
    assert!(pinned(&public_pem).verify(&token).is_err());
}

#[test]
fn iat_within_leeway_is_accepted() {
    let iat = now() + 30;
    let (token, public_pem) = sign(&claims(iat, iat + 3_600));
    pinned(&public_pem)
        .verify(&token)
        .expect("iat inside the 60s skew leeway must verify");
}

#[test]
fn missing_iat_is_rejected() {
    let (private_pem, public_pem) = keypair();
    let payload = format!(
        r#"{{"sub":"u","iss":"{ISS}","aud":"{AUD}","exp":{},"scope":"test:run"}}"#,
        now() + 3_600
    );
    let token = sign_raw(&private_pem, r#"{"alg":"ES256","typ":"JWT"}"#, &payload);
    assert!(pinned(&public_pem).verify(&token).is_err());
}
