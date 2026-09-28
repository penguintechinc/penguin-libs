"""Tests for the HKDF-derived HMAC-SHA256 blind index helper."""

import os

from penguin_security.crypto.envelope.blind_index import blind_index, derive_blind_index_key


def _key(
    root_key: bytes | None = None, tenant_id: str = "tenant-a", purpose: str = "email"
) -> bytes:
    return derive_blind_index_key(root_key or os.urandom(32), tenant_id=tenant_id, purpose=purpose)


def test_same_value_same_key_produces_same_index() -> None:
    """Deterministic — required so it can be used as an equality lookup key."""
    key = _key()
    assert blind_index("user@example.com", key) == blind_index("user@example.com", key)


def test_different_values_produce_different_index() -> None:
    """Distinct plaintexts should (overwhelmingly likely) produce distinct indexes."""
    key = _key()
    assert blind_index("a@example.com", key) != blind_index("b@example.com", key)


def test_different_tenant_keys_produce_different_index_for_same_value() -> None:
    """Documented leakage is scoped per key — the same email under two tenants' keys differs.

    This is the property that keeps equality/frequency leakage from crossing
    the tenant boundary: an attacker who recovers one tenant's blind index
    of "user@example.com" learns nothing comparable about another tenant's
    index of the same email.
    """
    key_tenant_a = _key(tenant_id="tenant-a")
    key_tenant_b = _key(tenant_id="tenant-b")

    idx_a = blind_index("user@example.com", key_tenant_a)
    idx_b = blind_index("user@example.com", key_tenant_b)

    assert idx_a != idx_b


def test_same_root_key_different_tenant_id_produces_different_index() -> None:
    """Even if a root key were accidentally reused across tenants, tenant_id separates them."""
    root_key = os.urandom(32)
    idx_a = blind_index("user@example.com", _key(root_key, tenant_id="tenant-a"))
    idx_b = blind_index("user@example.com", _key(root_key, tenant_id="tenant-b"))
    assert idx_a != idx_b


def test_same_root_key_different_purpose_produces_different_index() -> None:
    """Different indexed columns under the same root key get independent subkeys."""
    root_key = os.urandom(32)
    idx_email = blind_index("shared-value", _key(root_key, purpose="email"))
    idx_username = blind_index("shared-value", _key(root_key, purpose="username"))
    assert idx_email != idx_username


def test_blind_index_key_is_stable_across_calls_with_the_same_root_key() -> None:
    """The blind-index key must be reproducible from the same (root_key, tenant_id, purpose).

    This is what makes it usable for lookups at all — a caller resolving
    the tenant's stable blind-index root key twice must derive the same
    subkey both times, independent of any field-encryption DEK rotation.
    """
    root_key = os.urandom(32)
    key_1 = _key(root_key, tenant_id="tenant-a", purpose="email")
    key_2 = _key(root_key, tenant_id="tenant-a", purpose="email")
    assert key_1 == key_2


def test_normalize_callback_applied_before_hashing() -> None:
    """The optional normalize callback (e.g. lower/trim for email) changes what's hashed."""
    key = _key()
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
    key = _key()
    values = ["dup@example.com", "dup@example.com", "unique@example.com"]
    indexes = [blind_index(v, key) for v in values]

    assert indexes[0] == indexes[1]  # duplicate values are indistinguishable-but-equal
    assert indexes[0] != indexes[2]


def test_output_is_32_byte_hmac_sha256_digest() -> None:
    """Output size matches the schema's `_bidx BYTEA` HMAC-SHA256 expectation."""
    key = _key()
    assert len(blind_index("x", key)) == 32
