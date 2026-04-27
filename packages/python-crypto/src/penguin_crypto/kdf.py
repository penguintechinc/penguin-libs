"""Key derivation functions (Argon2id, HKDF)."""

import os
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from cryptography.hazmat.primitives import hashes
from argon2.low_level import hash_secret_raw, Type


def generate_salt(length: int = 32) -> bytes:
    """Generate a secure random salt.

    Args:
        length: Salt length in bytes (default 32)

    Returns:
        Secure random bytes of specified length
    """
    return os.urandom(length)


def derive_key_argon2id(
    password: str | bytes,
    salt: bytes,
    *,
    memory_cost: int = 65536,
    time_cost: int = 3,
    parallelism: int = 4,
    key_length: int = 32,
) -> bytes:
    """Derive a key using Argon2id (modern password hashing).

    Argon2id is recommended for password-based key derivation with
    resistance to GPU/ASIC attacks.

    Args:
        password: Password (str or bytes)
        salt: Random salt (should be 16+ bytes)
        memory_cost: Memory usage in KiB (default 65536 = 64MB, good for interactive use)
        time_cost: Number of iterations (default 3)
        parallelism: Parallelism factor (default 4)
        key_length: Desired key length in bytes (default 32)

    Returns:
        Derived key bytes

    Raises:
        ValueError: If salt is too short or parameters are invalid
    """
    if isinstance(password, str):
        password = password.encode()

    if len(salt) < 8:
        raise ValueError("Salt must be at least 8 bytes")

    if memory_cost < 8 or time_cost < 1 or parallelism < 1:
        raise ValueError("Invalid KDF parameters")

    derived = hash_secret_raw(
        secret=password,
        salt=salt,
        time_cost=time_cost,
        memory_cost=memory_cost,
        parallelism=parallelism,
        hash_len=key_length,
        type=Type.ID,
    )
    return derived


def derive_key_hkdf(
    input_key_material: bytes,
    salt: bytes | None,
    info: bytes,
    length: int = 32,
) -> bytes:
    """Derive a key using HKDF (HMAC-based key derivation function).

    HKDF is suitable for deriving keys from shared secrets (e.g., ECDH output).

    Args:
        input_key_material: Source key material (e.g., shared secret)
        salt: Optional salt (if None, a zero-filled salt is used)
        info: Context/application-specific info string
        length: Desired key length in bytes (default 32)

    Returns:
        Derived key bytes
    """
    if salt is None:
        salt = b"\x00" * 32

    hkdf = HKDF(
        algorithm=hashes.SHA256(),
        length=length,
        salt=salt,
        info=info,
    )
    return hkdf.derive(input_key_material)


# Backwards compatibility alias
derive_key = derive_key_argon2id

__all__ = [
    "generate_salt",
    "derive_key_argon2id",
    "derive_key_hkdf",
    "derive_key",
]
