"""Per-tenant HMAC-SHA256 blind index for equality-only search on encrypted columns.

Per the design (§3 of the tenant-envelope-encryption spec): a blind index is
a deterministic HMAC of the normalized plaintext, keyed by a per-tenant
subkey HKDF-derived from that tenant's DEK (`info=b"blind-index-v1"`), so it
rotates exactly when the DEK does and never leaks across tenant boundaries.

**Documented leakage — read before using on a new column.** A blind index
reveals *equality and frequency* within its key scope: two rows sharing the
same underlying value produce the same index value, so duplicates are
visible without decryption (though the plaintext itself is not). This is
acceptable for high-entropy fields used for exact-match lookups (e.g.
`email`). It is **not** appropriate for low-entropy/low-cardinality fields
(an IPv4 has ~2**32 possible values but real-world traffic clusters into a
tiny observed set; most `user_agent` strings collapse to a few hundred
distinct values) — a small value space is a dictionary attack away from a
full plaintext-equivalent lookup table. There is no substring/LIKE/full-text
capability here; only exact-match equality is supported.
"""

from __future__ import annotations

import hmac
from collections.abc import Callable
from hashlib import sha256

from ..kdf import derive_key_hkdf

_BLIND_INDEX_INFO = b"blind-index-v1"


def derive_blind_index_key(dek: bytes, *, info: bytes = _BLIND_INDEX_INFO) -> bytes:
    """Derive a tenant's blind-index HMAC subkey from its DEK via HKDF.

    Args:
        dek: The tenant's (or platform identity's) unwrapped 32-byte DEK.
        info: HKDF context string — kept as a fixed versioned constant so
            the derivation is reproducible; change only with a new
            info-string version if the scheme itself changes.

    Returns:
        32-byte HMAC-SHA256 key, scoped to this DEK/dek_version — rotating
        the DEK rotates this subkey too, with no separate process needed.
    """
    return derive_key_hkdf(input_key_material=dek, salt=None, info=info, length=32)


def blind_index(
    value: str,
    key: bytes,
    *,
    normalize: Callable[[str], str] | None = None,
) -> bytes:
    """Compute the equality-only blind index for one plaintext value.

    Args:
        value: Plaintext value (e.g. an email address) to index.
        key: Per-tenant blind-index key from `derive_blind_index_key`.
        normalize: Optional normalization applied before hashing (e.g.
            `lambda v: v.strip().lower()` for email, matching the design's
            `lower(trim(email))`). Defaults to no normalization — callers
            indexing case/whitespace-sensitive values should pass `None`
            explicitly and normalize upstream, or rely on this default.

    Returns:
        32-byte HMAC-SHA256 digest, stored as the column's `_bidx BYTEA` value.
    """
    normalized = normalize(value) if normalize is not None else value
    return hmac.new(key, normalized.encode("utf-8"), sha256).digest()


__all__ = ["derive_blind_index_key", "blind_index"]
