"""AES-256-GCM symmetric encryption module."""

import os

from cryptography.hazmat.primitives.ciphers.aead import AESGCM  # type: ignore[import-untyped]


def generate_key(length: int = 32) -> bytes:
    """Generate a secure random encryption key.

    Args:
        length: Key length in bytes (default 32 for AES-256)

    Returns:
        Secure random bytes of specified length
    """
    return os.urandom(length)


def encrypt(plaintext: bytes | str, key: bytes) -> bytes:
    """Encrypt plaintext using AES-256-GCM.

    Args:
        plaintext: Data to encrypt (bytes or str)
        key: 32-byte encryption key (AES-256)

    Returns:
        nonce (12 bytes) + ciphertext + tag (16 bytes) concatenated

    Raises:
        ValueError: If key length is not 32 bytes
    """
    if isinstance(plaintext, str):
        plaintext = plaintext.encode()

    if len(key) != 32:
        raise ValueError(f"Key must be 32 bytes, got {len(key)}")

    nonce = os.urandom(12)  # 96-bit nonce for GCM
    cipher = AESGCM(key)
    ciphertext = cipher.encrypt(nonce, plaintext, None)
    return nonce + ciphertext


def decrypt(ciphertext: bytes, key: bytes) -> bytes:
    """Decrypt ciphertext using AES-256-GCM.

    Args:
        ciphertext: Encrypted data (nonce + ciphertext + tag)
        key: 32-byte decryption key (AES-256)

    Returns:
        Decrypted plaintext bytes

    Raises:
        InvalidTag: If ciphertext is tampered or key is wrong
        ValueError: If ciphertext is too short or key length is invalid
    """
    if len(key) != 32:
        raise ValueError(f"Key must be 32 bytes, got {len(key)}")

    if len(ciphertext) < 28:  # 12 byte nonce + 16 byte tag minimum
        raise ValueError("Ciphertext too short")

    nonce = ciphertext[:12]
    encrypted_data = ciphertext[12:]
    cipher = AESGCM(key)
    plaintext = cipher.decrypt(nonce, encrypted_data, None)
    return plaintext


__all__ = [
    "generate_key",
    "encrypt",
    "decrypt",
]
