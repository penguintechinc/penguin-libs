//! `binding.mac` computation and verification (spec §5.11, D30) — the
//! tenant-binding HMAC every [`StageEnvelope`] carries. `envelope.rs`'s doc
//! comments reference this module as "Task 19"; this is that landing, and
//! the single source of truth `svc-ingest` (minting) and `svc-process`/
//! `svc-action` (verification) should all call into instead of each
//! hand-rolling the formula.
//!
//! Reproduced byte-for-byte from `waddles core/svc_action/src/hop.rs`
//! (verified-correct, reviewed) — same formula, same keyring shape, same
//! constant-time comparison. That module's own doc comment already frames
//! swapping to this crate's `compute_binding_mac`/`verify_binding` as "a
//! drop-in replacement, not a behavior change"; this module is written to
//! honor that exactly. Refactoring `svc_action::hop` onto this helper is a
//! separate follow-up (requires a `penguin-spine` re-release and an
//! `svc_action` pin bump), not done here.
//!
//! **Known follow-up, not addressed here:** the wire formula concatenates
//! `tenant ‖ community ‖ workstream_id ‖ event_id ‖ trace_id` with no
//! delimiter or length prefix (spec §5.11 as published), which is a latent
//! canonicalization ambiguity — e.g. a boundary shift between adjacent
//! fields could in principle produce the same byte string from two
//! different tuples. A reviewer suggested domain separation (delimiters or
//! length-prefixing each field) to close this. That is a **spec change**
//! (§5.11 formula, §11.1 threat-model update) requiring a coordinated
//! `svc-ingest`/`svc-process`/`svc-action` rollout — every already-minted
//! envelope's MAC would stop verifying otherwise — so it is not done
//! unilaterally in this module. Tracked as a follow-up.

use hmac::{Hmac, Mac};
use sha2::Sha256;
use subtle::ConstantTimeEq;

use crate::envelope::{StageEnvelope, trace_id_from_traceparent};
use crate::scope::TENANT_WIDE_SEGMENT;

type HmacSha256 = Hmac<Sha256>;

/// Errors from keyring construction, MAC computation, or MAC verification —
/// every fallible operation this module exposes returns one of these.
#[derive(Debug, Clone, PartialEq, Eq, thiserror::Error)]
pub enum BindingError {
    /// `binding.mac` did not recompute to the value on the wire under the
    /// claimed `kid`.
    #[error("binding.mac mismatch")]
    MacMismatch,
    /// The claimed `kid` names a key this [`KeyRing`] does not hold.
    #[error("binding.kid {0:?} is not a known key version")]
    UnknownKid(String),
    /// An `ENVELOPE_BINDING_KEYS` entry was not of the form `kid:hexkey`.
    #[error("ENVELOPE_BINDING_KEYS entry {0:?} is not of the form kid:hexkey")]
    MalformedKeyEntry(String),
    /// An `ENVELOPE_BINDING_KEYS` entry's key material was not valid hex.
    #[error("ENVELOPE_BINDING_KEYS entry for kid {0:?} is not valid hex: {1}")]
    InvalidKeyHex(String, String),
    /// [`KeyRing::parse`] produced zero entries — a misconfigured or
    /// missing keyring must be a hard startup error, never a silent
    /// "every MAC fails" (which would DLQ 100% of traffic) or "every MAC
    /// passes" (which would defeat the tenant wall entirely).
    #[error("keyring is empty -- binding-MAC verification cannot start with no keys")]
    EmptyKeyring,
}

/// Symmetric HMAC key material for `binding.mac`, keyed by `kid` (spec
/// §5.11: "Keys are named by `kid` and rotated with an overlap window").
/// Verification accepts a MAC produced under any `kid` the ring holds; this
/// type only looks keys up, it never decides which `kid` is "current" —
/// that policy lives with the caller (`svc-ingest`'s minting config).
#[derive(Clone, Debug)]
pub struct KeyRing {
    keys: Vec<(String, Vec<u8>)>,
}

impl KeyRing {
    /// Builds a ring directly from `(kid, key_bytes)` pairs — the
    /// programmatic constructor tests and callers with their own key
    /// sourcing use. Does not reject an empty `Vec`; callers that must
    /// enforce the "non-empty at startup" rule should use
    /// [`KeyRing::parse`] instead.
    pub fn new(keys: Vec<(String, Vec<u8>)>) -> Self {
        Self { keys }
    }

    /// Parses the `ENVELOPE_BINDING_KEYS` env-var shape:
    /// `kid1:hexkey1,kid2:hexkey2`. Refuses to build an empty ring (spec
    /// §5.11, §12.3) — see [`BindingError::EmptyKeyring`].
    pub fn parse(raw: &str) -> Result<Self, BindingError> {
        let mut keys = Vec::new();
        for entry in raw.split(',') {
            let entry = entry.trim();
            if entry.is_empty() {
                continue;
            }
            let (kid, hexkey) = entry
                .split_once(':')
                .ok_or_else(|| BindingError::MalformedKeyEntry(entry.to_string()))?;
            if kid.is_empty() || hexkey.is_empty() {
                return Err(BindingError::MalformedKeyEntry(entry.to_string()));
            }
            let key_bytes = hex::decode(hexkey)
                .map_err(|e| BindingError::InvalidKeyHex(kid.to_string(), e.to_string()))?;
            keys.push((kid.to_string(), key_bytes));
        }
        if keys.is_empty() {
            return Err(BindingError::EmptyKeyring);
        }
        Ok(Self { keys })
    }

    /// Looks up the key bytes for a `kid`, or `None` if this ring doesn't
    /// hold it.
    fn key_for(&self, kid: &str) -> Option<&[u8]> {
        self.keys
            .iter()
            .find(|(k, _)| k == kid)
            .map(|(_, v)| v.as_slice())
    }
}

/// Computes `binding.mac` (spec §5.11's exact formula):
/// `hex(HMAC-SHA256(k_binding[kid], tenant ‖ community ‖ workstream_id ‖
/// event_id ‖ trace_id))`, where `community` renders as
/// [`TENANT_WIDE_SEGMENT`] when absent and `trace_id` is the 32-hex
/// trace-id segment of `traceparent` (empty string when no trace is
/// present). Exposed directly for `svc-ingest`'s minting path and for
/// tests; verification should go through [`verify_binding`] instead so the
/// constant-time comparison can't be forgotten at a call site.
pub fn compute_binding_mac(
    ring: &KeyRing,
    kid: &str,
    tenant: &str,
    community: Option<&str>,
    workstream_id: &str,
    event_id: &str,
    trace_id: Option<&str>,
) -> Result<String, BindingError> {
    let key = ring
        .key_for(kid)
        .ok_or_else(|| BindingError::UnknownKid(kid.to_string()))?;
    // HMAC accepts key material of any length (RFC 2104) -- this only
    // fails for a `Mac` implementation with a fixed key-size requirement,
    // which `Hmac<Sha256>` is not, so this branch is not reachable in
    // practice. Mapped to `MacMismatch` rather than `.expect()`-ed away, in
    // keeping with "no unwrap/expect outside tests" even for a practically
    // infallible call.
    let mut mac = HmacSha256::new_from_slice(key).map_err(|_| BindingError::MacMismatch)?;
    mac.update(tenant.as_bytes());
    mac.update(community.unwrap_or(TENANT_WIDE_SEGMENT).as_bytes());
    mac.update(workstream_id.as_bytes());
    mac.update(event_id.as_bytes());
    mac.update(trace_id.unwrap_or("").as_bytes());
    Ok(hex::encode(mac.finalize().into_bytes()))
}

/// Recomputes `env.binding.mac` under `env.binding.kid` and compares
/// against the value on the wire in constant time (`subtle`) — a
/// variable-time `==` on a MAC is a timing side channel a network attacker
/// can use to forge a valid one byte at a time. Implements spec §5.11
/// verification check 1 only ("`binding.mac` recomputes to the value on the
/// envelope, under the `kid` it names"); checks 2-4 (tenant/community vs.
/// the stream key, grant/install-approval scope, credential/target
/// resolution) are the calling stage's own responsibility — see the module
/// doc for why they aren't part of this shared primitive.
pub fn verify_binding(ring: &KeyRing, env: &StageEnvelope) -> Result<(), BindingError> {
    let trace_id = env
        .trace
        .as_ref()
        .and_then(|t| trace_id_from_traceparent(&t.traceparent));
    let expected = compute_binding_mac(
        ring,
        &env.binding.kid,
        &env.tenant,
        env.community.as_deref(),
        &env.workstream_id,
        &env.event_id,
        trace_id,
    )?;
    let expected_bytes = expected.as_bytes();
    let actual_bytes = env.binding.mac.as_bytes();
    if expected_bytes.len() == actual_bytes.len() && bool::from(expected_bytes.ct_eq(actual_bytes))
    {
        Ok(())
    } else {
        Err(BindingError::MacMismatch)
    }
}

#[cfg(test)]
mod tests {
    #![allow(clippy::unwrap_used)]
    use super::*;

    // Canonical test vectors — same tenant/community/workstream_id/
    // event_id/traceparent tuple `waddles core/svc_action/src/hop.rs`'s own
    // test fixtures use (`ring()`/`valid_envelope`/`mac_for` there), so both
    // repos exercise byte-identical inputs. The literal hex outputs below
    // were captured from this crate's own `compute_binding_mac` (not
    // hand-computed), giving a pinned regression value in addition to the
    // determinism checks further down.
    const TENANT: &str = "acme";
    const COMMUNITY: &str = "main";
    const WORKSTREAM_ID: &str = "8f14e45f-ceea-467e-adde-3fb5c9752730";
    const EVENT_ID: &str = "3fa85f64-5717-4562-b3fc-2c963f66afa6";
    const TRACEPARENT: &str = "00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01";
    const TRACE_ID: &str = "4bf92f3577b34da6a3ce929d0e0e4736";

    const K1_MAIN_MAC: &str = "d94c3849257550fe817c399410113a45e22b1c9203fbd02908f6bcc19df95f3f";
    const K2_MAIN_MAC: &str = "543a96e6e39083ca2405e603ecd28f33ce38866d437b52349836d9251046a279";
    const K1_TENANT_WIDE_MAC: &str =
        "dbd314bbfd446050f1caeb02f0af18e79059ff6daae4fc4c548532e34f4ed6a9";
    const K1_NO_TRACE_MAC: &str =
        "3e856f8b2ee9566e36f448ed0a0c2406499ca003e54fc5f2aad0ea237efb1115";
    const K1_OTHER_TENANT_MAC: &str =
        "a9b5486de948f27f1874e612675024ffffa6bae0b0d7054189517409e9419fab";

    fn ring() -> KeyRing {
        KeyRing::new(vec![
            ("k1".to_string(), vec![1u8; 32]),
            ("k2".to_string(), vec![2u8; 32]),
        ])
    }

    fn valid_envelope(mac: String, kid: &str) -> StageEnvelope {
        serde_json::from_value(serde_json::json!({
            "schema_version": 2,
            "tenant": TENANT,
            "community": COMMUNITY,
            "app_id": "waddles.bot.commands.default",
            "stage": "action",
            "event": {
                "platform": "twitch",
                "event_type": "chat.message",
                "actor": "some_user",
                "payload": {},
                "occurred_at": "2026-09-14T12:00:00.000Z",
                "source": null
            },
            "ts": "2026-09-14T12:00:00.123Z",
            "target_app_id": null,
            "workstream_id": WORKSTREAM_ID,
            "event_id": EVENT_ID,
            "session_id": null,
            "trace": {
                "traceparent": TRACEPARENT,
                "tracestate": null
            },
            "binding": {"kid": kid, "mac": mac}
        }))
        .unwrap()
    }

    fn mac_for(ring: &KeyRing, kid: &str) -> String {
        compute_binding_mac(
            ring,
            kid,
            TENANT,
            Some(COMMUNITY),
            WORKSTREAM_ID,
            EVENT_ID,
            Some(TRACE_ID),
        )
        .unwrap()
    }

    #[test]
    fn compute_binding_mac_matches_the_canonical_k1_vector() {
        assert_eq!(mac_for(&ring(), "k1"), K1_MAIN_MAC);
    }

    #[test]
    fn compute_binding_mac_matches_the_canonical_k2_vector() {
        assert_eq!(mac_for(&ring(), "k2"), K2_MAIN_MAC);
    }

    #[test]
    fn compute_binding_mac_matches_the_canonical_tenant_wide_vector() {
        let mac = compute_binding_mac(
            &ring(),
            "k1",
            TENANT,
            None,
            WORKSTREAM_ID,
            EVENT_ID,
            Some(TRACE_ID),
        )
        .unwrap();
        assert_eq!(mac, K1_TENANT_WIDE_MAC);
    }

    #[test]
    fn compute_binding_mac_matches_the_canonical_no_trace_vector() {
        let mac = compute_binding_mac(
            &ring(),
            "k1",
            TENANT,
            Some(COMMUNITY),
            WORKSTREAM_ID,
            EVENT_ID,
            None,
        )
        .unwrap();
        assert_eq!(mac, K1_NO_TRACE_MAC);
    }

    #[test]
    fn compute_mac_is_deterministic_and_64_hex_chars() {
        let mac1 = mac_for(&ring(), "k1");
        let mac2 = mac_for(&ring(), "k1");
        assert_eq!(mac1, mac2);
        assert_eq!(mac1.len(), 64);
        assert!(mac1.chars().all(|c| c.is_ascii_hexdigit()));
    }

    #[test]
    fn different_kid_produces_a_different_mac() {
        assert_ne!(mac_for(&ring(), "k1"), mac_for(&ring(), "k2"));
    }

    #[test]
    fn compute_mac_rejects_unknown_kid() {
        let err = compute_binding_mac(&ring(), "nope", TENANT, None, "w", "e", None).unwrap_err();
        assert_eq!(err, BindingError::UnknownKid("nope".to_string()));
    }

    #[test]
    fn keyring_parse_reads_kid_hexkey_pairs() {
        let ring = KeyRing::parse("k1:0102030405060708090a0b0c0d0e0f10,k2:ff").unwrap();
        assert!(ring.key_for("k1").is_some());
        assert_eq!(ring.key_for("k2"), Some(&[0xffu8][..]));
    }

    #[test]
    fn keyring_parse_rejects_empty_string() {
        assert_eq!(KeyRing::parse("").unwrap_err(), BindingError::EmptyKeyring);
    }

    #[test]
    fn keyring_parse_rejects_malformed_entry() {
        assert!(matches!(
            KeyRing::parse("k1-nocolon"),
            Err(BindingError::MalformedKeyEntry(_))
        ));
    }

    #[test]
    fn keyring_parse_rejects_invalid_hex() {
        assert!(matches!(
            KeyRing::parse("k1:zzzz"),
            Err(BindingError::InvalidKeyHex(_, _))
        ));
    }

    #[test]
    fn valid_mac_and_kid_verifies() {
        let ring = ring();
        let mac = mac_for(&ring, "k1");
        let env = valid_envelope(mac, "k1");
        assert!(verify_binding(&ring, &env).is_ok());
    }

    // -- tampered MAC: one hex character flipped, still 64 valid hex chars,
    // just wrong -- must be rejected regardless of which kid is claimed. --
    #[test]
    fn tampered_mac_is_rejected() {
        let ring = ring();
        let mut mac = mac_for(&ring, "k1");
        let flipped = if &mac[0..1] == "0" { "1" } else { "0" };
        mac.replace_range(0..1, flipped);
        let env = valid_envelope(mac, "k1");
        assert_eq!(
            verify_binding(&ring, &env).unwrap_err(),
            BindingError::MacMismatch
        );
    }

    #[test]
    fn unknown_kid_on_envelope_is_rejected() {
        let ring = ring();
        let mac = mac_for(&ring, "k1");
        let env = valid_envelope(mac, "k99");
        assert!(matches!(
            verify_binding(&ring, &env),
            Err(BindingError::UnknownKid(_))
        ));
    }

    // -- cross-tenant: a MAC minted for tenant "other-tenant" replayed onto
    // an envelope claiming tenant "acme" must not verify -- the tenant
    // string is part of the HMAC input, not sourced or checked separately,
    // so recomputation under the claimed (wrong) tenant simply disagrees. --
    #[test]
    fn cross_tenant_mac_reuse_is_rejected() {
        let ring = ring();
        let other_tenant_mac = compute_binding_mac(
            &ring,
            "k1",
            "other-tenant",
            Some(COMMUNITY),
            WORKSTREAM_ID,
            EVENT_ID,
            Some(TRACE_ID),
        )
        .unwrap();
        assert_eq!(other_tenant_mac, K1_OTHER_TENANT_MAC);
        // Same MAC, but stamped onto an envelope claiming tenant "acme".
        let env = valid_envelope(other_tenant_mac, "k1");
        assert_eq!(
            verify_binding(&ring, &env).unwrap_err(),
            BindingError::MacMismatch
        );
    }

    #[test]
    fn verify_binding_with_no_trace_present() {
        let ring = ring();
        let mac = compute_binding_mac(
            &ring,
            "k1",
            TENANT,
            Some(COMMUNITY),
            WORKSTREAM_ID,
            EVENT_ID,
            None,
        )
        .unwrap();
        let mut v = serde_json::json!({
            "schema_version": 2,
            "tenant": TENANT,
            "community": COMMUNITY,
            "app_id": "waddles.bot.commands.default",
            "stage": "action",
            "event": {
                "platform": "twitch",
                "event_type": "chat.message",
                "actor": "some_user",
                "payload": {},
                "occurred_at": "2026-09-14T12:00:00.000Z",
                "source": null
            },
            "ts": "2026-09-14T12:00:00.123Z",
            "target_app_id": null,
            "workstream_id": WORKSTREAM_ID,
            "event_id": EVENT_ID,
            "session_id": null,
            "trace": null,
            "binding": {"kid": "k1", "mac": mac}
        });
        v.as_object_mut().unwrap().remove("trace");
        let env: StageEnvelope = serde_json::from_value(v).unwrap();
        assert!(verify_binding(&ring, &env).is_ok());
    }

    #[test]
    fn boundary_check_error_messages_name_the_offending_value() {
        let err = BindingError::UnknownKid("k99".to_string());
        assert!(err.to_string().contains("k99"));
        let err = BindingError::MalformedKeyEntry("bogus".to_string());
        assert!(err.to_string().contains("bogus"));
        let err = BindingError::InvalidKeyHex("k1".to_string(), "odd length".to_string());
        assert!(err.to_string().contains("k1"));
        assert!(err.to_string().contains("odd length"));
    }
}
