"""Elliptic curve cryptography (X25519, Ed25519)."""

from cryptography.exceptions import InvalidSignature  # type: ignore[import-untyped]
from cryptography.hazmat.primitives.asymmetric.ed25519 import (  # type: ignore[import-untyped]
    Ed25519PrivateKey,
    Ed25519PublicKey,
)
from cryptography.hazmat.primitives.asymmetric.x25519 import (  # type: ignore[import-untyped]
    X25519PrivateKey,
    X25519PublicKey,
)


def generate_x25519_keypair() -> tuple[X25519PrivateKey, X25519PublicKey]:
    """Generate an X25519 key exchange keypair.

    X25519 is used for Elliptic Curve Diffie-Hellman key exchange.

    Returns:
        Tuple of (private_key, public_key)
    """
    private_key = X25519PrivateKey.generate()
    public_key = private_key.public_key()
    return private_key, public_key


def x25519_exchange(
    private_key: X25519PrivateKey,
    peer_public_key: X25519PublicKey,
) -> bytes:
    """Perform X25519 key exchange (ECDH).

    Args:
        private_key: Local X25519 private key
        peer_public_key: Peer's X25519 public key

    Returns:
        32-byte shared secret
    """
    return private_key.exchange(peer_public_key)


def generate_ed25519_keypair() -> tuple[Ed25519PrivateKey, Ed25519PublicKey]:
    """Generate an Ed25519 signing keypair.

    Ed25519 is used for digital signatures (EdDSA).

    Returns:
        Tuple of (private_key, public_key)
    """
    private_key = Ed25519PrivateKey.generate()
    public_key = private_key.public_key()
    return private_key, public_key


def ed25519_sign(private_key: Ed25519PrivateKey, message: bytes) -> bytes:
    """Sign a message with Ed25519.

    Args:
        private_key: Ed25519 private key
        message: Message to sign (bytes)

    Returns:
        64-byte signature
    """
    return private_key.sign(message)


def ed25519_verify(
    public_key: Ed25519PublicKey,
    message: bytes,
    signature: bytes,
) -> bool:
    """Verify an Ed25519 signature.

    Args:
        public_key: Ed25519 public key
        message: Original message (bytes)
        signature: Signature bytes

    Returns:
        True if signature is valid, False otherwise (never raises on bad sig)
    """
    try:
        public_key.verify(signature, message)
        return True
    except InvalidSignature:
        return False


def serialize_public_key(key: X25519PublicKey | Ed25519PublicKey) -> bytes:
    """Serialize a public key to raw 32-byte format.

    Args:
        key: X25519PublicKey or Ed25519PublicKey

    Returns:
        32-byte raw key encoding
    """
    if isinstance(key, X25519PublicKey):
        return key.public_bytes_raw()
    elif isinstance(key, Ed25519PublicKey):
        return key.public_bytes_raw()
    else:
        raise TypeError(f"Unsupported key type: {type(key)}")


def serialize_private_key(key: X25519PrivateKey | Ed25519PrivateKey) -> bytes:
    """Serialize a private key to raw 32-byte format.

    Args:
        key: X25519PrivateKey or Ed25519PrivateKey

    Returns:
        32-byte raw key encoding
    """
    if isinstance(key, X25519PrivateKey):
        return key.private_bytes_raw()
    elif isinstance(key, Ed25519PrivateKey):
        return key.private_bytes_raw()
    else:
        raise TypeError(f"Unsupported key type: {type(key)}")


def load_x25519_public_key(raw: bytes) -> X25519PublicKey:
    """Load an X25519 public key from raw 32-byte format.

    Args:
        raw: 32-byte raw key bytes

    Returns:
        X25519PublicKey

    Raises:
        ValueError: If raw bytes are not 32 bytes
    """
    if len(raw) != 32:
        raise ValueError(f"X25519 public key must be 32 bytes, got {len(raw)}")
    return X25519PublicKey.from_public_bytes(raw)


def load_ed25519_public_key(raw: bytes) -> Ed25519PublicKey:
    """Load an Ed25519 public key from raw 32-byte format.

    Args:
        raw: 32-byte raw key bytes

    Returns:
        Ed25519PublicKey

    Raises:
        ValueError: If raw bytes are not 32 bytes
    """
    if len(raw) != 32:
        raise ValueError(f"Ed25519 public key must be 32 bytes, got {len(raw)}")
    return Ed25519PublicKey.from_public_bytes(raw)


__all__ = [
    "generate_x25519_keypair",
    "x25519_exchange",
    "generate_ed25519_keypair",
    "ed25519_sign",
    "ed25519_verify",
    "serialize_public_key",
    "serialize_private_key",
    "load_x25519_public_key",
    "load_ed25519_public_key",
]
