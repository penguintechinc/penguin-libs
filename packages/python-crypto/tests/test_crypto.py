"""Comprehensive tests for penguin-crypto module.

Tests for:
- encrypt/decrypt roundtrip
- key derivation
- hashing utilities
- tamper detection (authenticated encryption)
"""

import pytest

from penguin_crypto import (
    decrypt,
    derive_key,
    encrypt,
    generate_key,
    generate_salt,
    hmac_sha256,
    sha256,
    sha512,
)


class TestCryptoModule:
    """Tests for penguin-crypto module."""

    def test_module_exists(self) -> None:
        """Test that penguin_crypto module can be imported."""
        import penguin_crypto

        assert penguin_crypto is not None
        assert isinstance(penguin_crypto.__all__, list)

    def test_module_docstring(self) -> None:
        """Test module has documentation."""
        import penguin_crypto

        assert penguin_crypto.__doc__ is not None
        assert "Crypto" in penguin_crypto.__doc__


class TestEncryption:
    """Tests for encryption utilities."""

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

        with pytest.raises(Exception):  # cryptography.hazmat.primitives.ciphers.aead.InvalidTag
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

        with pytest.raises(Exception):  # cryptography.hazmat.primitives.ciphers.aead.InvalidTag
            decrypt(tampered, key)


class TestKeyDerivation:
    """Tests for key derivation utilities."""

    def test_key_derivation_deterministic(self) -> None:
        """Test key derivation is deterministic for same inputs."""
        password = "my_password"
        salt = generate_salt(32)
        key1 = derive_key(password, salt)
        key2 = derive_key(password, salt)
        assert key1 == key2

    def test_key_derivation_different_password(self) -> None:
        """Test key derivation differs for different passwords."""
        salt = generate_salt(32)
        key1 = derive_key("password1", salt)
        key2 = derive_key("password2", salt)
        assert key1 != key2

    def test_key_derivation_different_salt(self) -> None:
        """Test key derivation differs for different salts."""
        password = "my_password"
        key1 = derive_key(password, generate_salt(32))
        key2 = derive_key(password, generate_salt(32))
        assert key1 != key2

    def test_key_derivation_length(self) -> None:
        """Test derived key has correct length."""
        password = "my_password"
        salt = generate_salt(32)
        for length in [16, 32, 64]:
            key = derive_key(password, salt, key_length=length)
            assert len(key) == length

    def test_key_derivation_bytes_password(self) -> None:
        """Test key derivation accepts bytes password."""
        password_str = "my_password"
        password_bytes = b"my_password"
        salt = generate_salt(32)
        key1 = derive_key(password_str, salt)
        key2 = derive_key(password_bytes, salt)
        assert key1 == key2


class TestHashing:
    """Tests for hashing utilities."""

    def test_sha256_known_vector(self) -> None:
        """Test SHA-256 against known test vector."""
        # SHA256("") = e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855
        result = sha256(b"")
        assert result == "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"

    def test_sha256_deterministic(self) -> None:
        """Test SHA-256 is deterministic."""
        data = b"test data"
        hash1 = sha256(data)
        hash2 = sha256(data)
        assert hash1 == hash2

    def test_sha256_different_inputs(self) -> None:
        """Test different inputs produce different SHA-256 hashes."""
        hash1 = sha256(b"data1")
        hash2 = sha256(b"data2")
        assert hash1 != hash2

    def test_sha256_unicode(self) -> None:
        """Test SHA-256 with Unicode strings."""
        result = sha256("hello")
        # Verify it's a valid hex string
        assert len(result) == 64
        assert all(c in "0123456789abcdef" for c in result)

    def test_sha256_empty_input(self) -> None:
        """Test SHA-256 with empty string."""
        result = sha256("")
        assert result == "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"

    def test_sha512_known_vector(self) -> None:
        """Test SHA-512 against known test vector."""
        # SHA512("") = cf83e1357eefb8bdf1542850d66d8007d620e4050b5715dc83f4a921d36ce9ce47d0d13c5d85f2b0ff8318d2877eec2f63b931bd47417a81a538327af927da3e
        result = sha512(b"")
        assert (
            result
            == "cf83e1357eefb8bdf1542850d66d8007d620e4050b5715dc83f4a921d36ce9ce47d0d13c5d85f2b0ff8318d2877eec2f63b931bd47417a81a538327af927da3e"
        )

    def test_sha512_deterministic(self) -> None:
        """Test SHA-512 is deterministic."""
        data = b"test data"
        hash1 = sha512(data)
        hash2 = sha512(data)
        assert hash1 == hash2

    def test_sha512_different_inputs(self) -> None:
        """Test different inputs produce different SHA-512 hashes."""
        hash1 = sha512(b"data1")
        hash2 = sha512(b"data2")
        assert hash1 != hash2

    def test_hmac_sha256_known_vector(self) -> None:
        """Test HMAC-SHA256 against known test vector."""
        key = b"key"
        data = b"The quick brown fox jumps over the lazy dog"
        result = hmac_sha256(data, key)
        # HMAC-SHA256(key, data)
        assert result == "f7bc83f430538424b13298e6aa6fb143ef4d59a14946175997479dbc2d1a3cd8"

    def test_hmac_sha256_deterministic(self) -> None:
        """Test HMAC-SHA256 is deterministic."""
        key = generate_key(32)
        data = b"test data"
        hmac1 = hmac_sha256(data, key)
        hmac2 = hmac_sha256(data, key)
        assert hmac1 == hmac2

    def test_hmac_sha256_string_input(self) -> None:
        """Test HMAC-SHA256 with string input."""
        key = b"secret"
        data = "message"
        result = hmac_sha256(data, key)
        assert len(result) == 64
        assert all(c in "0123456789abcdef" for c in result)


class TestTokenGeneration:
    """Tests for secure token generation."""

    def test_generate_key_randomness(self) -> None:
        """Test generated keys are random."""
        key1 = generate_key(32)
        key2 = generate_key(32)
        assert key1 != key2

    def test_generate_key_length(self) -> None:
        """Test generated keys have expected length."""
        for length in [16, 24, 32, 64]:
            key = generate_key(length)
            assert len(key) == length

    def test_generate_salt_randomness(self) -> None:
        """Test generated salts are random."""
        salt1 = generate_salt(32)
        salt2 = generate_salt(32)
        assert salt1 != salt2

    def test_generate_salt_length(self) -> None:
        """Test generated salts have expected length."""
        for length in [16, 24, 32, 64]:
            salt = generate_salt(length)
            assert len(salt) == length

    def test_generate_key_default_length(self) -> None:
        """Test generated key has default length 32."""
        key = generate_key()
        assert len(key) == 32

    def test_generate_salt_default_length(self) -> None:
        """Test generated salt has default length 32."""
        salt = generate_salt()
        assert len(salt) == 32


class TestAuthenticatedEncryption:
    """Tests for authenticated encryption."""

    def test_authenticated_encrypt_decrypt(self) -> None:
        """Test authenticated encryption roundtrip."""
        key = generate_key(32)
        plaintext = b"sensitive data"
        ciphertext = encrypt(plaintext, key)
        decrypted = decrypt(ciphertext, key)
        assert decrypted == plaintext

    def test_ciphertext_tamper_detection(self) -> None:
        """Test that ciphertext tampering is detected."""
        key = generate_key(32)
        plaintext = b"sensitive data"
        ciphertext = encrypt(plaintext, key)

        # Tamper with authentication tag (last 16 bytes)
        tampered = bytearray(ciphertext)
        tampered[-1] ^= 0xFF
        tampered = bytes(tampered)

        with pytest.raises(Exception):  # InvalidTag
            decrypt(tampered, key)

    def test_tag_verification(self) -> None:
        """Test authentication tag is verified."""
        key = generate_key(32)
        plaintext = b"test"
        ciphertext = encrypt(plaintext, key)

        # Tamper anywhere in the ciphertext
        tampered = bytearray(ciphertext)
        tampered[20] ^= 0x01
        tampered = bytes(tampered)

        with pytest.raises(Exception):  # InvalidTag
            decrypt(tampered, key)

    def test_aead_different_keys_fail(self) -> None:
        """Test AEAD with different key fails."""
        key1 = generate_key(32)
        key2 = generate_key(32)
        plaintext = b"authenticated data"
        ciphertext = encrypt(plaintext, key1)

        with pytest.raises(Exception):  # InvalidTag
            decrypt(ciphertext, key2)
