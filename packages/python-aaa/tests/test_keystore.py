"""Tests for penguin_aaa.crypto.keystore and penguin_aaa.crypto.jwks."""

import json
import uuid
from pathlib import Path

import pytest
from cryptography.hazmat.primitives.asymmetric.ec import EllipticCurvePrivateKey
from cryptography.hazmat.primitives.asymmetric.rsa import RSAPrivateKey

from penguin_aaa.crypto.jwks import public_key_to_jwk
from penguin_aaa.crypto.keystore import FileKeyStore, MemoryKeyStore


class TestMemoryKeyStoreRSA:
    def test_generates_rsa_key_by_default(self):
        store = MemoryKeyStore(algorithm="RS256")
        key, kid = store.get_signing_key()
        assert isinstance(key, RSAPrivateKey)

    def test_kid_is_valid_uuid(self):
        store = MemoryKeyStore()
        _, kid = store.get_signing_key()
        parsed = uuid.UUID(kid)
        assert str(parsed) == kid

    def test_jwks_returns_rsa_public_key(self):
        store = MemoryKeyStore(algorithm="RS256")
        jwks = store.get_jwks()
        assert "keys" in jwks
        assert len(jwks["keys"]) == 1
        jwk = jwks["keys"][0]
        assert jwk["kty"] == "RSA"
        assert "n" in jwk
        assert "e" in jwk
        assert "d" not in jwk  # private exponent must not be present

    def test_rotate_key_adds_new_key(self):
        store = MemoryKeyStore()
        _, original_kid = store.get_signing_key()
        store.rotate_key()
        _, new_kid = store.get_signing_key()
        assert new_kid != original_kid

    def test_rotation_retains_at_most_three_keys(self):
        store = MemoryKeyStore()
        for _ in range(5):
            store.rotate_key()
        assert len(store.get_jwks()["keys"]) <= 3

    def test_jwks_kid_matches_signing_key(self):
        store = MemoryKeyStore()
        _, kid = store.get_signing_key()
        jwks = store.get_jwks()
        kids = [k["kid"] for k in jwks["keys"]]
        assert kid in kids


class TestMemoryKeyStoreEC:
    def test_generates_ec_key(self):
        store = MemoryKeyStore(algorithm="ES256")
        key, _ = store.get_signing_key()
        assert isinstance(key, EllipticCurvePrivateKey)

    def test_jwks_returns_ec_public_key(self):
        store = MemoryKeyStore(algorithm="ES256")
        jwks = store.get_jwks()
        jwk = jwks["keys"][0]
        assert jwk["kty"] == "EC"
        assert jwk["crv"] == "P-256"
        assert "x" in jwk
        assert "y" in jwk
        assert "d" not in jwk  # private scalar must not be present


class TestFileKeyStore:
    def test_creates_key_file_on_init(self, tmp_path: Path):
        key_file = tmp_path / "keys.json"
        store = FileKeyStore(key_file, algorithm="RS256")
        assert key_file.exists()

    def test_key_file_contains_valid_json(self, tmp_path: Path):
        key_file = tmp_path / "keys.json"
        FileKeyStore(key_file, algorithm="RS256")
        data = json.loads(key_file.read_text())
        assert "keys" in data
        assert len(data["keys"]) == 1
        assert "kid" in data["keys"][0]
        assert "pem" in data["keys"][0]

    def test_loads_existing_keys(self, tmp_path: Path):
        key_file = tmp_path / "keys.json"
        store1 = FileKeyStore(key_file, algorithm="RS256")
        _, kid1 = store1.get_signing_key()

        store2 = FileKeyStore(key_file, algorithm="RS256")
        _, kid2 = store2.get_signing_key()

        assert kid1 == kid2

    def test_rotate_key_persists_new_key(self, tmp_path: Path):
        key_file = tmp_path / "keys.json"
        store = FileKeyStore(key_file, algorithm="RS256")
        _, original_kid = store.get_signing_key()
        store.rotate_key()
        _, new_kid = store.get_signing_key()
        assert new_kid != original_kid

        # Reload and verify new key is present
        store2 = FileKeyStore(key_file, algorithm="RS256")
        _, reloaded_kid = store2.get_signing_key()
        assert reloaded_kid == new_kid

    def test_rotation_retains_at_most_three_keys(self, tmp_path: Path):
        key_file = tmp_path / "keys.json"
        store = FileKeyStore(key_file, algorithm="RS256")
        for _ in range(5):
            store.rotate_key()
        assert len(store.get_jwks()["keys"]) <= 3

    def test_creates_parent_directories(self, tmp_path: Path):
        key_file = tmp_path / "nested" / "dir" / "keys.json"
        FileKeyStore(key_file, algorithm="RS256")
        assert key_file.exists()

    def test_ec_key_file(self, tmp_path: Path):
        key_file = tmp_path / "ec_keys.json"
        store = FileKeyStore(key_file, algorithm="ES256")
        key, _ = store.get_signing_key()
        assert isinstance(key, EllipticCurvePrivateKey)


class TestPublicKeyToJwk:
    def test_rsa_jwk_structure(self):
        store = MemoryKeyStore(algorithm="RS256")
        key, kid = store.get_signing_key()
        public_key = key.public_key()
        jwk = public_key_to_jwk(public_key, kid, "RS256")

        assert jwk["kty"] == "RSA"
        assert jwk["alg"] == "RS256"
        assert jwk["kid"] == kid
        assert jwk["use"] == "sig"
        assert "n" in jwk
        assert "e" in jwk

    def test_ec_p256_jwk_structure(self):
        store = MemoryKeyStore(algorithm="ES256")
        key, kid = store.get_signing_key()
        public_key = key.public_key()
        jwk = public_key_to_jwk(public_key, kid, "ES256")

        assert jwk["kty"] == "EC"
        assert jwk["crv"] == "P-256"
        assert jwk["alg"] == "ES256"
        assert jwk["kid"] == kid
        assert "x" in jwk
        assert "y" in jwk

    def test_ec_p384_jwk_structure(self):
        store = MemoryKeyStore(algorithm="ES384")
        key, kid = store.get_signing_key()
        public_key = key.public_key()
        jwk = public_key_to_jwk(public_key, kid, "ES384")

        assert jwk["crv"] == "P-384"

    def test_unsupported_key_type_raises_type_error(self):
        with pytest.raises(TypeError, match="Unsupported key type"):
            public_key_to_jwk("not-a-key", "kid", "RS256")  # type: ignore[arg-type]
