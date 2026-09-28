"""Versioned AES-256-GCM envelope field encryption.

Wraps a plaintext field value in a self-describing ciphertext envelope
(format version + dek_version + nonce + AESGCM ct||tag), bound to a caller-
supplied AAD (see `aad.build_aad`). Also implements the per-DEK encryption-
count cap from the tenant-envelope-encryption design: NIST SP 800-38D's
random-96-bit-nonce collision bound means risk becomes non-negligible well
before 2**32 encryptions under one key, so each dek_version is capped well
inside that margin (default 2**30) and rotation is signaled on the cap.
"""

from __future__ import annotations

import os
import struct
import threading
from typing import Protocol

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

_FORMAT_VERSION = 1
_NONCE_LEN = 12  # 96-bit GCM nonce
_HEADER_STRUCT = struct.Struct(">BI")  # format version (1B) + dek_version (4B)
_DEFAULT_ENCRYPTION_CAP = 2**30


class CiphertextFormatError(ValueError):
    """Raised when a ciphertext envelope is malformed, truncated, or an unknown version."""


class RotationRequiredError(RuntimeError):
    """Raised when a DEK has already reached its configured encryption-operation cap.

    Raised *before* any nonce is generated or encryption performed — the
    call that raises this never encrypts, so there is never an operation
    beyond the configured cap. Signals the caller to rotate to a new
    dek_version; it does not block decryption of already-written ciphertext.
    """

    def __init__(self, dek_version: int, cap: int, envelope: bytes | None = None) -> None:
        """Record the dek_version/cap that tripped; `envelope` is always None on this path."""
        self.dek_version = dek_version
        self.cap = cap
        self.envelope = envelope
        super().__init__(f"dek_version {dek_version} reached its encryption cap of {cap}")


class EncryptionCounter(Protocol):
    """Pluggable per-DEK encryption-count tracker, checked before every encryption.

    **Atomicity contract (mandatory for any implementation):** two
    concurrent callers must never both observe the same pre-increment count
    — `check_and_increment` must be a single atomic check-and-increment, not
    a read followed by a separate write. `InMemoryEncryptionCounter` below
    satisfies this with a `threading.Lock` for single-process use.

    **Multi-process/multi-replica deployments MUST NOT use
    `InMemoryEncryptionCounter`** — each process would maintain its own
    independent count, silently multiplying the effective cap by the
    replica count. Back this protocol with a shared, atomically-incrementing
    store instead, for example:

    - **Valkey/Redis:** a Lua script (or `INCR` on a per-dek_version key
      combined with `cap` compared client-side under a distributed lock) —
      plain `INCR` followed by a separate compare is *not* atomic enough on
      its own without a script, since two replicas could both read the
      pre-increment value between the `INCR` and the comparison in a naive
      implementation; use `EVAL "local n = redis.call('INCR', KEYS[1]); if
      n > tonumber(ARGV[1]) then return redis.call('DECR', KEYS[1]) end;
      return n" 1 <key> <cap>`-style atomicity, or simply treat `INCR`
      itself as authoritative (it already is atomic) and compare afterward,
      accepting that at most one caller across the fleet ever observes the
      cap-exceeding count and raises — client-side rollback (`DECR`) that
      exact count so accounting stays correct is recommended.
    - **Postgres/a DB-backed counter:** `UPDATE dek_encryption_counters
      SET count = count + 1 WHERE dek_version = %s AND count < %s
      RETURNING count` — an unmatched `WHERE` (i.e. zero rows returned)
      means the cap was already reached; the row is never incremented past it.
    """

    def check_and_increment(self, dek_version: int, cap: int) -> None:
        """Atomically increment dek_version's count, or raise if already at `cap`.

        Raises:
            RotationRequiredError: If the count for `dek_version` is already
                `>= cap` — the caller must not proceed to encrypt.
        """
        ...


class InMemoryEncryptionCounter:
    """Single-process, lock-protected, non-durable `EncryptionCounter` (default cap 2**30).

    Thread-safe within one process via a single `threading.Lock` guarding
    the check-and-increment as one atomic step. **Not safe across
    independent processes/replicas** — see `EncryptionCounter`'s docstring
    for the durable-store contract a production, multi-replica deployment
    must implement instead.
    """

    def __init__(self, cap: int = _DEFAULT_ENCRYPTION_CAP) -> None:
        """Initialize with the encryption-operation cap per dek_version."""
        self.cap = cap
        self._counts: dict[int, int] = {}
        self._lock = threading.Lock()

    def check_and_increment(self, dek_version: int, cap: int) -> None:
        """Atomically increment dek_version's count under `self._lock`, or raise at `cap`."""
        with self._lock:
            count = self._counts.get(dek_version, 0)
            if count >= cap:
                raise RotationRequiredError(dek_version, cap)
            self._counts[dek_version] = count + 1


def envelope_encrypt(
    plaintext: bytes | str,
    dek: bytes,
    *,
    dek_version: int,
    aad: bytes,
    counter: EncryptionCounter | None = None,
    cap: int = _DEFAULT_ENCRYPTION_CAP,
) -> bytes:
    """Encrypt one field value into a versioned envelope ciphertext.

    Args:
        plaintext: Field value to encrypt.
        dek: 32-byte unwrapped data-encryption key (AES-256).
        dek_version: Version identifier stored alongside the ciphertext, so
            a rotation always decrypts against the correct key.
        aad: Additional authenticated data from `aad.build_aad` (or
            equivalent) — binds the ciphertext to its tenant/table/column/row.
        counter: Optional encryption-count tracker; when supplied, checked
            against `cap` after each encryption.
        cap: Encryption-operation cap per dek_version (default 2**30).

    Returns:
        `version(1B) || dek_version(4B) || nonce(12B) || ciphertext||tag`.

    Raises:
        ValueError: If `dek` is not 32 bytes.
        RotationRequiredError: If `counter` reports `dek_version` has already
            reached `cap`. Raised *before* any nonce is generated or
            encryption performed, so this dek_version is never used for
            more than `cap` encryptions — catch this, rotate to a new
            dek_version, and retry the write under the new version.
    """
    if len(dek) != 32:
        raise ValueError(f"DEK must be 32 bytes, got {len(dek)}")

    if counter is not None:
        counter.check_and_increment(dek_version, cap)

    if isinstance(plaintext, str):
        plaintext = plaintext.encode("utf-8")

    nonce = os.urandom(_NONCE_LEN)
    ct = AESGCM(dek).encrypt(nonce, plaintext, aad)
    return _HEADER_STRUCT.pack(_FORMAT_VERSION, dek_version) + nonce + ct


def envelope_decrypt(envelope: bytes, dek: bytes, *, aad: bytes) -> bytes:
    """Decrypt a versioned envelope ciphertext produced by `envelope_encrypt`.

    Args:
        envelope: The full envelope byte string.
        dek: 32-byte unwrapped data-encryption key matching the envelope's
            `dek_version` (caller is responsible for resolving the right
            DEK by version before calling this).
        aad: The exact AAD used at encryption time — any mismatch (wrong
            tenant, table, column, row_uuid, or dek_version) fails the GCM
            authentication tag check and raises `InvalidTag`.

    Returns:
        The original plaintext bytes.

    Raises:
        CiphertextFormatError: If the envelope is truncated or its format
            version is unrecognized.
        ValueError: If `dek` is not 32 bytes.
        cryptography.exceptions.InvalidTag: If the AAD, key, or ciphertext
            don't match (tamper, wrong tenant/row/column, or wrong key).
    """
    if len(dek) != 32:
        raise ValueError(f"DEK must be 32 bytes, got {len(dek)}")

    header_len = _HEADER_STRUCT.size
    min_len = header_len + _NONCE_LEN + 16  # + GCM tag
    if len(envelope) < min_len:
        raise CiphertextFormatError(f"envelope too short: {len(envelope)} < {min_len} bytes")

    version, _dek_version = _HEADER_STRUCT.unpack_from(envelope, 0)
    if version != _FORMAT_VERSION:
        raise CiphertextFormatError(f"unsupported envelope format version: {version}")

    offset = header_len
    nonce = envelope[offset : offset + _NONCE_LEN]
    ct = envelope[offset + _NONCE_LEN :]

    try:
        return AESGCM(dek).decrypt(nonce, ct, aad)
    except InvalidTag:
        raise


def envelope_dek_version(envelope: bytes) -> int:
    """Read the dek_version out of an envelope without decrypting it.

    Used by callers to resolve which DEK to fetch before calling
    `envelope_decrypt`.

    Args:
        envelope: The full envelope byte string.

    Returns:
        The dek_version stored in the envelope header.

    Raises:
        CiphertextFormatError: If the envelope is truncated or its format
            version is unrecognized.
    """
    header_len = _HEADER_STRUCT.size
    if len(envelope) < header_len:
        raise CiphertextFormatError(f"envelope too short: {len(envelope)} < {header_len} bytes")

    version, dek_version = _HEADER_STRUCT.unpack_from(envelope, 0)
    if version != _FORMAT_VERSION:
        raise CiphertextFormatError(f"unsupported envelope format version: {version}")

    return int(dek_version)


__all__ = [
    "CiphertextFormatError",
    "RotationRequiredError",
    "EncryptionCounter",
    "InMemoryEncryptionCounter",
    "envelope_encrypt",
    "envelope_decrypt",
    "envelope_dek_version",
]
