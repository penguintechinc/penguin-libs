"""
Crypto module - Modern cryptographic primitives.

Provides:
- Symmetric encryption: AES-256-GCM
- Key derivation: Argon2id, HKDF
- Elliptic curve: X25519 (ECDH), Ed25519 (signatures)
- Hybrid encryption: X25519 + AES-256-GCM
- Hashing: SHA-256, SHA-512, BLAKE2b, HMAC-SHA256
"""

from .ecc import (  # type: ignore[import-untyped]
    ed25519_sign,
    ed25519_verify,
    generate_ed25519_keypair,
    generate_x25519_keypair,
    load_ed25519_public_key,
    load_x25519_public_key,
    serialize_private_key,
    serialize_public_key,
    x25519_exchange,
)
from .hashing import blake2b, hmac_sha256, sha256, sha512  # type: ignore[import-untyped]
from .hybrid import hybrid_decrypt, hybrid_encrypt  # type: ignore[import-untyped]
from .kdf import (  # type: ignore[import-untyped]
    derive_key,
    derive_key_argon2id,
    derive_key_hkdf,
    generate_salt,
)
from .symmetric import decrypt, encrypt, generate_key  # type: ignore[import-untyped]

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
