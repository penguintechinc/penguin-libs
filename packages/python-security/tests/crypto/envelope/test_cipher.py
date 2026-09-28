"""Tests for versioned envelope AES-256-GCM encrypt/decrypt and the nonce cap."""

import os
import threading

import pytest
from cryptography.exceptions import InvalidTag

from penguin_security.crypto.envelope.aad import build_aad
from penguin_security.crypto.envelope.cipher import (
    CiphertextFormatError,
    InMemoryEncryptionCounter,
    RotationRequiredError,
    envelope_decrypt,
    envelope_dek_version,
    envelope_encrypt,
)


def _dek() -> bytes:
    return os.urandom(32)


def _aad(tenant_id: object = 1, row_uuid: str = "row-1", dek_version: int = 1) -> bytes:
    return build_aad(
        tenant_id=tenant_id,
        table="hub_chat_messages",
        column="message_content",
        row_uuid=row_uuid,
        dek_version=dek_version,
    )


def test_round_trip() -> None:
    """A field encrypted and decrypted under the same key/AAD returns the original plaintext."""
    dek = _dek()
    aad = _aad()
    envelope = envelope_encrypt("hello tenant", dek, dek_version=1, aad=aad)
    assert envelope_decrypt(envelope, dek, aad=aad) == b"hello tenant"


def test_round_trip_bytes_plaintext() -> None:
    """Raw bytes plaintext is accepted without implicit str conversion."""
    dek = _dek()
    aad = _aad()
    envelope = envelope_encrypt(b"\x00\x01raw-bytes", dek, dek_version=1, aad=aad)
    assert envelope_decrypt(envelope, dek, aad=aad) == b"\x00\x01raw-bytes"


def test_rejects_wrong_key_length() -> None:
    """A DEK that isn't exactly 32 bytes is always a caller bug."""
    with pytest.raises(ValueError, match="32 bytes"):
        envelope_encrypt("x", os.urandom(16), dek_version=1, aad=_aad())


def test_aad_mismatch_is_rejected() -> None:
    """Decrypting with a different AAD than was used to encrypt fails closed."""
    dek = _dek()
    envelope = envelope_encrypt("secret", dek, dek_version=1, aad=_aad(row_uuid="row-1"))
    with pytest.raises(InvalidTag):
        envelope_decrypt(envelope, dek, aad=_aad(row_uuid="row-2"))


def test_cross_tenant_ciphertext_swap_is_rejected() -> None:
    """Copying one tenant's ciphertext bytes into another tenant's row must not decrypt.

    This is the core cryptographic-isolation property from the design: even
    with the *same* DEK (e.g. a bug that reused a key across tenants), the
    AAD's tenant_id component makes a cross-tenant copy fail to decrypt.
    """
    dek = _dek()
    tenant_a_aad = _aad(tenant_id="tenant-a")
    tenant_b_aad = _aad(tenant_id="tenant-b")

    stolen_envelope = envelope_encrypt("tenant a's secret", dek, dek_version=1, aad=tenant_a_aad)

    with pytest.raises(InvalidTag):
        envelope_decrypt(stolen_envelope, dek, aad=tenant_b_aad)


def test_tamper_detection_flipped_ciphertext_byte() -> None:
    """Any bit-flip in the ciphertext/tag region fails the GCM authentication check."""
    dek = _dek()
    aad = _aad()
    envelope = bytearray(envelope_encrypt("integrity matters", dek, dek_version=1, aad=aad))
    envelope[-1] ^= 0xFF  # flip the last byte (inside the GCM tag)

    with pytest.raises(InvalidTag):
        envelope_decrypt(bytes(envelope), dek, aad=aad)


def test_tamper_detection_flipped_nonce_byte() -> None:
    """A tampered nonce also fails the authentication check, not just the ciphertext."""
    dek = _dek()
    aad = _aad()
    envelope = bytearray(envelope_encrypt("integrity matters", dek, dek_version=1, aad=aad))
    envelope[5] ^= 0xFF  # byte 5 is inside the 12-byte nonce (header is 5 bytes)

    with pytest.raises(InvalidTag):
        envelope_decrypt(bytes(envelope), dek, aad=aad)


def test_envelope_too_short_raises_format_error() -> None:
    """A truncated envelope is a format error, not a cryptography-library crash."""
    with pytest.raises(CiphertextFormatError, match="too short"):
        envelope_decrypt(b"\x01\x00\x00\x00\x01", os.urandom(32), aad=_aad())


def test_envelope_one_byte_short_of_valid_raises_format_error() -> None:
    """The minimum-length boundary check is exact, not off-by-one in either direction.

    An empty-plaintext envelope is exactly `min_len` bytes (header + nonce +
    bare GCM tag); trimming one more byte must fail the length check itself
    rather than falling through to an AESGCM InvalidTag.
    """
    dek = _dek()
    envelope = envelope_encrypt("", dek, dek_version=1, aad=_aad())
    with pytest.raises(CiphertextFormatError, match="too short"):
        envelope_decrypt(envelope[:-1], dek, aad=_aad())


def test_unsupported_format_version_raises_format_error() -> None:
    """An envelope claiming an unknown format version is rejected before touching AESGCM."""
    dek = _dek()
    envelope = bytearray(envelope_encrypt("x", dek, dek_version=1, aad=_aad()))
    envelope[0] = 99  # corrupt the format-version byte
    with pytest.raises(CiphertextFormatError, match="format version"):
        envelope_decrypt(bytes(envelope), dek, aad=_aad())


def test_envelope_dek_version_reads_header_without_decrypting() -> None:
    """Callers can resolve which DEK version to fetch before attempting decryption."""
    dek = _dek()
    envelope = envelope_encrypt("x", dek, dek_version=7, aad=_aad(dek_version=7))
    assert envelope_dek_version(envelope) == 7


def test_envelope_dek_version_rejects_truncated_header() -> None:
    """Reading the header off a too-short envelope raises a format error, not an IndexError."""
    with pytest.raises(CiphertextFormatError, match="too short"):
        envelope_dek_version(b"\x01")


def test_nonce_cap_signals_rotation_required() -> None:
    """Reaching the configured per-DEK encryption cap raises RotationRequiredError.

    Exactly `cap` encryptions succeed; the (cap+1)-th attempt is blocked
    *before* any nonce is generated or encryption performed — no over-cap
    encryption ever happens.
    """
    dek = _dek()
    counter = InMemoryEncryptionCounter(cap=3)

    for _ in range(3):
        envelope_encrypt("x", dek, dek_version=1, aad=_aad(), counter=counter, cap=3)

    with pytest.raises(RotationRequiredError) as exc_info:
        envelope_encrypt("x", dek, dek_version=1, aad=_aad(), counter=counter, cap=3)

    assert exc_info.value.dek_version == 1
    assert exc_info.value.cap == 3
    # No encryption was attempted for the call that tripped the cap.
    assert exc_info.value.envelope is None


def test_nonce_cap_is_tracked_independently_per_dek_version() -> None:
    """Rotating to a new dek_version resets the counter for that version."""
    dek = _dek()
    counter = InMemoryEncryptionCounter(cap=2)

    envelope_encrypt("x", dek, dek_version=1, aad=_aad(dek_version=1), counter=counter, cap=2)
    envelope_encrypt("x", dek, dek_version=1, aad=_aad(dek_version=1), counter=counter, cap=2)
    with pytest.raises(RotationRequiredError):
        envelope_encrypt("x", dek, dek_version=1, aad=_aad(dek_version=1), counter=counter, cap=2)

    # dek_version 2 has never been used against this counter and is unaffected.
    envelope_encrypt("x", dek, dek_version=2, aad=_aad(dek_version=2), counter=counter, cap=2)


def test_default_cap_is_two_to_the_thirty() -> None:
    """The documented default cap matches the design's NIST SP 800-38D margin."""
    counter = InMemoryEncryptionCounter()
    assert counter.cap == 2**30


def test_counter_check_and_increment_is_thread_safe() -> None:
    """Concurrent callers never over-run the cap and never lose an increment (no lost update).

    Hammers one counter from many threads right at the cap boundary; the
    single `threading.Lock` in `InMemoryEncryptionCounter.check_and_increment`
    must make each check-and-increment atomic, so exactly `cap` calls
    succeed regardless of scheduling.
    """
    cap = 200
    counter = InMemoryEncryptionCounter(cap=cap)
    successes = 0
    failures = 0
    lock = threading.Lock()

    def _attempt() -> None:
        nonlocal successes, failures
        try:
            counter.check_and_increment(1, cap)
        except RotationRequiredError:
            with lock:
                failures += 1
        else:
            with lock:
                successes += 1

    threads = [threading.Thread(target=_attempt) for _ in range(cap * 3)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert successes == cap
    assert failures == cap * 3 - cap
