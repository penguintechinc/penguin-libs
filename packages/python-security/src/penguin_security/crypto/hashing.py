"""Cryptographic hashing functions (SHA, BLAKE2b, HMAC)."""

import hashlib
import hmac


def sha256(data: bytes | str) -> str:
    """Hash data using SHA-256.

    Args:
        data: Data to hash (bytes or str)

    Returns:
        Hex digest string (64 characters)
    """
    if isinstance(data, str):
        data = data.encode()
    return hashlib.sha256(data).hexdigest()


def sha512(data: bytes | str) -> str:
    """Hash data using SHA-512.

    Args:
        data: Data to hash (bytes or str)

    Returns:
        Hex digest string (128 characters)
    """
    if isinstance(data, str):
        data = data.encode()
    return hashlib.sha512(data).hexdigest()


def blake2b(data: bytes | str, digest_size: int = 64) -> str:
    """Hash data using BLAKE2b (modern fast cryptographic hash).

    BLAKE2b is faster than MD5, SHA-1, SHA-2, and SHA-3, while being at least
    as secure as SHA-3.

    Args:
        data: Data to hash (bytes or str)
        digest_size: Output digest size in bytes (default 64, max 64)

    Returns:
        Hex digest string

    Raises:
        ValueError: If digest_size is not 1-64
    """
    if isinstance(data, str):
        data = data.encode()

    if not 1 <= digest_size <= 64:
        raise ValueError(f"digest_size must be 1-64, got {digest_size}")

    return hashlib.blake2b(data, digest_size=digest_size).hexdigest()


def hmac_sha256(data: bytes | str, key: bytes) -> str:
    """Compute HMAC-SHA256.

    Args:
        data: Data to hash (bytes or str)
        key: HMAC key (bytes)

    Returns:
        Hex digest string (64 characters)
    """
    if isinstance(data, str):
        data = data.encode()
    return hmac.new(key, data, hashlib.sha256).hexdigest()


__all__ = [
    "sha256",
    "sha512",
    "blake2b",
    "hmac_sha256",
]
