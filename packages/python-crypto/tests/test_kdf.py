"""Tests for key derivation functions (Argon2id, HKDF)."""

import pytest

from penguin_crypto.kdf import (
    generate_salt,
    derive_key_argon2id,
    derive_key_hkdf,
    derive_key,
)


class TestSaltGeneration:
    """Tests for secure salt generation."""

    def test_generate_salt_correct_length(self) -> None:
        """Test generated salt has correct length."""
        salt = generate_salt(32)
        assert len(salt) == 32

    def test_generate_salt_custom_length(self) -> None:
        """Test salt generation with custom length."""
        for length in [16, 24, 32, 64]:
            salt = generate_salt(length)
            assert len(salt) == length

    def test_generate_salt_randomness(self) -> None:
        """Test that generated salts are random."""
        salt1 = generate_salt(32)
        salt2 = generate_salt(32)
        assert salt1 != salt2

    def test_generate_salt_default_length(self) -> None:
        """Test generated salt has default length 32."""
        salt = generate_salt()
        assert len(salt) == 32


class TestArgon2id:
    """Tests for Argon2id key derivation."""

    def test_argon2id_deterministic(self) -> None:
        """Test Argon2id is deterministic for same inputs."""
        password = "my_password"
        salt = generate_salt(32)
        key1 = derive_key_argon2id(password, salt)
        key2 = derive_key_argon2id(password, salt)
        assert key1 == key2

    def test_argon2id_different_password(self) -> None:
        """Test Argon2id differs for different passwords."""
        salt = generate_salt(32)
        key1 = derive_key_argon2id("password1", salt)
        key2 = derive_key_argon2id("password2", salt)
        assert key1 != key2

    def test_argon2id_different_salt(self) -> None:
        """Test Argon2id differs for different salts."""
        password = "my_password"
        key1 = derive_key_argon2id(password, generate_salt(32))
        key2 = derive_key_argon2id(password, generate_salt(32))
        assert key1 != key2

    def test_argon2id_key_length(self) -> None:
        """Test Argon2id derived key has correct length."""
        password = "my_password"
        salt = generate_salt(32)
        for length in [16, 32, 64]:
            key = derive_key_argon2id(password, salt, key_length=length)
            assert len(key) == length

    def test_argon2id_bytes_password(self) -> None:
        """Test Argon2id accepts bytes password."""
        password_str = "my_password"
        password_bytes = b"my_password"
        salt = generate_salt(32)
        key1 = derive_key_argon2id(password_str, salt)
        key2 = derive_key_argon2id(password_bytes, salt)
        assert key1 == key2

    def test_argon2id_short_salt_fails(self) -> None:
        """Test Argon2id fails with salt < 8 bytes."""
        password = "password"
        salt = b"short"

        with pytest.raises(ValueError, match="Salt must be at least 8 bytes"):
            derive_key_argon2id(password, salt)

    def test_argon2id_custom_parameters(self) -> None:
        """Test Argon2id with custom parameters."""
        password = "password"
        salt = generate_salt(32)
        key = derive_key_argon2id(
            password,
            salt,
            memory_cost=32768,
            time_cost=2,
            parallelism=2,
            key_length=32,
        )
        assert len(key) == 32

    def test_argon2id_invalid_parameters(self) -> None:
        """Test Argon2id rejects invalid parameters."""
        password = "password"
        salt = generate_salt(32)

        with pytest.raises(ValueError, match="Invalid KDF parameters"):
            derive_key_argon2id(password, salt, memory_cost=0)

        with pytest.raises(ValueError, match="Invalid KDF parameters"):
            derive_key_argon2id(password, salt, time_cost=0)

        with pytest.raises(ValueError, match="Invalid KDF parameters"):
            derive_key_argon2id(password, salt, parallelism=0)


class TestHKDF:
    """Tests for HKDF key derivation."""

    def test_hkdf_deterministic(self) -> None:
        """Test HKDF is deterministic for same inputs."""
        ikm = b"shared_secret_from_ecdh"
        salt = b"salt_value_123"
        info = b"application_context"
        key1 = derive_key_hkdf(ikm, salt, info)
        key2 = derive_key_hkdf(ikm, salt, info)
        assert key1 == key2

    def test_hkdf_different_ikm(self) -> None:
        """Test HKDF differs for different input key material."""
        salt = b"salt_value"
        info = b"info"
        key1 = derive_key_hkdf(b"ikm1", salt, info)
        key2 = derive_key_hkdf(b"ikm2", salt, info)
        assert key1 != key2

    def test_hkdf_different_salt(self) -> None:
        """Test HKDF differs for different salt."""
        ikm = b"ikm"
        info = b"info"
        key1 = derive_key_hkdf(ikm, b"salt1", info)
        key2 = derive_key_hkdf(ikm, b"salt2", info)
        assert key1 != key2

    def test_hkdf_different_info(self) -> None:
        """Test HKDF differs for different info."""
        ikm = b"ikm"
        salt = b"salt"
        key1 = derive_key_hkdf(ikm, salt, b"info1")
        key2 = derive_key_hkdf(ikm, salt, b"info2")
        assert key1 != key2

    def test_hkdf_none_salt(self) -> None:
        """Test HKDF with None salt uses zero-filled salt."""
        ikm = b"ikm"
        info = b"info"
        key1 = derive_key_hkdf(ikm, None, info)
        key2 = derive_key_hkdf(ikm, None, info)
        assert key1 == key2
        assert len(key1) == 32

    def test_hkdf_custom_length(self) -> None:
        """Test HKDF with custom output length."""
        ikm = b"ikm"
        salt = b"salt"
        info = b"info"
        for length in [16, 32, 64]:
            key = derive_key_hkdf(ikm, salt, info, length=length)
            assert len(key) == length

    def test_hkdf_default_length(self) -> None:
        """Test HKDF default output length is 32."""
        key = derive_key_hkdf(b"ikm", b"salt", b"info")
        assert len(key) == 32


class TestBackwardsCompatibilityAlias:
    """Tests for backwards compatibility alias."""

    def test_derive_key_alias_is_argon2id(self) -> None:
        """Test derive_key is alias for derive_key_argon2id."""
        password = "password"
        salt = generate_salt(32)
        key1 = derive_key(password, salt)
        key2 = derive_key_argon2id(password, salt)
        assert key1 == key2

    def test_derive_key_alias_works(self) -> None:
        """Test derive_key alias works as expected."""
        password = "test_password"
        salt = generate_salt(32)
        key = derive_key(password, salt)
        assert len(key) == 32
        assert isinstance(key, bytes)
