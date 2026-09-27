"""Tests for the HKDF-derived HMAC-SHA256 blind index helper."""

import os

from penguin_crypto.envelope.blind_index import blind_index, derive_blind_index_key


def test_same_value_same_key_produces_same_index() -> None:
    """Deterministic — required so it can be used as an equality lookup key."""
    key = derive_blind_index_key(os.urandom(32))
    assert blind_index("user@example.com", key) == blind_index("user@example.com", key)


def test_different_values_produce_different_index() -> None:
    """Distinct plaintexts should (overwhelmingly likely) produce distinct indexes."""
    key = derive_blind_index_key(os.urandom(32))
    assert blind_index("a@example.com", key) != blind_index("b@example.com", key)


def test_different_tenant_keys_produce_different_index_for_same_value() -> None:
    """Documented leakage is scoped per key — the same email under two tenants' keys differs.

    This is the property that keeps equality/frequency leakage from crossing
    the tenant boundary: an attacker who recovers one tenant's blind index
    of "user@example.com" learns nothing comparable about another tenant's
    index of the same email.
    """
    key_tenant_a = derive_blind_index_key(os.urandom(32))
    key_tenant_b = derive_blind_index_key(os.urandom(32))

    idx_a = blind_index("user@example.com", key_tenant_a)
    idx_b = blind_index("user@example.com", key_tenant_b)

    assert idx_a != idx_b


def test_blind_index_rotates_with_the_dek() -> None:
    """A new dek_version's derived subkey produces a different index for the same value.

    Matches the design: blind-index rotation is not a separate process, it
    happens exactly when the DEK rotates because the subkey is HKDF-derived
    from the DEK itself.
    """
    dek_v1 = os.urandom(32)
    dek_v2 = os.urandom(32)

    idx_v1 = blind_index("user@example.com", derive_blind_index_key(dek_v1))
    idx_v2 = blind_index("user@example.com", derive_blind_index_key(dek_v2))

    assert idx_v1 != idx_v2


def test_normalize_callback_applied_before_hashing() -> None:
    """The optional normalize callback (e.g. lower/trim for email) changes what's hashed."""
    key = derive_blind_index_key(os.urandom(32))
    normalize = lambda v: v.strip().lower()  # noqa: E731 - concise, matches the design's example

    assert blind_index("  User@Example.com  ", key, normalize=normalize) == blind_index(
        "user@example.com", key, normalize=normalize
    )
    # Without normalization these differ.
    assert blind_index("  User@Example.com  ", key) != blind_index("user@example.com", key)


def test_reveals_equality_and_frequency_within_key_scope() -> None:
    """Documents the accepted leakage: duplicate plaintexts are visible via equal indexes.

    This is the tradeoff the design explicitly accepts for high-entropy
    fields used in equality lookups — the plaintext itself is not revealed.
    """
    key = derive_blind_index_key(os.urandom(32))
    values = ["dup@example.com", "dup@example.com", "unique@example.com"]
    indexes = [blind_index(v, key) for v in values]

    assert indexes[0] == indexes[1]  # duplicate values are indistinguishable-but-equal
    assert indexes[0] != indexes[2]


def test_output_is_32_byte_hmac_sha256_digest() -> None:
    """Output size matches the schema's `_bidx BYTEA` HMAC-SHA256 expectation."""
    key = derive_blind_index_key(os.urandom(32))
    assert len(blind_index("x", key)) == 32
