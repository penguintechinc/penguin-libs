"""Tests for elliptic curve cryptography (X25519, Ed25519)."""

import pytest

from penguin_crypto.ecc import (
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


class TestX25519:
    """Tests for X25519 elliptic curve key exchange."""

    def test_generate_x25519_keypair(self) -> None:
        """Test X25519 keypair generation."""
        private_key, public_key = generate_x25519_keypair()
        assert private_key is not None
        assert public_key is not None

    def test_x25519_public_key_is_32_bytes(self) -> None:
        """Test X25519 public key is 32 bytes when serialized."""
        _, public_key = generate_x25519_keypair()
        raw = public_key.public_bytes_raw()
        assert len(raw) == 32

    def test_x25519_private_key_is_32_bytes(self) -> None:
        """Test X25519 private key is 32 bytes when serialized."""
        private_key, _ = generate_x25519_keypair()
        raw = private_key.private_bytes_raw()
        assert len(raw) == 32

    def test_x25519_exchange_identical_secret(self) -> None:
        """Test X25519 exchange produces identical shared secret both ways."""
        private_key_a, public_key_a = generate_x25519_keypair()
        private_key_b, public_key_b = generate_x25519_keypair()

        secret_a = x25519_exchange(private_key_a, public_key_b)
        secret_b = x25519_exchange(private_key_b, public_key_a)

        assert secret_a == secret_b
        assert len(secret_a) == 32

    def test_x25519_exchange_different_keypairs_different_secrets(self) -> None:
        """Test different keypairs produce different shared secrets."""
        _, pub_b = generate_x25519_keypair()
        _, pub_c = generate_x25519_keypair()
        priv_a, _ = generate_x25519_keypair()

        secret1 = x25519_exchange(priv_a, pub_b)
        secret2 = x25519_exchange(priv_a, pub_c)

        assert secret1 != secret2

    def test_x25519_serialize_public_key(self) -> None:
        """Test X25519 public key serialization."""
        _, public_key = generate_x25519_keypair()
        raw = serialize_public_key(public_key)
        assert len(raw) == 32
        assert isinstance(raw, bytes)

    def test_x25519_serialize_private_key(self) -> None:
        """Test X25519 private key serialization."""
        private_key, _ = generate_x25519_keypair()
        raw = serialize_private_key(private_key)
        assert len(raw) == 32
        assert isinstance(raw, bytes)

    def test_x25519_load_public_key(self) -> None:
        """Test loading X25519 public key from raw bytes."""
        _, original_public = generate_x25519_keypair()
        raw = serialize_public_key(original_public)
        loaded_public = load_x25519_public_key(raw)
        assert serialize_public_key(loaded_public) == raw

    def test_x25519_load_public_key_wrong_length(self) -> None:
        """Test loading X25519 public key with wrong length fails."""
        with pytest.raises(ValueError, match="X25519 public key must be 32 bytes"):
            load_x25519_public_key(b"short")

    def test_x25519_keypair_roundtrip(self) -> None:
        """Test X25519 keypair serialization roundtrip."""
        private_a, public_a = generate_x25519_keypair()
        private_b, public_b = generate_x25519_keypair()

        secret1 = x25519_exchange(private_a, public_b)

        # Serialize and load public key B
        pub_b_raw = serialize_public_key(public_b)
        loaded_pub_b = load_x25519_public_key(pub_b_raw)

        secret2 = x25519_exchange(private_a, loaded_pub_b)
        assert secret1 == secret2


class TestEd25519:
    """Tests for Ed25519 digital signatures."""

    def test_generate_ed25519_keypair(self) -> None:
        """Test Ed25519 keypair generation."""
        private_key, public_key = generate_ed25519_keypair()
        assert private_key is not None
        assert public_key is not None

    def test_ed25519_public_key_is_32_bytes(self) -> None:
        """Test Ed25519 public key is 32 bytes when serialized."""
        _, public_key = generate_ed25519_keypair()
        raw = public_key.public_bytes_raw()
        assert len(raw) == 32

    def test_ed25519_private_key_is_32_bytes(self) -> None:
        """Test Ed25519 private key is 32 bytes when serialized."""
        private_key, _ = generate_ed25519_keypair()
        raw = private_key.private_bytes_raw()
        assert len(raw) == 32

    def test_ed25519_sign_and_verify(self) -> None:
        """Test Ed25519 signature and verification."""
        private_key, public_key = generate_ed25519_keypair()
        message = b"Hello, World!"

        signature = ed25519_sign(private_key, message)
        assert len(signature) == 64
        assert isinstance(signature, bytes)

        is_valid = ed25519_verify(public_key, message, signature)
        assert is_valid is True

    def test_ed25519_verify_wrong_message(self) -> None:
        """Test Ed25519 verification fails with wrong message."""
        private_key, public_key = generate_ed25519_keypair()
        message = b"original message"
        signature = ed25519_sign(private_key, message)

        is_valid = ed25519_verify(public_key, b"different message", signature)
        assert is_valid is False

    def test_ed25519_verify_wrong_key(self) -> None:
        """Test Ed25519 verification fails with wrong key."""
        private_key1, public_key1 = generate_ed25519_keypair()
        _, public_key2 = generate_ed25519_keypair()
        message = b"message"
        signature = ed25519_sign(private_key1, message)

        is_valid = ed25519_verify(public_key2, message, signature)
        assert is_valid is False

    def test_ed25519_verify_tampered_signature(self) -> None:
        """Test Ed25519 verification fails with tampered signature."""
        private_key, public_key = generate_ed25519_keypair()
        message = b"message"
        signature = ed25519_sign(private_key, message)

        # Tamper with signature
        tampered = bytearray(signature)
        tampered[0] ^= 0xFF
        tampered = bytes(tampered)

        is_valid = ed25519_verify(public_key, message, tampered)
        assert is_valid is False

    def test_ed25519_sign_deterministic(self) -> None:
        """Test Ed25519 signatures are deterministic."""
        private_key, _ = generate_ed25519_keypair()
        message = b"test message"

        sig1 = ed25519_sign(private_key, message)
        sig2 = ed25519_sign(private_key, message)

        assert sig1 == sig2

    def test_ed25519_serialize_public_key(self) -> None:
        """Test Ed25519 public key serialization."""
        _, public_key = generate_ed25519_keypair()
        raw = serialize_public_key(public_key)
        assert len(raw) == 32
        assert isinstance(raw, bytes)

    def test_ed25519_serialize_private_key(self) -> None:
        """Test Ed25519 private key serialization."""
        private_key, _ = generate_ed25519_keypair()
        raw = serialize_private_key(private_key)
        assert len(raw) == 32
        assert isinstance(raw, bytes)

    def test_ed25519_load_public_key(self) -> None:
        """Test loading Ed25519 public key from raw bytes."""
        _, original_public = generate_ed25519_keypair()
        raw = serialize_public_key(original_public)
        loaded_public = load_ed25519_public_key(raw)
        assert serialize_public_key(loaded_public) == raw

    def test_ed25519_load_public_key_wrong_length(self) -> None:
        """Test loading Ed25519 public key with wrong length fails."""
        with pytest.raises(ValueError, match="Ed25519 public key must be 32 bytes"):
            load_ed25519_public_key(b"short")

    def test_ed25519_keypair_roundtrip(self) -> None:
        """Test Ed25519 keypair serialization roundtrip."""
        private_key, public_key = generate_ed25519_keypair()
        message = b"test message"

        sig1 = ed25519_sign(private_key, message)

        # Serialize and load public key
        pub_raw = serialize_public_key(public_key)
        loaded_pub = load_ed25519_public_key(pub_raw)

        is_valid = ed25519_verify(loaded_pub, message, sig1)
        assert is_valid is True

    def test_ed25519_verify_never_raises_on_bad_sig(self) -> None:
        """Test Ed25519 verify returns False instead of raising on bad signature."""
        private_key, public_key = generate_ed25519_keypair()
        message = b"message"
        signature = ed25519_sign(private_key, message)

        # Verify should return False, not raise
        result = ed25519_verify(public_key, b"wrong", signature)
        assert result is False
        assert isinstance(result, bool)

    def test_ed25519_sign_empty_message(self) -> None:
        """Test Ed25519 can sign empty message."""
        private_key, public_key = generate_ed25519_keypair()
        message = b""

        signature = ed25519_sign(private_key, message)
        is_valid = ed25519_verify(public_key, message, signature)
        assert is_valid is True


class TestKeySerializationErrors:
    """Tests for key serialization error handling."""

    def test_serialize_public_key_invalid_type(self) -> None:
        """Test serialize_public_key rejects invalid key type."""
        with pytest.raises(TypeError, match="Unsupported key type"):
            serialize_public_key("invalid_key")  # type: ignore

    def test_serialize_private_key_invalid_type(self) -> None:
        """Test serialize_private_key rejects invalid key type."""
        with pytest.raises(TypeError, match="Unsupported key type"):
            serialize_private_key("invalid_key")  # type: ignore
