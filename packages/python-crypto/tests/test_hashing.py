"""Tests for cryptographic hashing functions."""

import pytest

from penguin_crypto.hashing import sha256, sha512, blake2b, hmac_sha256


class TestSHA256:
    """Tests for SHA-256 hashing."""

    def test_sha256_known_vector_empty(self) -> None:
        """Test SHA-256 against known test vector for empty input."""
        result = sha256(b"")
        assert result == "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"

    def test_sha256_known_vector_string(self) -> None:
        """Test SHA-256 with string input."""
        result = sha256("")
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

    def test_sha256_output_length(self) -> None:
        """Test SHA-256 output is 64 hex characters (256 bits)."""
        result = sha256(b"test")
        assert len(result) == 64
        assert all(c in "0123456789abcdef" for c in result)

    def test_sha256_unicode(self) -> None:
        """Test SHA-256 with Unicode strings."""
        result = sha256("hello")
        assert len(result) == 64
        assert all(c in "0123456789abcdef" for c in result)

    def test_sha256_large_input(self) -> None:
        """Test SHA-256 with large input."""
        data = b"x" * (1024 * 1024)  # 1 MB
        result = sha256(data)
        assert len(result) == 64


class TestSHA512:
    """Tests for SHA-512 hashing."""

    def test_sha512_known_vector_empty(self) -> None:
        """Test SHA-512 against known test vector for empty input."""
        result = sha512(b"")
        assert (
            result
            == "cf83e1357eefb8bdf1542850d66d8007d620e4050b5715dc83f4a921d36ce9ce47d0d13c5d85f2b0ff8318d2877eec2f63b931bd47417a81a538327af927da3e"
        )

    def test_sha512_known_vector_string(self) -> None:
        """Test SHA-512 with string input."""
        result = sha512("")
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

    def test_sha512_output_length(self) -> None:
        """Test SHA-512 output is 128 hex characters (512 bits)."""
        result = sha512(b"test")
        assert len(result) == 128
        assert all(c in "0123456789abcdef" for c in result)

    def test_sha512_large_input(self) -> None:
        """Test SHA-512 with large input."""
        data = b"y" * (1024 * 1024)
        result = sha512(data)
        assert len(result) == 128


class TestBLAKE2b:
    """Tests for BLAKE2b hashing."""

    def test_blake2b_default_digest_size(self) -> None:
        """Test BLAKE2b default digest size is 64 bytes."""
        result = blake2b(b"test")
        assert len(result) == 128  # 64 bytes = 128 hex characters

    def test_blake2b_custom_digest_sizes(self) -> None:
        """Test BLAKE2b with custom digest sizes."""
        for digest_size in [1, 16, 32, 64]:
            result = blake2b(b"test", digest_size=digest_size)
            expected_hex_len = digest_size * 2
            assert len(result) == expected_hex_len

    def test_blake2b_deterministic(self) -> None:
        """Test BLAKE2b is deterministic."""
        data = b"test data"
        hash1 = blake2b(data)
        hash2 = blake2b(data)
        assert hash1 == hash2

    def test_blake2b_different_inputs(self) -> None:
        """Test different inputs produce different BLAKE2b hashes."""
        hash1 = blake2b(b"data1")
        hash2 = blake2b(b"data2")
        assert hash1 != hash2

    def test_blake2b_different_digest_sizes(self) -> None:
        """Test different digest sizes produce different hashes."""
        data = b"test"
        hash1 = blake2b(data, digest_size=16)
        hash2 = blake2b(data, digest_size=32)
        assert hash1 != hash2
        assert len(hash1) == 32  # 16 bytes
        assert len(hash2) == 64  # 32 bytes

    def test_blake2b_invalid_digest_size_too_small(self) -> None:
        """Test BLAKE2b rejects digest_size < 1."""
        with pytest.raises(ValueError, match="digest_size must be 1-64"):
            blake2b(b"test", digest_size=0)

    def test_blake2b_invalid_digest_size_too_large(self) -> None:
        """Test BLAKE2b rejects digest_size > 64."""
        with pytest.raises(ValueError, match="digest_size must be 1-64"):
            blake2b(b"test", digest_size=65)

    def test_blake2b_unicode(self) -> None:
        """Test BLAKE2b with Unicode strings."""
        result = blake2b("hello world", digest_size=32)
        assert len(result) == 64
        assert all(c in "0123456789abcdef" for c in result)

    def test_blake2b_is_fast_hash(self) -> None:
        """Test BLAKE2b is suitable for performance-critical code."""
        # Just verify it works with large input
        data = b"x" * (10 * 1024 * 1024)  # 10 MB
        result = blake2b(data, digest_size=32)
        assert len(result) == 64


class TestHMACSHA256:
    """Tests for HMAC-SHA256."""

    def test_hmac_sha256_known_vector(self) -> None:
        """Test HMAC-SHA256 against known test vector."""
        key = b"key"
        data = b"The quick brown fox jumps over the lazy dog"
        result = hmac_sha256(data, key)
        assert result == "f7bc83f430538424b13298e6aa6fb143ef4d59a14946175997479dbc2d1a3cd8"

    def test_hmac_sha256_deterministic(self) -> None:
        """Test HMAC-SHA256 is deterministic."""
        key = b"secret_key"
        data = b"test data"
        hmac1 = hmac_sha256(data, key)
        hmac2 = hmac_sha256(data, key)
        assert hmac1 == hmac2

    def test_hmac_sha256_different_keys(self) -> None:
        """Test different keys produce different HMACs."""
        data = b"message"
        hmac1 = hmac_sha256(data, b"key1")
        hmac2 = hmac_sha256(data, b"key2")
        assert hmac1 != hmac2

    def test_hmac_sha256_different_data(self) -> None:
        """Test different data produces different HMACs."""
        key = b"key"
        hmac1 = hmac_sha256(b"data1", key)
        hmac2 = hmac_sha256(b"data2", key)
        assert hmac1 != hmac2

    def test_hmac_sha256_output_length(self) -> None:
        """Test HMAC-SHA256 output is 64 hex characters."""
        result = hmac_sha256(b"test", b"key")
        assert len(result) == 64
        assert all(c in "0123456789abcdef" for c in result)

    def test_hmac_sha256_string_input(self) -> None:
        """Test HMAC-SHA256 with string input."""
        key = b"secret"
        data = "message"
        result = hmac_sha256(data, key)
        assert len(result) == 64
        assert all(c in "0123456789abcdef" for c in result)

    def test_hmac_sha256_empty_data(self) -> None:
        """Test HMAC-SHA256 with empty data."""
        key = b"key"
        result = hmac_sha256(b"", key)
        assert len(result) == 64

    def test_hmac_sha256_empty_key(self) -> None:
        """Test HMAC-SHA256 with empty key."""
        data = b"data"
        result = hmac_sha256(data, b"")
        assert len(result) == 64

    def test_hmac_sha256_large_key(self) -> None:
        """Test HMAC-SHA256 with large key."""
        key = b"x" * 1024
        data = b"data"
        result = hmac_sha256(data, key)
        assert len(result) == 64


class TestHashingIntegration:
    """Integration tests for hashing functions."""

    def test_all_hash_functions_work(self) -> None:
        """Test all hash functions can be imported and used."""
        data = b"test data"

        h256 = sha256(data)
        assert len(h256) == 64

        h512 = sha512(data)
        assert len(h512) == 128

        hb2b = blake2b(data, digest_size=32)
        assert len(hb2b) == 64

        hmac = hmac_sha256(data, b"key")
        assert len(hmac) == 64

    def test_different_hash_functions_different_outputs(self) -> None:
        """Test different hash functions produce different outputs."""
        data = b"test"

        h256 = sha256(data)
        h512 = sha512(data)
        hb2b = blake2b(data, digest_size=32)

        # Should all be different
        assert h256 != h512[:64]
        assert h256 != hb2b
        assert h512 != hb2b * 2  # Different lengths anyway
