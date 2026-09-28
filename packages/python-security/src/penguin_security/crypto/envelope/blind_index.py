"""Per-tenant HMAC-SHA256 blind index for equality-only search on encrypted columns.

Per the design (§3 of the tenant-envelope-encryption spec): a blind index is
a deterministic HMAC of the normalized plaintext, keyed by a per-tenant
subkey. **This subkey MUST be derived from a stable, dedicated per-tenant
blind-index root key — never from the currently-active, rotating
field-encryption DEK.** Deriving it from the working DEK would tie the
blind index's lifetime to routine, non-security-driven rotations (e.g. the
per-DEK encryption-count cap in `cipher.py`, which can trip on ordinary
write volume alone), forcing a full re-index of every blind-indexed row on
every such rotation just to keep lookups working. Instead: mint one stable
root key per tenant (per platform-identity sentinel for the identity-table
exception) at tenant-creation time, wrapped/cached the same way as the
field-encryption DEK but tracked as its own independent lineage, and only
re-key it via an explicit, deliberate **re-index procedure** (compromise
response, not routine rotation):

1. Mint a new blind-index root key (new version).
2. Dual-write: compute and store the new `_bidx` value alongside the old
   one for every write, while old and new indexes are both queried until
   backfill completes (`old_bidx OR new_bidx` at read time, or an
   application-level fallback from a new-index miss to an old-index hit).
3. Backfill: a bounded, resumable background job recomputes `_bidx` for
   every existing row under the new root key.
4. Cutover: once backfill reports 100% coverage, stop writing/reading the
   old `_bidx` and drop the column.

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

_BLIND_INDEX_INFO_PREFIX = b"blind-index-v1"


def derive_blind_index_key(root_key: bytes, *, tenant_id: str, purpose: str) -> bytes:
    """Derive a tenant+purpose-scoped blind-index HMAC subkey via HKDF.

    Args:
        root_key: The tenant's **stable blind-index root key** — a
            dedicated secret minted at tenant-creation time and re-keyed
            only via the explicit re-index procedure documented on this
            module, never the currently-active field-encryption DEK.
        tenant_id: Owning tenant (or the platform-identity sentinel) —
            folded into the HKDF `info` so a root key accidentally reused
            across tenants still can't produce colliding subkeys.
        purpose: A stable identifier for what's being indexed (e.g. the
            column name, `"hub_users.email"`) — folded into `info` so the
            same root key produces independent subkeys per indexed field,
            limiting the blast radius of any one subkey's exposure.

    Returns:
        32-byte HMAC-SHA256 key, scoped to this (root_key, tenant_id,
        purpose) triple. `tenant_id`/`purpose` are length-prefixed in the
        derived `info` so no combination of values can produce a colliding
        boundary between them.
    """
    tenant_bytes = tenant_id.encode("utf-8")
    purpose_bytes = purpose.encode("utf-8")
    info = (
        _BLIND_INDEX_INFO_PREFIX
        + b"|"
        + len(tenant_bytes).to_bytes(4, "big")
        + tenant_bytes
        + len(purpose_bytes).to_bytes(4, "big")
        + purpose_bytes
    )
    return derive_key_hkdf(input_key_material=root_key, salt=None, info=info, length=32)


def blind_index(
    value: str,
    key: bytes,
    *,
    normalize: Callable[[str], str] | None = None,
) -> bytes:
    """Compute the equality-only blind index for one plaintext value.

    Args:
        value: Plaintext value (e.g. an email address) to index.
        key: Per-tenant, per-purpose blind-index key from `derive_blind_index_key`.
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
