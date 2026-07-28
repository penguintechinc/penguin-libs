"""Tests for hybrid encryption (X25519 + AES-256-GCM)."""

import pytest
from cryptography.exceptions import InvalidTag

from penguin_crypto.hybrid import hybrid_encrypt, hybrid_decrypt
from penguin_crypto.ecc import generate_x25519_keypair


class TestHybridEncryption:
    """Tests for X25519 + AES-256-GCM hybrid encryption."""

    def test_hybrid_encrypt_decrypt_roundtrip(self) -> None:
        """Test hybrid encrypt/decrypt roundtrip."""
        _, recipient_public = generate_x25519_keypair()
        plaintext = b"Secret message"

        ciphertext = hybrid_encrypt(plaintext, recipient_public)
        # Should not succeed - need the private key

    def test_hybrid_encrypt_decrypt_complete(self) -> None:
        """Test complete hybrid encryption roundtrip."""
        recipient_private, recipient_public = generate_x25519_keypair()
        plaintext = b"Secret message"

        ciphertext = hybrid_encrypt(plaintext, recipient_public)
        decrypted = hybrid_decrypt(ciphertext, recipient_private)

        assert decrypted == plaintext

    def test_hybrid_encrypt_with_string_input(self) -> None:
        """Test hybrid encryption accepts string input."""
        recipient_private, recipient_public = generate_x25519_keypair()
        plaintext = "Secret message"

        ciphertext = hybrid_encrypt(plaintext, recipient_public)
        decrypted = hybrid_decrypt(ciphertext, recipient_private)

        assert decrypted == plaintext.encode()

    def test_hybrid_encrypt_empty_plaintext(self) -> None:
        """Test hybrid encryption with empty plaintext."""
        recipient_private, recipient_public = generate_x25519_keypair()
        plaintext = b""

        ciphertext = hybrid_encrypt(plaintext, recipient_public)
        decrypted = hybrid_decrypt(ciphertext, recipient_private)

        assert decrypted == plaintext

    def test_hybrid_encrypt_unicode_plaintext(self) -> None:
        """Test hybrid encryption with Unicode plaintext."""
        recipient_private, recipient_public = generate_x25519_keypair()
        plaintext = "こんにちは世界 🌍"

        ciphertext = hybrid_encrypt(plaintext, recipient_public)
        decrypted = hybrid_decrypt(ciphertext, recipient_private)

        assert decrypted == plaintext.encode()

    def test_hybrid_encrypt_large_plaintext(self) -> None:
        """Test hybrid encryption with large plaintext."""
        recipient_private, recipient_public = generate_x25519_keypair()
        plaintext = b"x" * (1024 * 1024)  # 1 MB

        ciphertext = hybrid_encrypt(plaintext, recipient_public)
        decrypted = hybrid_decrypt(ciphertext, recipient_private)

        assert decrypted == plaintext

    def test_hybrid_decrypt_wrong_private_key(self) -> None:
        """Test hybrid decryption with wrong private key fails."""
        _, recipient_public = generate_x25519_keypair()
        wrong_private, _ = generate_x25519_keypair()
        plaintext = b"Secret"

        ciphertext = hybrid_encrypt(plaintext, recipient_public)

        with pytest.raises(InvalidTag):
            hybrid_decrypt(ciphertext, wrong_private)

    def test_hybrid_decrypt_tampered_ciphertext(self) -> None:
        """Test hybrid decryption fails with tampered ciphertext."""
        recipient_private, recipient_public = generate_x25519_keypair()
        plaintext = b"Secret"

        ciphertext = hybrid_encrypt(plaintext, recipient_public)

        # Tamper with ciphertext (skip ephemeral pubkey at start)
        tampered = bytearray(ciphertext)
        tampered[50] ^= 0xFF
        tampered = bytes(tampered)

        with pytest.raises(InvalidTag):
            hybrid_decrypt(tampered, recipient_private)

    def test_hybrid_ciphertext_structure(self) -> None:
        """Test hybrid ciphertext structure."""
        _, recipient_public = generate_x25519_keypair()
        plaintext = b"test"

        ciphertext = hybrid_encrypt(plaintext, recipient_public)

        # Structure: ephemeral_pubkey (32) + nonce (12) + ciphertext + tag (16)
        # Minimum: 32 + 12 + 0 + 16 = 60 bytes
        assert len(ciphertext) >= 60

    def test_hybrid_nonce_is_random(self) -> None:
        """Test hybrid encryption uses random nonce each time."""
        _, recipient_public = generate_x25519_keypair()
        plaintext = b"same plaintext"

        ciphertext1 = hybrid_encrypt(plaintext, recipient_public)
        ciphertext2 = hybrid_encrypt(plaintext, recipient_public)

        # Ciphertexts should differ (different ephemeral keypairs + nonces)
        assert ciphertext1 != ciphertext2

    def test_hybrid_decrypt_wrong_format(self) -> None:
        """Test hybrid decryption fails with malformed ciphertext."""
        recipient_private, _ = generate_x25519_keypair()

        with pytest.raises(ValueError, match="Ciphertext too short"):
            hybrid_decrypt(b"short", recipient_private)

    def test_hybrid_different_recipients_different_secrets(self) -> None:
        """Test each recipient gets a different shared secret."""
        recipient1_private, recipient1_public = generate_x25519_keypair()
        recipient2_private, recipient2_public = generate_x25519_keypair()
        plaintext = b"message"

        # Encrypt with same plaintext for different recipients
        ciphertext1 = hybrid_encrypt(plaintext, recipient1_public)
        ciphertext2 = hybrid_encrypt(plaintext, recipient2_public)

        # Only the intended recipient can decrypt
        assert hybrid_decrypt(ciphertext1, recipient1_private) == plaintext
        with pytest.raises(InvalidTag):
            hybrid_decrypt(ciphertext1, recipient2_private)

        assert hybrid_decrypt(ciphertext2, recipient2_private) == plaintext
        with pytest.raises(InvalidTag):
            hybrid_decrypt(ciphertext2, recipient1_private)

    def test_hybrid_consistency(self) -> None:
        """Test multiple encryptions with same plaintext can be decrypted."""
        recipient_private, recipient_public = generate_x25519_keypair()
        plaintext = b"test message"

        for _ in range(5):
            ciphertext = hybrid_encrypt(plaintext, recipient_public)
            decrypted = hybrid_decrypt(ciphertext, recipient_private)
            assert decrypted == plaintext

    def test_hybrid_encrypt_with_bytes_plaintext(self) -> None:
        """Test hybrid encryption specifically with bytes input."""
        recipient_private, recipient_public = generate_x25519_keypair()
        plaintext = b"bytes plaintext"

        ciphertext = hybrid_encrypt(plaintext, recipient_public)
        decrypted = hybrid_decrypt(ciphertext, recipient_private)

        assert decrypted == plaintext
        assert isinstance(decrypted, bytes)
