"""Hybrid encryption (X25519 + AES-256-GCM)."""

from cryptography.hazmat.primitives.asymmetric.x25519 import (  # type: ignore[import-untyped]
    X25519PrivateKey,
    X25519PublicKey,
)
from cryptography.hazmat.primitives.ciphers.aead import AESGCM  # type: ignore[import-untyped]

from .ecc import generate_x25519_keypair, x25519_exchange
from .kdf import derive_key_hkdf


def hybrid_encrypt(plaintext: bytes | str, recipient_public_key: X25519PublicKey) -> bytes:
    """Encrypt using hybrid encryption (X25519 + AES-256-GCM).

    Process:
    1. Generate ephemeral X25519 keypair
    2. Perform ECDH with recipient's public key
    3. Derive AES-256-GCM key via HKDF-SHA256
    4. Encrypt plaintext with AES-256-GCM
    5. Return: ephemeral_pubkey (32B) + nonce (12B) + ciphertext + tag (16B)

    Args:
        plaintext: Data to encrypt (bytes or str)
        recipient_public_key: Recipient's X25519 public key

    Returns:
        Encrypted bundle: ephemeral_pubkey + nonce + ciphertext + tag
    """
    if isinstance(plaintext, str):
        plaintext = plaintext.encode()

    # Generate ephemeral keypair
    ephemeral_private, ephemeral_public = generate_x25519_keypair()

    # Perform ECDH
    shared_secret = x25519_exchange(ephemeral_private, recipient_public_key)

    # Derive AES key using HKDF
    aes_key = derive_key_hkdf(
        input_key_material=shared_secret,
        salt=None,
        info=b"penguin-hybrid-v1",
        length=32,
    )

    # Encrypt with AES-256-GCM
    import os

    nonce = os.urandom(12)
    cipher = AESGCM(aes_key)
    ciphertext = cipher.encrypt(nonce, plaintext, None)

    # Return ephemeral pubkey + encrypted data
    ephemeral_pubkey_bytes = ephemeral_public.public_bytes_raw()
    return ephemeral_pubkey_bytes + nonce + ciphertext


def hybrid_decrypt(ciphertext: bytes, recipient_private_key: X25519PrivateKey) -> bytes:
    """Decrypt using hybrid encryption (X25519 + AES-256-GCM).

    Process:
    1. Extract ephemeral public key (first 32 bytes)
    2. Perform ECDH with local private key
    3. Derive AES-256-GCM key via HKDF-SHA256 (same params as encrypt)
    4. Extract nonce (next 12 bytes) and encrypted data
    5. Decrypt with AES-256-GCM

    Args:
        ciphertext: Encrypted bundle from hybrid_encrypt
        recipient_private_key: Recipient's X25519 private key

    Returns:
        Decrypted plaintext bytes

    Raises:
        InvalidTag: If ciphertext is tampered
        ValueError: If ciphertext is malformed
    """
    if len(ciphertext) < 60:  # 32 (pubkey) + 12 (nonce) + 16 (tag minimum)
        raise ValueError("Ciphertext too short")

    # Extract ephemeral public key
    ephemeral_pubkey_bytes = ciphertext[:32]
    from .ecc import load_x25519_public_key

    ephemeral_public_key = load_x25519_public_key(ephemeral_pubkey_bytes)

    # Perform ECDH
    shared_secret = x25519_exchange(recipient_private_key, ephemeral_public_key)

    # Derive AES key (same as encryption)
    aes_key = derive_key_hkdf(
        input_key_material=shared_secret,
        salt=None,
        info=b"penguin-hybrid-v1",
        length=32,
    )

    # Extract nonce and encrypted data
    nonce = ciphertext[32:44]
    encrypted_data = ciphertext[44:]

    # Decrypt
    cipher = AESGCM(aes_key)
    plaintext = cipher.decrypt(nonce, encrypted_data, None)
    return plaintext


__all__ = [
    "hybrid_encrypt",
    "hybrid_decrypt",
]
