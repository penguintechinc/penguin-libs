"""Tests for symmetric encryption (AES-256-GCM)."""

import pytest
from cryptography.exceptions import InvalidTag

from penguin_crypto.symmetric import encrypt, decrypt, generate_key


class TestSymmetricEncryption:
    """Tests for AES-256-GCM symmetric encryption."""

    def test_encrypt_decrypt_roundtrip(self) -> None:
        """Test encrypt/decrypt roundtrip with valid plaintext."""
        key = generate_key(32)
        plaintext = b"Hello, World!"
        ciphertext = encrypt(plaintext, key)
        decrypted = decrypt(ciphertext, key)
        assert decrypted == plaintext

    def test_encrypt_decrypt_empty_plaintext(self) -> None:
        """Test encryption with empty plaintext."""
        key = generate_key(32)
        plaintext = b""
        ciphertext = encrypt(plaintext, key)
        decrypted = decrypt(ciphertext, key)
        assert decrypted == plaintext

    def test_encrypt_decrypt_one_byte(self) -> None:
        """Test encryption with single byte."""
        key = generate_key(32)
        plaintext = b"a"
        ciphertext = encrypt(plaintext, key)
        decrypted = decrypt(ciphertext, key)
        assert decrypted == plaintext

    def test_encrypt_decrypt_1kb(self) -> None:
        """Test encryption with 1 KB plaintext."""
        key = generate_key(32)
        plaintext = b"x" * 1024
        ciphertext = encrypt(plaintext, key)
        decrypted = decrypt(ciphertext, key)
        assert decrypted == plaintext

    def test_encrypt_decrypt_64kb(self) -> None:
        """Test encryption with 64 KB plaintext."""
        key = generate_key(32)
        plaintext = b"y" * (64 * 1024)
        ciphertext = encrypt(plaintext, key)
        decrypted = decrypt(ciphertext, key)
        assert decrypted == plaintext

    def test_encrypt_unicode_plaintext(self) -> None:
        """Test encryption with Unicode plaintext."""
        key = generate_key(32)
        plaintext = "こんにちは世界 🌍"  # Hello World in Japanese with emoji
        ciphertext = encrypt(plaintext, key)
        decrypted = decrypt(ciphertext, key)
        assert decrypted == plaintext.encode()

    def test_encrypt_with_string_input(self) -> None:
        """Test encryption accepts string input."""
        key = generate_key(32)
        plaintext = "test string"
        ciphertext = encrypt(plaintext, key)
        decrypted = decrypt(ciphertext, key)
        assert decrypted == plaintext.encode()

    def test_decrypt_with_wrong_key(self) -> None:
        """Test decryption with wrong key fails."""
        key1 = generate_key(32)
        key2 = generate_key(32)
        plaintext = b"secret data"
        ciphertext = encrypt(plaintext, key1)

        with pytest.raises(InvalidTag):
            decrypt(ciphertext, key2)

    def test_decrypt_tampered_ciphertext(self) -> None:
        """Test decryption with tampered ciphertext fails."""
        key = generate_key(32)
        plaintext = b"secret data"
        ciphertext = encrypt(plaintext, key)

        # Tamper with ciphertext
        tampered = bytearray(ciphertext)
        tampered[15] ^= 0xFF  # Flip bits in the middle
        tampered = bytes(tampered)

        with pytest.raises(InvalidTag):
            decrypt(tampered, key)

    def test_encrypt_wrong_key_length(self) -> None:
        """Test encryption with wrong key length fails."""
        key = b"short"
        plaintext = b"data"

        with pytest.raises(ValueError, match="Key must be 32 bytes"):
            encrypt(plaintext, key)

    def test_decrypt_wrong_key_length(self) -> None:
        """Test decryption with wrong key length fails."""
        key = b"short"
        ciphertext = b"data"

        with pytest.raises(ValueError, match="Key must be 32 bytes"):
            decrypt(ciphertext, key)

    def test_decrypt_too_short_ciphertext(self) -> None:
        """Test decryption with ciphertext too short fails."""
        key = generate_key(32)
        ciphertext = b"short"

        with pytest.raises(ValueError, match="Ciphertext too short"):
            decrypt(ciphertext, key)

    def test_ciphertext_contains_nonce(self) -> None:
        """Test ciphertext contains 12-byte nonce prefix."""
        key = generate_key(32)
        plaintext = b"test"
        ciphertext = encrypt(plaintext, key)

        # Ciphertext should be at least 12 (nonce) + 4 (plaintext) + 16 (tag) = 32 bytes
        assert len(ciphertext) >= 32

    def test_nonce_is_random(self) -> None:
        """Test that each encryption uses a different nonce."""
        key = generate_key(32)
        plaintext = b"same plaintext"
        ciphertext1 = encrypt(plaintext, key)
        ciphertext2 = encrypt(plaintext, key)

        # Ciphertexts should differ (different nonces)
        assert ciphertext1 != ciphertext2

        # But both should decrypt to same plaintext
        assert decrypt(ciphertext1, key) == plaintext
        assert decrypt(ciphertext2, key) == plaintext

    def test_decrypt_tampered_tag(self) -> None:
        """Test decryption fails with tampered authentication tag."""
        key = generate_key(32)
        plaintext = b"test"
        ciphertext = encrypt(plaintext, key)

        # Tamper with authentication tag (last 16 bytes)
        tampered = bytearray(ciphertext)
        tampered[-1] ^= 0xFF
        tampered = bytes(tampered)

        with pytest.raises(InvalidTag):
            decrypt(tampered, key)
