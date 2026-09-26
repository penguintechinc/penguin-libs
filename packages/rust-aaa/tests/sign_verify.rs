//! Sign/verify + alg-confusion-rejection tests, ported/adapted from
//! `engines/testserver-rs/crates/core/src/auth.rs` (verify side) and
//! `agents/node-agent/crates/core/src/jwt.rs` (sign side) in the
//! `tobogganing` repository, exercised here through the unified
//! `penguin_aaa` public API (`Es256Signer` / `Es256Verifier` / `Claims`)
//! instead of each service's bespoke wrapper.
//!
//! Covers every algorithm in the crate's policy: `ES256`/`ES384`/`ES512`/
//! `EdDSA` (elliptic-curve family, primary) and `RS256` (RSA 4096-bit,
//! legacy backup) round-trip + wrong-key rejection, plus confirmation
//! that every HMAC variant and `alg: none` are rejected.
//!
//! The forged/cross-algorithm tests below construct tokens by hand
//! (base64url + `serde_json` + raw signing) rather than through
//! `Es256Signer`, since a well-behaved signer can't be asked to produce a
//! malformed or wrong-algorithm token — that's the entire point of these
//! tests. `Es256Signer` itself only ever signs `ES256`; the ES384/ES512/
//! EdDSA/RS256 test tokens are produced directly with each algorithm's
//! own signing primitive (`p384`/`p521`/`ed25519-dalek`/`openssl` CLI) to
//! exercise `Es256Verifier`'s *verify* side for those algorithms.

use base64::Engine;
use base64::engine::general_purpose::{STANDARD, URL_SAFE_NO_PAD};
use der::Encode;
use hmac::{Hmac, Mac};
use p256::ecdsa::signature::Signer;
use p256::ecdsa::{Signature, SigningKey, VerifyingKey};
use p256::pkcs8::{DecodePrivateKey, EncodePrivateKey, EncodePublicKey, LineEnding};
use penguin_aaa::{Claims, Es256Signer, Es256Verifier};
use sha2::Sha256;
use std::sync::OnceLock;

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

fn verifier_for(public_pem: &str) -> Es256Verifier {
    Es256Verifier::from_public_key_pem(public_pem.as_bytes())
        .expect("a freshly generated/exported public key must build a verifier")
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

// ---------------------------------------------------------------------
// ES256 (elliptic-curve family, primary — also the only signed algorithm)
// ---------------------------------------------------------------------

#[test]
fn sign_then_verify_round_trips_all_claims() {
    let (private_pem, public_pem) = generate_test_keypair();
    let signer = Es256Signer::from_ec_pem(private_pem.as_bytes())
        .expect("a freshly generated EC private key must build a signer");
    let verifier = verifier_for(&public_pem);

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

    assert!(verifier_for(&real_public_pem).verify(&token).is_err());
}

#[test]
fn verify_rejects_expired_token() {
    let (private_pem, public_pem) = generate_test_keypair();
    let signer = Es256Signer::from_ec_pem(private_pem.as_bytes())
        .expect("a freshly generated EC private key must build a signer");

    let token = signer
        .sign(&sample_claims(1))
        .expect("signing an already-expired claim set must still succeed");

    assert!(verifier_for(&public_pem).verify(&token).is_err());
}

#[test]
fn verify_rejects_missing_required_claim() {
    let (private_pem, public_pem) = generate_test_keypair();

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

    assert!(verifier_for(&public_pem).verify(&token).is_err());
}

/// Alg-confusion guard: a token signed HS256 using this verifier's own
/// public key bytes as the HMAC secret (the textbook asymmetric→HS256
/// confusion attack — a public key is not secret, so anyone who can see
/// it could forge an HS256-signed token if the verifier ever accepted
/// HS256) must be rejected. `Es256Verifier` has no HS256 code path at
/// all — the forged token is rejected by the explicit `alg` check before
/// its signature segment is ever interpreted.
#[test]
fn verify_rejects_hs256_alg_confusion_token() {
    let (_, public_pem) = generate_test_keypair();

    let forged = forge_hs256(
        public_pem.as_bytes(),
        r#"{"alg":"HS256","typ":"JWT"}"#,
        &format!(
            r#"{{"sub":"attacker","iss":"x","aud":"y","iat":{},"exp":{},"scope":"admin:*"}}"#,
            now(),
            now() + 3600
        ),
    );

    assert!(verifier_for(&public_pem).verify(&forged).is_err());
}

/// HMAC is forbidden unconditionally, regardless of variant — HS384 and
/// HS512 must be rejected the same way HS256 is.
#[test]
fn verify_rejects_hs384_and_hs512() {
    let (_, public_pem) = generate_test_keypair();
    for alg in ["HS384", "HS512"] {
        let forged = forge_hs256(
            public_pem.as_bytes(),
            &format!(r#"{{"alg":"{alg}","typ":"JWT"}}"#),
            &format!(
                r#"{{"sub":"attacker","iss":"x","aud":"y","iat":{},"exp":{},"scope":"admin:*"}}"#,
                now(),
                now() + 3600
            ),
        );
        assert!(
            verifier_for(&public_pem).verify(&forged).is_err(),
            "{alg} must be rejected"
        );
    }
}

/// Alg-confusion guard: a token that declares `alg: none` and carries no
/// signature must be rejected — caught by `Es256Verifier`'s explicit
/// `alg` check before any signature parsing is attempted.
#[test]
fn verify_rejects_alg_none_token() {
    let (_, public_pem) = generate_test_keypair();

    let header = URL_SAFE_NO_PAD.encode(br#"{"alg":"none","typ":"JWT"}"#);
    let payload = URL_SAFE_NO_PAD.encode(format!(
        r#"{{"sub":"attacker","iss":"x","aud":"y","iat":{},"exp":{},"scope":"admin:*"}}"#,
        now(),
        now() + 3600
    ));
    let forged = format!("{header}.{payload}.");

    assert!(verifier_for(&public_pem).verify(&forged).is_err());
}

#[test]
fn verify_rejects_malformed_token_with_wrong_segment_count() {
    let (_, public_pem) = generate_test_keypair();
    let verifier = verifier_for(&public_pem);

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

    let wrong_audience = verifier_for(&public_pem).with_audience("other-service");
    assert!(wrong_audience.verify(&token).is_err());

    let right_audience = verifier_for(&public_pem).with_audience("hub-api");
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

    let wrong_issuer = verifier_for(&public_pem).with_issuer("someone-else");
    assert!(wrong_issuer.verify(&token).is_err());

    let right_issuer = verifier_for(&public_pem).with_issuer("auth.penguintech.io");
    assert!(right_issuer.verify(&token).is_ok());
}

#[test]
fn signer_from_ec_pem_rejects_garbage_key_material() {
    let err = Es256Signer::from_ec_pem(b"not a real key")
        .expect_err("garbage PEM bytes must not build a signer");
    assert!(err.to_string().contains("invalid ES256 key material"));
}

#[test]
fn verifier_from_public_key_pem_rejects_garbage_key_material() {
    let err = Es256Verifier::from_public_key_pem(b"not a real key")
        .expect_err("garbage PEM bytes must not build a verifier");
    assert!(err.to_string().contains("invalid"));
}

#[test]
fn signer_from_ec_pem_rejects_non_utf8_bytes() {
    let err = Es256Signer::from_ec_pem(&[0xFF, 0xFE, 0xFD])
        .expect_err("non-UTF-8 bytes must not build a signer");
    assert!(err.to_string().contains("invalid ES256 key material"));
}

#[test]
fn verifier_from_public_key_pem_rejects_non_utf8_bytes() {
    let err = Es256Verifier::from_public_key_pem(&[0xFF, 0xFE, 0xFD])
        .expect_err("non-UTF-8 bytes must not build a verifier");
    assert!(err.to_string().contains("invalid"));
}

#[test]
fn verify_rejects_invalid_base64_header_segment() {
    let (_, public_pem) = generate_test_keypair();
    assert!(
        verifier_for(&public_pem)
            .verify("not!valid!base64.payload.sig")
            .is_err()
    );
}

#[test]
fn verify_rejects_header_segment_that_is_not_valid_json() {
    let (_, public_pem) = generate_test_keypair();
    let not_json_header = URL_SAFE_NO_PAD.encode(b"not json at all");
    assert!(
        verifier_for(&public_pem)
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

#[test]
fn signer_and_verifier_debug_impls_never_leak_key_material() {
    let (private_pem, public_pem) = generate_test_keypair();
    let signer = Es256Signer::from_ec_pem(private_pem.as_bytes())
        .expect("a freshly generated EC private key must build a signer");
    let verifier = verifier_for(&public_pem);

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

// ---------------------------------------------------------------------
// ES384 (elliptic-curve family — verify only; this crate never signs it)
// ---------------------------------------------------------------------

#[test]
fn es384_round_trips_and_rejects_wrong_key() {
    use p384::ecdsa::signature::Signer as _;
    use p384::ecdsa::{Signature, SigningKey, VerifyingKey};
    use p384::pkcs8::EncodePublicKey as _;

    let sk = SigningKey::random(&mut rand_core::OsRng);
    let pub_pem = VerifyingKey::from(&sk)
        .to_public_key_pem(LineEnding::LF)
        .expect("encode P-384 public key");
    let token = sign_raw_generic(
        r#"{"alg":"ES384","typ":"JWT"}"#,
        &claims_json(now() + 3600),
        |signing_input| {
            let sig: Signature = sk.sign(signing_input);
            sig.to_bytes().to_vec()
        },
    );

    let verifier = Es256Verifier::from_public_key_pem(pub_pem.as_bytes())
        .expect("a P-384 SPKI public key must build a verifier");
    let claims = verifier.verify(&token).expect("ES384 token must verify");
    assert_eq!(claims.sub, "user-123");

    // Wrong key: an independently generated P-384 keypair must reject.
    let other_sk = SigningKey::random(&mut rand_core::OsRng);
    let other_pub_pem = VerifyingKey::from(&other_sk)
        .to_public_key_pem(LineEnding::LF)
        .expect("encode other P-384 public key");
    let other_verifier = Es256Verifier::from_public_key_pem(other_pub_pem.as_bytes())
        .expect("a P-384 SPKI public key must build a verifier");
    assert!(other_verifier.verify(&token).is_err());
}

// ---------------------------------------------------------------------
// ES512 (elliptic-curve family — verify only; `p521`'s own PKCS8/PEM
// trait impls are incomplete in 0.13.3, so keys are handled via raw
// SEC1/scalar bytes wrapped in a minimal hand-rolled SPKI DER instead of
// `to_public_key_pem`/`from_pkcs8_pem`)
// ---------------------------------------------------------------------

/// Hand-rolls a minimal SPKI DER wrapper
/// (`SEQUENCE { SEQUENCE { OID id-ecPublicKey, OID curve }, BIT STRING point }`)
/// around a raw uncompressed SEC1 EC point — test-only, needed because
/// `p521` 0.13.3 can produce/consume raw SEC1 points but not SPKI PEM
/// directly (its `ecdsa-core/pem` feature forwarding is incomplete).
/// `Es256Verifier::from_public_key_pem`'s own SPKI parsing (via `spki`)
/// doesn't care how the DER was built, so this is a faithful stand-in for
/// a real P-521 SPKI key — cross-checked against a real
/// `openssl ecparam -name secp521r1`-generated key in
/// `es512_detect_accepts_a_real_openssl_generated_key`.
fn wrap_ec_point_as_spki_pem(curve_oid: &str, sec1_point: &[u8]) -> String {
    fn der_len(len: usize) -> Vec<u8> {
        if len < 128 {
            vec![len as u8]
        } else {
            let bytes = len.to_be_bytes();
            let start = bytes
                .iter()
                .position(|&b| b != 0)
                .unwrap_or(bytes.len() - 1);
            let mut out = vec![0x80 | (bytes.len() - start) as u8];
            out.extend_from_slice(&bytes[start..]);
            out
        }
    }
    let oid_ec = der::asn1::ObjectIdentifier::new_unwrap("1.2.840.10045.2.1")
        .to_der()
        .expect("encode id-ecPublicKey OID");
    let oid_curve = der::asn1::ObjectIdentifier::new_unwrap(curve_oid)
        .to_der()
        .expect("encode curve OID");
    let mut alg_id_body = Vec::new();
    alg_id_body.extend_from_slice(&oid_ec);
    alg_id_body.extend_from_slice(&oid_curve);
    let mut alg_id = vec![0x30u8];
    alg_id.extend_from_slice(&der_len(alg_id_body.len()));
    alg_id.extend_from_slice(&alg_id_body);

    let mut bit_string = vec![0x03u8];
    bit_string.extend_from_slice(&der_len(sec1_point.len() + 1));
    bit_string.push(0x00); // unused-bits count
    bit_string.extend_from_slice(sec1_point);

    let mut body = Vec::new();
    body.extend_from_slice(&alg_id);
    body.extend_from_slice(&bit_string);
    let mut der_bytes = vec![0x30u8];
    der_bytes.extend_from_slice(&der_len(body.len()));
    der_bytes.extend_from_slice(&body);

    der_to_pem(&der_bytes, "PUBLIC KEY")
}

fn der_to_pem(der_bytes: &[u8], label: &str) -> String {
    let b64 = STANDARD.encode(der_bytes);
    let mut out = format!("-----BEGIN {label}-----\n");
    for chunk in b64.as_bytes().chunks(64) {
        out.push_str(std::str::from_utf8(chunk).expect("base64 output is ASCII"));
        out.push('\n');
    }
    out.push_str(&format!("-----END {label}-----\n"));
    out
}

#[test]
fn es512_round_trips_and_rejects_wrong_key() {
    use p521::ecdsa::signature::Signer as _;
    use p521::ecdsa::{Signature, SigningKey, VerifyingKey};

    let sk = SigningKey::random(&mut rand_core::OsRng);
    let pub_pem = wrap_ec_point_as_spki_pem(
        "1.3.132.0.35",
        VerifyingKey::from(&sk).to_encoded_point(false).as_bytes(),
    );
    let token = sign_raw_generic(
        r#"{"alg":"ES512","typ":"JWT"}"#,
        &claims_json(now() + 3600),
        |signing_input| {
            let sig: Signature = sk.sign(signing_input);
            sig.to_bytes().to_vec()
        },
    );

    let verifier = Es256Verifier::from_public_key_pem(pub_pem.as_bytes())
        .expect("a P-521 SPKI public key must build a verifier");
    let claims = verifier.verify(&token).expect("ES512 token must verify");
    assert_eq!(claims.sub, "user-123");

    let other_sk = SigningKey::random(&mut rand_core::OsRng);
    let other_pub_pem = wrap_ec_point_as_spki_pem(
        "1.3.132.0.35",
        VerifyingKey::from(&other_sk)
            .to_encoded_point(false)
            .as_bytes(),
    );
    let other_verifier = Es256Verifier::from_public_key_pem(other_pub_pem.as_bytes())
        .expect("a P-521 SPKI public key must build a verifier");
    assert!(other_verifier.verify(&token).is_err());
}

/// Confirms the hand-rolled SPKI wrapper above matches real-world P-521
/// SPKI keys structurally: a real `openssl ecparam -name secp521r1`
/// public key must be detected/constructed successfully too, generated
/// fresh at test time via the `openssl` CLI (never a committed key).
#[test]
fn es512_accepts_a_real_openssl_generated_key() {
    let dir = std::env::temp_dir().join(format!("penguin-aaa-es512-test-{}", std::process::id()));
    std::fs::create_dir_all(&dir).expect("create temp dir");
    let priv_path = dir.join("ec521.pem");
    let pub_path = dir.join("ec521_pub.pem");

    run_openssl(&[
        "ecparam",
        "-name",
        "secp521r1",
        "-genkey",
        "-noout",
        "-out",
        priv_path.to_str().expect("temp path must be valid UTF-8"),
    ]);
    run_openssl(&[
        "ec",
        "-in",
        priv_path.to_str().expect("temp path must be valid UTF-8"),
        "-pubout",
        "-out",
        pub_path.to_str().expect("temp path must be valid UTF-8"),
    ]);

    let pub_pem = std::fs::read_to_string(&pub_path).expect("read openssl P-521 pubkey");
    Es256Verifier::from_public_key_pem(pub_pem.as_bytes())
        .expect("a real openssl-generated P-521 SPKI key must build a verifier");

    let _ = std::fs::remove_dir_all(&dir);
}

// ---------------------------------------------------------------------
// EdDSA / Ed25519 (elliptic-curve family — verify only)
// ---------------------------------------------------------------------

#[test]
fn eddsa_round_trips_and_rejects_wrong_key() {
    use ed25519_dalek::pkcs8::{DecodePrivateKey as _, EncodePublicKey as _};
    use ed25519_dalek::{Signature, Signer as _, SigningKey};

    let mut csprng = rand_core::OsRng;
    let sk = SigningKey::generate(&mut csprng);
    let pub_pem = sk
        .verifying_key()
        .to_public_key_pem(LineEnding::LF)
        .expect("encode Ed25519 public key");
    let priv_pem = sk
        .to_pkcs8_pem(LineEnding::LF)
        .expect("encode Ed25519 private key")
        .to_string();
    // Round-trip the private key through PEM too, proving the whole
    // pipeline (not just the in-memory key) produces a working signer.
    let sk2 = SigningKey::from_pkcs8_pem(&priv_pem).expect("reload Ed25519 private key from PEM");

    let token = sign_raw_generic(
        r#"{"alg":"EdDSA","typ":"JWT"}"#,
        &claims_json(now() + 3600),
        |signing_input| {
            let sig: Signature = sk2.sign(signing_input);
            sig.to_bytes().to_vec()
        },
    );

    let verifier = Es256Verifier::from_public_key_pem(pub_pem.as_bytes())
        .expect("an Ed25519 SPKI public key must build a verifier");
    let claims = verifier.verify(&token).expect("EdDSA token must verify");
    assert_eq!(claims.sub, "user-123");

    let other_sk = SigningKey::generate(&mut csprng);
    let other_pub_pem = other_sk
        .verifying_key()
        .to_public_key_pem(LineEnding::LF)
        .expect("encode other Ed25519 public key");
    let other_verifier = Es256Verifier::from_public_key_pem(other_pub_pem.as_bytes())
        .expect("an Ed25519 SPKI public key must build a verifier");
    assert!(other_verifier.verify(&token).is_err());
}

// ---------------------------------------------------------------------
// RS256 (RSA — legacy backup, verify only, 4096-bit minimum enforced)
// ---------------------------------------------------------------------

/// RSA-4096 key generation has no pure-Rust path in this crate's
/// dependency set by design (that's the entire point — see the crate
/// README's crypto-backend policy), so these tests shell out to the
/// `openssl` CLI to produce test fixtures, generated fresh per test run
/// and never committed. Requires `openssl` on `PATH` (present on every
/// GitHub Actions `ubuntu-latest` runner and virtually every dev
/// workstation); this is a hard test dependency, not a silent skip — a
/// missing `openssl` fails the test loudly rather than passing green with
/// nothing verified.
fn run_openssl(args: &[&str]) {
    let status = std::process::Command::new("openssl")
        .args(args)
        .status()
        .expect(
            "the `openssl` CLI is required to generate RSA-4096 test fixtures \
             (RSA key generation has no pure-Rust path in this crate by design)",
        );
    assert!(status.success(), "openssl {args:?} failed");
}

struct RsaFixture {
    pub_pem: String,
    other_pub_pem: String,
    /// A complete, validly-signed RS256 JWT (openssl-signed, 4096-bit key)
    /// carrying `sample_claims`, ready to hand straight to `verify()`.
    token: String,
}

/// Generates two independent RSA-4096 keypairs and one real RS256 JWT
/// (openssl-signed over the exact `header_b64.payload_b64` signing
/// input), once per test binary run — RSA-4096 keygen is slow, so sharing
/// this fixture across the round-trip and wrong-key tests keeps the
/// suite fast.
fn rsa_fixture() -> &'static RsaFixture {
    static FIXTURE: OnceLock<RsaFixture> = OnceLock::new();
    FIXTURE.get_or_init(|| {
        let dir = std::env::temp_dir().join(format!("penguin-aaa-rsa-test-{}", std::process::id()));
        std::fs::create_dir_all(&dir).expect("create temp dir");
        let priv_path = dir.join("priv.pem");
        let pub_path = dir.join("pub.pem");
        let other_priv_path = dir.join("other_priv.pem");
        let other_pub_path = dir.join("other_pub.pem");
        let msg_path = dir.join("signing_input.bin");
        let sig_path = dir.join("sig.bin");

        run_openssl(&[
            "genpkey",
            "-algorithm",
            "RSA",
            "-pkeyopt",
            "rsa_keygen_bits:4096",
            "-out",
            priv_path.to_str().expect("temp path must be valid UTF-8"),
        ]);
        run_openssl(&[
            "rsa",
            "-in",
            priv_path.to_str().expect("temp path must be valid UTF-8"),
            "-pubout",
            "-out",
            pub_path.to_str().expect("temp path must be valid UTF-8"),
        ]);
        run_openssl(&[
            "genpkey",
            "-algorithm",
            "RSA",
            "-pkeyopt",
            "rsa_keygen_bits:4096",
            "-out",
            other_priv_path
                .to_str()
                .expect("temp path must be valid UTF-8"),
        ]);
        run_openssl(&[
            "rsa",
            "-in",
            other_priv_path
                .to_str()
                .expect("temp path must be valid UTF-8"),
            "-pubout",
            "-out",
            other_pub_path
                .to_str()
                .expect("temp path must be valid UTF-8"),
        ]);

        let signing_input = format!(
            "{}.{}",
            URL_SAFE_NO_PAD.encode(r#"{"alg":"RS256","typ":"JWT"}"#),
            URL_SAFE_NO_PAD.encode(claims_json(now() + 3600))
        );
        std::fs::write(&msg_path, signing_input.as_bytes()).expect("write signing input");
        run_openssl(&[
            "dgst",
            "-sha256",
            "-sign",
            priv_path.to_str().expect("temp path must be valid UTF-8"),
            "-out",
            sig_path.to_str().expect("temp path must be valid UTF-8"),
            msg_path.to_str().expect("temp path must be valid UTF-8"),
        ]);
        let sig = std::fs::read(&sig_path).expect("read RSA signature");
        let token = format!("{signing_input}.{}", URL_SAFE_NO_PAD.encode(sig));

        let fixture = RsaFixture {
            pub_pem: std::fs::read_to_string(&pub_path).expect("read RSA pubkey"),
            other_pub_pem: std::fs::read_to_string(&other_pub_path).expect("read other RSA pubkey"),
            token,
        };
        let _ = std::fs::remove_dir_all(&dir);
        fixture
    })
}

#[test]
fn rs256_verifies_a_genuine_openssl_signature_and_rejects_wrong_key() {
    let fixture = rsa_fixture();

    let verifier = Es256Verifier::from_public_key_pem(fixture.pub_pem.as_bytes())
        .expect("a 4096-bit RSA SPKI public key must build a verifier");
    let claims = verifier
        .verify(&fixture.token)
        .expect("RS256 token must verify");
    assert_eq!(claims.sub, "user-123");

    // Wrong key: the second independent RSA-4096 keypair must reject.
    let other_verifier = Es256Verifier::from_public_key_pem(fixture.other_pub_pem.as_bytes())
        .expect("a 4096-bit RSA SPKI public key must build a verifier");
    assert!(other_verifier.verify(&fixture.token).is_err());
}

#[test]
fn rs256_rejects_a_2048_bit_key_at_construction() {
    let dir = std::env::temp_dir().join(format!("penguin-aaa-rsa2048-test-{}", std::process::id()));
    std::fs::create_dir_all(&dir).expect("create temp dir");
    let priv_path = dir.join("priv2048.pem");
    let pub_path = dir.join("pub2048.pem");

    run_openssl(&[
        "genpkey",
        "-algorithm",
        "RSA",
        "-pkeyopt",
        "rsa_keygen_bits:2048",
        "-out",
        priv_path.to_str().expect("temp path must be valid UTF-8"),
    ]);
    run_openssl(&[
        "rsa",
        "-in",
        priv_path.to_str().expect("temp path must be valid UTF-8"),
        "-pubout",
        "-out",
        pub_path.to_str().expect("temp path must be valid UTF-8"),
    ]);

    let pub_pem = std::fs::read_to_string(&pub_path).expect("read 2048-bit RSA pubkey");
    let err = Es256Verifier::from_public_key_pem(pub_pem.as_bytes())
        .expect_err("a 2048-bit RSA key must be rejected below the 4096-bit minimum");
    assert!(err.to_string().contains("4096"));

    let _ = std::fs::remove_dir_all(&dir);
}

// ---------------------------------------------------------------------
// Key-detection rejections (unsupported curve / unsupported algorithm)
// ---------------------------------------------------------------------

/// An EC key on a curve outside the accepted P-256/P-384/P-521 set (here,
/// secp256k1 — same `id-ecPublicKey` family OID, different curve OID)
/// must be rejected at construction, not silently accepted.
#[test]
fn verifier_rejects_ec_key_on_an_unsupported_curve() {
    let dir =
        std::env::temp_dir().join(format!("penguin-aaa-secp256k1-test-{}", std::process::id()));
    std::fs::create_dir_all(&dir).expect("create temp dir");
    let priv_path = dir.join("secp256k1.pem");
    let pub_path = dir.join("secp256k1_pub.pem");

    run_openssl(&[
        "ecparam",
        "-name",
        "secp256k1",
        "-genkey",
        "-noout",
        "-out",
        priv_path.to_str().expect("temp path must be valid UTF-8"),
    ]);
    run_openssl(&[
        "ec",
        "-in",
        priv_path.to_str().expect("temp path must be valid UTF-8"),
        "-pubout",
        "-out",
        pub_path.to_str().expect("temp path must be valid UTF-8"),
    ]);

    let pub_pem = std::fs::read_to_string(&pub_path).expect("read secp256k1 pubkey");
    let err = Es256Verifier::from_public_key_pem(pub_pem.as_bytes())
        .expect_err("secp256k1 is not one of the accepted P-256/P-384/P-521 curves");
    assert!(err.to_string().contains("unsupported EC curve"));

    let _ = std::fs::remove_dir_all(&dir);
}

/// A key of a completely different algorithm family (X25519 — key
/// agreement, not a signature scheme at all, and a different top-level
/// SPKI OID than EC/Ed25519/RSA) must be rejected at construction.
#[test]
fn verifier_rejects_a_non_signature_key_algorithm() {
    let dir = std::env::temp_dir().join(format!("penguin-aaa-x25519-test-{}", std::process::id()));
    std::fs::create_dir_all(&dir).expect("create temp dir");
    let priv_path = dir.join("x25519.pem");
    let pub_path = dir.join("x25519_pub.pem");

    run_openssl(&[
        "genpkey",
        "-algorithm",
        "X25519",
        "-out",
        priv_path.to_str().expect("temp path must be valid UTF-8"),
    ]);
    run_openssl(&[
        "pkey",
        "-in",
        priv_path.to_str().expect("temp path must be valid UTF-8"),
        "-pubout",
        "-out",
        pub_path.to_str().expect("temp path must be valid UTF-8"),
    ]);

    let pub_pem = std::fs::read_to_string(&pub_path).expect("read X25519 pubkey");
    let err = Es256Verifier::from_public_key_pem(pub_pem.as_bytes())
        .expect_err("X25519 is a key-agreement algorithm, not one of the five accepted JWS algs");
    assert!(err.to_string().contains("unsupported public key algorithm"));

    let _ = std::fs::remove_dir_all(&dir);
}

// ---------------------------------------------------------------------
// Shared test-only signing-input helpers (used by ES384/ES512/EdDSA)
// ---------------------------------------------------------------------

fn claims_json(exp: i64) -> String {
    serde_json::to_string(&sample_claims(exp)).expect("Claims always serializes")
}

/// Builds a compact JWS from a header/claims JSON pair using `sign_fn` to
/// produce the raw signature bytes over the exact `header_b64.payload_b64`
/// signing input — shared by the ES384/ES512/EdDSA tests, each of which
/// signs with its own algorithm's native primitive (`Es256Signer` only
/// ever signs ES256).
fn sign_raw_generic(
    header_json: &str,
    payload_json: &str,
    sign_fn: impl FnOnce(&[u8]) -> Vec<u8>,
) -> String {
    let signing_input = format!(
        "{}.{}",
        URL_SAFE_NO_PAD.encode(header_json),
        URL_SAFE_NO_PAD.encode(payload_json)
    );
    let sig = sign_fn(signing_input.as_bytes());
    format!("{signing_input}.{}", URL_SAFE_NO_PAD.encode(sig))
}
