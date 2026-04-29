"""
Crypto module - Modern cryptographic primitives.

Provides:
- Symmetric encryption: AES-256-GCM
- Key derivation: Argon2id, HKDF
- Elliptic curve: X25519 (ECDH), Ed25519 (signatures)
- Hybrid encryption: X25519 + AES-256-GCM
- Hashing: SHA-256, SHA-512, BLAKE2b, HMAC-SHA256
"""

# Symmetric encryption
from .symmetric import encrypt, decrypt, generate_key  # type: ignore[import-untyped]

# Key derivation functions
from .kdf import generate_salt, derive_key, derive_key_argon2id, derive_key_hkdf  # type: ignore[import-untyped]

# Elliptic curve cryptography
from .ecc import (  # type: ignore[import-untyped]
    generate_x25519_keypair,
    x25519_exchange,
    generate_ed25519_keypair,
    ed25519_sign,
    ed25519_verify,
    serialize_public_key,
    serialize_private_key,
    load_x25519_public_key,
    load_ed25519_public_key,
)

# Hybrid encryption
from .hybrid import hybrid_encrypt, hybrid_decrypt  # type: ignore[import-untyped]

# Hashing
from .hashing import sha256, sha512, blake2b, hmac_sha256  # type: ignore[import-untyped]

__all__ = [
    # Symmetric
    "encrypt",
    "decrypt",
    "generate_key",
    # KDF
    "generate_salt",
    "derive_key",
    "derive_key_argon2id",
    "derive_key_hkdf",
    # ECC
    "generate_x25519_keypair",
    "x25519_exchange",
    "generate_ed25519_keypair",
    "ed25519_sign",
    "ed25519_verify",
    "serialize_public_key",
    "serialize_private_key",
    "load_x25519_public_key",
    "load_ed25519_public_key",
    # Hybrid
    "hybrid_encrypt",
    "hybrid_decrypt",
    # Hashing
    "sha256",
    "sha512",
    "blake2b",
    "hmac_sha256",
]
