"""Canonical AAD (additional authenticated data) construction.

The AAD binds a GCM ciphertext to its exact tenant/table/column/row/key
context so that copying raw ciphertext bytes into another row, column,
table, or tenant fails to decrypt instead of silently decrypting under the
wrong context. Per the tenant-envelope-encryption design, fields are
length-prefixed (not delimiter-joined) so no combination of field values
can produce a colliding AAD byte string.
"""

from __future__ import annotations

import struct

_LEN_STRUCT = struct.Struct(">I")  # 4-byte big-endian length prefix


def _encode_field(value: str | int) -> bytes:
    """Length-prefix-encode a single AAD field to remove delimiter ambiguity.

    Args:
        value: Field value; integers are rendered as decimal ASCII text.

    Returns:
        4-byte big-endian length prefix followed by the UTF-8 field bytes.
    """
    raw = str(value).encode("utf-8")
    return _LEN_STRUCT.pack(len(raw)) + raw


def build_aad(
    *,
    tenant_id: str | int,
    table: str,
    column: str,
    row_uuid: str,
    dek_version: int,
) -> bytes:
    """Build the canonical AAD for one encrypted field.

    Args:
        tenant_id: Owning tenant identifier (or a fixed sentinel for the
            platform identity DEK, per the design's identity-table exception).
        table: Destination table name.
        column: Destination column name.
        row_uuid: App-generated UUIDv4 for the row, minted before the
            ciphertext is built (never the auto-increment PK).
        dek_version: Version of the DEK used to encrypt this field.

    Returns:
        A length-prefixed, unambiguous byte string suitable as GCM AAD.

    Raises:
        ValueError: If dek_version is negative.
    """
    if dek_version < 0:
        raise ValueError(f"dek_version must be non-negative, got {dek_version}")

    return (
        _encode_field(tenant_id)
        + _encode_field(table)
        + _encode_field(column)
        + _encode_field(row_uuid)
        + _encode_field(dek_version)
    )


__all__ = ["build_aad"]
