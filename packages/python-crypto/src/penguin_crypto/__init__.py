"""Crypto module - Modern cryptographic primitives for PenguinTech applications.

Provides:
- Symmetric encryption: AES-256-GCM
- Key derivation: Argon2id, HKDF
- Elliptic curve: X25519 (ECDH), Ed25519 (signatures)
- Hybrid encryption: X25519 + AES-256-GCM
- Hashing: SHA-256, SHA-512, BLAKE2b, HMAC-SHA256
- Envelope encryption (`penguin_crypto.envelope`): versioned AES-256-GCM
  field encryption, KMS DEK wrap/unwrap providers, a bounded/epoch-checked
  DEK cache, and HKDF blind-index helpers for per-tenant field encryption.
"""

from . import envelope
from .ecc import (
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
from .hashing import blake2b, hmac_sha256, sha256, sha512
from .hybrid import hybrid_decrypt, hybrid_encrypt
from .kdf import (
    derive_key,
    derive_key_argon2id,
    derive_key_hkdf,
    generate_salt,
)
from .symmetric import decrypt, encrypt, generate_key

__all__ = [
    "envelope",
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
